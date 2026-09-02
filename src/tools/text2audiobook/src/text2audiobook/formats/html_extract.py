"""Shared HTML extraction and h1/h2 chapter splitting for web/local HTML."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from text2audiobook.formats.markdown import extract_chapters as extract_markdown_chapters
from text2audiobook.io import BookMetadata, Chapter, finalize_metadata

_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "iframe",
)


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


def prepare_html_soup(html: str | bytes) -> BeautifulSoup:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_STRIP_TAGS):
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
        heading.replace_with(NavigableString(f"\n\n{'#' * level} {title}\n\n"))

    text = _node_text(root)
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
        return extract_markdown_chapters(content, preamble_title=preamble_title)
    except ValueError as exc:
        raise ValueError("No readable chapters found in HTML") from exc


def metadata_from_html(
    html: str | bytes,
    *,
    staging_root: Path,
    output_root: Path,
    fallback_title: str,
    author: str = "Unknown Author",
) -> BookMetadata:
    soup = prepare_html_soup(html)
    title = page_title(soup, fallback=fallback_title)
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
) -> tuple[BookMetadata, list[Chapter]]:
    metadata = metadata_from_html(
        html,
        staging_root=staging_root,
        output_root=output_root,
        fallback_title=fallback_title,
        author=author,
    )
    chapters = extract_html_chapters(html, preamble_title=fallback_title)
    cache_path = metadata.staging_dir / "source.html"
    if isinstance(html, bytes):
        cache_path.write_bytes(html)
    else:
        cache_path.write_text(html, encoding="utf-8")
    return metadata, chapters
