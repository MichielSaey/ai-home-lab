"""Two chunkers: word windows for LLM formatting, phoneme units for Kokoro."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from text2audiobook.io import Chapter

logger = logging.getLogger(__name__)

PHONEMES_PER_WORD = 2.5
_HARD_BREAK_RE = re.compile(r"(?<=[;:—–])\s+")
_COMMA_BREAK_RE = re.compile(r"(?<=,)\s+")

_punkt_ready = False
_g2p_cache: dict[bool, object] = {}


@dataclass
class TextChunk:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    chunk_index: int
    text: str
    source_kind: str = "ebook"


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


def phoneme_count(text: str, *, british: bool = False) -> int:
    """Length of Kokoro's English phoneme string, with a 2.5/word fallback."""
    stripped = text.strip()
    if not stripped:
        return 0
    try:
        return _misaki_phoneme_len(stripped, british=british)
    except Exception:
        logger.debug("G2P unavailable; approximating phoneme count", exc_info=True)
        return max(1, round(len(stripped.split()) * PHONEMES_PER_WORD))


def _misaki_phoneme_len(text: str, *, british: bool) -> int:
    g2p = _g2p_cache.get(british)
    if g2p is None:
        from misaki import en

        g2p = en.G2P(british=british, unk="")
        _g2p_cache[british] = g2p
    phonemes, _tokens = g2p(text)
    if isinstance(phonemes, str):
        return len(phonemes.strip())
    joined = "".join(
        (getattr(token, "phonemes", None) or "")
        + (" " if getattr(token, "whitespace", "") else "")
        for token in _tokens
    ).strip()
    return len(joined)


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


def chunk_sentences_by_phonemes(
    text: str,
    *,
    target_phonemes: int = 160,
    max_phonemes: int = 400,
    british: bool = False,
    count_fn: Callable[[str], int] | None = None,
) -> list[str]:
    """Pack sentences toward target_phonemes without exceeding max_phonemes.

    Over-long sentences split on ; : em-dash first, then commas, then words.
    """
    if max_phonemes < 1:
        raise ValueError("max_phonemes must be positive")
    if target_phonemes < 1:
        target_phonemes = max_phonemes
    target_phonemes = min(target_phonemes, max_phonemes)
    count = count_fn or (lambda piece: phoneme_count(piece, british=british))

    units: list[str] = []
    current: list[str] = []

    def current_text() -> str:
        return " ".join(current)

    def flush() -> None:
        if current:
            units.append(current_text())
            current.clear()

    for sentence in split_sentences(text):
        for piece in _split_overlong(sentence, max_phonemes, count):
            if not current:
                current.append(piece)
                continue
            candidate = f"{current_text()} {piece}"
            candidate_count = count(candidate)
            if candidate_count <= target_phonemes:
                current.append(piece)
            elif candidate_count <= max_phonemes and count(current_text()) < target_phonemes:
                current.append(piece)
                flush()
            else:
                flush()
                current.append(piece)
                if count(current_text()) >= target_phonemes:
                    flush()

    flush()
    return units


def _split_overlong(
    sentence: str,
    max_phonemes: int,
    count: Callable[[str], int],
) -> list[str]:
    if count(sentence) <= max_phonemes:
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
            if current and count(trial) > max_phonemes:
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
        if current and count(trial) > max_phonemes:
            packed.append(" ".join(current))
            current = [part]
            if count(part) > max_phonemes:
                packed.extend(_split_overlong(part, max_phonemes, count))
                current = []
        else:
            current.append(part)
    if current:
        packed.append(" ".join(current))
    return packed


def build_chunks(
    chapters: list[Chapter],
    words_per_chunk: int,
    *,
    max_chunks_per_chapter: int | None = None,
    source_kind: str = "ebook",
) -> list[TextChunk]:
    all_chunks: list[TextChunk] = []
    for chapter in chapters:
        texts = chunk_sentences(chapter.text, words_per_chunk)
        if max_chunks_per_chapter is not None:
            texts = texts[:max_chunks_per_chapter]

        for i, chunk_text in enumerate(texts):
            all_chunks.append(
                TextChunk(
                    chapter_index=chapter.index,
                    chapter_title=chapter.title,
                    chapter_slug=chapter.slug,
                    chunk_index=i,
                    text=chunk_text,
                    source_kind=source_kind,
                )
            )
    return all_chunks


def build_speak_units(
    chapters: list[Chapter],
    *,
    target_phonemes: int,
    max_phonemes: int,
    british: bool = False,
    source_kind: str = "ebook",
    count_fn: Callable[[str], int] | None = None,
) -> list[TextChunk]:
    all_units: list[TextChunk] = []
    for chapter in chapters:
        texts = chunk_sentences_by_phonemes(
            chapter.text,
            target_phonemes=target_phonemes,
            max_phonemes=max_phonemes,
            british=british,
            count_fn=count_fn,
        )
        for i, unit_text in enumerate(texts):
            all_units.append(
                TextChunk(
                    chapter_index=chapter.index,
                    chapter_title=chapter.title,
                    chapter_slug=chapter.slug,
                    chunk_index=i,
                    text=unit_text,
                    source_kind=source_kind,
                )
            )
    return all_units
