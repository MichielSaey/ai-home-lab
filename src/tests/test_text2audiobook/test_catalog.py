"""Chapter selection / decisions-cache behavior."""

from pathlib import Path

from text2audiobook.catalog import (
    ChapterDecision,
    OpeningAnalysis,
    save_decisions_cache,
    select_chapters,
)
from text2audiobook.config import SelectionConfig
from text2audiobook.io import Chapter


def test_select_chapters_cache_hit_does_not_need_llm(tmp_path: Path) -> None:
    chapters = [
        Chapter(index=0, title="Intro", text="Hello world " * 40, slug="intro"),
        Chapter(index=1, title="Body", text="More words " * 40, slug="body"),
    ]
    selection = SelectionConfig()
    save_decisions_cache(
        tmp_path,
        book_title="Demo",
        chapter_count=2,
        selection=selection,
        analyses=[
            OpeningAnalysis(0, "introduction", True, "opens the book"),
            OpeningAnalysis(1, "chapter", True, "main text"),
        ],
        decisions=[
            ChapterDecision(0, True, "intro"),
            ChapterDecision(1, True, "body"),
        ],
    )

    kept, decisions = select_chapters(
        None,
        None,
        chapters,
        book_title="Demo",
        selection=selection,
        staging_dir=tmp_path,
    )
    assert [c.index for c in kept] == [0, 1]
    assert decisions[0].keep is True
    assert decisions[1].keep is True


def test_select_chapters_without_cache_requires_llm(tmp_path: Path) -> None:
    chapters = [
        Chapter(index=0, title="Intro", text="Hello world " * 40, slug="intro"),
    ]
    try:
        select_chapters(
            None,
            None,
            chapters,
            book_title="Demo",
            selection=SelectionConfig(),
            staging_dir=tmp_path,
        )
    except RuntimeError as exc:
        assert "LLM" in str(exc)
    else:
        raise AssertionError("expected RuntimeError without cache or model")
