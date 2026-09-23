import logging
import re

from text2audiobook.chunking import TextChunk
from text2audiobook.config import DEFAULT_CLEAN_PROMPT, LlmConfig, load_config
from text2audiobook.formatting import (
    format_for_tts,
    prepare_chapters_for_tts,
    year_to_words,
)
from text2audiobook.io import Chapter
from text2audiobook.llm import clean_chunks_batched


def test_slash_date_is_spoken_in_full() -> None:
    assert format_for_tts("Meet on 03/09/2026.") == (
        "Meet on the third of September, twenty twenty-six."
    )


def test_unpadded_and_hyphen_dates() -> None:
    text = format_for_tts("Born 1/1/2000 or 31-12-1999.")
    assert "the first of January, two thousand" in text
    assert "the thirty-first of December, nineteen ninety-nine" in text


def test_invalid_dates_are_left_alone() -> None:
    assert "32/01/2020" in format_for_tts("On 32/01/2020 nothing happened.")


def test_non_leap_feb_29_is_left_alone() -> None:
    source = "On 29/02/2021 nothing happened."
    assert format_for_tts(source) == source


def test_leap_feb_29_is_spoken() -> None:
    assert format_for_tts("On 29/02/2020 it rained.") == (
        "On the twenty-ninth of February, twenty twenty it rained."
    )


def test_year_to_words_matches_narration() -> None:
    assert year_to_words(2012) == "twenty twelve"
    assert year_to_words(2026) == "twenty twenty-six"
    assert year_to_words(2008) == "two thousand eight"
    assert year_to_words(1907) == "nineteen oh seven"


def test_ie_and_ei_become_in_other_words() -> None:
    text = format_for_tts("The machine, e.i. the computer, failed. The map, i.e., the chart, did not.")
    assert "e.i." not in text.lower()
    assert "i.e." not in text.lower()
    assert text.count("in other words") == 2


def test_eg_becomes_for_example() -> None:
    assert "for example" in format_for_tts("Bring layers, e.g. a coat.")


def test_reference_section_is_removed() -> None:
    text = format_for_tts(
        "The argument ends here.\n\n## References\n\nMark Fisher (2012). Something, p. 1.\n"
    )
    assert "argument ends here." in text
    assert "References" not in text
    assert "Something" not in text


def test_plain_bibliography_heading_is_removed() -> None:
    text = format_for_tts("Keep this.\n\nBibliography\nFisher, Mark. 2012.")
    assert text == "Keep this."


def test_citation_only_endnote_is_dropped_but_notes_prose_kept() -> None:
    text = format_for_tts(
        "Cute remains cryptic.\n"
        "36\n"
        "and empty of sapience.\n\n"
        "Notes\n"
        "35\n. Harris,\nCute, Quaint, Hungry and Romantic\n, 20.\n"
        "36\n. Humpty Dumpty is a can(n)onical eggman and arche-grammatologist of "
        "language after the crack.\n",
        speak_footnote_cues=True,
    )
    assert "Harris" not in text
    assert "Footnote." in text
    assert text.index("Cute remains cryptic.") < text.index("Footnote.")
    assert text.index("Footnote.") < text.index("Humpty Dumpty")
    assert text.index("Humpty Dumpty") < text.index("and empty of sapience.")


def test_footnote_callout_and_see_note_are_stripped() -> None:
    text = format_for_tts(
        "Burikko is closer to aegyo [see note 55] and sajiao.\n"
        "34\n"
        "Cute diffuses across surfaces.\n\n"
        "Notes\n"
        "34\n. Harris, Cute, Quaint, Hungry and Romantic, 20.\n"
        "55\n. Ngai, Our Aesthetic Categories, 4."
    )
    assert "see note" not in text.lower()
    assert re.search(r"(?m)^34\s*$", text) is None
    assert "Harris" not in text
    assert "Ngai" not in text
    assert "Footnote." not in text
    assert "Burikko is closer to aegyo" in text
    assert "and sajiao." in text
    assert "Cute diffuses across surfaces." in text


