"""v2 orchestration: extract → clean → format → speak stems, sequential GPU, optional stage flags."""

from __future__ import annotations

import json
import logging
import platform
import shutil
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from text2audiobook import formats  # noqa: F401 — register built-in readers
from text2audiobook.audio import build_m4b, encode_chapter_mp3
from text2audiobook.catalog import select_chapters
from text2audiobook.cleanup import CLEANER_VERSION, CleanSection, clean_chapters
from text2audiobook.chunking import (
    TextChunk,
    build_chunks_from_sections,
    build_speak_units_from_chunks,
)
from text2audiobook.config import (
    AppConfig,
    TtsConfig,
    resolve_book_config,
    with_speak_footnote_cues,
)
from text2audiobook.formatting import FORMATTER_VERSION
from text2audiobook.gpu import resolve_tts_device
from text2audiobook.io import (
    BookMetadata,
    Chapter,
    find_sources,
    infer_source_kind,
    parse_source,
)
from text2audiobook.llm import (
    CleanedChunk,
    FormatCacheEntry,
    LoadedLlm,
    apply_direction_pass,
    iter_clean_chunks_batched,
    load_llm,
    text_hash,
    unload_llm,
)
from text2audiobook.logging_setup import ProgressContext, setup_logging
from text2audiobook.stems import (
    PIPELINE_STAGES,
    BookStems,
    append_jsonl,
    canonical_stages,
    chapters_to_payload,
    clean_sections_hash,
    file_sha256,
    format_scripts_hash,
    load_clean_sections,
    load_extract_chapters,
    load_format_scripts,
    load_format_units,
    load_jsonl,
    manifest_matches,
    save_clean_sections,
    save_extract_chapters,
    save_format_script,
    stable_hash,
    write_json,
)
from text2audiobook.tracking import BookRecord, RunTracker
from text2audiobook.tts import (
    compose_instruct,
    is_voice_design,
    load_tts,
    synthesize_to_wav,
    unload_tts,
)
from text2audiobook.voices import (
    VOICE_DESIGN_LABEL,
    is_voice_design_label,
    lang_for_voice,
    resolve_voice,
)

logger = logging.getLogger(__name__)


@dataclass
class StageState:
    """Mutable stem outputs threaded through injectable stage handlers."""

    chapters: list[Chapter] | None = None
    sections: list[CleanSection] | None = None
    format_units: list[TextChunk] | None = None
    scripts: list[Chapter] | None = None


def run(
    config: AppConfig,
    *,
    source_paths: list[Path] | None = None,
    stages: tuple[str, ...] | list[str] | None = None,
    force: bool = False,
    voice: str | None = None,
    speak_footnote_cues: bool | None = None,
) -> int:
    """Process supported sources. Returns a process exit code.

    When ``source_paths`` is provided (e.g. from ``--url``), those paths are
    used and the input directory is not scanned.
    """
    selected = canonical_stages(stages)
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    setup_logging(tracker.log_path)
    logger.info("Run %s — manifest: %s", tracker.run_id, tracker.run_json_path)
    logger.info("Stages: %s%s", ", ".join(selected), " (force)" if force else "")
    logger.debug("Config: %s", json.dumps(config.to_dict(), indent=2))
    if config.pipeline.concurrent_models:
        logger.warning(
            "pipeline.concurrent_models is ignored in v2: format unloads the LLM "
            "before TTS loads."
        )

    try:
        sources = (
            list(source_paths)
            if source_paths is not None
            else find_sources(config.paths.input_dir)
        )
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        tracker.finalize("failed")
        return 1
    if not sources:
        logger.error("No sources to process")
        tracker.finalize("failed")
        return 1
    logger.info(
        "Found %d source(s)%s",
        len(sources),
        "" if source_paths is not None else f" under {config.paths.input_dir}",
    )

    need_llm = _run_needs_llm(config, selected)
    tts_device = resolve_tts_device(config.tts.device)
    tracker.set_environment(
        python=platform.python_version(),
        llm_model_id=config.llm.model_id if need_llm else None,
        llm_device=config.llm.device if need_llm else None,
        tts_model_id=(
            config.tts.model_id if "speak" in selected else None
        ),
        tts_device=tts_device if "speak" in selected else None,
        concurrent_models=False,
        stages=list(selected),
        force=force,
    )

    started = time.perf_counter()
    interrupted = False
    fatal = False

    try:
        for position, source_path in enumerate(sources, start=1):
            record = tracker.start_book(source_path)
            try:
                process_source(
                    source_path,
                    config,
                    tracker=tracker,
                    record=record,
                    position=(position, len(sources)),
                    tts_device=tts_device,
                    stages=selected,
                    force=force,
                    voice=voice,
                    speak_footnote_cues=speak_footnote_cues,
                )
            except KeyboardInterrupt:
                tracker.finish_book(record, status="failed", error="KeyboardInterrupt")
                raise
            except Exception as exc:
                logger.error("FAILED %s: %s", source_path.name, exc)
                logger.debug("Book failure traceback", exc_info=True)
                tracker.finish_book(
                    record, status="failed", error=f"{type(exc).__name__}: {exc}"
                )
    except KeyboardInterrupt:
        interrupted = True
        logger.info("Interrupted — flushing run manifest and exiting.")
    except Exception as exc:
        fatal = True
        logger.error("Fatal error: %s", exc)
        logger.debug("Fatal traceback", exc_info=True)

    tracker.finalize("interrupted" if interrupted else "failed" if fatal else "completed")
    _log_summary(tracker, time.perf_counter() - started)

    if interrupted:
        return 130
    if fatal or any(record.status == "failed" for record in tracker.books):
        return 1
    return 0


