"""Tests for PDF source reader."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pypdf import PdfReader, PdfWriter

from text2audiobook import formats  # noqa: F401
from text2audiobook.formats.pdf import (
    OutlineEntry,
    _assert_extractable_text,
    _page_ranges_from_outline,
    _sections_from_page_headings,
    _word_count,
    extract_cover_bytes,
    extract_chapters,
)
from text2audiobook.io import find_sources, parse_source

BRASSIER_PDF = (
    Path(__file__).resolve().parents[2]
    / "tools/text2audiobook/data/input/ray-brassier-nihil-unbound-enlightenment-and-extinction.pdf"
)
_LONG = " ".join(f"word{i}" for i in range(40))
_PNG_12K = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
    b"\x00\x02\x00\x01\xe5'\xd4\xfc\x00\x00\x00\x00IEND\xaeB`\x82"
) + (b"\x00" * 12_000)


def _blank_pdf(page_count: int = 3) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_is_cover_image_accepts_large_png() -> None:
    from text2audiobook.formats.pdf import _is_cover_image

    assert _is_cover_image(_PNG_12K)
    assert not _is_cover_image(_PNG_12K[:100])


def test_find_sources_finds_pdf_and_epub(tmp_path: Path) -> None:
    (tmp_path / "book.epub").write_bytes(b"not a real epub")
    (tmp_path / "notes.pdf").write_bytes(_blank_pdf(1))
    sources = find_sources(tmp_path)
    assert {path.name for path in sources} == {"book.epub", "notes.pdf"}


def test_assert_extractable_text_rejects_blank_pdf() -> None:
    reader = PdfReader(io.BytesIO(_blank_pdf(5)))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    with pytest.raises(ValueError, match="No extractable text"):
        _assert_extractable_text(page_texts)


def test_page_ranges_from_outline() -> None:
    entries = [
        OutlineEntry(title="Preface", page=10),
        OutlineEntry(title="Chapter 1", page=20),
        OutlineEntry(title="Chapter 2", page=30),
    ]
    ranges = _page_ranges_from_outline(entries, page_count=40)
    assert ranges == [
        ("Preface", 10, 19),
        ("Chapter 1", 20, 29),
        ("Chapter 2", 30, 39),
    ]


def test_sections_from_page_headings() -> None:
    filler = _LONG
    page_texts = [
        filler,
        f"Chapter 1\n\n{filler}",
        filler,
        f"Chapter 2\n\n{filler}",
    ]
    sections = _sections_from_page_headings(page_texts)
    assert sections is not None
    titles = [title for title, _text in sections]
    assert titles == ["Chapter 1", "Chapter 2"]
    assert all(_word_count(text) >= 30 for _title, text in sections)


def test_extract_chapters_from_page_headings_without_outline() -> None:
    filler = _LONG
    page_texts = [
        filler,
        f"Preface\n\n{filler}",
        f"Chapter 1\n\n{filler}",
    ]
    reader = MagicMock()
    reader.outline = None
    chapters = extract_chapters(reader, page_texts)
    assert [chapter.title for chapter in chapters] == ["Preface", "Chapter 1"]


def test_extract_cover_bytes_from_page_images() -> None:
    page = MagicMock()
    image = MagicMock()
    image.data = _PNG_12K
    page.images = [image]
    reader = MagicMock()
    reader.outline = None
    reader.pages = [page]
    cover = extract_cover_bytes(reader)
    assert cover == _PNG_12K


def test_parse_source_dispatches_pdf_with_outline(tmp_path: Path) -> None:
    if not BRASSIER_PDF.is_file():
        pytest.skip("Brassier PDF fixture not present")

    staging = tmp_path / "staging"
    output = tmp_path / "output"
    metadata, chapters = parse_source(
        BRASSIER_PDF,
        staging_root=staging,
        output_root=output,
    )
    assert "Nihil Unbound" in metadata.title
    assert metadata.author == "Ray Brassier"
    assert metadata.cover_bytes is not None
    assert len(metadata.cover_bytes) >= 10_000
    assert metadata.cover_bytes.startswith(b"\x89PNG") or metadata.cover_bytes.startswith(
        b"\xff\xd8\xff"
    )

    chapter_titles = [chapter.title for chapter in chapters]
    chapter_count = sum(1 for title in chapter_titles if title.startswith("Chapter "))
    assert chapter_count >= 7
    assert _word_count("\n".join(chapter.text for chapter in chapters)) > 50_000

    assert (metadata.staging_dir / "source.pdf").is_file()
    cover_files = list(metadata.staging_dir.glob("cover.*"))
    assert cover_files


def test_parse_source_brassier_outline_depth(tmp_path: Path) -> None:
    if not BRASSIER_PDF.is_file():
        pytest.skip("Brassier PDF fixture not present")

    _metadata, chapters = parse_source(
        BRASSIER_PDF,
        staging_root=tmp_path / "staging",
        output_root=tmp_path / "output",
    )
    preface = next((ch for ch in chapters if ch.title == "Preface"), None)
    assert preface is not None
    assert _word_count(preface.text) >= 30
