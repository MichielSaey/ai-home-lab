"""VRAM capacity model and GPU calibration for TTS batch packing."""

from __future__ import annotations

import json
import statistics
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

DEFAULT_CALIBRATE_LENGTHS = (40, 80, 120, 200, 300, 400, 600, 800, 1000, 1200)
DEFAULT_CALIBRATE_NS = (1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32)

_CALIBRATE_PHRASE = (
    "The quick brown fox jumps over the lazy dog. "
    "Pack my box with five dozen liquor jugs. "
)


def batch_vram_cost(lengths: Sequence[int], *, overhead_chars: int) -> int:
    """Pad-style VRAM cost: ``n * (max(lengths) + overhead)``; 0 if empty."""
    if not lengths:
        return 0
    return len(lengths) * (max(lengths) + overhead_chars)


def batch_fits_vram(
    lengths: Sequence[int],
    *,
    budget_chars: int,
    overhead_chars: int,
    max_items: int,
) -> bool:
    """True when a batch of these lengths fits the VRAM capacity model.

    A single unit (``n == 1``) always fits so the caller can still synthesize
    oversized chunks alone. ``max_items <= 0`` disables the item ceiling;
    ``budget_chars <= 0`` disables the budget check.
    """
    n = len(lengths)
    if n == 0:
        return True
    if n == 1:
        return True
    if max_items > 0 and n > max_items:
        return False
    if budget_chars > 0 and batch_vram_cost(lengths, overhead_chars=overhead_chars) > budget_chars:
        return False
    return True


def fit_batch_vram_model(
    points: Sequence[tuple[int, int]],
    *,
    safety: float = 0.9,
) -> tuple[int, int]:
    """Fit ``(budget_chars, overhead_chars)`` from equal-length frontiers.

    ``points`` are ``(L, n_max)`` where ``n_max`` is the largest batch size that
    succeeded for equal-length units of ``L`` chars. Searches integer overhead
    in ``range(0, 801, 25)`` and prefers the value that minimizes relative
    spread (``pstdev / mean``) of ``n * (L + overhead)``. Budget is
    ``int(safety * min(scores))``.
    """
    valid = [(int(length), int(n_max)) for length, n_max in points if int(n_max) > 1]
    if not valid:
        return (2800, 0)

    best_spread: float | None = None
    best_overhead = 0
    best_budget = 2800
    for overhead in range(0, 801, 25):
        scores = [n * (length + overhead) for length, n in valid]
        mean = sum(scores) / len(scores)
        if mean <= 0:
            continue
        spread = 0.0 if len(scores) == 1 else statistics.pstdev(scores) / mean
        budget = int(safety * min(scores))
        if (
            best_spread is None
            or spread < best_spread
            or (spread == best_spread and overhead < best_overhead)
        ):
            best_spread = spread
            best_overhead = overhead
            best_budget = budget
    return (best_budget, best_overhead)


