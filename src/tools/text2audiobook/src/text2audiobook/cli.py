"""Command-line entry point: fire-and-forget folder scan or --url one-shot."""

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from text2audiobook.config import DEFAULT_CONFIG_PATH
from text2audiobook.stems import PIPELINE_STAGES


def _selected_stages(args: argparse.Namespace) -> list[str] | None:
    """Return requested stage names, or None for the full default pipeline."""
    selected = [name for name in PIPELINE_STAGES if getattr(args, name, False)]
    return selected or None


def _run_batch_vram_calibration(config_path: Path | None) -> int:
    """Load Base TTS, run VRAM batch calibration, print fitted knobs, exit."""
    from text2audiobook.batch_vram import run_batch_vram_calibration
    from text2audiobook.config import load_config
    from text2audiobook.gpu import prepare_gpu_env
    from text2audiobook.logging_setup import setup_logging
    from text2audiobook.tts import (
        is_base,
        load_tts,
        unload_tts,
    )

    prepare_gpu_env()
    setup_logging()
    config = load_config(config_path)
    tts = config.tts

    if not is_base(tts.model_id):
        print(
            "error: --calibrate-tts-batch requires a Base (voice-clone) model_id "
            f"(got {tts.model_id!r})",
            file=sys.stderr,
        )
        return 2
    if not tts.ref_audio:
        print("error: tts.ref_audio is required for batch VRAM calibration", file=sys.stderr)
        return 2
    ref_audio = Path(tts.ref_audio)
    if not ref_audio.is_file():
        print(f"error: tts.ref_audio not found: {ref_audio}", file=sys.stderr)
        return 2
    if not tts.x_vector_only and not (tts.ref_text and tts.ref_text.strip()):
        print(
            "error: tts.ref_text is required unless tts.x_vector_only is true",
            file=sys.stderr,
        )
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = config.paths.runs_dir / f"{stamp}_batch_vram"
    out_dir.mkdir(parents=True, exist_ok=True)

    model = load_tts(
        tts,
        hub_prefer_local=config.pipeline.hub_prefer_local,
        hub_offline=config.pipeline.hub_offline,
    )

    def _hard_unload(current) -> None:
        unload_tts(current)
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            try:
                torch.cuda.synchronize()
            except Exception:
                pass
            torch.cuda.empty_cache()
        gc.collect()

    def reload_model():
        """Fully drop the old model; return (model, None) and use ref_audio per trial."""
        nonlocal model
        _hard_unload(model)
        model = None
        model = load_tts(
            tts,
            hub_prefer_local=config.pipeline.hub_prefer_local,
            hub_offline=config.pipeline.hub_offline,
        )
        # Skip rebuild of voice_clone_prompt here — encoding the ref right after an
        # OOM often OOMs again. synthesize uses ref_audio when prompt is None.
        return model, None

    try:
        result = run_batch_vram_calibration(
            model,
            voice=tts.voice,
            language=tts.lang,
            model_id=tts.model_id,
            voice_clone_prompt=None,
            ref_audio=ref_audio,
            ref_text=tts.ref_text,
            x_vector_only=tts.x_vector_only,
            out_dir=out_dir,
            reload_model=reload_model,
        )
    finally:
        if model is not None:
            unload_tts(model)

    print()
    print("Suggested config.tts values:")
    print(f'  "batch_max_pad_chars": {result["budget_chars"]},')
    print(f'  "batch_vram_overhead": {result["overhead_chars"]},')
    print(f'  "batch_max_items": {result["max_items_suggested"]},')
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="text2audiobook",
        description=(
            "Convert supported text sources (EPUB, PDF, Markdown, HTML, .url) "
            "to M4B audiobooks."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Path to a config JSON file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="URL",
        help=(
            "Fetch and convert a web page (repeatable). "
            "When set, the input folder is not scanned."
        ),
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Run the extract stage (combinable with other stage flags).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Run the clean stage (combinable; requires extract stem if extract is skipped).",
    )
    parser.add_argument(
        "--format",
        action="store_true",
        dest="format",
        help="Run the format stage (combinable; requires clean stem if clean is skipped).",
    )
    parser.add_argument(
        "--speak",
        action="store_true",
        help=(
            "Run the speak stage (combinable; requires format stem if format is skipped). "
            "Speak-only does not load the LLM."
        ),
    )
    parser.add_argument(
        "--calibrate-tts-batch",
        action="store_true",
        help=(
            "Measure TTS batch VRAM frontiers on the voice-clone path, fit "
            "batch_max_pad_chars / batch_vram_overhead, write calibration.json, "
            "and exit (does not process books)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redo requested stages even when stems or the M4B already exist.",
    )
    parser.add_argument(
        "--voice",
        default=None,
        help=(
            "CustomVoice speaker (e.g. Serena, Ryan, Aiden), 'random' for the "
            "CustomVoice pool, 'cloned' for Base voice clone (uses tts.ref_audio), "
            "or 'designed' for VoiceDesign. Content language stays from config "
            "tts.lang."
        ),
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help=(
            "Print CustomVoice speakers plus Base/VoiceDesign notes, then exit "
            "(no GPU / LLM load)."
        ),
    )
    cues = parser.add_mutually_exclusive_group()
    cues.add_argument(
        "--footnote-cues",
        action="store_true",
        dest="footnote_cues",
        help="Speak footnote start/end markers (overrides config).",
    )
    cues.add_argument(
        "--no-footnote-cues",
        action="store_false",
        dest="footnote_cues",
        help="Omit spoken footnote markers (overrides config).",
    )
    parser.set_defaults(footnote_cues=None)

    clone = parser.add_mutually_exclusive_group()
    clone.add_argument(
        "--x-vector-only",
        action="store_true",
        dest="x_vector_only",
        help=(
            "Base voice clone: speaker embedding only (no ICL ref_text). "
            "Use to suppress <|im_end|>/ref-tail onset artifacts; may reduce "
            "prosody match vs full ICL (overrides config)."
        ),
    )
    clone.add_argument(
        "--icl",
        action="store_false",
        dest="x_vector_only",
        help="Base voice clone: full ICL with ref_text (overrides config).",
    )
    parser.set_defaults(x_vector_only=None)
    args = parser.parse_args(argv)

    if args.list_voices:
        from text2audiobook.voices import format_voice_table

        print(format_voice_table())
        return 0

    if args.calibrate_tts_batch:
        return _run_batch_vram_calibration(args.config)

    from text2audiobook.gpu import prepare_gpu_env

    prepare_gpu_env()

    from text2audiobook.config import load_config
    from text2audiobook.formats.url import write_url_source
    from text2audiobook.logging_setup import setup_logging
    from text2audiobook.pipeline import run

    setup_logging()
    config = load_config(args.config)

    source_paths: list[Path] | None = None
    if args.url:
        url_dir = config.paths.staging_dir / "_cli_urls"
        source_paths = [
            write_url_source(url_dir, url, stem=f"cli_{index}")
            for index, url in enumerate(args.url, start=1)
        ]

    return run(
        config,
        source_paths=source_paths,
        stages=_selected_stages(args),
        force=args.force,
        voice=args.voice,
        speak_footnote_cues=args.footnote_cues,
        x_vector_only=args.x_vector_only,
    )


if __name__ == "__main__":
    sys.exit(main())
