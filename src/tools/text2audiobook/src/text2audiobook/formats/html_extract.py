"""Shared HTML extraction and h1/h2 chapter splitting for web/local HTML."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from text2audiobook.formats.markdown import extract_chapters as extract_markdown_chapters
from text2audiobook.io import BookMetadata, Chapter, finalize_metadata
from text2audiobook.structure import parse_plain_document

_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "aside",
    "form",
    "button",
    "iframe",
)
# Site chrome only — keep <header>/<footer> inside article/main (e.g. WP entry-header).
_CHROME_TAGS = ("header", "footer")
# Marks real h1/h2 lines so literal "#" in page text is not treated as ATX.
_HEADING_MARK = "\ue000"


def title_from_filename(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip().title() or "Untitled"


def _node_text(node: Tag | BeautifulSoup) -> str:
    text = node.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _pick_content_root(soup: BeautifulSoup) -> Tag:
    for selector in ("article", "main", '[role="main"]'):
        found = soup.select_one(selector)
        if found is not None:
            return found
    body = soup.body
    return body if body is not None else soup


def _inside_content_root(tag: Tag, roots: list[Tag]) -> bool:
    for root in roots:
        if tag is root:
            return True
        if any(parent is root for parent in tag.parents):
            return True
    return False


def prepare_html_soup(html: str | bytes) -> BeautifulSoup:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    content_roots = soup.select("article, main, [role='main']")
    for tag in list(soup.find_all(_CHROME_TAGS)):
        if content_roots and _inside_content_root(tag, content_roots):
            continue
        tag.decompose()
    return soup


def page_title(soup: BeautifulSoup, *, fallback: str) -> str:
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        if title:
            return title
    h1 = soup.find("h1")
    if h1 is not None:
        text = _node_text(h1).strip()
        if text:
            return text
    return fallback


def html_to_markdownish(html: str | bytes) -> str:
    """Strip chrome and turn h1/h2 into ATX headings for the Markdown splitter."""
    soup = prepare_html_soup(html)
    root = _pick_content_root(soup)

    for heading in list(root.find_all(["h1", "h2"])):
        level = 1 if heading.name == "h1" else 2
        title = _node_text(heading).strip() or "Untitled"
        heading.replace_with(
            NavigableString(f"\n\n{_HEADING_MARK}{'#' * level} {title}\n\n")
        )

    text = _node_text(root)
    # Literal "# …" lines in body/pre/code must not become chapters.
    text = re.sub(r"(?m)^(#{1,6}\s)", r" \1", text)
    text = text.replace(_HEADING_MARK, "")
    # Collapse excessive blank lines
    lines = [line.rstrip() for line in text.splitlines()]
    collapsed: list[str] = []
    blank = 0
    for line in lines:
        if not line.strip():
            blank += 1
            if blank <= 2:
                collapsed.append("")
            continue
        blank = 0
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def extract_html_chapters(html: str | bytes, *, preamble_title: str) -> list[Chapter]:
    content = html_to_markdownish(html)
    try:
        chapters = extract_markdown_chapters(content, preamble_title=preamble_title)
    except ValueError as exc:
        raise ValueError("No readable chapters found in HTML") from exc
    for chapter in chapters:
        chapter.blocks = parse_plain_document(chapter.text)
    return chapters


def metadata_from_html(
    html: str | bytes,
    *,
    staging_root: Path,
    output_root: Path,
    fallback_title: str,
    author: str = "Unknown Author",
    title_override: str | None = None,
) -> BookMetadata:
    soup = prepare_html_soup(html)
    title = title_override.strip() if title_override else page_title(soup, fallback=fallback_title)
    return finalize_metadata(
        title=title,
        author=author,
        language="en",
        cover_bytes=None,
        staging_root=staging_root,
        output_root=output_root,
    )


def parse_html_document(
    html: str | bytes,
    *,
    staging_root: Path,
    output_root: Path,
    fallback_title: str,
    author: str = "Unknown Author",
    title_override: str | None = None,
) -> tuple[BookMetadata, list[Chapter]]:
    metadata = metadata_from_html(
        html,
        staging_root=staging_root,
        output_root=output_root,
        fallback_title=fallback_title,
        author=author,
        title_override=title_override,
    )
    chapters = extract_html_chapters(html, preamble_title=fallback_title)
    cache_path = metadata.staging_dir / "source.html"
    if isinstance(html, bytes):
        cache_path.write_bytes(html)
    else:
        cache_path.write_text(html, encoding="utf-8")
    return metadata, chapters
