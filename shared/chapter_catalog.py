"""EPUB chapter catalog helpers and LLM-based section classification."""

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol


class ChapterLike(Protocol):
    index: int
    title: str
    text: str


@dataclass
class CatalogEntry:
    index: int
    title: str
    word_count: int
    preview: str


@dataclass
class OpeningAnalysis:
    index: int
    section_type: str
    narratively_important: bool
    reason: str


@dataclass
class ChapterDecision:
    index: int
    keep: bool
    reason: str


def first_chunk_words(text: str, word_count: int) -> str:
    words = text.split()
    chunk = " ".join(words[:word_count])
    if len(words) > word_count:
        chunk += "…"
    return chunk


def build_catalog_entries(chapters: list[ChapterLike], preview_words: int = 40) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for ch in chapters:
        words = ch.text.split()
        preview = first_chunk_words(ch.text, preview_words)
        entries.append(
            CatalogEntry(
                index=ch.index,
                title=ch.title,
                word_count=len(words),
                preview=preview,
            )
        )
    return entries


def _llm_generate(model: Any, tokenizer: Any, messages: list[dict], max_new_tokens: int) -> str:
    import torch

    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=0.0,
        )
    generated = output_ids[0][inputs["input_ids"].shape[-1] :]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def _parse_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("LLM response must be a JSON array")
    return data


def parse_opening_analyses(raw: str, valid_indices: set[int]) -> list[OpeningAnalysis]:
    analyses: list[OpeningAnalysis] = []
    for item in _parse_json_array(raw):
        if not isinstance(item, dict):
            continue
        idx = int(item["index"])
        if idx not in valid_indices:
            continue
        analyses.append(
            OpeningAnalysis(
                index=idx,
                section_type=str(item.get("section_type", "unclear")),
                narratively_important=bool(item.get("narratively_important", False)),
                reason=str(item.get("reason", "")),
            )
        )
    if not analyses:
        raise ValueError("LLM returned no valid opening analyses")
    return analyses


def parse_chapter_decisions(raw: str, valid_indices: set[int]) -> list[ChapterDecision]:
    decisions: list[ChapterDecision] = []
    for item in _parse_json_array(raw):
        if not isinstance(item, dict):
            continue
        idx = int(item["index"])
        if idx not in valid_indices:
            continue
        decisions.append(
            ChapterDecision(
                index=idx,
                keep=bool(item.get("keep", False)),
                reason=str(item.get("reason", "")),
            )
        )
    if not decisions:
        raise ValueError("LLM returned no valid chapter decisions")
    return decisions


OPENING_SYSTEM_PROMPT = (
    "You classify EPUB section openings for audiobook narration. Return only valid JSON."
)

OPENING_BATCH_USER_PROMPT = """\
Book title: {book_title}

For each section below, read the **opening excerpt** (not just the file title).
Decide whether this section is narratively important for a text-to-speech audiobook,
or non-narration material (TOC, copyright, ads, bibliography, etc.).

Publisher file names are often opaque codes — the opening text is the primary signal.

{include_intro}
{include_appendix}

Return a JSON array with one object per section:
[{{"index": 0, "section_type": "table_of_contents", "narratively_important": false, "reason": "..."}}, ...]

section_type: narrative_chapter | introduction | conclusion | table_of_contents | copyright |
dedication | acknowledgments | bibliography | appendix | advertisement | about_author |
other_back_matter | unclear

Sections:
{sections_json}
"""

CATALOG_SYSTEM_PROMPT = (
    "You select EPUB sections for audiobook narration. Return only valid JSON."
)

CATALOG_FINAL_USER_PROMPT = """\
Book title: {book_title}

Each section below includes an **opening_analysis** from a prior review of the section's
opening text. Make the final keep/skip decision for audiobook narration.

Trust opening_analysis over opaque file titles. Every section index must appear exactly once.

{include_intro}
{include_appendix}

Return a JSON array:
[{{"index": 0, "keep": false, "reason": "table of contents"}}, ...]

Catalog with opening analysis:
{catalog_json}
"""