def _make_equal_length_text(length: int) -> str:
    """Build an English filler string of exactly ``length`` characters."""
    if length <= 0:
        return ""
    phrase = _CALIBRATE_PHRASE
    reps = (length // len(phrase)) + 2
    return (phrase * reps)[:length]


def _peak_allocated_mb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return float(torch.cuda.max_memory_allocated()) / (1024.0 * 1024.0)
    except Exception:
        return None


def _reset_peak_memory() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


def run_batch_vram_calibration(
    model: Any,
    *,
    voice: str,
    language: str,
    model_id: str,
    voice_clone_prompt: Any | None = None,
    ref_audio: Path | str | None = None,
    ref_text: str | None = None,
    x_vector_only: bool = False,
    lengths: Sequence[int] = DEFAULT_CALIBRATE_LENGTHS,
    ns: Sequence[int] = DEFAULT_CALIBRATE_NS,
    out_dir: Path,
    reload_model: Callable[[], tuple[Any, Any]] | None = None,
    safety: float = 0.9,
) -> dict[str, Any]:
    """Measure equal-length batch frontiers on the real voice-clone path.

    For each length ``L`` (ascending), binary-searches the largest batch size ``n``
    in ``ns`` that succeeds. Uses ``on_oom=\"raise\"`` so OOM is recorded without
    half-split retries. After OOM, cleans CUDA state and optionally reloads
    the TTS model via ``reload_model`` (returns ``(model, voice_clone_prompt)``).

    Writes ``calibration.json`` under ``out_dir`` and returns the result dict.
    """
    from text2audiobook.tts import (
        _cuda_oom_cleanup,
        _is_cuda_oom,
        synthesize_batch_to_wavs,
    )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    frontiers: dict[int, int] = {}
    current_model = model
    current_prompt = voice_clone_prompt
    needs_reload = False

    # Keep the calibration table readable (synthesize logs every trial otherwise).
    import logging

    tts_logger = logging.getLogger("text2audiobook.tts")
    prev_tts_level = tts_logger.level
    tts_logger.setLevel(logging.WARNING)

    print(
        f"{'L':>5} {'n':>4} {'pad':>8} {'ok':>3} {'peak_MB':>10}  note"
    )
    print("-" * 56)

    try:
        for length in sorted(int(x) for x in lengths):
            if needs_reload and reload_model is not None:
                try:
                    current_model, current_prompt = reload_model()
                    needs_reload = False
                    print(f"# recovered model before L={length}")
                except Exception as reload_exc:
                    print(
                        f"# reload still failing before L={length}: "
                        f"{type(reload_exc).__name__}"
                    )
                    frontiers[length] = 0
                    continue

            n_candidates = sorted(int(x) for x in ns)
            n_max = 0
            # Binary search the largest successful n in the candidate list.
            lo = 0
            hi = len(n_candidates) - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                n = n_candidates[mid]
                texts = [_make_equal_length_text(length) for _ in range(n)]
                pad_cost = n * length
                peak_mb: float | None = None
                note = ""

                with tempfile.TemporaryDirectory(prefix="batch_vram_cal_") as tmp:
                    tmp_dir = Path(tmp)
                    items = [
                        (text, tmp_dir / f"{i:03d}.wav") for i, text in enumerate(texts)
                    ]
                    _reset_peak_memory()
                    try:
                        synthesize_batch_to_wavs(
                            current_model,
                            items,
                            voice=voice,
                            language=language,
                            model_id=model_id,
                            voice_clone_prompt=current_prompt,
                            ref_audio=ref_audio,
                            ref_text=ref_text,
                            x_vector_only=x_vector_only,
                            on_oom="raise",
                        )
                        peak_mb = _peak_allocated_mb()
                        n_max = max(n_max, n)
                        note = "ok"
                        rows.append(
                            {
                                "length": length,
                                "n": n,
                                "pad_cost": pad_cost,
                                "ok": True,
                                "error": None,
                                "peak_allocated_mb": peak_mb,
                            }
                        )
                        print(
                            f"{length:5d} {n:4d} {pad_cost:8d} {'yes':>3} "
                            f"{_fmt_peak(peak_mb):>10}  {note}"
                        )
                        lo = mid + 1
                    except Exception as exc:
                        peak_mb = _peak_allocated_mb()
                        error = f"{type(exc).__name__}: {exc}"
                        if _is_cuda_oom(exc):
                            note = "OOM"
                            _cuda_oom_cleanup()
                            if reload_model is not None:
                                try:
                                    current_model, current_prompt = reload_model()
                                    note = "OOM+reload"
                                except Exception as reload_exc:
                                    note = (
                                        f"OOM+reload_failed:{type(reload_exc).__name__}"
                                    )
                                    needs_reload = True
                                    _cuda_oom_cleanup()
                            rows.append(
                                {
                                    "length": length,
                                    "n": n,
                                    "pad_cost": pad_cost,
                                    "ok": False,
                                    "error": error,
                                    "peak_allocated_mb": peak_mb,
                                }
                            )
                            print(
                                f"{length:5d} {n:4d} {pad_cost:8d} {'no':>3} "
                                f"{_fmt_peak(peak_mb):>10}  {note}"
                            )
                            if needs_reload:
                                break
                            hi = mid - 1
                            continue
                        note = "error"
                        needs_reload = True
                        rows.append(
                            {
                                "length": length,
                                "n": n,
                                "pad_cost": pad_cost,
                                "ok": False,
                                "error": error,
                                "peak_allocated_mb": peak_mb,
                            }
                        )
                        print(
                            f"{length:5d} {n:4d} {pad_cost:8d} {'no':>3} "
                            f"{_fmt_peak(peak_mb):>10}  {note}"
                        )
                        break

            frontiers[length] = n_max
    finally:
        tts_logger.setLevel(prev_tts_level)

    points = [(length, n_max) for length, n_max in sorted(frontiers.items())]
    budget_chars, overhead_chars = fit_batch_vram_model(points, safety=safety)
    max_items_suggested = max((n for _, n in points), default=0)

    result: dict[str, Any] = {
        "rows": rows,
        "points": [{"length": length, "n_max": n_max} for length, n_max in points],
        "budget_chars": budget_chars,
        "overhead_chars": overhead_chars,
        "max_items_suggested": max_items_suggested,
        "safety": safety,
        "lengths": list(sorted(int(x) for x in lengths)),
        "ns": list(sorted(int(x) for x in ns)),
    }
    (out_dir / "calibration.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print()
    print(
        f"Fitted: batch_max_pad_chars={budget_chars} "
        f"batch_vram_overhead={overhead_chars} "
        f"batch_max_items(suggested)={max_items_suggested}"
    )
    print(f"Wrote {out_dir / 'calibration.json'}")
    return result


def _fmt_peak(peak_mb: float | None) -> str:
    if peak_mb is None:
        return "-"
    return f"{peak_mb:.1f}"