def process_source(
    source_path: Path,
    config: AppConfig,
    *,
    tracker: RunTracker,
    record: BookRecord,
    llm: LoadedLlm | None = None,
    tts_model: Any = None,
    position: tuple[int, int] | None = None,
    tts_device: str | None = None,
    stages: tuple[str, ...] = PIPELINE_STAGES,
    force: bool = False,
    voice: str | None = None,
    speak_footnote_cues: bool | None = None,
) -> None:
    """Convert one source through the requested extract / format / speak stages."""
    selected = canonical_stages(stages)
    if tts_device is None:
        tts_device = resolve_tts_device(config.tts.device)

    with tracker.stage(record, "parse"):
        metadata, all_chapters = parse_source(
            source_path,
            staging_root=config.paths.staging_dir,
            output_root=config.paths.output_dir,
            force_fetch=force and "extract" in selected,
        )
    record.title = metadata.title
    record.author = metadata.author
    tracker.write()

    config = resolve_book_config(config, metadata.slug)
    if speak_footnote_cues is not None:
        config = with_speak_footnote_cues(config, speak_footnote_cues)

    book_idx, total_books = position if position is not None else (1, 1)
    progress = ProgressContext(
        book_title=metadata.title,
        book_idx=book_idx,
        total_books=total_books,
    )
    if position is not None:
        logger.info("")
        logger.info(
            "=== [%d/%d] %s — %s ===",
            position[0],
            position[1],
            metadata.title,
            metadata.author,
        )

    source_kind = infer_source_kind(source_path)
    stems = BookStems(metadata.staging_dir)
    tts_config = _resolve_tts(config, voice=voice, staging_root=config.paths.staging_dir)

    if (
        "speak" in selected
        and config.output.skip_existing
        and not force
        and metadata.m4b_path.exists()
        and _speak_current(stems, config, tts_config)
    ):
        logger.info(
            "Skipping '%s' — audiobook already exists: %s",
            metadata.title,
            metadata.m4b_path,
        )
        tracker.finish_book(record, status="skipped", output_path=metadata.m4b_path)
        return

    logger.info("Source catalog (%d sections):", len(all_chapters))
    for chapter in all_chapters:
        logger.info(
            "  [%2d] %s (%d words)",
            chapter.index,
            chapter.title,
            len(chapter.text.split()),
        )

    own_llm: LoadedLlm | None = None
    own_tts: Any = None

    def ensure_llm() -> LoadedLlm | None:
        nonlocal own_llm
        if llm is not None:
            return llm
        if own_llm is None:
            own_llm = load_llm(config.llm)
        return own_llm

    state = StageState()

    def run_extract() -> None:
        state.chapters = _run_extract(
            all_chapters,
            metadata=metadata,
            source_path=source_path,
            source_kind=source_kind,
            config=config,
            stems=stems,
            tracker=tracker,
            record=record,
            progress=progress,
            selected=selected,
            force=force,
            ensure_llm=ensure_llm,
        )

    def run_clean() -> None:
        chapters = state.chapters
        if chapters is None:
            chapters = _run_extract(
                all_chapters,
                metadata=metadata,
                source_path=source_path,
                source_kind=source_kind,
                config=config,
                stems=stems,
                tracker=tracker,
                record=record,
                progress=progress,
                selected=selected,
                force=force,
                ensure_llm=ensure_llm,
            )
            state.chapters = chapters
        state.sections = _run_clean(
            chapters,
            metadata=metadata,
            source_kind=source_kind,
            config=config,
            stems=stems,
            tracker=tracker,
            record=record,
            selected=selected,
            force=force,
        )

    def run_format() -> None:
        sections = state.sections
        if sections is None:
            extract_hash = (
                file_sha256(stems.chapters_json) if stems.chapters_json.exists() else ""
            )
            fingerprint = _clean_fingerprint(
                config, extract_hash=extract_hash, source_kind=source_kind
            )
            clean_ok = (
                manifest_matches(stems.clean_manifest, fingerprint)
                and stems.clean_sections_jsonl.exists()
                and stems.clean_chapters_index.exists()
            )
            if not clean_ok:
                raise FileNotFoundError(
                    f"Clean stem missing for {metadata.title!r}. "
                    "Run --clean first."
                )
            sections = load_clean_sections(stems)
            state.sections = sections
        state.scripts, state.format_units = _run_format(
            sections,
            metadata=metadata,
            source_kind=source_kind,
            config=config,
            stems=stems,
            tracker=tracker,
            record=record,
            progress=progress,
            selected=selected,
            force=force,
            ensure_llm=ensure_llm,
        )

    def run_speak() -> None:
        nonlocal own_llm, own_tts
        if own_llm is not None:
            unload_llm(own_llm)
            own_llm = None
            logger.info("Unloaded LLM to free GPU memory for TTS")

        scripts = state.scripts
        format_units = state.format_units
        if scripts is None or format_units is None:
            clean_hash = (
                clean_sections_hash(stems) if stems.clean_sections_jsonl.exists() else ""
            )
            format_fingerprint = _format_fingerprint(
                config, clean_hash=clean_hash, source_kind=source_kind
            )
            format_ok = (
                manifest_matches(stems.format_manifest, format_fingerprint)
                and stems.format_chapters_index.exists()
                and stems.format_chunks_jsonl.exists()
            )
            if not format_ok:
                raise FileNotFoundError(
                    f"Format stem missing or stale for {metadata.title!r}. "
                    "Run --format first."
                )
            if scripts is None:
                scripts = load_format_scripts(stems)
            if format_units is None:
                format_units = load_format_units(stems)
            state.scripts = scripts
            state.format_units = format_units

        own_tts = tts_model
        loaded_here = False
        if own_tts is None:
            own_tts = load_tts(tts_config, device=tts_device)
            loaded_here = True
        try:
            _run_speak(
                format_units,
                scripts=scripts,
                metadata=metadata,
                config=config,
                tts_config=tts_config,
                stems=stems,
                tts_model=own_tts,
                tracker=tracker,
                record=record,
                progress=progress,
                force=force,
            )
        finally:
            if loaded_here:
                unload_tts(own_tts)
                own_tts = None

    handlers = {
        "extract": run_extract,
        "clean": run_clean,
        "format": run_format,
        "speak": run_speak,
    }

    try:
        for stage_name in selected:
            handlers[stage_name]()
        if "speak" not in selected:
            tracker.finish_book(record, status="ok")
    finally:
        if own_llm is not None:
            unload_llm(own_llm)
        if own_tts is not None and tts_model is None:
            unload_tts(own_tts)


