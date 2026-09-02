"""EPUB chapter catalog helpers and LLM-based section classification.

Chapter catalog and LLM-based section classification for audiobook narration.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from text2audiobook.config import SelectionConfig
from text2audiobook.logging_setup import ProgressContext

logger = logging.getLogger(__name__)


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


_TOC_TITLE_RE = re.compile(
    r"\b(?:table\s+of\s+)?contents?\b|\btoc\b",
    re.IGNORECASE,
)


def is_obvious_table_of_contents(title: str, text: str) -> bool:
    """Conservative heuristic for obvious TOC pages — never skips long narrative."""
    words = text.split()
    word_count = len(words)
    if word_count > 500:
        return False

    title_lower = title.lower().strip()
    if _TOC_TITLE_RE.search(title_lower) and word_count < 300:
        return True

    if word_count < 150:
        digit_tokens = sum(1 for word in words if re.search(r"\d", word))
        colon_count = text.count(":")
        digit_ratio = digit_tokens / word_count if word_count else 0.0
        if word_count < 100 and digit_ratio > 0.3:
            return True
        if word_count < 100 and colon_count >= 3 and digit_ratio > 0.2:
            return True

    return False


def obvious_non_narrative_indices(chapters: list[ChapterLike]) -> set[int]:
    """Section indices that look like TOC listings and should be skipped."""
    return {
        chapter.index
        for chapter in chapters
        if is_obvious_table_of_contents(chapter.title, chapter.text)
    }


def first_chunk_words(text: str, word_count: int) -> str:
    words = text.split()
    chunk = " ".join(words[:word_count])
    if len(words) > word_count:
        chunk += "…"
    return chunk


def build_catalog_entries(
    chapters: list[ChapterLike], preview_words: int = 40
) -> list[CatalogEntry]:
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


def _decisions_cache_path(staging_dir: Path) -> Path:
    return staging_dir / "decisions.json"


def _selection_fingerprint(selection: SelectionConfig) -> dict[str, Any]:
    return {
        "include_intro": selection.include_intro,
        "include_appendix": selection.include_appendix,
        "opening_words": selection.opening_words,
        "opening_batch_size": selection.opening_batch_size,
        "max_chapters": selection.max_chapters,
    }


def load_decisions_cache(
    staging_dir: Path,
    *,
    book_title: str,
    chapter_count: int,
    selection: SelectionConfig,
) -> tuple[list[OpeningAnalysis], list[ChapterDecision]] | None:
    """Return cached analyses + decisions when the staging file matches this book."""
    path = _decisions_cache_path(staging_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("book_title") != book_title:
            return None
        if data.get("chapter_count") != chapter_count:
            return None
        if data.get("selection") != _selection_fingerprint(selection):
            return None
        analyses = [
            OpeningAnalysis(
                index=int(item["index"]),
                section_type=str(item["section_type"]),
                narratively_important=bool(item["narratively_important"]),
                reason=str(item["reason"]),
            )
            for item in data["analyses"]
        ]
        decisions = [
            ChapterDecision(
                index=int(item["index"]),
                keep=bool(item["keep"]),
                reason=str(item["reason"]),
            )
            for item in data["decisions"]
        ]
        return analyses, decisions
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.debug("Ignoring invalid decisions cache at %s", path)
        return None


def save_decisions_cache(
    staging_dir: Path,
    *,
    book_title: str,
    chapter_count: int,
    selection: SelectionConfig,
    analyses: list[OpeningAnalysis],
    decisions: list[ChapterDecision],
) -> None:
    path = _decisions_cache_path(staging_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "book_title": book_title,
        "chapter_count": chapter_count,
        "selection": _selection_fingerprint(selection),
        "analyses": [asdict(item) for item in analyses],
        "decisions": [asdict(item) for item in decisions],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def select_chapters(
    model: Any,
    tokenizer: Any,
    all_chapters: list[ChapterLike],
    *,
    book_title: str,
    selection: SelectionConfig,
    staging_dir: Path | None = None,
    progress: ProgressContext | None = None,
) -> tuple[list[ChapterLike], dict[int, ChapterDecision]]:
    """Notebook steps 6+7: opening analysis, then the final keep/skip catalog.

    A manual selection.keep_chapter_indices override skips the LLM entirely.
    """
    def log_step(step: str, *, chapter_title: str | None = None) -> None:
        if progress is not None:
            logger.info("%s", progress.format(step, chapter_title=chapter_title))
        else:
            logger.info("%s", step)

    obvious_skip = obvious_non_narrative_indices(all_chapters)
    if obvious_skip:
        log_step(f"heuristic TOC skip ({len(obvious_skip)} section(s))")

    if selection.keep_chapter_indices:
        keep = set(selection.keep_chapter_indices)
        chapters = [ch for ch in all_chapters if ch.index in keep]
        if selection.max_chapters is not None:
            chapters = chapters[: selection.max_chapters]
        if not chapters:
            raise ValueError("No chapters match keep_chapter_indices")
        decision_map: dict[int, ChapterDecision] = {}
        log_step(f"manual selection: {len(chapters)} section(s)")
    else:
        if model is None or tokenizer is None:
            raise RuntimeError("LLM model and tokenizer are required for chapter selection")

        cached = (
            load_decisions_cache(
                staging_dir,
                book_title=book_title,
                chapter_count=len(all_chapters),
                selection=selection,
            )
            if staging_dir is not None
            else None
        )
        if cached is not None:
            analyses, decisions = cached
            log_step(f"classify cache hit ({len(analyses)} sections)")
        else:
            llm_chapters = [ch for ch in all_chapters if ch.index not in obvious_skip]
            log_step("classify openings")
            analyses = analyze_chapter_openings_with_llm(
                model,
                tokenizer,
                llm_chapters,
                book_title=book_title,
                opening_words=selection.opening_words,
                include_intro=selection.include_intro,
                include_appendix=selection.include_appendix,
                batch_size=selection.opening_batch_size,
            )
            for analysis in analyses:
                title = next((ch.title for ch in all_chapters if ch.index == analysis.index), "")
                flag = "KEEP" if analysis.narratively_important else "SKIP"
                log_step(f"classify opening {flag}: {analysis.section_type}", chapter_title=title)

            entries = build_catalog_entries(all_chapters)
            log_step("classify final catalog")
            decisions = classify_chapters_with_llm(
                model,
                tokenizer,
                book_title=book_title,
                entries=entries,
                opening_analyses=analyses,
                include_intro=selection.include_intro,
                include_appendix=selection.include_appendix,
            )
            if staging_dir is not None:
                save_decisions_cache(
                    staging_dir,
                    book_title=book_title,
                    chapter_count=len(all_chapters),
                    selection=selection,
                    analyses=analyses,
                    decisions=decisions,
                )

        chapters, decision_map = apply_chapter_decisions(
            all_chapters,
            decisions,
            keep_indices_override=None,
            max_chapters=selection.max_chapters,
        )
        for idx in obvious_skip:
            decision_map[idx] = ChapterDecision(idx, False, "obvious table of contents (heuristic)")

        log_step(f"keep_indices = {[ch.index for ch in chapters]}")

    log_step(f"processing {len(chapters)} chapter(s)")

    return chapters, decision_map