def test_see_note_inserts_discursive_footnote() -> None:
    text = format_for_tts(
        "Burikko is closer to aegyo [see note 55] and sajiao.\n\n"
        "Notes\n"
        "55\n. Aegyo is a performative mode of sweetness with its own grammar of voice.",
        speak_footnote_cues=True,
    )
    assert "see note" not in text.lower()
    assert "Footnote." in text
    assert text.index("closer to aegyo") < text.index("Footnote.")
    assert text.index("Footnote.") < text.index("Aegyo is a performative")
    assert text.index("Aegyo is a performative") < text.index("and sajiao.")


def test_duplicate_note_number_prefers_discursive_body() -> None:
    text = format_for_tts(
        "Claim stands.\n"
        "7\n"
        "Next sentence.\n\n"
        "Notes\n"
        "7\n. Harris, Cute, Quaint, Hungry and Romantic, 20.\n"
        "7\n. Discursive expansion about cuteness as an inhuman dynamic of surfaces.",
        speak_footnote_cues=True,
    )
    assert "Harris" not in text
    assert "Discursive expansion about cuteness" in text
    assert text.index("Claim stands.") < text.index("Footnote.")
    assert text.index("Footnote.") < text.index("Next sentence.")


def test_second_format_pass_keeps_digits_inside_footnotes() -> None:
    source = (
        "Claim stands.\n"
        "8\n"
        "Next sentence.\n\n"
        "Notes\n"
        "8\n. The count was\n42\nand then the argument continued about cuteness."
    )
    chapters = [
        Chapter(index=0, title="One", text=source, slug="one"),
    ]
    prepared = prepare_chapters_for_tts(chapters, speak_footnote_cues=True)[0].text
    assert "42" in prepared
    again = format_for_tts(prepared, speak_footnote_cues=True)
    assert "42" in again
    assert again.count("Footnote.") == prepared.count("Footnote.")


def test_see_notes_range_inserts_each_discursive_note() -> None:
    text = format_for_tts(
        "See the twin asides [see notes 1-3] in order.\n\n"
        "Notes\n"
        "1\n. First discursive aside about surfaces.\n"
        "2\n. Middle discursive aside about curves.\n"
        "3\n. Third discursive aside about bobbles.",
        speak_footnote_cues=True,
    )
    assert text.index("twin asides") < text.index("First discursive")
    assert text.index("First discursive") < text.index("Middle discursive")
    assert text.index("Middle discursive") < text.index("Third discursive")
    assert text.index("Third discursive") < text.index("in order.")
    assert text.count("Footnote.") == 3


def test_chunked_format_pass_keeps_digits_without_footnote_cue() -> None:
    # Simulate a format window that split away from the Footnote. cue.
    window = "The count was\n42\nand then the argument continued about cuteness."
    assert format_for_tts(window) == (
        "The count was\n42\nand then the argument continued about cuteness."
    )


def test_see_note_consumes_below_and_trailing_punct() -> None:
    text = format_for_tts(
        "Read on (see note 9 below). Next claim.\n\n"
        "Notes\n"
        "9\n. Discursive clarification about the prior claim.",
        speak_footnote_cues=True,
    )
    assert "below" not in text.lower()
    assert "Footnote." in text
    assert "Discursive clarification" in text
    assert "Read on." in text
    assert text.index("Read on.") < text.index("Footnote.")
    assert text.index("Footnote.") < text.index("Next claim.")


def test_orphan_see_note_without_notes_section_is_stripped() -> None:
    text = format_for_tts("Burikko is closer to aegyo [see note 55] and sajiao.")
    assert "see note" not in text.lower()
    assert "Burikko is closer to aegyo" in text
    assert "and sajiao." in text


def test_short_discursive_note_is_kept() -> None:
    text = format_for_tts(
        "Main claim.\n\nNotes\n"
        "15\n. Even the norm daddies can’t help yielding to the pleasure of telling you what to do.",
        speak_footnote_cues=True,
    )
    assert "norm daddies" in text
    assert "Footnote." in text
    assert "Main claim." in text


def test_see_opener_without_biblio_signals_is_kept() -> None:
    text = format_for_tts(
        "Main claim.\n\nNotes\n"
        "41\n. See Mackay for the fuller account of hyperplastic supernormal stimuli in practice."
    )
    assert "hyperplastic supernormal stimuli" in text


