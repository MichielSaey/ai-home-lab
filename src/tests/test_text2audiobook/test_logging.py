from text2audiobook.logging_setup import format_progress


def test_format_progress_with_chunk() -> None:
    line = format_progress(
        "The Tenant",
        1,
        3,
        "tts",
        chunk_idx=2,
        chapter_title="Chapter One",
        total_chunks=10,
    )
    assert line == "[The Tenant/1/3] [2|Chapter On|10] tts"


def test_format_progress_book_only() -> None:
    line = format_progress("Invisible Man", 2, 5, "classify openings")
    assert line == "[Invisible /2/5] classify openings"