def _run_needs_llm(config: AppConfig, stages: tuple[str, ...]) -> bool:
    if "extract" in stages and config.selection.keep_chapter_indices is None:
        return True
    return "format" in stages and (config.llm.cleanup or config.llm.direction)


def _resolve_tts(
    config: AppConfig,
    *,
    voice: str | None,
    staging_root: Path,
) -> TtsConfig:
    lang = config.tts.lang
    if is_voice_design(config.tts.model_id):
        # VoiceDesign: no CustomVoice speaker; persona comes from tts.instruct.
        # Keep config.lang as content language (do not map via speaker native).
        requested = voice
        if requested and requested.strip() and not is_voice_design_label(requested):
            logger.info(
                "VoiceDesign uses instruct persona; ignoring --voice=%s",
                requested,
            )
            requested = None
        chosen = resolve_voice(
            requested,
            default=config.tts.voice or VOICE_DESIGN_LABEL,
            state_path=staging_root / "_voice_random.json",
        )
        logger.info(
            "VoiceDesign voice=%s (lang=%s; persona from tts.instruct)",
            chosen,
            lang,
        )
        return replace(config.tts, voice=chosen, lang=lang)

    chosen = resolve_voice(
        voice,
        default=config.tts.voice,
        state_path=staging_root / "_voice_random.json",
    )
    # Content language stays from config (book text). Speaker native language is
    # only a quality hint — CustomVoice speakers can narrate any supported lang.
    native = lang_for_voice(chosen)
    if chosen != config.tts.voice:
        logger.info("Voice %s (lang=%s, native=%s)", chosen, lang, native)
    elif native != lang:
        logger.info("Voice %s (lang=%s; speaker native is %s)", chosen, lang, native)
    return replace(config.tts, voice=chosen, lang=lang)


def _extract_fingerprint(
    source_path: Path,
    *,
    source_kind: str,
    config: AppConfig,
    chapters: list,
) -> dict[str, Any]:
    selection = config.selection
    return {
        "version": 2,
        "source_hash": file_sha256(source_path),
        "parsed_hash": stable_hash(chapters_to_payload(chapters)),
        "source_kind": source_kind,
        "selection": {
            "keep_chapter_indices": selection.keep_chapter_indices,
            "max_chapters": selection.max_chapters,
            "include_intro": selection.include_intro,
            "include_appendix": selection.include_appendix,
            "opening_words": selection.opening_words,
            "opening_batch_size": selection.opening_batch_size,
        },
    }