def _include_intro_text(include_intro: bool) -> str:
    if include_intro:
        return "Keep introduction/preface sections unless opening text is purely metadata."
    return "Skip introduction/preface unless opening text is clearly main narrative."


def _include_appendix_text(include_appendix: bool) -> str:
    if include_appendix:
        return "Keep appendix sections when opening text has substantive reader-facing content."
    return "Skip appendix and supplement back matter."


def analyze_chapter_openings_with_llm(
    model: Any,
    tokenizer: Any,
    chapters: list[ChapterLike],
    *,
    book_title: str,
    opening_words: int = 250,
    include_intro: bool = True,
    include_appendix: bool = False,
    batch_size: int = 4,
    max_new_tokens: int = 1024,
) -> list[OpeningAnalysis]:
    """Step 1: classify each section from its opening text."""
    all_analyses: list[OpeningAnalysis] = []

    for batch_start in range(0, len(chapters), batch_size):
        batch = chapters[batch_start : batch_start + batch_size]
        valid_indices = {ch.index for ch in batch}
        sections = []
        for ch in batch:
            sections.append(
                {
                    "index": ch.index,
                    "title": ch.title,
                    "word_count": len(ch.text.split()),
                    "opening": first_chunk_words(ch.text, opening_words),
                }
            )

        user_content = OPENING_BATCH_USER_PROMPT.format(
            book_title=book_title,
            sections_json=json.dumps(sections, indent=2),
            include_intro=_include_intro_text(include_intro),
            include_appendix=_include_appendix_text(include_appendix),
        )
        raw = _llm_generate(
            model,
            tokenizer,
            [
                {"role": "system", "content": OPENING_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_new_tokens,
        )
        all_analyses.extend(parse_opening_analyses(raw, valid_indices))

    return sorted(all_analyses, key=lambda a: a.index)


def classify_chapters_with_llm(
    model: Any,
    tokenizer: Any,
    *,
    book_title: str,
    entries: list[CatalogEntry],
    opening_analyses: list[OpeningAnalysis],
    include_intro: bool = True,
    include_appendix: bool = False,
    max_new_tokens: int = 2048,
) -> list[ChapterDecision]:
    """Step 2: final keep/skip using catalog metadata + opening analyses."""
    analysis_by_index = {a.index: a for a in opening_analyses}
    payload = []
    for entry in entries:
        analysis = analysis_by_index.get(entry.index)
        item: dict[str, Any] = {
            "index": entry.index,
            "title": entry.title,
            "word_count": entry.word_count,
            "short_preview": entry.preview,
        }
        if analysis:
            item["opening_analysis"] = {
                "section_type": analysis.section_type,
                "narratively_important": analysis.narratively_important,
                "reason": analysis.reason,
            }
        payload.append(item)

    user_content = CATALOG_FINAL_USER_PROMPT.format(
        book_title=book_title,
        catalog_json=json.dumps(payload, indent=2),
        include_intro=_include_intro_text(include_intro),
        include_appendix=_include_appendix_text(include_appendix),
    )
    raw = _llm_generate(
        model,
        tokenizer,
        [
            {"role": "system", "content": CATALOG_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_new_tokens,
    )
    return parse_chapter_decisions(raw, {e.index for e in entries})


def apply_chapter_decisions(
    all_chapters: list[ChapterLike],
    decisions: list[ChapterDecision],
    *,
    keep_indices_override: list[int] | None = None,
    max_chapters: int | None = None,
) -> tuple[list[ChapterLike], dict[int, ChapterDecision]]:
    decision_map = {d.index: d for d in decisions}

    if keep_indices_override is not None:
        chapters = [ch for ch in all_chapters if ch.index in set(keep_indices_override)]
    else:
        chapters = [
            ch
            for ch in all_chapters
            if decision_map.get(ch.index, ChapterDecision(ch.index, False, "")).keep
        ]

    if not chapters:
        raise ValueError("No chapters left after classification")

    if max_chapters is not None:
        chapters = chapters[:max_chapters]

    return chapters, decision_map
