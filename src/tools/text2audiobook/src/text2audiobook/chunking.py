"""Two chunkers: word windows for LLM formatting, character units for TTS."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from text2audiobook.io import Chapter
from text2audiobook.formatting import normalize_speak_text

logger = logging.getLogger(__name__)

_HARD_BREAK_RE = re.compile(r"(?<=[;:—–])\s+")
_COMMA_BREAK_RE = re.compile(r"(?<=,)\s+")

_punkt_ready = False


@dataclass
class TextChunk:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    chunk_index: int
    text: str
    source_kind: str = "ebook"
    instruct: str | None = None


def _ensure_punkt() -> None:
    global _punkt_ready
    if _punkt_ready:
        return
    import nltk

    nltk.download("punkt", quiet=True)
    nltk.download("punkt_tab", quiet=True)
    _punkt_ready = True


def split_sentences(text: str) -> list[str]:
    _ensure_punkt()
    from nltk.tokenize import sent_tokenize

    return [s.strip() for s in sent_tokenize(text) if s.strip()]


def char_count(text: str) -> int:
    """Character count used for speak-unit packing (includes spaces)."""
    return len(text)


def chunk_sentences(text: str, words_per_chunk: int) -> list[str]:
    """Pack whole sentences up to words_per_chunk words per chunk.

    A sentence is only split mid-sentence when it alone exceeds the limit; its
    tail then seeds the next chunk so following sentences pack onto it.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    def flush() -> None:
        nonlocal current, current_words
        if current:
            chunks.append(" ".join(current))
            current = []
            current_words = 0

    for sentence in split_sentences(text):
        words = sentence.split()
        if len(words) > words_per_chunk:
            flush()
            start = 0
            while len(words) - start > words_per_chunk:
                chunks.append(" ".join(words[start : start + words_per_chunk]))
                start += words_per_chunk
            current = [" ".join(words[start:])]
            current_words = len(words) - start
            continue
        if current_words + len(words) > words_per_chunk:
            flush()
        current.append(sentence)
        current_words += len(words)

    flush()
    return chunks


