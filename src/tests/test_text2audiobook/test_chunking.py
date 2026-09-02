from text2audiobook.chunking import build_chunks, chunk_sentences
from text2audiobook.io import Chapter


def test_chunk_sentences_respects_word_limit() -> None:
    text = "One two three. Four five six seven eight. Nine ten."
    chunks = chunk_sentences(text, words_per_chunk=5)
    assert len(chunks) >= 2
    assert all(len(chunk.split()) <= 5 for chunk in chunks)
    assert sum(len(chunk.split()) for chunk in chunks) == len(text.split())


def test_build_chunks_caps_per_chapter() -> None:
    chapters = [
        Chapter(index=0, title="Intro", text=" ".join(f"word{i}" for i in range(100)), slug="intro")
    ]
    chunks = build_chunks(chapters, words_per_chunk=20, max_chunks_per_chapter=2)
    assert len(chunks) == 2
    assert chunks[0].chapter_slug == "intro"