def _clean_fingerprint(config: AppConfig, *, extract_hash: str, source_kind: str) -> dict[str, Any]:
    return {
        "version": 2,
        "extract_hash": extract_hash,
        "cleaner_version": CLEANER_VERSION,
        "source_kind": source_kind,
        "speak_footnote_cues": config.output.speak_footnote_cues,
    }


def _format_fingerprint(config: AppConfig, *, clean_hash: str, source_kind: str) -> dict[str, Any]:
    return {
        "version": 2,
        "clean_hash": clean_hash,
        "formatter_version": FORMATTER_VERSION,
        "source_kind": source_kind,
        "llm_model_id": config.llm.model_id,
        "cleanup": config.llm.cleanup,
        "direction": config.llm.direction,
        "max_new_tokens": config.llm.max_new_tokens,
        "direction_max_new_tokens": config.llm.direction_max_new_tokens,
        "cleanup_batch_size": config.llm.cleanup_batch_size,
        "clean_prompt_hash": text_hash(config.llm.clean_prompt),
        "direction_prompt_hash": text_hash(config.llm.direction_prompt),
        "format_words_per_chunk": config.chunking.format_words_per_chunk,
        "max_chunks_per_chapter": config.chunking.max_chunks_per_chapter,
    }


def _speak_fingerprint(config: AppConfig, tts: TtsConfig, *, format_hash: str) -> dict[str, Any]:
    return {
        "version": 2,
        "format_hash": format_hash,
        "model_id": tts.model_id,
        "voice": tts.voice,
        "lang": tts.lang,
        "instruct": tts.instruct,
        "m4b_bitrate": config.output.m4b_bitrate,
        "loudnorm": config.output.loudnorm,
        "chunk_silence_ms": config.output.chunk_silence_ms,
        "chapter_silence_ms": config.output.chapter_silence_ms,
        "speak_target_chars": config.chunking.speak_target_chars,
        "speak_max_chars": config.chunking.speak_max_chars,
    }


def _format_units_hash(stems: BookStems) -> str:
    """Hash cleaned format windows so speak invalidates when chunks change."""
    if not stems.format_chunks_jsonl.exists():
        return ""
    rows = load_jsonl(stems.format_chunks_jsonl)
    return stable_hash(
        [
            {
                "chapter_index": row.get("chapter_index"),
                "chunk_index": row.get("chunk_index"),
                "cleaned_text": row.get("cleaned_text"),
                "instruct": row.get("instruct"),
            }
            for row in rows
        ]
    )


def _live_format_hash(stems: BookStems, config: AppConfig) -> str:
    """Hash formatter inputs plus on-disk scripts/units (not only the manifest)."""
    source_kind = "ebook"
    data = json.loads(stems.format_manifest.read_text(encoding="utf-8")) if stems.format_manifest.exists() else {}
    if isinstance(data, dict) and data.get("source_kind"):
        source_kind = str(data["source_kind"])
    clean_hash = clean_sections_hash(stems) if stems.clean_sections_jsonl.exists() else ""
    fingerprint = _format_fingerprint(config, clean_hash=clean_hash, source_kind=source_kind)
    return stable_hash(
        {
            **fingerprint,
            "scripts_hash": format_scripts_hash(stems),
            "units_hash": _format_units_hash(stems),
        }
    )


def _speak_current(stems: BookStems, config: AppConfig, tts: TtsConfig) -> bool:
    if not stems.format_manifest.exists() or not stems.speak_manifest.exists():
        return False
    format_hash = _live_format_hash(stems, config)
    return manifest_matches(stems.speak_manifest, _speak_fingerprint(config, tts, format_hash=format_hash))


def _run_extract(
    all_chapters: list,
    *,
    metadata: BookMetadata,
    source_path: Path,
    source_kind: str,
    config: AppConfig,
    stems: BookStems,
    tracker: RunTracker,
    record: BookRecord,
    progress: ProgressContext,
    selected: tuple[str, ...],
    force: bool,
    ensure_llm,
) -> list:
    fingerprint = _extract_fingerprint(
        source_path, source_kind=source_kind, config=config, chapters=all_chapters
    )
    extract_ok = manifest_matches(stems.extract_manifest, fingerprint) and stems.chapters_json.exists()

    if "extract" not in selected:
        if not extract_ok:
            raise FileNotFoundError(
                f"Extract stem missing for {metadata.title!r}. Run --extract first."
            )
        return load_extract_chapters(stems)

    if extract_ok and not force:
        logger.info("Extract stem current — skipping classify")
        return load_extract_chapters(stems)

    if force:
        decisions = metadata.staging_dir / "decisions.json"
        if decisions.exists():
            decisions.unlink()

    with tracker.stage(record, "classify"):
        active = None
        if config.selection.keep_chapter_indices is None:
            active = ensure_llm()
        chapters, _decisions = select_chapters(
            active.model if active is not None else None,
            active.tokenizer if active is not None else None,
            all_chapters,
            book_title=metadata.title,
            selection=config.selection,
            staging_dir=metadata.staging_dir,
            progress=progress,
        )
    save_extract_chapters(stems, chapters)
    write_json(
        stems.extract_manifest,
        {
            **fingerprint,
            "chapters_hash": file_sha256(stems.chapters_json),
            "title": metadata.title,
            "author": metadata.author,
            "language": metadata.language,
            "chapter_count": len(chapters),
        },
    )
    logger.info("Wrote extract stem (%d chapter(s))", len(chapters))
    return chapters