def chunk_sentences_by_chars(
    text: str,
    *,
    target_chars: int = 400,
    max_chars: int = 800,
    count_fn: Callable[[str], int] | None = None,
) -> list[str]:
    """Pack sentences toward target_chars without exceeding max_chars.

    Over-long sentences split on ; : em-dash first, then commas, then words.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if target_chars < 1:
        target_chars = max_chars
    target_chars = min(target_chars, max_chars)
    count = count_fn or char_count

    units: list[str] = []
    current: list[str] = []

    def current_text() -> str:
        return " ".join(current)

    def flush() -> None:
        if current:
            units.append(current_text())
            current.clear()

    for sentence in split_sentences(text):
        for piece in _split_overlong(sentence, max_chars, count):
            if not current:
                current.append(piece)
                continue
            candidate = f"{current_text()} {piece}"
            candidate_count = count(candidate)
            if candidate_count <= target_chars:
                current.append(piece)
            elif candidate_count <= max_chars and count(current_text()) < target_chars:
                current.append(piece)
                flush()
            else:
                flush()
                current.append(piece)
                if count(current_text()) >= target_chars:
                    flush()

    flush()
    return units


def _split_overlong(
    sentence: str,
    max_chars: int,
    count: Callable[[str], int],
) -> list[str]:
    if count(sentence) <= max_chars:
        return [sentence]
    parts = [piece.strip() for piece in _HARD_BREAK_RE.split(sentence) if piece.strip()]
    if len(parts) == 1:
        parts = [piece.strip() for piece in _COMMA_BREAK_RE.split(sentence) if piece.strip()]
    if len(parts) == 1:
        words = sentence.split()
        packed: list[str] = []
        current: list[str] = []
        for word in words:
            trial = " ".join(current + [word])
            if current and count(trial) > max_chars:
                packed.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            packed.append(" ".join(current))
        return packed
    packed = []
    current: list[str] = []
    for part in parts:
        trial = " ".join(current + [part])
        if current and count(trial) > max_chars:
            packed.append(" ".join(current))
            current = [part]
            if count(part) > max_chars:
                packed.extend(_split_overlong(part, max_chars, count))
                current = []
        else:
            current.append(part)
    if current:
        packed.append(" ".join(current))
    return packed


def further_split(
    units: list[TextChunk],
    *,
    over_budget: Callable[[str], bool],
    split_text: Callable[[str], list[str]],
) -> list[TextChunk]:
    """Keep units under budget; only subdivide oversized ones. Never merge.

    Child units inherit ``instruct`` from their parent format window.
    """
    out: list[TextChunk] = []
    for unit in units:
        if not over_budget(unit.text):
            out.append(
                TextChunk(
                    chapter_index=unit.chapter_index,
                    chapter_title=unit.chapter_title,
                    chapter_slug=unit.chapter_slug,
                    chunk_index=len(out),
                    text=unit.text,
                    source_kind=unit.source_kind,
                    instruct=unit.instruct,
                )
            )
            continue
        for piece in split_text(unit.text):
            if not piece.strip():
                continue
            out.append(
                TextChunk(
                    chapter_index=unit.chapter_index,
                    chapter_title=unit.chapter_title,
                    chapter_slug=unit.chapter_slug,
                    chunk_index=len(out),
                    text=piece,
                    source_kind=unit.source_kind,
                    instruct=unit.instruct,
                )
            )
    # Re-number chunk_index per chapter for stable speak/format resumes.
    by_chapter: dict[int, int] = {}
    renumbered: list[TextChunk] = []
    for unit in out:
        index = by_chapter.get(unit.chapter_index, 0)
        by_chapter[unit.chapter_index] = index + 1
        renumbered.append(
            TextChunk(
                chapter_index=unit.chapter_index,
                chapter_title=unit.chapter_title,
                chapter_slug=unit.chapter_slug,
                chunk_index=index,
                text=unit.text,
                source_kind=unit.source_kind,
                instruct=unit.instruct,
            )
        )
    return renumbered


def build_chunks(
    chapters: list[Chapter],
    words_per_chunk: int,
    *,
    max_chunks_per_chapter: int | None = None,
    source_kind: str = "ebook",
) -> list[TextChunk]:
    seeds = [
        TextChunk(
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            chapter_slug=chapter.slug,
            chunk_index=0,
            text=chapter.text,
            source_kind=source_kind,
        )
        for chapter in chapters
    ]
    chunks = further_split(
        seeds,
        over_budget=lambda text: len(text.split()) > words_per_chunk,
        split_text=lambda text: chunk_sentences(text, words_per_chunk),
    )
    if max_chunks_per_chapter is None:
        return chunks
    capped: list[TextChunk] = []
    counts: dict[int, int] = {}
    for chunk in chunks:
        used = counts.get(chunk.chapter_index, 0)
        if used >= max_chunks_per_chapter:
            continue
        counts[chunk.chapter_index] = used + 1
        capped.append(chunk)
    return capped


def build_chunks_from_sections(
    sections: list,
    words_per_chunk: int,
    *,
    max_chunks_per_chapter: int | None = None,
    source_kind: str = "ebook",
) -> list[TextChunk]:
    """Further-split clean sections by word budget without rematching chapters."""
    seeds = [
        TextChunk(
            chapter_index=section.chapter_index,
            chapter_title=section.chapter_title,
            chapter_slug=section.chapter_slug,
            chunk_index=section.section_index,
            text=section.text,
            source_kind=source_kind,
        )
        for section in sections
    ]
    chunks = further_split(
        seeds,
        over_budget=lambda text: len(text.split()) > words_per_chunk,
        split_text=lambda text: chunk_sentences(text, words_per_chunk),
    )
    if max_chunks_per_chapter is None:
        return chunks
    capped: list[TextChunk] = []
    counts: dict[int, int] = {}
    for chunk in chunks:
        used = counts.get(chunk.chapter_index, 0)
        if used >= max_chunks_per_chapter:
            continue
        counts[chunk.chapter_index] = used + 1
        capped.append(chunk)
    return capped


def build_speak_units(
    chapters: list[Chapter],
    *,
    target_chars: int,
    max_chars: int,
    source_kind: str = "ebook",
    count_fn: Callable[[str], int] | None = None,
) -> list[TextChunk]:
    seeds = [
        TextChunk(
            chapter_index=chapter.index,
            chapter_title=chapter.title,
            chapter_slug=chapter.slug,
            chunk_index=0,
            text=chapter.text,
            source_kind=source_kind,
        )
        for chapter in chapters
    ]
    return build_speak_units_from_chunks(
        seeds,
        target_chars=target_chars,
        max_chars=max_chars,
        count_fn=count_fn,
    )


def build_speak_units_from_chunks(
    format_units: list[TextChunk],
    *,
    target_chars: int,
    max_chars: int,
    count_fn: Callable[[str], int] | None = None,
) -> list[TextChunk]:
    """Further-split prior format units by character budget; never rematch.

    Speak units are whitespace-normalized (newlines → spaces) so TTS never
    sees paragraph breaks. Format windows must keep newlines — do not call
    ``normalize_speak_text`` from shared ``further_split``.
    """
    count = count_fn or char_count

    def split_text(text: str) -> list[str]:
        return chunk_sentences_by_chars(
            text,
            target_chars=target_chars,
            max_chars=max_chars,
            count_fn=count,
        )

    units = further_split(
        format_units,
        over_budget=lambda text: count(text) > max_chars,
        split_text=split_text,
    )
    normalized: list[TextChunk] = []
    for unit in units:
        text = normalize_speak_text(unit.text)
        if not text:
            continue
        normalized.append(
            TextChunk(
                chapter_index=unit.chapter_index,
                chapter_title=unit.chapter_title,
                chapter_slug=unit.chapter_slug,
                chunk_index=unit.chunk_index,
                text=text,
                source_kind=unit.source_kind,
                instruct=unit.instruct,
            )
        )
    # Re-number after dropping empties so chunk_index stays dense per chapter.
    by_chapter: dict[int, int] = {}
    renumbered: list[TextChunk] = []
    for unit in normalized:
        index = by_chapter.get(unit.chapter_index, 0)
        by_chapter[unit.chapter_index] = index + 1
        renumbered.append(
            TextChunk(
                chapter_index=unit.chapter_index,
                chapter_title=unit.chapter_title,
                chapter_slug=unit.chapter_slug,
                chunk_index=index,
                text=unit.text,
                source_kind=unit.source_kind,
                instruct=unit.instruct,
            )
        )
    return renumbered
