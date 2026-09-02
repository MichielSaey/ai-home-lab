"""Sentence-boundary chunking sized for Kokoro's input window."""

from dataclasses import dataclass

from text2audiobook.io import Chapter

_punkt_ready = False


@dataclass
class TextChunk:
    chapter_index: int
    chapter_title: str
    chapter_slug: str
    chunk_index: int
    text: str


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


def build_chunks(
    chapters: list[Chapter],
    words_per_chunk: int,
    *,
    max_chunks_per_chapter: int | None = None,
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
                )
            )
    return all_chunks
