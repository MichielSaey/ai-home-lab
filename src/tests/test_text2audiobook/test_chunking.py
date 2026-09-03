from text2audiobook.chunking import (
    build_chunks,
    chunk_sentences,
    chunk_sentences_by_phonemes,
)
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


def test_phoneme_packer_stays_under_cap() -> None:
    text = "Short one. Another short sentence. Third sentence here."
    units = chunk_sentences_by_phonemes(
        text,
        target_phonemes=20,
        max_phonemes=40,
        count_fn=len,
    )
    assert units
    assert all(len(unit) <= 40 for unit in units)
    assert " ".join(units).replace("  ", " ")
    joined = " ".join(units)
    for word in text.replace(".", "").split():
        assert word in joined


def test_phoneme_packer_splits_semicolon_before_comma() -> None:
    long_piece = "aaaa; " + ("b" * 12) + ", " + ("c" * 12)
    units = chunk_sentences_by_phonemes(
        long_piece,
        target_phonemes=10,
        max_phonemes=20,
        count_fn=len,
    )
    assert len(units) >= 2
    assert all(len(unit) <= 20 for unit in units)

