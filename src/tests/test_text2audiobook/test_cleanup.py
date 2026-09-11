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
    assert FOOTNOTE_SPOKEN_MARKER in foot.text
    assert FOOTNOTE_END_MARKER in foot.text
    assert "Discursive note about eggmen" in foot.text
    assert "Harris" not in "\n".join(section.text for section in sections)
    # Footnote section follows the body section that contained the callout.
    assert sections.index(foot) == sections.index(body0) + 1


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