def test_prepare_chapters_relocates_footnotes_before_chunking() -> None:
    chapters = [
        Chapter(
            index=4,
            title="Topology of Bobbles",
            text=(
                "Cuddles have no interiority.\n"
                "36\n"
                "Cute stays cryptic.\n\n"
                "Notes\n"
                "35\n. Harris, Cute, Quaint, Hungry and Romantic, 20.\n"
                "36\n. Discursive note about eggmen and language after the crack."
            ),
            slug="topology_of_bobbles",
        ),
    ]
    prepared = prepare_chapters_for_tts(chapters, speak_footnote_cues=True)
    assert len(prepared) == 1
    text = prepared[0].text
    assert "Harris" not in text
    assert "Footnote." in text
    assert "End of footnote." in text
    assert text.index("Cuddles have no interiority.") < text.index("Footnote.")
    assert text.index("Footnote.") < text.index("Discursive note about eggmen")
    assert text.index("Discursive note about eggmen") < text.index("Cute stays cryptic.")
    assert re.search(r"(?m)^36\s*$", text) is None

    uncued = prepare_chapters_for_tts(chapters)[0].text
    assert "Footnote." not in uncued
    assert "End of footnote." not in uncued
    assert "Discursive note about eggmen" in uncued


def test_cleanup_accepts_heavy_citation_cuts() -> None:
    from text2audiobook.llm import _guard_cleaned

    raw = " ".join(["word"] * 100)
    cleaned = " ".join(["word"] * 10)
    assert _guard_cleaned(raw, cleaned) == cleaned


def test_cleanup_reject_log_includes_chapter_and_chunk(caplog) -> None:
    from text2audiobook.llm import _guard_cleaned

    raw = " ".join(["word"] * 100)
    cleaned = " ".join(["word"] * 400)
    with caplog.at_level(logging.WARNING, logger="text2audiobook.llm"):
        assert _guard_cleaned(
            raw,
            cleaned,
            chapter_index=9,
            chunk_index=1,
            chapter_title="On Several Regimes of Lines",
        ) == raw
    assert "chapter=9 chunk=1 (On Several Regimes of Lines)" in caplog.text
    assert "100 -> 400 words" in caplog.text


def test_references_heading_with_colon_is_removed() -> None:
    text = format_for_tts("Keep this.\n\nReferences:\nFisher, Mark. 2012.")
    assert text == "Keep this."


def test_plain_appendix_after_references_is_kept() -> None:
    text = format_for_tts(
        "The argument ends here.\n\n"
        "References\n"
        "Mark Fisher (2012). Terminator vs Avatar, Urbanomic, p. 342.\n\n"
        "Appendix\n"
        "This extra note should still be narrated."
    )
    assert "argument ends here." in text
    assert "Terminator vs Avatar" not in text
    assert "This extra note should still be narrated." in text


def test_american_acknowledgments_after_references_is_kept() -> None:
    text = format_for_tts(
        "The argument ends here.\n\n"
        "References\n"
        "Mark Fisher (2012). Terminator vs Avatar, Urbanomic, p. 342.\n\n"
        "Acknowledgments\n"
        "Thanks to the editors."
    )
    assert "Thanks to the editors." in text
    assert "Terminator vs Avatar" not in text


def test_inline_bibliographic_citation_is_simplified() -> None:
    source = (
        "Acceleration is already here. Mark Fisher (2012). Terminator vs Avatar in "
        "#Accelerate: The Accelerationist Reader, Urbanomic, p. 342."
    )
    cleaned = format_for_tts(source)
    assert cleaned == (
        "Acceleration is already here. Wrote Mark Fisher in twenty twelve."
    )


def test_parenthetical_citation_is_simplified() -> None:
    cleaned = format_for_tts(
        "Acceleration is a political project (Fisher, 2012, p. 342) in this reading."
    )
    assert cleaned == "Acceleration is a political project in this reading."


def test_editorial_ellipsis_brackets_are_removed() -> None:
    cleaned = format_for_tts("The model is ‘probably […] the twofold birth’ of birds.")
    assert "[...]" not in cleaned
    assert "probably the twofold birth" in cleaned