def _run_clean(
    chapters: list[Chapter],
    *,
    metadata: BookMetadata,
    source_kind: str,
    config: AppConfig,
    stems: BookStems,
    tracker: RunTracker,
    record: BookRecord,
    selected: tuple[str, ...],
    force: bool,
) -> list[CleanSection]:
    extract_hash = file_sha256(stems.chapters_json)
    fingerprint = _clean_fingerprint(
        config, extract_hash=extract_hash, source_kind=source_kind
    )
    clean_ok = (
        manifest_matches(stems.clean_manifest, fingerprint)
        and stems.clean_sections_jsonl.exists()
        and stems.clean_chapters_index.exists()
    )

    if "clean" not in selected:
        if not clean_ok:
            raise FileNotFoundError(
                f"Clean stem missing for {metadata.title!r}. Run --clean first."
            )
        return load_clean_sections(stems)

    if clean_ok and not force:
        logger.info("Clean stem current — skipping deterministic cleanup")
        sections = load_clean_sections(stems)
        record.chapter_count = len({section.chapter_index for section in sections})
        record.chunk_count = len(sections)
        record.word_count = sum(len(section.text.split()) for section in sections)
        tracker.write()
        return sections

    if force and stems.clean_dir.exists():
        shutil.rmtree(stems.clean_dir)

    with tracker.stage(record, "clean"):
        sections = clean_chapters(
            chapters,
            source_kind=source_kind,
            speak_footnote_cues=config.output.speak_footnote_cues,
        )
    if not sections:
        raise ValueError(
            f"No sections left after clean stage for {metadata.title!r}"
        )

    save_clean_sections(stems, sections)
    write_json(
        stems.clean_manifest,
        {
            **fingerprint,
            "sections_hash": clean_sections_hash(stems),
            "section_count": len(sections),
            "chapter_count": len({section.chapter_index for section in sections}),
        },
    )
    record.chapter_count = len({section.chapter_index for section in sections})
    record.chunk_count = len(sections)
    record.word_count = sum(len(section.text.split()) for section in sections)
    tracker.write()
    logger.info(
        "Wrote clean stem (%d section(s) across %d chapter(s))",
        len(sections),
        record.chapter_count,
    )
    return sections


def _chapter_stubs_from_sections(sections: list[CleanSection]) -> list[Chapter]:
    """Unique chapter meta in section order (empty text; scripts filled later)."""
    stubs: list[Chapter] = []
    seen: set[int] = set()
    for section in sections:
        if section.chapter_index in seen:
            continue
        seen.add(section.chapter_index)
        stubs.append(
            Chapter(
                index=section.chapter_index,
                title=section.chapter_title,
                slug=section.chapter_slug,
                text="",
            )
        )
    return stubs


def _format_units_from_cleaned(
    cleaned: list[CleanedChunk],
    *,
    source_kind: str,
) -> list[TextChunk]:
    return [
        TextChunk(
            chapter_index=item.chapter_index,
            chapter_title=item.chapter_title,
            chapter_slug=item.chapter_slug,
            chunk_index=item.chunk_index,
            text=item.cleaned_text,
            source_kind=source_kind,
            instruct=item.instruct,
        )
        for item in cleaned
    ]


