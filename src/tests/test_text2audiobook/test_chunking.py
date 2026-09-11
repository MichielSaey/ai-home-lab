from text2audiobook.chunking import (
    TextChunk,
    build_chunks,
    build_chunks_from_sections,
    build_speak_units_from_chunks,
    chunk_sentences,
    chunk_sentences_by_chars,
    further_split,
)
from text2audiobook.cleanup import CleanSection
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


def test_further_split_preserves_unit_boundaries() -> None:
    units = [
        TextChunk(0, "A", "a", 0, "Short body."),
        TextChunk(0, "A", "a", 1, " ".join(f"word{i}." for i in range(30))),
    ]
    out = further_split(
        units,
        over_budget=lambda text: len(text.split()) > 10,
        split_text=lambda text: chunk_sentences(text, 10),
    )
    assert out[0].text == "Short body."
    assert all(len(unit.text.split()) <= 10 for unit in out[1:])
    assert len(out) > 2


def test_build_chunks_from_sections_does_not_rematch() -> None:
    sections = [
        CleanSection(1, "Ch", "ch", 0, "body", "Alpha sentence here."),
        CleanSection(1, "Ch", "ch", 1, "footnote", " ".join(f"note{i}" for i in range(40))),
    ]
    chunks = build_chunks_from_sections(sections, words_per_chunk=1000)
    assert len(chunks) == 2
    assert chunks[0].text == "Alpha sentence here."
    assert chunks[1].text.startswith("note0")


def test_speak_further_split_from_format_units() -> None:
    units = [
        TextChunk(0, "A", "a", 0, "Short."),
        TextChunk(0, "A", "a", 1, "Longer unit one. Longer unit two. Longer unit three."),
    ]
    spoken = build_speak_units_from_chunks(
        units,
        target_chars=8,
        max_chars=12,
        count_fn=len,
    )
    assert spoken[0].text == "Short."
    assert all(len(unit.text) <= 12 for unit in spoken)


def test_further_split_inherits_instruct() -> None:
    units = [
        TextChunk(
            0,
            "A",
            "a",
            0,
            " ".join(f"word{i}." for i in range(30)),
            instruct="Calm steady pace.",
        ),
    ]
    out = further_split(
        units,
        over_budget=lambda text: len(text.split()) > 10,
        split_text=lambda text: chunk_sentences(text, 10),
    )
    assert len(out) > 1
    assert all(unit.instruct == "Calm steady pace." for unit in out)


def test_char_packer_stays_under_cap() -> None:
    text = "Short one. Another short sentence. Third sentence here."
    units = chunk_sentences_by_chars(
        text,
        target_chars=20,
        max_chars=40,
        count_fn=len,
    )
    assert units
    assert all(len(unit) <= 40 for unit in units)
    assert " ".join(units).replace("  ", " ")
    joined = " ".join(units)
    for word in text.replace(".", "").split():
        assert word in joined


def test_char_packer_splits_semicolon_before_comma() -> None:
    long_piece = "aaaa; " + ("b" * 12) + ", " + ("c" * 12)
    units = chunk_sentences_by_chars(
        long_piece,
        target_chars=10,
        max_chars=20,
        count_fn=len,
    )
    assert len(units) >= 2
    assert all(len(unit) <= 20 for unit in units)