def test_urbanomic_bibliographic_paren_is_shortened() -> None:
    cleaned = format_for_tts(
        "its model ‘probably […] the “twofold birth” of birds’ (M. Eliade, "
        "Rites and Symbols of Initiation, tr. W.R. Trask [New York: Harper Colophon, 1958], "
        "53–58; on the ‘second birth’, see also C. Kerslake, Deleuze and the Unconscious "
        "[London: Bloomsbury, 2007], 81–82)."
    )
    assert "Harper" not in cleaned
    assert "53" not in cleaned
    assert "Kerslake" not in cleaned
    assert "[...]" not in cleaned
    assert "Eliade in Rites and Symbols of Initiation" in cleaned


def test_see_especially_biblio_paren_is_shortened() -> None:
    cleaned = format_for_tts(
        "Dalcq belongs to a sensitive moment (see especially Deleuze, "
        "Difference and Repetition, 250–52) in embryology."
    )
    assert "250" not in cleaned
    assert "Deleuze in Difference and Repetition" in cleaned


def test_place_year_parenthetical_is_left_alone() -> None:
    source = "They met in winter (Paris, 2012) and stayed in (New York, 2012) later."
    assert format_for_tts(source) == source


def test_citation_starting_with_index_is_not_a_resume_heading() -> None:
    text = format_for_tts(
        "Keep this.\n\nReferences\n"
        "Index of Capital, Volume One. London, 1976, p. 12.\n"
        "Mark Fisher (2012). Terminator vs Avatar, Urbanomic, p. 342."
    )
    assert text == "Keep this."
    assert "Index of Capital" not in text
    assert "Terminator vs Avatar" not in text


def test_markdown_subheading_inside_references_is_still_dropped() -> None:
    text = format_for_tts(
        "Keep this.\n\n## References\n\n### Primary sources\n\n"
        "Mark Fisher (2012). Terminator vs Avatar, Urbanomic, p. 342."
    )
    assert text == "Keep this."
    assert "Primary sources" not in text


def test_same_sentence_page_mention_is_not_a_citation() -> None:
    source = (
        "Mark Fisher (2012). He later appeared in The Guardian and cited p. 12 for the chart."
    )
    assert format_for_tts(source) == source


def test_page_mention_in_a_later_sentence_is_not_a_citation() -> None:
    source = (
        "Mark Fisher (2012). He later appeared in The Guardian. See p. 12 for the chart."
    )
    assert format_for_tts(source) == source


def test_narrative_in_the_is_not_treated_as_a_citation() -> None:
    source = (
        "Mark Fisher (2012). He later appeared in The Guardian after the book came out."
    )
    assert format_for_tts(source) == source


def test_running_text_author_year_is_not_a_bibliography_line() -> None:
    source = "John Smith (2012) went to the store after the talk."
    assert format_for_tts(source) == source


def test_figure_year_is_not_treated_as_a_citation() -> None:
    source = "See the chart (Figure 2012) for the trend."
    assert format_for_tts(source) == source


def test_numbered_inline_refs_are_stripped() -> None:
    cleaned = format_for_tts("The claim is settled [1] and later expanded [12-14].")
    assert "[" not in cleaned
    assert "The claim is settled and later expanded." in cleaned


def test_prepare_chapters_drops_references_chapter() -> None:
    chapters = [
        Chapter(index=0, title="One", text="Narrative stays here.", slug="one"),
        Chapter(
            index=1,
            title="References",
            text="Mark Fisher (2012). Terminator vs Avatar, p. 342.",
            slug="references",
        ),
    ]
    prepared = prepare_chapters_for_tts(chapters)
    assert [ch.slug for ch in prepared] == ["one"]
    assert prepared[0].text == "Narrative stays here."


def test_format_for_tts_is_idempotent() -> None:
    source = (
        "On 03/09/2026, e.i. soon, Fisher spoke. Mark Fisher (2012). "
        "Terminator vs Avatar in #Accelerate, Urbanomic, p. 342."
    )
    once = format_for_tts(source)
    assert format_for_tts(once) == once


def test_passthrough_cleanup_still_formats() -> None:
    chunks = [
        TextChunk(
            chapter_index=0,
            chapter_title="One",
            chapter_slug="one",
            chunk_index=0,
            text="See you on 03/09/2026, e.i. next week.",
        )
    ]
    cleaned = clean_chunks_batched(None, chunks, LlmConfig(cleanup=False))
    assert cleaned[0].cleaned_text == (
        "See you on the third of September, twenty twenty-six, in other words next week."
    )


