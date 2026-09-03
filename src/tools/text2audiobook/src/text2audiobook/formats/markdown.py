"""Markdown metadata and chapter extraction from ATX headings."""

from __future__ import annotations

import re
from pathlib import Path

from text2audiobook.io import (
    MIN_SECTION_WORDS,
    BookMetadata,
    Chapter,
    assign_chapter_slugs,
    finalize_metadata,
)

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"^```")


def _heading_matches(content: str) -> list[re.Match[str]]:
    """ATX headings outside fenced code blocks (``` ... ```)."""
    in_fence = False
    matches: list[re.Match[str]] = []
    for line_match in re.finditer(r"^(.*)$", content, re.MULTILINE):
        line = line_match.group(1)
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING_RE.match(line)
        if heading is not None:
            # Re-bind match to absolute offsets in content
            absolute = _HEADING_RE.match(content, line_match.start())
            if absolute is not None:
                matches.append(absolute)
    return matches


def markdown_to_text(content: str) -> str:
    text = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _title_from_filename(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip().title() or "Untitled"


def _first_h1_title(content: str) -> str | None:
    for match in _heading_matches(content):
        prefix = match.group(0).lstrip()
        if prefix.startswith("#") and not prefix.startswith("##"):
            return match.group(1).strip()
    return None


def extract_chapters(content: str, *, preamble_title: str) -> list[Chapter]:
    """Split on every ATX heading (# through ######) outside code fences."""
    matches = _heading_matches(content)
    sections: list[tuple[str, str]] = []

    if matches and matches[0].start() > 0:
        preamble = markdown_to_text(content[: matches[0].start()])
        if len(preamble.split()) >= MIN_SECTION_WORDS:
            sections.append((preamble_title, preamble))

    for index, match in enumerate(matches):
        title = match.group(1).strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = markdown_to_text(content[body_start:body_end])
        if len(text.split()) < MIN_SECTION_WORDS:
            continue
        sections.append((title, text))

    if not sections:
        whole = markdown_to_text(content)
        if len(whole.split()) < MIN_SECTION_WORDS:
            raise ValueError("No readable chapters found in Markdown")
        sections.append((preamble_title, whole))

    return assign_chapter_slugs(sections)


def metadata_from_markdown(
    path: Path,
    content: str,
    staging_root: Path,
    output_root: Path,
) -> BookMetadata:
    title = _first_h1_title(content) or _title_from_filename(path)
    return finalize_metadata(
        title=title,
        author="Unknown Author",
        language="en",
        cover_bytes=None,
        staging_root=staging_root,
        output_root=output_root,
    )


class MarkdownReader:
    @property
    def suffixes(self) -> frozenset[str]:
        return frozenset({".md", ".markdown"})

    def read(
        self, path: Path, *, staging_root: Path, output_root: Path, force_fetch: bool = False
    ) -> tuple[BookMetadata, list[Chapter]]:
        del force_fetch
        content = path.read_text(encoding="utf-8")
        metadata = metadata_from_markdown(path, content, staging_root, output_root)
        chapters = extract_chapters(content, preamble_title=_title_from_filename(path))
        return metadata, chapters
