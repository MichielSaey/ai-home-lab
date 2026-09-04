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
    cfg = load_config()
    assert "in other words" in cfg.llm.clean_prompt
    assert cfg.tts.voice == "af_bella"
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
