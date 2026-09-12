"""CPU tests for VRAM batch capacity model and packing with overhead."""

from text2audiobook.batch_vram import (
    batch_fits_vram,
    batch_vram_cost,
    fit_batch_vram_model,
)
from text2audiobook.tts import iter_speak_batches


def test_batch_vram_cost_empty_and_basic() -> None:
    assert batch_vram_cost([], overhead_chars=100) == 0
    assert batch_vram_cost([80, 80, 80], overhead_chars=0) == 240
    assert batch_vram_cost([80, 100], overhead_chars=50) == 2 * (100 + 50)


def test_batch_fits_vram_single_oversized_always() -> None:
    assert batch_fits_vram(
        [10_000],
        budget_chars=100,
        overhead_chars=0,
        max_items=1,
    )
    assert batch_fits_vram(
        [10_000],
        budget_chars=100,
        overhead_chars=500,
        max_items=4,
    )


def test_batch_fits_vram_budget_and_items() -> None:
    assert batch_fits_vram(
        [100, 100, 100],
        budget_chars=300,
        overhead_chars=0,
        max_items=8,
    )
    assert not batch_fits_vram(
        [100, 100, 100, 100],
        budget_chars=300,
        overhead_chars=0,
        max_items=8,
    )
    assert not batch_fits_vram(
        [50, 50, 50],
        budget_chars=10_000,
        overhead_chars=0,
        max_items=2,
    )
    # Caps disabled
    assert batch_fits_vram(
        [100] * 20,
        budget_chars=0,
        overhead_chars=0,
        max_items=0,
    )


def test_fit_batch_vram_model_synthetic_frontier() -> None:
    # True model: n * (L + 100) ≈ 3000 → n_max ≈ 3000 / (L + 100)
    points = []
    for length in (40, 80, 200, 400, 800):
        n_max = max(1, 3000 // (length + 100))
        points.append((length, n_max))
    budget, overhead = fit_batch_vram_model(points, safety=0.9)
    assert overhead == 100
    # min score is ~3000 (integer division may undershoot slightly)
    assert 2400 <= budget <= 3000
    assert fit_batch_vram_model([], safety=0.9) == (2800, 0)


def test_iter_speak_batches_overhead_prefers_shorts() -> None:
    class Unit:
        def __init__(self, text: str, label: str) -> None:
            self.text = text
            self.label = label

    shorts = [Unit("s" * 50, f"s{i}") for i in range(20)]
    longs = [Unit("L" * 700, f"L{i}") for i in range(8)]
    budget = 2800
    overhead = 100

    short_batches = list(
        iter_speak_batches(
            shorts,
            max_chars=0,
            max_items=32,
            max_pad=budget,
            vram_overhead=overhead,
        )
    )
    long_batches = list(
        iter_speak_batches(
            longs,
            max_chars=0,
            max_items=32,
            max_pad=budget,
            vram_overhead=overhead,
        )
    )
    # cost = n*(50+100)=n*150 ≤ 2800 → n ≤ 18
    assert max(len(b) for b in short_batches) >= 10
    # cost = n*(700+100)=n*800 ≤ 2800 → n ≤ 3
    assert max(len(b) for b in long_batches) <= 3
    assert max(len(b) for b in short_batches) > max(len(b) for b in long_batches)
