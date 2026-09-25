"""Deterministic clean stage: link paragraphs to footnotes, then scrub print junk.

Runs after extract and before LLM format. Artifacts live under ``clean/`` so the
split and scrub can be inspected before any model rewrite.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from text2audiobook.formatting import (
    FOOTNOTE_SPOKEN_MARKER,
    _is_resume_heading,
    expand_abbreviations,
    expand_dates,
    expand_example_parentheticals,
    expand_section_marks,
    expand_symbols,
    is_references_heading,
    replace_tables_and_figures,
    visual_reference,
    _collapse_whitespace,
)
from text2audiobook.io import Block, Chapter
from text2audiobook.structure import parse_plain_document

CLEANER_VERSION = "4"
FOOTNOTE_END_MARKER = "End of footnote."

_URL_RE = re.compile(
    r"""
    <\s*https?://[^>\s]+>
    | https?://[^\s<>\]]+
    | www\.[^\s<>\]]+
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class CleanSection:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    section_index: int
    kind: str  # "body" | "footnote"
    text: str
    note_number: str | None = None
    block_id: str | None = None
    parent_id: str | None = None
    bibliographic_hint: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "chapter_index": self.chapter_index,
            "chapter_title": self.chapter_title,
            "chapter_slug": self.chapter_slug,
            "section_index": self.section_index,
            "kind": self.kind,
            "note_number": self.note_number,
            "block_id": self.block_id,
            "parent_id": self.parent_id,
            "bibliographic_hint": self.bibliographic_hint,
            "text": self.text,
            "text_hash": text_hash(self.text),
        }


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text)


def format_footnote_section_text(
    body: str,
    *,
    speak_footnote_cues: bool = False,
) -> str:
    stripped = body.strip()
    if not speak_footnote_cues:
        return stripped
    return f"{FOOTNOTE_SPOKEN_MARKER}\n{stripped}\n{FOOTNOTE_END_MARKER}"


def apply_deterministic_cleanup(
    text: str,
    *,
    chapter_title: str = "",
    source_kind: str = "ebook",
    kind: str = "body",
    speak_footnote_cues: bool = False,
) -> str:
    """Scrub print conventions from an already-split body or footnote section."""
    text = strip_urls(text)
    text = replace_tables_and_figures(
        text, chapter_title=chapter_title, source_kind=source_kind
    )
    # Citation wording is a format-stage decision. Clean only scrubs print junk.
    text = expand_section_marks(text)
    text = expand_dates(text)
    text = expand_abbreviations(text)
    text = expand_example_parentheticals(text)
    text = expand_symbols(text)
    text = _collapse_whitespace(text)
    if kind == "footnote":
        # Strip cues before optionally re-wrapping so scrubbing never doubles them.
        body = text
        if body.startswith(FOOTNOTE_SPOKEN_MARKER):
            body = body[len(FOOTNOTE_SPOKEN_MARKER) :].strip()
        if body.endswith(FOOTNOTE_END_MARKER):
            body = body[: -len(FOOTNOTE_END_MARKER)].strip()
        return format_footnote_section_text(
            body, speak_footnote_cues=speak_footnote_cues
        )
    return text