def _run_format(
    sections: list[CleanSection],
    *,
    metadata: BookMetadata,
    source_kind: str,
    config: AppConfig,
    stems: BookStems,
    tracker: RunTracker,
    record: BookRecord,
    progress: ProgressContext,
    selected: tuple[str, ...],
    force: bool,
    ensure_llm,
) -> tuple[list[Chapter], list[TextChunk]]:
    clean_hash = (
        clean_sections_hash(stems) if stems.clean_sections_jsonl.exists() else ""
    )
    fingerprint = _format_fingerprint(
        config, clean_hash=clean_hash, source_kind=source_kind
    )
    format_ok = (
        manifest_matches(stems.format_manifest, fingerprint)
        and stems.format_chapters_index.exists()
        and stems.format_chunks_jsonl.exists()
    )

    if "format" not in selected:
        if "speak" in selected and not format_ok:
            raise FileNotFoundError(
                f"Format stem missing for {metadata.title!r}. Run --format first."
            )
        return load_format_scripts(stems), load_format_units(stems)

    if format_ok and not force:
        logger.info("Format stem current — skipping LLM cleanup")
        scripts = load_format_scripts(stems)
        format_units = load_format_units(stems)
        record.chapter_count = len(scripts)
        record.chunk_count = len(format_units)
        record.word_count = sum(len(unit.text.split()) for unit in format_units)
        tracker.write()
        return scripts, format_units

    if force and stems.format_dir.exists():
        shutil.rmtree(stems.format_dir)
    else:
        _drop_stale_format_cache(stems, fingerprint)

    if not sections:
        raise ValueError(
            f"No sections left after clean stage for {metadata.title!r}"
        )

    chunks = build_chunks_from_sections(
        sections,
        config.chunking.format_words_per_chunk,
        max_chunks_per_chapter=config.chunking.max_chunks_per_chapter,
        source_kind=source_kind,
    )
    chapter_stubs = _chapter_stubs_from_sections(sections)
    record.chapter_count = len(chapter_stubs)
    record.chunk_count = len(chunks)
    record.word_count = sum(len(chunk.text.split()) for chunk in chunks)
    tracker.write()
    logger.info(
        "Created %d format window(s) @ %d words",
        len(chunks),
        config.chunking.format_words_per_chunk,
    )

    cache: dict[tuple[int, int], FormatCacheEntry] = {}
    if config.output.skip_existing and not force:
        cache = _load_format_cache(stems, chunks)
        if cache:
            logger.info("Resuming: %d of %d window(s) already formatted", len(cache), len(chunks))

    need_llm = config.llm.cleanup or config.llm.direction
    active_llm = ensure_llm() if need_llm else None
    cleaned_list = list(
        _timed_persist_iter(
            iter_clean_chunks_batched(
                active_llm,
                chunks,
                config.llm,
                already_cleaned=cache,
                progress=progress,
            ),
            tracker=tracker,
            record=record,
            cache=cache,
            stems=stems,
            source_kind=source_kind,
        )
    )
    if config.llm.direction:
        cleaned_list = apply_direction_pass(
            active_llm,
            cleaned_list,
            config.llm,
            progress=progress,
        )
        _rewrite_format_chunks_jsonl(stems, cleaned_list, source_kind=source_kind)
    _write_format_scripts(stems, chapter_stubs, cleaned_list)
    write_json(
        stems.format_manifest,
        {**fingerprint, "scripts_hash": format_scripts_hash(stems)},
    )
    logger.info("Wrote format stem (%d chapter script(s))", len(chapter_stubs))
    scripts = load_format_scripts(stems)
    format_units = _format_units_from_cleaned(cleaned_list, source_kind=source_kind)
    return scripts, format_units


def _write_format_scripts(
    stems: BookStems,
    chapters: list[Chapter],
    cleaned: list[CleanedChunk],
) -> None:
    by_slug: dict[str, list[str]] = defaultdict(list)
    for item in cleaned:
        by_slug[item.chapter_slug].append(item.cleaned_text)
    index = []
    for chapter in chapters:
        text = " ".join(by_slug.get(chapter.slug, []))
        save_format_script(stems, chapter, text)
        index.append({"index": chapter.index, "title": chapter.title, "slug": chapter.slug})
    write_json(stems.format_chapters_index, index)


