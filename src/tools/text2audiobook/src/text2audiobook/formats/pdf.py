"""PDF metadata, cover extraction, and chapter splitting from outlines or page heuristics."""

from __future__ import annotations

import logging
import re
import shutil
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader as PyPdfReader

_PYPDF_FONT_LOGGER = "pypdf._cmap"


@contextmanager
def _quiet_pypdf_font_warnings():
    """Publisher PDFs with CFF Type1 fonts spam pypdf._cmap warnings per page."""
    logger = logging.getLogger(_PYPDF_FONT_LOGGER)
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)

from text2audiobook.formats.html_extract import title_from_filename
from text2audiobook.structure import parse_plain_document, strip_pdf_furniture
from text2audiobook.io import (
    MIN_SECTION_WORDS,
    BookMetadata,
    Chapter,
    assign_chapter_slugs,
    finalize_metadata,
)

_MIN_COVER_BYTES = 10_000
_MIN_TEXT_WORDS = 200
_COVER_TITLE_RE = re.compile(r"\bcover\b", re.IGNORECASE)
_CHAPTER_HEADING_RE = re.compile(
    r"^(?:Chapter\s+\d+|Preface|Introduction|Acknowledgements?)\b",
    re.IGNORECASE,
)
_CHAPTER_OUTLINE_RE = re.compile(
    r"^(?:Chapter\s+\d+|Preface|Introduction|Acknowledgements?)\b",
    re.IGNORECASE,
)
_INDEX_LETTER_RE = re.compile(r"^[A-Z]$")


def _is_cover_image(data: bytes) -> bool:
    if len(data) < _MIN_COVER_BYTES:
        return False
    if data.startswith(b"\xff\xd8\xff"):
        return True
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _cover_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    return ".jpg"


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=\w)", "", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_page_texts(reader: PyPdfReader) -> list[str]:
    pages: list[str] = []
    for page in reader.pages:
        raw = page.extract_text() or ""
        pages.append(_normalize_text(raw))
    return pages


def _word_count(text: str) -> int:
    return len(text.split())


def _images_on_page(page) -> list[bytes]:
    images: list[bytes] = []
    for image in page.images:
        try:
            images.append(image.data)
        except Exception:
            continue
    return images


def _best_cover_from_pages(reader: PyPdfReader, page_indices: Iterable[int]) -> bytes | None:
    best: bytes | None = None
    best_len = 0
    for index in page_indices:
        if index < 0 or index >= len(reader.pages):
            continue
        for data in _images_on_page(reader.pages[index]):
            if _is_cover_image(data) and len(data) > best_len:
                best = data
                best_len = len(data)
    return best


def _outline_cover_page(reader: PyPdfReader) -> int | None:
    outline = reader.outline
    if not outline:
        return None

    def walk(items: Iterable) -> int | None:
        for item in items:
            if isinstance(item, list):
                found = walk(item)
                if found is not None:
                    return found
                continue
            title = getattr(item, "title", "") or ""
            if _COVER_TITLE_RE.search(title.strip()):
                try:
                    return reader.get_destination_page_number(item)
                except Exception:
                    return None
        return None

    return walk(outline)


def extract_cover_bytes(reader: PyPdfReader) -> bytes | None:
    cover_page = _outline_cover_page(reader)
    if cover_page is not None:
        cover = _best_cover_from_pages(reader, [cover_page])
        if cover is not None:
            return cover
    return _best_cover_from_pages(reader, range(min(3, len(reader.pages))))


def _write_cover_cache(staging_dir: Path, cover_bytes: bytes) -> None:
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / f"cover{_cover_extension(cover_bytes)}").write_bytes(cover_bytes)


@dataclass(frozen=True)
class OutlineEntry:
    title: str
    page: int


def _outline_entries_at_depth(items: Iterable, reader: PyPdfReader, depth: int) -> list[OutlineEntry]:
    result: list[OutlineEntry] = []

    def walk(nodes: Iterable, current_depth: int = 0) -> None:
        for node in nodes:
            if isinstance(node, list):
                walk(node, current_depth + 1)
                continue
            if current_depth != depth:
                continue
            title = (getattr(node, "title", "") or "").strip()
            if not title:
                continue
            try:
                page = reader.get_destination_page_number(node)
            except Exception:
                continue
            result.append(OutlineEntry(title=title, page=page))

    walk(items)
    return result


def _outline_quality(entries: list[OutlineEntry]) -> tuple[int, int]:
    """Higher is better: (chapter_like_count, -index_letter_count)."""
    chapter_like = sum(1 for entry in entries if _CHAPTER_OUTLINE_RE.match(entry.title))
    index_letters = sum(1 for entry in entries if _INDEX_LETTER_RE.match(entry.title))
    return chapter_like, -index_letters


def _pick_outline_depth(reader: PyPdfReader) -> int | None:
    outline = reader.outline
    if not outline:
        return None

    candidates: list[tuple[int, list[OutlineEntry]]] = []
    for depth in range(4):
        entries = _outline_entries_at_depth(outline, reader, depth)
        if entries:
            candidates.append((depth, entries))

    if not candidates:
        return None

    depth_one = next((entries for depth, entries in candidates if depth == 1), None)
    if depth_one:
        chapter_like, _ = _outline_quality(depth_one)
        if chapter_like >= 2:
            return 1

    best_depth, _best_entries = max(candidates, key=lambda item: _outline_quality(item[1]))
    return best_depth


