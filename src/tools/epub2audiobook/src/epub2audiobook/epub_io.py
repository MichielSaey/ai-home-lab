"""EPUB discovery, metadata, and chapter extraction (with real TOC titles)."""

import posixpath
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

MIN_SECTION_WORDS = 30


def find_epubs(epub_dir: Path) -> list[Path]:
    """Every .epub under epub_dir (recursive), sorted by path."""
    if not epub_dir.exists():
        raise FileNotFoundError(
            f"No EPUB directory at {epub_dir.resolve()}. "
            "Create it and add a .epub file."
        )
    epubs = sorted(epub_dir.rglob("*.epub"))
    if not epubs:
        raise FileNotFoundError(f"No .epub files found under {epub_dir.resolve()}")
    return epubs


def read_book(epub_path: Path) -> epub.EpubBook:
    return epub.read_epub(str(epub_path))


def slugify(text: str, max_len: int = 80) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text).strip("_")
    return text[:max_len] or "untitled"


@dataclass
class BookMetadata:
    title: str
    author: str
    language: str
    cover_bytes: bytes | None
    slug: str
    staging_dir: Path
    m4b_path: Path


def get_metadata(
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

    slug = slugify(title)
    staging_dir = Path(staging_root) / slug
    staging_dir.mkdir(parents=True, exist_ok=True)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    m4b_path = output_root / f"{slug}.m4b"

    return BookMetadata(
        title=title,
        author=author,
        language=language,
        cover_bytes=cover_bytes,
        slug=slug,
        staging_dir=staging_dir,
        m4b_path=m4b_path,
    )


@dataclass
class Chapter:
    index: int
    title: str
    text: str
    slug: str


def html_to_text(content: bytes | str) -> str:
    # EPUB chapter files are XHTML (XML), not plain HTML.
    try:
        soup = BeautifulSoup(content, features="xml")
    except Exception:
        soup = BeautifulSoup(content, "lxml")

    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


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
    """Map normalized document hrefs (and basenames) to TOC titles.

    First occurrence wins: the first nav/NCX entry pointing into a file is
    that file's chapter title.
    """
    titles: dict[str, str] = {}
    for href, title in _walk_toc(epub_book.toc or []):
        key = _normalize_href(href)
        title = title.strip()
        if not key or not title:
            continue
        titles.setdefault(key, title)
        titles.setdefault(posixpath.basename(key), title)
    return titles


def extract_all_chapters(epub_book: epub.EpubBook) -> list[Chapter]:
    """All readable document sections, titled from the TOC when possible."""
    toc_titles = toc_title_map(epub_book)
    chapters: list[Chapter] = []
    seen_slugs: set[str] = set()
    chapter_idx = 0

    for item in epub_book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        text = html_to_text(item.get_content())
        if len(text.split()) < MIN_SECTION_WORDS:
            continue

        name = _normalize_href(item.get_name())
        title = toc_titles.get(name) or toc_titles.get(posixpath.basename(name))
        if not title:
            stem = Path(item.get_name()).stem.replace("_", " ").strip()
            title = stem.title() if stem else f"Chapter {chapter_idx + 1}"

        base_slug = slugify(title)
        slug = base_slug
        suffix = 2
        while slug in seen_slugs:
            slug = f"{base_slug}_{suffix}"
            suffix += 1
        seen_slugs.add(slug)

        chapters.append(Chapter(index=chapter_idx, title=title, text=text, slug=slug))
        chapter_idx += 1

    if not chapters:
        raise ValueError("No readable chapters found in EPUB")

    return chapters