def _run_speak(
    format_units: list[TextChunk],
    *,
    scripts: list[Chapter],
    metadata: BookMetadata,
    config: AppConfig,
    tts_config: TtsConfig,
    stems: BookStems,
    tts_model: Any,
    tracker: RunTracker,
    record: BookRecord,
    progress: ProgressContext,
    force: bool,
) -> None:
    format_hash = _live_format_hash(stems, config)
    fingerprint = _speak_fingerprint(config, tts_config, format_hash=format_hash)
    speak_ok = manifest_matches(stems.speak_manifest, fingerprint)

    units = build_speak_units_from_chunks(
        format_units,
        target_chars=config.chunking.speak_target_chars,
        max_chars=config.chunking.speak_max_chars,
    )
    record.chapter_count = len(scripts)
    record.chunk_count = len(units)
    record.word_count = sum(len(unit.text.split()) for unit in format_units)
    tracker.write()
    logger.info(
        "Created %d speak unit(s) (target %d chars, cap %d)",
        len(units),
        config.chunking.speak_target_chars,
        config.chunking.speak_max_chars,
    )

    if force and stems.speak_wav_dir.exists():
        shutil.rmtree(stems.speak_wav_dir)

    previous_hashes: dict[tuple[str, int], str] = {}
    for row in load_jsonl(stems.speak_units_jsonl):
        try:
            previous_hashes[(str(row["chapter_slug"]), int(row["chunk_index"]))] = str(
                row["text_hash"]
            )
        except (KeyError, TypeError, ValueError):
            continue

    unit_rows = [
        {
            "chapter_index": unit.chapter_index,
            "chapter_slug": unit.chapter_slug,
            "chapter_title": unit.chapter_title,
            "chunk_index": unit.chunk_index,
            "text": unit.text,
            "text_hash": text_hash(unit.text),
            "instruct": unit.instruct,
        }
        for unit in units
    ]
    stems.speak_units_jsonl.parent.mkdir(parents=True, exist_ok=True)
    stems.speak_units_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in unit_rows),
        encoding="utf-8",
    )

    with ThreadPoolExecutor(max_workers=max(1, config.pipeline.ffmpeg_workers)) as executor:
        wavs_by_slug, futures = _synthesize_and_encode(
            units,
            tts_model=tts_model,
            config=config,
            tts_config=tts_config,
            metadata=metadata,
            stems=stems,
            tracker=tracker,
            record=record,
            executor=executor,
            progress=progress,
            skip_wavs=config.output.skip_existing and speak_ok and not force,
            previous_text_hashes=previous_hashes,
        )
        for future in futures:
            future.result()

    with tracker.stage(record, "m4b"):
        chapter_wavs = [
            (chapter.title, wavs_by_slug[chapter.slug])
            for chapter in scripts
            if wavs_by_slug.get(chapter.slug)
        ]
        build_m4b(
            metadata.m4b_path,
            chapter_wavs,
            title=metadata.title,
            author=metadata.author,
            language=metadata.language,
            cover_bytes=metadata.cover_bytes,
            bitrate=config.output.m4b_bitrate,
            chapter_silence_ms=config.output.chapter_silence_ms,
            loudnorm=config.output.loudnorm,
        )

    write_json(stems.speak_manifest, fingerprint)

    if not config.output.keep_wav:
        if stems.speak_wav_dir.exists():
            shutil.rmtree(stems.speak_wav_dir)
            logger.info("Removed WAV directory: %s", stems.speak_wav_dir)
    if not config.output.chapter_mp3 and not config.output.keep_wav:
        mp3_root = metadata.staging_dir / "mp3"
        if mp3_root.exists():
            shutil.rmtree(mp3_root)
            logger.info("Removed MP3 directory: %s", mp3_root)

    tracker.finish_book(record, status="ok", output_path=metadata.m4b_path)


def _synthesize_and_encode(
    units: list[TextChunk],
    *,
    tts_model: Any,
    config: AppConfig,
    tts_config: TtsConfig,
    metadata: BookMetadata,
    stems: BookStems,
    tracker: RunTracker,
    record: BookRecord,
    executor: ThreadPoolExecutor,
    progress: ProgressContext,
    skip_wavs: bool,
    previous_text_hashes: dict[tuple[str, int], str] | None = None,
) -> tuple[dict[str, list[Path]], list[Future]]:
    expected = Counter(unit.chapter_slug for unit in units)
    done: Counter[str] = Counter()
    wavs_by_slug: dict[str, list[Path]] = defaultdict(list)
    futures: list[Future] = []
    total = len(units)
    slug_titles = {unit.chapter_slug: unit.chapter_title for unit in units}
    chapter_order = {
        slug: idx for idx, slug in enumerate(dict.fromkeys(unit.chapter_slug for unit in units))
    }
    total_chapters = len(chapter_order)

    def encode_job(wav_paths: list[Path], mp3_path: Path, chapter_title: str) -> None:
        start = time.perf_counter()
        encode_chapter_mp3(
            wav_paths,
            mp3_path,
            bitrate=config.output.mp3_bitrate,
            loudnorm=config.output.loudnorm,
            progress=progress,
            chapter_title=chapter_title,
        )
        tracker.add_duration(record, "encode", time.perf_counter() - start)

    for unit_number, unit in enumerate(units, start=1):
        wav_path = stems.speak_wav_dir / unit.chapter_slug / f"{unit.chunk_index:04d}.wav"
        prior = (previous_text_hashes or {}).get((unit.chapter_slug, unit.chunk_index))
        hash_ok = prior == text_hash(unit.text)
        if not (skip_wavs and wav_path.exists() and hash_ok):
            start = time.perf_counter()
            synthesize_to_wav(
                tts_model,
                unit.text,
                wav_path,
                voice=tts_config.voice,
                language=tts_config.lang,
                instruct=compose_instruct(tts_config.instruct, unit.instruct),
                chunk_silence_ms=config.output.chunk_silence_ms,
                model_id=tts_config.model_id,
            )
            tracker.add_duration(record, "tts", time.perf_counter() - start)
        logger.info(
            "%s",
            progress.format(
                "tts",
                unit_done=unit_number,
                total_chunks=total,
                chapter_idx=chapter_order[unit.chapter_slug],
                total_chapters=total_chapters,
                chapter_title=unit.chapter_title,
                chapter_unit=unit.chunk_index + 1,
                chapter_units=expected[unit.chapter_slug],
            ),
        )
        wavs_by_slug[unit.chapter_slug].append(wav_path)
        done[unit.chapter_slug] += 1
        if done[unit.chapter_slug] == expected[unit.chapter_slug] and config.output.chapter_mp3:
            mp3_path = metadata.staging_dir / "mp3" / f"{unit.chapter_slug}.mp3"
            chapter_title = slug_titles.get(unit.chapter_slug, unit.chapter_slug)
            futures.append(
                executor.submit(
                    encode_job, list(wavs_by_slug[unit.chapter_slug]), mp3_path, chapter_title
                )
            )

    return dict(wavs_by_slug), futures


