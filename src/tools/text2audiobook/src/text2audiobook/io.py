"""Shared source types, discovery, and pluggable format readers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MIN_SECTION_WORDS = 30


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


@dataclass
class Chapter:
    index: int
    title: str
    text: str
    slug: str


def finalize_metadata(
    *,
    title: str,
    author: str,
    language: str,
    cover_bytes: bytes | None,
    staging_root: Path,
    output_root: Path,
) -> BookMetadata:
    slug = slugify(title)
    staging_dir = Path(staging_root) / slug
    staging_dir.mkdir(parents=True, exist_ok=True)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    return BookMetadata(
        title=title,
        author=author,
        language=language,
        cover_bytes=cover_bytes,
        slug=slug,
        staging_dir=staging_dir,
        m4b_path=output_root / f"{slug}.m4b",
    )


def assign_chapter_slugs(chapters: list[tuple[str, str]]) -> list[Chapter]:
    """Build Chapter list from (title, text) pairs with unique slugs."""
    result: list[Chapter] = []
    seen_slugs: set[str] = set()
    for index, (title, text) in enumerate(chapters):
        base_slug = slugify(title)
        slug = base_slug
        suffix = 2
        while slug in seen_slugs:
            slug = f"{base_slug}_{suffix}"
            suffix += 1
        seen_slugs.add(slug)
        result.append(Chapter(index=index, title=title, text=text, slug=slug))
    return result


class SourceReader(Protocol):
    @property
    def suffixes(self) -> frozenset[str]: ...

    def read(
        self, path: Path, *, staging_root: Path, output_root: Path
    ) -> tuple[BookMetadata, list[Chapter]]: ...


_READERS: dict[str, SourceReader] = {}


def register_reader(reader: SourceReader) -> None:
    for suffix in reader.suffixes:
        _READERS[suffix.lower()] = reader


def supported_suffixes() -> frozenset[str]:
    return frozenset(_READERS)


def find_sources(input_dir: Path) -> list[Path]:
    """Every supported source file under input_dir (recursive), sorted by path."""
    if not _READERS:
        raise RuntimeError("No source readers registered")

    if not input_dir.exists():
        suffix_list = ", ".join(sorted(supported_suffixes()))
        raise FileNotFoundError(
            f"No input directory at {input_dir.resolve()}. "
            f"Create it and add a supported file ({suffix_list})."
        )

    sources: list[Path] = []
    for suffix in sorted(supported_suffixes()):
        sources.extend(input_dir.rglob(f"*{suffix}"))
    sources = sorted(set(sources))
    if not sources:
        suffix_list = ", ".join(sorted(supported_suffixes()))
        raise FileNotFoundError(
            f"No supported files found under {input_dir.resolve()} ({suffix_list})"
        )
    return sources


def parse_source(
    path: Path, *, staging_root: Path, output_root: Path
) -> tuple[BookMetadata, list[Chapter]]:
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        supported = ", ".join(sorted(supported_suffixes()))
        raise ValueError(f"Unsupported source type {path.suffix!r} (supported: {supported})")
    return reader.read(path, staging_root=staging_root, output_root=output_root)
