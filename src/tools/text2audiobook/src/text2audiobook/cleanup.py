"""Deterministic clean stage: split body/footnotes, then scrub citations and print junk.

Runs after extract and before LLM format. Artifacts live under ``clean/`` so the
split and scrub can be inspected before any model rewrite.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from text2audiobook.chunking import split_sentences
from text2audiobook.formatting import (
    FOOTNOTE_SPOKEN_MARKER,
    _FOOTNOTE_CALLOUT_LINE_RE,
    _consume_footnote,
    _extract_notes_apparatus,
    _note_numbers_from_spec,
    _SEE_NOTE_NUM_RE,
    expand_abbreviations,
    expand_dates,
    expand_example_parentheticals,
    expand_section_marks,
    expand_symbols,
    is_citation_only_note,
    is_references_heading,
    replace_tables_and_figures,
    simplify_inline_citations,
    strip_reference_sections,
    _collapse_whitespace,
)
from text2audiobook.io import Chapter

CLEANER_VERSION = "1"
FOOTNOTE_END_MARKER = "End of footnote."

_FN_TOKEN_RE = re.compile(r"⟦FN:(\d+[a-z]?)⟧\.?")
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

    def to_json(self) -> dict[str, object]:
        return {
            "chapter_index": self.chapter_index,
            "chapter_title": self.chapter_title,
            "chapter_slug": self.chapter_slug,
            "section_index": self.section_index,
            "kind": self.kind,
            "note_number": self.note_number,
            "text": self.text,
            "text_hash": text_hash(self.text),
        }


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_urls(text: str) -> str:
    return _URL_RE.sub("", text)


def format_footnote_section_text(body: str) -> str:
    return f"{FOOTNOTE_SPOKEN_MARKER}\n{body.strip()}\n{FOOTNOTE_END_MARKER}"


def apply_deterministic_cleanup(
    text: str,
    *,
    chapter_title: str = "",
    source_kind: str = "ebook",
    kind: str = "body",
) -> str:
    """Scrub print conventions from an already-split body or footnote section."""
    text = strip_urls(text)
    text = replace_tables_and_figures(
        text, chapter_title=chapter_title, source_kind=source_kind
    )
    text = simplify_inline_citations(text)
    text = expand_section_marks(text)
    text = expand_dates(text)
    text = expand_abbreviations(text)
    text = expand_example_parentheticals(text)
    text = expand_symbols(text)
    text = _collapse_whitespace(text)
    if kind == "footnote":
        # Preserve spoken markers if cleanup collapsed them away.
        body = text
        if body.startswith(FOOTNOTE_SPOKEN_MARKER):
            body = body[len(FOOTNOTE_SPOKEN_MARKER) :].strip()
        if body.endswith(FOOTNOTE_END_MARKER):
            body = body[: -len(FOOTNOTE_END_MARKER)].strip()
        return format_footnote_section_text(body)
    return text


def _attach_callout_tokens(body: str) -> str:
    """Place footnote callouts as tokens; keep them after finished sentences."""
    lines_out: list[str] = []
    sentence_end = re.compile(r'[.!?…]["\'\)\]]*\s*$')
    for line in body.splitlines():
        if _FOOTNOTE_CALLOUT_LINE_RE.match(line):
            token = f"⟦FN:{line.strip()}⟧"
            if lines_out and sentence_end.search(lines_out[-1]):
                lines_out.append(token)
            elif lines_out:
                lines_out[-1] = f"{lines_out[-1].rstrip()} {token}"
            else:
                lines_out.append(token)
            continue
        lines_out.append(_SEE_NOTE_NUM_RE.sub(_see_note_to_tokens, line))
    return "\n".join(lines_out)


def _see_note_to_tokens(match: re.Match[str]) -> str:
    nums = _note_numbers_from_spec(match.group("nums"))
    if not nums:
        return ""
    return " " + " ".join(f"⟦FN:{num}⟧" for num in nums) + " "


def _sentence_note_numbers(sentence: str) -> list[str]:
    return [match.group(1) for match in _FN_TOKEN_RE.finditer(sentence)]


def _strip_fn_tokens(sentence: str) -> str:
    text = _FN_TOKEN_RE.sub("", sentence)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"(?m)^\s*\.\s*$", "", text)
    return text.strip()


def split_chapter_sections(
    chapter: Chapter,
    *,
    source_kind: str = "ebook",
) -> list[CleanSection]:
    """Split one chapter into body/footnote sections in reading order.

    Discursive notes are placed after the sentence that referenced them.
    Citation-only notes are dropped. Each footnote section is wrapped with
    spoken start/end markers for later verification and narration.
    """
    if is_references_heading(chapter.title):
        return []

    text = strip_reference_sections(chapter.text)
    body, preamble, entries = _extract_notes_apparatus(text)
    tokenized = _attach_callout_tokens(body)
    # Standalone callout tokens must be their own sentences for split order.
    tokenized = re.sub(r"(?m)^(⟦FN:\d+[a-z]?⟧)\s*$", r"\1.", tokenized)
    sentences = split_sentences(tokenized) if tokenized.strip() else []

    raw_sections: list[tuple[str, str | None, str]] = []
    body_parts: list[str] = []
    used: set[str] = set()

    def flush_body() -> None:
        nonlocal body_parts
        joined = "\n".join(part for part in body_parts if part).strip()
        body_parts = []
        if joined:
            raw_sections.append(("body", None, joined))

    for sentence in sentences:
        nums = _sentence_note_numbers(sentence)
        plain = _strip_fn_tokens(sentence)
        if plain:
            body_parts.append(plain)
        if not nums:
            continue
        flush_body()
        for num in nums:
            block = _consume_footnote(num, entries, used)
            if block is None:
                continue
            # _consume_footnote returns "Footnote.\\n{body}" — strip marker for storage.
            note_body = block
            if note_body.startswith(FOOTNOTE_SPOKEN_MARKER):
                note_body = note_body[len(FOOTNOTE_SPOKEN_MARKER) :].strip()
            raw_sections.append(("footnote", num, note_body))

    flush_body()

    if preamble and preamble.strip():
        raw_sections.append(("body", None, preamble.strip()))

    for num in sorted(entries, key=lambda value: int(re.sub(r"\D", "", value) or 0)):
        if num in used:
            continue
        note_body = entries[num]
        if is_citation_only_note(note_body):
            continue
        raw_sections.append(("footnote", num, note_body))

    sections: list[CleanSection] = []
    for section_index, (kind, note_number, raw_text) in enumerate(raw_sections):
        if kind == "footnote":
            cleaned = apply_deterministic_cleanup(
                format_footnote_section_text(raw_text),
                chapter_title=chapter.title,
                source_kind=source_kind,
                kind="footnote",
            )
        else:
            cleaned = apply_deterministic_cleanup(
                raw_text,
                chapter_title=chapter.title,
                source_kind=source_kind,
                kind="body",
            )
        if not cleaned.strip():
            continue
        sections.append(
            CleanSection(
                chapter_index=chapter.index,
                chapter_title=chapter.title,
                chapter_slug=chapter.slug,
                section_index=section_index,
                kind=kind,
                text=cleaned,
                note_number=note_number,
            )
        )
    # Re-number after dropping empties.
    return [
        CleanSection(
            chapter_index=section.chapter_index,
            chapter_title=section.chapter_title,
            chapter_slug=section.chapter_slug,
            section_index=index,
            kind=section.kind,
            text=section.text,
            note_number=section.note_number,
        )
        for index, section in enumerate(sections)
    ]


def clean_chapters(
    chapters: list[Chapter],
    *,
    source_kind: str = "ebook",
) -> list[CleanSection]:
    """Run split + deterministic cleanup for every non-reference chapter."""
    sections: list[CleanSection] = []
    for chapter in chapters:
        sections.extend(split_chapter_sections(chapter, source_kind=source_kind))
    return sections


def chapters_from_clean_sections(sections: list[CleanSection]) -> list[Chapter]:
    """Merge cleaned sections back into Chapter objects for format chunking."""
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
) -> list[Chapter]:
    """Compatibility wrapper: clean-stage split/scrub, then merge to chapters."""
    return chapters_from_clean_sections(
        clean_chapters(chapters, source_kind=source_kind)
    )