def _timed_persist_iter(
    source: Iterator[CleanedChunk],
    *,
    tracker: RunTracker,
    record: BookRecord,
    cache: dict[tuple[int, int], FormatCacheEntry | str],
    stems: BookStems,
    source_kind: str,
) -> Iterator[CleanedChunk]:
    while True:
        start = time.perf_counter()
        try:
            item = next(source)
        except StopIteration:
            return
        finally:
            tracker.add_duration(record, "format", time.perf_counter() - start)
        if (item.chapter_index, item.chunk_index) not in cache:
            append_jsonl(
                stems.format_chunks_jsonl,
                {
                    "chapter_index": item.chapter_index,
                    "chunk_index": item.chunk_index,
                    "chapter_title": item.chapter_title,
                    "chapter_slug": item.chapter_slug,
                    "source_kind": source_kind,
                    "raw_hash": text_hash(item.raw_text),
                    "cleaned_text": item.cleaned_text,
                    "instruct": item.instruct,
                },
            )
        yield item


def _rewrite_format_chunks_jsonl(
    stems: BookStems,
    cleaned: list[CleanedChunk],
    *,
    source_kind: str,
) -> None:
    """Rewrite format/chunks.jsonl so resume cache includes per-chunk instruct."""
    rows = [
        {
            "chapter_index": item.chapter_index,
            "chunk_index": item.chunk_index,
            "chapter_title": item.chapter_title,
            "chapter_slug": item.chapter_slug,
            "source_kind": source_kind,
            "raw_hash": text_hash(item.raw_text),
            "cleaned_text": item.cleaned_text,
            "instruct": item.instruct,
        }
        for item in cleaned
    ]
    stems.format_chunks_jsonl.parent.mkdir(parents=True, exist_ok=True)
    stems.format_chunks_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _format_in_progress_path(stems: BookStems) -> Path:
    return stems.format_dir / "in_progress.json"


def _drop_stale_format_cache(stems: BookStems, fingerprint: dict[str, Any]) -> None:
    """Keep chunks.jsonl only when it was written under the current format fingerprint."""
    in_progress = _format_in_progress_path(stems)
    if not manifest_matches(in_progress, fingerprint) and stems.format_chunks_jsonl.exists():
        stems.format_chunks_jsonl.unlink()
        logger.info("Dropped stale format cache at %s", stems.format_chunks_jsonl)
    write_json(in_progress, fingerprint)


def _load_format_cache(
    stems: BookStems, chunks: list[TextChunk]
) -> dict[tuple[int, int], FormatCacheEntry]:
    expected_hashes = {
        (chunk.chapter_index, chunk.chunk_index): text_hash(chunk.text) for chunk in chunks
    }
    cache: dict[tuple[int, int], FormatCacheEntry] = {}
    for entry in load_jsonl(stems.format_chunks_jsonl):
        try:
            key = (int(entry["chapter_index"]), int(entry["chunk_index"]))
            if expected_hashes.get(key) == entry["raw_hash"]:
                instruct_raw = entry.get("instruct")
                instruct = (
                    None
                    if instruct_raw is None
                    else str(instruct_raw).strip() or None
                )
                cache[key] = FormatCacheEntry(
                    cleaned_text=str(entry["cleaned_text"]),
                    instruct=instruct,
                )
        except (ValueError, KeyError, TypeError):
            logger.debug("Skipping malformed format cache entry")
    return cache


def _log_summary(tracker: RunTracker, elapsed: float) -> None:
    counts = Counter(record.status for record in tracker.books)
    logger.info("")
    logger.info("Run summary (%s):", tracker.run_id)
    for record in tracker.books:
        name = record.title or Path(record.source_path).name
        if record.author:
            name = f"{name} — {record.author}"
        duration = f"{record.total_seconds:.1f}s" if record.total_seconds is not None else "-"
        line = f"  {record.status:<8s} {name} [{duration}]"
        if record.status == "ok" and record.output_path:
            line += f" -> {record.output_path}"
        if record.error:
            line += f" ({record.error})"
        logger.info("%s", line)
    logger.info(
        "Books: %d ok, %d skipped, %d failed in %.1fs",
        counts.get("ok", 0),
        counts.get("skipped", 0),
        counts.get("failed", 0),
        elapsed,
    )
