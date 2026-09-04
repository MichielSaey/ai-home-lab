from text2audiobook.logging_setup import format_progress


def test_format_progress_with_unit_percent() -> None:
    line = format_progress(
        "The Tenant",
        1,
        3,
        "tts",
        unit_done=42,
        total_chunks=1313,
        chapter_idx=11,
        total_chapters=201,
        chapter_title="Capital Escapes",
        chapter_unit=4,
        chapter_units=8,
    )
    assert line == (
        "[book 1/3 The Tenant] | stage=tts | unit=42/1313 (3%) | "
        "chapter=12/201 Capital Escapes unit=4/8"
    )


def test_format_progress_book_only() -> None:
    line = format_progress("Invisible Man", 2, 5, "classify openings")
    assert line == "[book 2/5 Invisible Man] | stage=classify openings"


def test_format_progress_truncates_long_titles() -> None:
    line = format_progress(
        "A Very Long Book Title That Needs Truncation",
        1,
        1,
        "format",
        unit_done=1,
        total_chunks=10,
        chapter_title="An Extremely Long Chapter Title For Display",
    )
    assert "stage=format" in line
    assert "unit=1/10 (10%)" in line
    assert "…" in line
