---
name: garmin-week-review
description: Garmin coach — single-shot preload, review + next-week proposal.
version: 2.1.0
category: health
tags: [running, garmin, coaching, acwr]
requires_toolsets: [garmin-mcp]
status: published
source: taught
---

## When to Use

Garmin running coach via garmin-mcp. Week reviews, load checks, intensity feedback,
next-week proposals. **Agent mode only.**

## Procedure

1. Call **`get_coaching_brief`** once. Do not call any other Garmin read tools first.
2. Present `coaching_brief.narrative` in `presentation_order`:
   - `review_summary`
   - `intensity_check`
   - `load_check`
   - `proposal_summary`
   - `coaching_note`
3. Add a day-by-day table from `coaching_brief.next_week_proposal.sessions`.
4. Call `create_*_workout` only when the user asks to schedule on Garmin.

## Pitfalls

- One call per coaching turn — review and proposal are both in `coaching_brief`.
- Polarized only (easy or hard) — no Zone 3 / tempo prescriptions.
- Do not ask the user to paste Garmin data.

## Verification

- Numbers from `coaching_brief.narrative` and session dates from `next_week_proposal`.
