# Spike: time-based weekly volume (B.P2.1)

## Problem

Km-based targets (prev×1.10 / peak×0.80 / spike×latest×0.8) under-prescribed
after light or cross-training weeks (e.g. 15–20 km) while Garmin DSW stayed near
chronic capacity (~50 km equivalent). Garmin plans by **duration**, not distance.

## Approach (shipped)

1. **Chronic $$C$$** = mean of last ≤4 weeks’ `total_zone_min` (all sports), after
   dropping weeks more than **50%** from the median.
2. **Target** = $$C \times 1.15$$ (build) or $$C \times 0.80$$ (recovery).
3. **Race curve** = one-step climb toward title-heuristic peak minutes, capped at
   $$C \times 1.15$$; taper/race use peak minutes × 0.80 / 0.64 / 0.30.
4. **Spike** (ACWR > 1.3) forces recovery at $$C \times 0.80$$.
5. **Sessions** = 80/15/5 (or recovery 90/8/2) pools → 5 train + 2 rest skeleton.
6. Proposal exposes `target_min`, `chronic_min`, `outlier_weeks_dropped`, `sessions[]`.

## Validation

Unit tests in `test_training_plan.py` / `test_coaching_brief.py` cover outlier drop,
build/recovery targets, spike deload, session minute conservation, and race curve.