def test_section_mark_becomes_section() -> None:
    cleaned = format_for_tts("Wrote Nick Land in twenty eighteen. §0.21 in Crypto-Current.")
    assert "§" not in cleaned
    assert "section 0.21" in cleaned


def test_example_parenthetical_title_list() -> None:
    cleaned = format_for_tts(
        "ruin and runaway accelerate in tandem (Cyberpunk, Elysium). Ask first."
    )
    assert "(Cyberpunk, Elysium)" not in cleaned
    assert "for example Cyberpunk, Elysium" in cleaned


def test_eg_before_title_list_does_not_duplicate_for_example() -> None:
    cleaned = format_for_tts("See media, e.g. (Cyberpunk, Elysium), later.")
    assert cleaned.count("for example") == 1
    assert "for example Cyberpunk, Elysium" in cleaned


def test_author_list_parenthetical_is_left_alone() -> None:
    source = "As argued elsewhere (Marx, Engels) the point stands."
    assert format_for_tts(source) == source
    near_media = "Discussed in social media (Marx, Engels) often."
    assert format_for_tts(near_media) == near_media


def test_narrative_parenthetical_is_left_alone() -> None:
    source = "Still early (And we've scarcely started with DAOs yet.)"
    assert format_for_tts(source) == source


def test_hashtag_ampersand_percent_spoken() -> None:
    cleaned = format_for_tts("See #Accelerate & friends at 35%.")
    assert "#" not in cleaned
    assert "Accelerate and friends at 35 percent." in cleaned


def test_default_clean_prompt_covers_new_rules() -> None:
    assert "the third of September, twenty twenty-six" in DEFAULT_CLEAN_PROMPT
    assert "in other words" in DEFAULT_CLEAN_PROMPT
    assert "Wrote Mark Fisher in twenty twelve." in DEFAULT_CLEAN_PROMPT
    assert "page numbers" in DEFAULT_CLEAN_PROMPT
    assert "[...]" in DEFAULT_CLEAN_PROMPT
    cfg = load_config()
    assert "in other words" in cfg.llm.clean_prompt
    assert cfg.tts.voice == "cloned"
    assert cfg.tts.lang == "English"
    assert cfg.tts.instruct
    assert "audiobook" in cfg.tts.instruct.lower()
    assert "native" in cfg.tts.instruct.lower()
    assert cfg.tts.model_id == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert cfg.tts.ref_audio is not None
    assert cfg.tts.ref_audio.endswith("ref_clone.wav")
    assert cfg.tts.ref_text and "Homer" in cfg.tts.ref_text
    assert cfg.tts.x_vector_only is False
    assert cfg.llm.direction is True
    assert "{text}" in cfg.llm.direction_prompt
    assert cfg.llm.direction_max_new_tokens == 128
    assert cfg.llm.max_new_tokens == 2048
    assert cfg.chunking.format_words_per_chunk == 1000


def test_markdown_table_becomes_ebook_reference() -> None:
    source = (
        "Intro stays.\n"
        "| GDP | Year |\n"
        "| --- | --- |\n"
        "| 1 | 2020 |\n"
        "Outro stays."
    )
    cleaned = format_for_tts(source, chapter_title="One")
    assert "See the table GDP, Year in this chapter of the ebook." in cleaned
    assert "2020" not in cleaned
    assert "Intro stays." in cleaned
    assert "Outro stays." in cleaned


def test_untitled_html_table_on_a_page() -> None:
    source = "Before.<table><tr><td>1</td><td>2</td></tr></table>After."
    cleaned = format_for_tts(source, source_kind="page")
    assert cleaned == "Before.See the table on the original page.After."


def test_markdown_figure_uses_alt_text() -> None:
    cleaned = format_for_tts("Look ![Growth chart](chart.png) here.")
    assert "See the figure Growth chart in this chapter of the ebook." in cleaned
    assert "chart.png" not in cleaned


def test_normalize_speak_text_collapses_newlines() -> None:
    from text2audiobook.formatting import normalize_speak_text

    assert normalize_speak_text("A.\n\nB.\t C.") == "A. B. C."
    assert normalize_speak_text("  padded  \n") == "padded"
    assert normalize_speak_text("") == ""