def _sections_from_blocks(
    chapter: Chapter,
    blocks: list[Block],
    *,
    source_kind: str,
    speak_footnote_cues: bool,
) -> list[CleanSection]:
    """Scrub blocks in order. Notes stay attached to the paragraph that cites them.

    Bibliographic notes are kept. ``bibliographic_hint`` records the guess so the
    format stage can compress them without the clean stage deleting the argument.
    """
    skipping_refs = False
    kept: list[Block] = []
    for block in blocks:
        if block.kind == "heading" and is_references_heading(block.text):
            skipping_refs = True
            continue
        if skipping_refs:
            if block.kind == "heading" and _is_resume_heading(block.text):
                skipping_refs = False
            else:
                continue
        if block.kind in {"table", "figure"}:
            text = block.text.strip() or visual_reference(
                "figure" if block.kind == "figure" else "table",
                title=None,
                chapter_title=chapter.title,
                source_kind=source_kind,
            )
            kept.append(
                Block(
                    id=block.id,
                    kind="paragraph",
                    text=text,
                    note_refs=list(block.note_refs or []),
                    parent_id=block.parent_id,
                )
            )
            continue
        kept.append(block)

    sections: list[CleanSection] = []
    for block in kept:
        if block.kind == "footnote":
            cleaned = apply_deterministic_cleanup(
                format_footnote_section_text(
                    block.text, speak_footnote_cues=speak_footnote_cues
                ),
                chapter_title=chapter.title,
                source_kind=source_kind,
                kind="footnote",
                speak_footnote_cues=speak_footnote_cues,
            )
            kind = "footnote"
        else:
            cleaned = apply_deterministic_cleanup(
                block.text,
                chapter_title=chapter.title,
                source_kind=source_kind,
                kind="body",
            )
            kind = "body"
        if not cleaned.strip():
            continue
        sections.append(
            CleanSection(
                chapter_index=chapter.index,
                chapter_title=chapter.title,
                chapter_slug=chapter.slug,
                section_index=len(sections),
                kind=kind,
                text=cleaned,
                note_number=block.note_number,
                block_id=block.id,
                parent_id=block.parent_id,
                bibliographic_hint=block.bibliographic_hint,
            )
        )
    return sections


def split_chapter_sections(
    chapter: Chapter,
    *,
    source_kind: str = "ebook",
    speak_footnote_cues: bool = False,
) -> list[CleanSection]:
    """Split one chapter into body and footnote sections in reading order.

    Notes follow the paragraph that references them. Citation-only notes are
    kept, with ``bibliographic_hint`` set. Spoken start/end markers wrap
    footnote sections when ``speak_footnote_cues`` is true.
    """
    if is_references_heading(chapter.title):
        return []

    blocks = chapter.blocks if chapter.blocks is not None else parse_plain_document(chapter.text)
    return _sections_from_blocks(
        chapter,
        blocks,
        source_kind=source_kind,
        speak_footnote_cues=speak_footnote_cues,
    )


def clean_chapters(
    chapters: list[Chapter],
    *,
    source_kind: str = "ebook",
    speak_footnote_cues: bool = False,
) -> list[CleanSection]:
    """Run split + deterministic cleanup for every non-reference chapter."""
    sections: list[CleanSection] = []
    for chapter in chapters:
        sections.extend(
            split_chapter_sections(
                chapter,
                source_kind=source_kind,
                speak_footnote_cues=speak_footnote_cues,
            )
        )
    return sections


def chapters_from_clean_sections(sections: list[CleanSection]) -> list[Chapter]:
    """Merge cleaned sections back into Chapter objects (inspect/debug helper)."""
    order: list[tuple[int, str, str]] = []
    texts: dict[int, list[str]] = {}
    for section in sections:
        if section.chapter_index not in texts:
            texts[section.chapter_index] = []
            order.append(
                (section.chapter_index, section.chapter_title, section.chapter_slug)
            )
        texts[section.chapter_index].append(section.text)
    return [
        Chapter(
            index=index,
            title=title,
            slug=slug,
            text="\n\n".join(texts[index]).strip(),
        )
        for index, title, slug in order
        if texts[index]
    ]


def prepare_chapters_for_tts(
    chapters: list[Chapter],
    *,
    source_kind: str = "ebook",
    speak_footnote_cues: bool = False,
) -> list[Chapter]:
    """Compatibility wrapper: clean-stage split/scrub, then merge to chapters."""
    return chapters_from_clean_sections(
        clean_chapters(
            chapters,
            source_kind=source_kind,
            speak_footnote_cues=speak_footnote_cues,
        )
    )
