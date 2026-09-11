"""Tests for the deterministic clean stage (split + scrub)."""

import re

from text2audiobook.cleanup import (
    FOOTNOTE_END_MARKER,
    clean_chapters,
    split_chapter_sections,
)
from text2audiobook.cli import main
from text2audiobook.formatting import FOOTNOTE_SPOKEN_MARKER
from text2audiobook.io import Chapter


def test_split_places_discursive_footnote_after_sentence() -> None:
    chapter = Chapter(
        index=4,
        title="Topology of Bobbles",
        slug="topology",
        text=(
            "Cuddles have no interiority.\n"
            "36\n"
            "Cute stays cryptic.\n\n"
            "Notes\n"
            "35\n. Harris, Cute, Quaint, Hungry and Romantic, 20.\n"
            "36\n. Discursive note about eggmen and language after the crack."
        ),
    )
    sections = split_chapter_sections(chapter)
    kinds = [section.kind for section in sections]
    assert "footnote" in kinds
    assert all(section.section_index == index for index, section in enumerate(sections))
    body0 = next(section for section in sections if section.kind == "body")
    foot = next(section for section in sections if section.kind == "footnote")
    assert "Cuddles have no interiority." in body0.text
    assert re.search(r"(?m)^\s*\.\s*$", body0.text) is None
    assert foot.note_number == "36"
    assert FOOTNOTE_SPOKEN_MARKER not in foot.text
    assert FOOTNOTE_END_MARKER not in foot.text
    assert "Discursive note about eggmen" in foot.text
    cued = split_chapter_sections(chapter, speak_footnote_cues=True)
    cued_foot = next(section for section in cued if section.kind == "footnote")
    assert FOOTNOTE_SPOKEN_MARKER in cued_foot.text
    assert FOOTNOTE_END_MARKER in cued_foot.text
    assert "Harris" not in "\n".join(section.text for section in sections)
    # Footnote section follows the body section that contained the callout.
    assert sections.index(foot) == sections.index(body0) + 1


def test_newline_before_capital_ends_unit_for_footnote() -> None:
    """Attribution lines without '.' still end the unit when the next line is a new sentence."""
    chapter = Chapter(
        index=2,
        title="Kawaiizome",
        slug="kawaiizome",
        text=(
            "Love, honor, and serve degeneracy wherever it surfaces.\n"
            "William Burroughs\n"
            "1\n"
            "The two of us rode cute/acc together.\n\n"
            "Notes\n"
            "1\n. Discursive note about the Burroughs attribution and Massumi."
        ),
    )
    sections = split_chapter_sections(chapter)
    assert [s.kind for s in sections[:3]] == ["body", "footnote", "body"]
    assert "William Burroughs" in sections[0].text
    assert "cute/acc together" not in sections[0].text
    assert sections[1].note_number == "1"
    assert "cute/acc together" in sections[2].text


def test_mid_sentence_callout_waits_for_sentence_end() -> None:
    chapter = Chapter(
        index=4,
        title="Topology",
        slug="topology",
        text=(
            "everything flowers on a swollen superflatness,\n"
            "38\n"
            "and for the superficionado, there’s nothing underneath.\n\n"
            "Notes\n"
            "38\n. Discursive note about Murakami superflat aesthetics in detail here."
        ),
    )
    sections = split_chapter_sections(chapter)
    body = next(s for s in sections if s.kind == "body")
    foot = next(s for s in sections if s.kind == "footnote")
    assert "superflatness" in body.text
    assert "superficionado" in body.text
    assert sections.index(foot) == sections.index(body) + 1


def test_clean_chapters_drops_reference_only_chapter() -> None:
    chapters = [
        Chapter(index=0, title="One", text="Narrative stays here.", slug="one"),
        Chapter(
            index=1,
            title="References",
            text="Mark Fisher (2012). Terminator vs Avatar, p. 342.",
            slug="references",
        ),
    ]
    sections = clean_chapters(chapters)
    assert {section.chapter_slug for section in sections} == {"one"}


def test_cli_clean_flag_is_recognized() -> None:
    # argparse accepts --clean; list-voices path proves parser wiring without GPU.
    assert main(["--list-voices"]) == 0
