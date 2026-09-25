"""Fixtures for the document shapes this pipeline has to read aloud."""

from text2audiobook.cleanup import split_chapter_sections
from text2audiobook.config import DEFAULT_CLEAN_PROMPT
from text2audiobook.formats.html_extract import extract_html_chapters
from text2audiobook.formatting import format_for_tts
from text2audiobook.io import Chapter
from text2audiobook.structure import (
    parse_html_blocks,
    parse_plain_document,
    strip_pdf_furniture,
)


def _chapter(blocks: list, text: str = "") -> Chapter:
    return Chapter(index=0, title="Chapter", slug="chapter", text=text, blocks=blocks)


def test_indesign_footnote_stays_linked_and_keeps_mixed_note() -> None:
    html = """
    <html><body>
      <p>Movements etch ontogenesis over the earth.
        <span class="FN-REF"><a class="FN_REF" href="#footnote-005">1</a></span>
        The series stays finite.
      </p>
      <div class="_idFootnote" id="footnote-005">
        <p class="FOOTNOTE"><a href="#footnote-005-backlink">1</a>.
          See Deleuze and Guattari, A Thousand Plateaus
          (Minneapolis: University of Minnesota Press, 1987), 12.
          The distinction matters because desire here is machinic.
        </p>
      </div>
    </body></html>
    """
    blocks = parse_html_blocks(html)
    notes = [block for block in blocks if block.kind == "footnote"]
    assert len(notes) == 1
    assert "machinic" in notes[0].text
    assert "University of Minnesota Press" in notes[0].text
    assert notes[0].parent_id
    sections = split_chapter_sections(_chapter(blocks))
    body = next(section for section in sections if section.kind == "body")
    foot = next(section for section in sections if section.kind == "footnote")
    assert "etch ontogenesis" in body.text
    assert "stays finite" in body.text
    assert sections.index(foot) == sections.index(body) + 1
    assert "1" not in body.text.split()


def test_calibre_notes_without_a_notes_heading_stay_separate() -> None:
    html = """
    <html><body>
      <p>The term <a id="footnote1"></a><sup><a href="#bookmark1">1</a></sup>
      returns from the future.</p>
      <p>Capital dissolves <a id="footnote2"></a><sup><a href="#bookmark2">2</a></sup>
      its own form.</p>
      <p><a id="bookmark1"></a><a href="#footnote1">1</a> Land, Circuitries, 1992.</p>
      <p><a id="bookmark2"></a><a href="#footnote2">2</a> Marx, Grundrisse, on fixed capital as a scientific process.</p>
    </body></html>
    """
    blocks = parse_html_blocks(html)
    notes = [block for block in blocks if block.kind == "footnote"]
    assert [note.note_number for note in notes] == ["1", "2"]
    assert "Circuitries" in notes[0].text
    assert "Grundrisse" in notes[1].text
    assert "Circuitries" not in notes[1].text
    bodies = [block.text for block in blocks if block.kind == "paragraph"]
    assert any("returns from the future" in text for text in bodies)
    assert all(not text.strip().isdigit() for text in bodies)


def test_html_essay_without_anchors_invents_no_footnotes() -> None:
    filler = " ".join(f"word{i}" for i in range(40))
    html = f"""
    <html><body>
      <article>
        <h1>Capitalism is AI</h1>
        <p>Technics thinks about itself. The year 1992 is not a footnote. {filler}</p>
        <p>Comment threads stay ordinary paragraphs. {filler}</p>
      </article>
    </body></html>
    """
    blocks = parse_html_blocks(html)
    assert blocks
    assert all(block.kind != "footnote" for block in blocks)
    assert any("1992" in block.text for block in blocks)
    assert any(block.kind == "heading" and "Capitalism is AI" in block.text for block in blocks)
    chapters = extract_html_chapters(html, preamble_title="Essay")
    assert chapters
    assert all(
        block.kind != "footnote"
        for chapter in chapters
        for block in (chapter.blocks or [])
    )


def test_pdf_furniture_and_section_numbers_are_not_footnotes() -> None:
    pages = [
        "The Apoptosis of Belief 12\n"
        "PPL-UK_NU-Brassier_ch001.qxd  8/13/2007  3:42 PM  Page 12\n"
        "The Apoptosis of Belief1\n"
        "1.1 The manifest image stays a heading\n"
        "Sellars proposes a diagnosis.\n",
        "The Apoptosis of Belief 13\n"
        "Page 13\n"
        "The argument continues here with enough words to remain prose.\n",
    ]
    cleaned = strip_pdf_furniture(pages)
    joined = "\n".join(cleaned)
    assert "qxd" not in joined.lower()
    assert "The Apoptosis of Belief 12" not in joined
    assert "Page 13" not in joined
    assert "1.1 The manifest image stays a heading" in joined

    plain = (
        "The Apoptosis of Belief1\n"
        "1.1 The manifest image stays a heading\n"
        "Sellars proposes a diagnosis.\n\n"
        "Notes\n"
        "1\n. A substantive note about belief and the manifest image.\n"
    )
    blocks = parse_plain_document(plain)
    headings = [block.text for block in blocks if block.kind == "heading"]
    assert any(text.startswith("1.1 ") for text in headings)
    notes = [block for block in blocks if block.kind == "footnote"]
    assert len(notes) == 1
    assert notes[0].note_number == "1"
    bodies = " ".join(block.text for block in blocks if block.kind == "paragraph")
    assert "Belief1" not in bodies
    assert "Belief" in bodies


def test_long_note_follows_the_whole_paragraph() -> None:
    html = """
    <html><body>
      <p>The argument runs long, and the marker sits here
        <a class="FN_REF" href="#fn-9">9</a>
        before the sentence actually ends. A second sentence stays in the same paragraph.
      </p>
      <div class="_idFootnote" id="fn-9">
        <p>9. This note is long enough to hold an argument about why the marker
        must not cut the sentence in half for a listener.</p>
      </div>
    </body></html>
    """
    sections = split_chapter_sections(_chapter(parse_html_blocks(html)))
    body = next(section for section in sections if section.kind == "body")
    foot = next(section for section in sections if section.kind == "footnote")
    assert "marker sits here" in body.text
    assert "second sentence stays" in body.text
    assert sections.index(body) < sections.index(foot)
    assert "cut the sentence" in foot.text


def test_clean_prompt_asks_for_speech_not_deleted_endnotes() -> None:
    assert "Delete bibliography" not in DEFAULT_CLEAN_PROMPT
    assert "Footnote." in DEFAULT_CLEAN_PROMPT
    assert "This note looks bibliographic." in DEFAULT_CLEAN_PROMPT
    spoken = format_for_tts(
        "Main claim.\n\nFootnote 2.\nThis note looks bibliographic.\nSee Land, Circuitries."
    )
    assert "looks bibliographic" not in spoken.lower()
    assert "Main claim." in spoken
