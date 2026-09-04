"""v2 staging stems: extract / format / speak manifests and skip fingerprints."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from text2audiobook.io import Chapter

logger = logging.getLogger(__name__)

STEM_VERSION = 2
PIPELINE_STAGES = ("extract", "format", "speak")


@dataclass(frozen=True)
class BookStems:
    root: Path

    @property
    def extract_dir(self) -> Path:
        return self.root / "extract"

    @property
    def format_dir(self) -> Path:
        return self.root / "format"

    @property
    def speak_dir(self) -> Path:
        return self.root / "speak"

    @property
    def extract_manifest(self) -> Path:
        return self.extract_dir / "manifest.json"

    @property
    def format_manifest(self) -> Path:
        return self.format_dir / "manifest.json"

    @property
    def speak_manifest(self) -> Path:
        return self.speak_dir / "manifest.json"

    @property
    def chapters_json(self) -> Path:
        return self.extract_dir / "chapters.json"

    @property
    def format_chunks_jsonl(self) -> Path:
        return self.format_dir / "chunks.jsonl"

    @property
    def format_chapters_index(self) -> Path:
        return self.format_dir / "chapters.json"

    @property
    def format_chapter_dir(self) -> Path:
        return self.format_dir / "chapters"

    @property
    def speak_units_jsonl(self) -> Path:
        return self.speak_dir / "units.jsonl"

    @property
    def speak_wav_dir(self) -> Path:
        return self.speak_dir / "wav"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tmp_path.replace(path)


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.debug("Ignoring invalid JSON at %s", path)
        return None


def manifest_matches(path: Path, expected: dict[str, Any]) -> bool:
    data = read_json(path)
    if not isinstance(data, dict):
        return False
    return all(data.get(key) == value for key, value in expected.items())


def chapters_to_payload(chapters: list[Chapter]) -> list[dict[str, Any]]:
    return [
        {
            "index": chapter.index,
            "title": chapter.title,
            "text": chapter.text,
            "slug": chapter.slug,
        }
        for chapter in chapters
    ]


def chapters_from_payload(payload: list[dict[str, Any]]) -> list[Chapter]:
    return [
        Chapter(
            index=int(item["index"]),
            title=str(item["title"]),
            text=str(item["text"]),
            slug=str(item["slug"]),
        )
        for item in payload
    ]


def load_extract_chapters(stems: BookStems) -> list[Chapter]:
    payload = read_json(stems.chapters_json)
    if not isinstance(payload, list):
        raise FileNotFoundError(f"Extract stem missing chapters at {stems.chapters_json}")
    return chapters_from_payload(payload)


def save_extract_chapters(stems: BookStems, chapters: list[Chapter]) -> None:
    write_json(stems.chapters_json, chapters_to_payload(chapters))


def format_script_filename(chapter_index: int, slug: str) -> str:
    """Zero-padded index prefix so directory listing matches narration order."""
    return f"{int(chapter_index):04d}_{slug}.txt"


def format_script_path(stems: BookStems, chapter_index: int, slug: str) -> Path:
    """Resolve a chapter script path; fall back to legacy unprefixed slug.txt."""
    preferred = stems.format_chapter_dir / format_script_filename(chapter_index, slug)
    if preferred.exists():
        return preferred
    legacy = stems.format_chapter_dir / f"{slug}.txt"
    return preferred if not legacy.exists() else legacy


def save_format_script(stems: BookStems, chapter: Chapter, text: str) -> None:
    path = stems.format_chapter_dir / format_script_filename(chapter.index, chapter.slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    legacy = stems.format_chapter_dir / f"{chapter.slug}.txt"
    if legacy != path and legacy.exists():
        legacy.unlink()


def load_format_scripts(stems: BookStems) -> list[Chapter]:
    index = read_json(stems.format_chapters_index)
    if not isinstance(index, list):
        raise FileNotFoundError(
            f"Format stem missing chapter index at {stems.format_chapters_index}"
        )
    chapters: list[Chapter] = []
    for item in index:
        slug = str(item["slug"])
        chapter_index = int(item["index"])
        path = format_script_path(stems, chapter_index, slug)
        if not path.exists():
            raise FileNotFoundError(f"Format stem missing script {path}")
        chapters.append(
            Chapter(
                index=chapter_index,
                title=str(item["title"]),
                text=path.read_text(encoding="utf-8"),
                slug=slug,
            )
        )
    return chapters


def format_scripts_hash(stems: BookStems) -> str:
    """Hash merged chapter scripts so speak invalidates when format output changes."""
    index = read_json(stems.format_chapters_index)
    if not isinstance(index, list):
        return ""
    parts = []
    for item in index:
        slug = str(item["slug"])
        chapter_index = int(item["index"])
        path = format_script_path(stems, chapter_index, slug)
        parts.append(
            {
                "index": chapter_index,
                "slug": slug,
                "sha256": file_sha256(path) if path.exists() else "",
            }
        )
    return stable_hash(parts)


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.debug("Skipping malformed JSONL line in %s", path)
    return rows


def canonical_stages(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not values:
        return PIPELINE_STAGES
    unknown = [item for item in values if item not in PIPELINE_STAGES]
    if unknown:
        raise ValueError(
            f"Unknown stage(s) {unknown}. Choose from: {', '.join(PIPELINE_STAGES)}"
        )
    return tuple(stage for stage in PIPELINE_STAGES if stage in set(values))
