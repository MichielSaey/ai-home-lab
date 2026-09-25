"""EPUB metadata and chapter extraction (with real TOC titles)."""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import unquote

import ebooklib
from ebooklib import epub

from text2audiobook.io import (
    MIN_SECTION_WORDS,
    BookMetadata,
    Chapter,
    assign_chapter_slugs,
    finalize_metadata,
)
from text2audiobook.structure import parse_html_blocks, render_blocks


def html_to_text(content: bytes | str) -> str:
    """Flat text for inspection. Structure lives on the chapter blocks."""
    return render_blocks(parse_html_blocks(content))


def _normalize_href(href: str) -> str:
    href = unquote(href.split("#", 1)[0]).strip()
    if not href:
        return ""
    return posixpath.normpath(href).lstrip("/")


def _walk_toc(nodes: Iterable) -> Iterator[tuple[str, str]]:
    """Yield (href, title) pairs from ebooklib's nested toc structure."""
    for node in nodes:
        if isinstance(node, (list, tuple)):
            if len(node) == 2 and not isinstance(node[0], (list, tuple)):
                section, children = node
                href = getattr(section, "href", "") or ""
                title = getattr(section, "title", "") or ""
                if href and title:
                    yield href, title
                if isinstance(children, (list, tuple)):
                    yield from _walk_toc(children)
            else:
                yield from _walk_toc(node)
        else:
            href = getattr(node, "href", "") or ""
            title = getattr(node, "title", "") or ""
            if href and title:
                yield href, title


def toc_title_map(epub_book: epub.EpubBook) -> dict[str, str]:
    """Map normalized document hrefs (and basenames) to TOC titles."""
    titles: dict[str, str] = {}
    for href, title in _walk_toc(epub_book.toc or []):
        key = _normalize_href(href)
        title = title.strip()
        if not key or not title:
            continue
        titles.setdefault(key, title)
        titles.setdefault(posixpath.basename(key), title)
    return titles


def extract_chapters(epub_book: epub.EpubBook) -> list[Chapter]:
    """All readable document sections, titled from the TOC when possible."""
    toc_titles = toc_title_map(epub_book)
    sections: list[tuple[str, str]] = []
    block_lists: list = []
    chapter_idx = 0

    for item in epub_book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        blocks = parse_html_blocks(item.get_content())
        text = render_blocks(blocks)
        if len(text.split()) < MIN_SECTION_WORDS:
            continue

        name = _normalize_href(item.get_name())
        title = toc_titles.get(name) or toc_titles.get(posixpath.basename(name))
        if not title:
            stem = Path(item.get_name()).stem.replace("_", " ").strip()
            title = stem.title() if stem else f"Chapter {chapter_idx + 1}"

        sections.append((title, text))
        block_lists.append(blocks)
        chapter_idx += 1

    if not sections:
        raise ValueError("No readable chapters found in EPUB")

    chapters = assign_chapter_slugs(sections)
    for chapter, blocks in zip(chapters, block_lists):
        chapter.blocks = blocks
    return chapters


def metadata_from_epub(
    epub_book: epub.EpubBook,
    staging_root: Path,
    output_root: Path,
) -> BookMetadata:
    title = epub_book.get_metadata("DC", "title")
    author = epub_book.get_metadata("DC", "creator")
    language = epub_book.get_metadata("DC", "language")

    title = title[0][0] if title else "Unknown Title"
    author = author[0][0] if author else "Unknown Author"
    language = language[0][0] if language else "en"

    cover_bytes = None
    for item in epub_book.get_items_of_type(ebooklib.ITEM_COVER):
        cover_bytes = item.get_content()
        break
    if cover_bytes is None:
        for item in epub_book.get_items_of_type(ebooklib.ITEM_IMAGE):
            if "cover" in item.get_name().lower():
                cover_bytes = item.get_content()
                break

    return finalize_metadata(
        title=title,
        author=author,
        language=language,
        cover_bytes=cover_bytes,
        staging_root=staging_root,
        output_root=output_root,
    )


class EpubReader:
    @property
    def suffixes(self) -> frozenset[str]:
        return frozenset({".epub"})

    def read(
        self, path: Path, *, staging_root: Path, output_root: Path, force_fetch: bool = False
    ) -> tuple[BookMetadata, list[Chapter]]:
        del force_fetch
        book = epub.read_epub(str(path))
        metadata = metadata_from_epub(book, staging_root, output_root)
        chapters = extract_chapters(book)
        return metadata, chapters
