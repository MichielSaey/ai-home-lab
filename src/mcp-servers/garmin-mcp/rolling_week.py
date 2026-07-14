"""Unified rolling week boundaries for Garmin MCP reports and stats."""

from datetime import date, timedelta


def anchor_end(days_ago: int = 0, today: date | None = None) -> date:
    """Last day of the review block: yesterday minus ``days_ago`` shift."""
    if days_ago < 0:
        raise ValueError("days_ago must be zero or positive")
    ref = today or date.today()
    return ref - timedelta(days=1 + days_ago)


def block_bounds(anchor: date) -> tuple[date, date]:
    """Seven complete days ending on ``anchor``: [anchor - 6, anchor]."""
    return anchor - timedelta(days=6), anchor


def window_bounds(
    days: int, days_ago: int = 0, today: date | None = None
) -> tuple[date, date]:
    """Report window start/end aligned to rolling week rules.

    For ``days == 7``, returns the canonical review block via ``block_bounds``.
    Otherwise ``end`` is ``anchor_end`` and ``start`` is ``end - (days - 1)``.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    anchor = anchor_end(days_ago, today=today)
    if days == 7:
        return block_bounds(anchor)
    end = anchor
    start = end - timedelta(days=days - 1)
    return start, end
