from pathlib import Path

import pytest

from text2audiobook import formats  # noqa: F401
from text2audiobook.formats.markdown import extract_chapters, markdown_to_text
from text2audiobook.io import find_sources, parse_source

_LONG = " ".join(f"word{i}" for i in range(40))


def test_extract_chapters_splits_all_heading_levels() -> None:
    content = f"""# Part One

{_LONG}

## Scene A

{_LONG}

### Beat

{_LONG}

# Part Two

{_LONG}
"""
    chapters = extract_chapters(content, preamble_title="Book")
    titles = [chapter.title for chapter in chapters]
    assert titles == ["Part One", "Scene A", "Beat", "Part Two"]


def test_extract_chapters_omits_short_preamble() -> None:
    content = f"""Short intro.

# Chapter One

{_LONG}
"""
    chapters = extract_chapters(content, preamble_title="Book")
    assert [chapter.title for chapter in chapters] == ["Chapter One"]


def test_extract_chapters_includes_long_preamble() -> None:
    preamble = " ".join(f"word{i}" for i in range(40))
    content = f"{preamble}\n\n# Chapter One\n\n{_LONG}"
    chapters = extract_chapters(content, preamble_title="Preface")
    assert chapters[0].title == "Preface"
    assert chapters[1].title == "Chapter One"


def test_markdown_to_text_strips_markup() -> None:
    raw = "See [docs](https://example.com) and **bold** `code`."
    assert markdown_to_text(raw) == "See docs and bold code."


def test_find_sources_finds_epub_and_markdown(tmp_path: Path) -> None:
    (tmp_path / "book.epub").write_bytes(b"not a real epub")
    (tmp_path / "notes.md").write_text("# Hi\n\n", encoding="utf-8")
    sources = find_sources(tmp_path)
    assert {path.name for path in sources} == {"book.epub", "notes.md"}


def test_parse_source_dispatches_markdown(tmp_path: Path) -> None:
    md_path = tmp_path / "story.md"
    md_path.write_text(f"# Title\n\n{_LONG}", encoding="utf-8")
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    metadata, chapters = parse_source(md_path, staging_root=staging, output_root=output)
    assert metadata.title == "Title"
    assert metadata.author == "Unknown Author"
    assert len(chapters) == 1
    assert chapters[0].title == "Title"


def test_extract_chapters_filters_short_sections() -> None:
    content = f"""# Long Chapter

{_LONG}

## Tiny

three words only
"""
    chapters = extract_chapters(content, preamble_title="Book")
    assert [chapter.title for chapter in chapters] == ["Long Chapter"]


def test_extract_chapters_raises_when_empty() -> None:
    with pytest.raises(ValueError, match="No readable chapters"):
        extract_chapters("## Too short", preamble_title="Book")