def _page_ranges_from_outline(
    entries: list[OutlineEntry],
    page_count: int,
) -> list[tuple[str, int, int]]:
    if not entries:
        return []

    sorted_entries = sorted(entries, key=lambda entry: entry.page)
    ranges: list[tuple[str, int, int]] = []
    for index, entry in enumerate(sorted_entries):
        start = entry.page
        if index + 1 < len(sorted_entries):
            end = max(start, sorted_entries[index + 1].page - 1)
        else:
            end = page_count - 1
        ranges.append((entry.title, start, end))
    return ranges


def _text_for_page_range(page_texts: list[str], start: int, end: int) -> str:
    chunk = page_texts[start : end + 1]
    return "\n\n".join(text for text in chunk if text)


def _merge_outline_entries(*groups: list[OutlineEntry]) -> list[OutlineEntry]:
    merged: list[OutlineEntry] = []
    seen_pages: set[int] = set()
    for group in groups:
        for entry in group:
            if entry.page in seen_pages:
                continue
            seen_pages.add(entry.page)
            merged.append(entry)
    return sorted(merged, key=lambda entry: entry.page)


def _depth_zero_front_matter(reader: PyPdfReader) -> list[OutlineEntry]:
    """Preface/intro at outline depth 0 when chapters live at depth 1."""
    entries = _outline_entries_at_depth(reader.outline, reader, 0)
    return [entry for entry in entries if _CHAPTER_OUTLINE_RE.match(entry.title)]


def _sections_from_outline(
    reader: PyPdfReader,
    page_texts: list[str],
) -> list[tuple[str, str]] | None:
    depth = _pick_outline_depth(reader)
    if depth is None:
        return None

    entries = _outline_entries_at_depth(reader.outline, reader, depth)
    if depth == 1:
        entries = _merge_outline_entries(_depth_zero_front_matter(reader), entries)
    ranges = _page_ranges_from_outline(entries, len(page_texts))
    sections: list[tuple[str, str]] = []
    for title, start, end in ranges:
        text = _text_for_page_range(page_texts, start, end)
        if _word_count(text) >= MIN_SECTION_WORDS:
            sections.append((title, text))
    return sections or None


def _page_heading(title_lines: list[str]) -> str | None:
    for line in title_lines:
        if _CHAPTER_HEADING_RE.match(line.strip()):
            return line.strip()
    return None


def _sections_from_page_headings(page_texts: list[str]) -> list[tuple[str, str]] | None:
    breaks: list[tuple[str, int]] = []
    for index, text in enumerate(page_texts):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        heading = _page_heading(lines[:5])
        if heading is not None:
            breaks.append((heading, index))

    if not breaks:
        return None

    sections: list[tuple[str, str]] = []
    for idx, (title, start) in enumerate(breaks):
        end = (breaks[idx + 1][1] - 1) if idx + 1 < len(breaks) else len(page_texts) - 1
        body = _text_for_page_range(page_texts, start, end)
        if _word_count(body) >= MIN_SECTION_WORDS:
            sections.append((title, body))
    return sections or None


def extract_chapters(reader: PyPdfReader, page_texts: list[str]) -> list[Chapter]:
    page_texts = strip_pdf_furniture(page_texts)
    sections = _sections_from_outline(reader, page_texts)
    if sections is None:
        sections = _sections_from_page_headings(page_texts)
    if sections is None:
        whole = "\n\n".join(text for text in page_texts if text)
        if _word_count(whole) < MIN_SECTION_WORDS:
            raise ValueError("No readable chapters found in PDF")
        sections = [("Document", whole)]

    if not sections:
        raise ValueError("No readable chapters found in PDF")

    chapters = assign_chapter_slugs(sections)
    for chapter in chapters:
        chapter.blocks = parse_plain_document(chapter.text)
    return chapters


def _metadata_strings(reader: PyPdfReader, path: Path) -> tuple[str, str, str]:
    meta = reader.metadata or {}
    title = str(meta.get("/Title") or "").strip() or title_from_filename(path)
    author = str(meta.get("/Author") or "").strip() or "Unknown Author"
    language = str(meta.get("/Lang") or meta.get("/Language") or "").strip() or "en"
    return title, author, language


def metadata_from_pdf(
    reader: PyPdfReader,
    path: Path,
    staging_root: Path,
    output_root: Path,
) -> BookMetadata:
    title, author, language = _metadata_strings(reader, path)
    cover_bytes = extract_cover_bytes(reader)
    metadata = finalize_metadata(
        title=title,
        author=author,
        language=language,
        cover_bytes=cover_bytes,
        staging_root=staging_root,
        output_root=output_root,
    )
    if cover_bytes is not None:
        _write_cover_cache(metadata.staging_dir, cover_bytes)
    return metadata


def _assert_extractable_text(page_texts: list[str]) -> None:
    total_words = _word_count("\n".join(page_texts))
    if len(page_texts) > 1 and total_words < _MIN_TEXT_WORDS:
        raise ValueError(
            "No extractable text in PDF (likely scanned/image-only). OCR is not supported."
        )


class PdfReader:
    @property
    def suffixes(self) -> frozenset[str]:
        return frozenset({".pdf"})

    def read(
        self, path: Path, *, staging_root: Path, output_root: Path, force_fetch: bool = False
    ) -> tuple[BookMetadata, list[Chapter]]:
        del force_fetch
        with _quiet_pypdf_font_warnings():
            reader = PyPdfReader(str(path))
            page_texts = _extract_page_texts(reader)
            _assert_extractable_text(page_texts)
            metadata = metadata_from_pdf(reader, path, staging_root, output_root)
            chapters = extract_chapters(reader, page_texts)
        cache_path = metadata.staging_dir / "source.pdf"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, cache_path)
        return metadata, chapters
