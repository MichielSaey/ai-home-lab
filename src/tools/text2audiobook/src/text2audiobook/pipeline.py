"""Fire-and-forget orchestration: multi-book loop and the LLM→TTS→ffmpeg pipeline.

Concurrent mode (pipeline.concurrent_models = true) keeps Qwen and Kokoro
resident on the GPU for the whole run: an LLM thread produces cleaned chunks
into a bounded queue, the main thread consumes them into WAVs, and finished
chapters are encoded by a small ffmpeg thread pool. Sequential mode falls back
to the original notebook behavior: clean everything, unload the LLM, then
load Kokoro and synthesize.
"""

import json
import logging
import platform
import queue
import shutil
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from text2audiobook import formats  # noqa: F401 — register built-in readers
from text2audiobook.audio import build_m4b, encode_chapter_mp3
from text2audiobook.catalog import select_chapters
from text2audiobook.chunking import TextChunk, build_chunks
from text2audiobook.config import AppConfig
from text2audiobook.gpu import resolve_tts_device
from text2audiobook.io import BookMetadata, find_sources, parse_source
from text2audiobook.llm import (
    CleanedChunk,
    LoadedLlm,
    iter_clean_chunks_batched,
    load_llm,
    text_hash,
    unload_llm,
)
from text2audiobook.logging_setup import ProgressContext, setup_logging
from text2audiobook.tracking import BookRecord, RunTracker
from text2audiobook.tts import (
    KOKORO_REPO_ID,
    load_kokoro,
    synthesize_to_wav,
    unload_kokoro,
)

logger = logging.getLogger(__name__)

_SENTINEL: Any = object()


def run(
    config: AppConfig,
    *,
    source_paths: list[Path] | None = None,
) -> int:
    """Process supported sources. Returns a process exit code.

    When ``source_paths`` is provided (e.g. from ``--url``), those paths are
    used and the input directory is not scanned.
    """
    tracker = RunTracker(config.paths.runs_dir, config.to_dict())
    setup_logging(tracker.log_path)
    logger.info("Run %s — manifest: %s", tracker.run_id, tracker.run_json_path)
    logger.debug("Config: %s", json.dumps(config.to_dict(), indent=2))

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

    need_llm = config.llm.cleanup or config.selection.keep_chapter_indices is None
    tts_device = resolve_tts_device(config.tts.device)
    tracker.set_environment(
        python=platform.python_version(),
        llm_model_id=config.llm.model_id if need_llm else None,
        llm_device=config.llm.device if need_llm else None,
        tts_model_id=KOKORO_REPO_ID,
        tts_device=tts_device,
        concurrent_models=config.pipeline.concurrent_models,
    )

    llm: LoadedLlm | None = None
    kokoro: Any = None
    started = time.perf_counter()
    interrupted = False
    fatal = False

    try:
        if config.pipeline.concurrent_models:
            if need_llm:
                llm = load_llm(config.llm)
            kokoro = load_kokoro(config.tts, device=tts_device)

        for position, source_path in enumerate(sources, start=1):
            record = tracker.start_book(source_path)
            try:
                process_source(
                    source_path,
                    config,
                    tracker=tracker,
                    record=record,
                    llm=llm,
                    kokoro=kokoro,
                    position=(position, len(sources)),
                    tts_device=tts_device,
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
    kokoro: Any = None,
    position: tuple[int, int] | None = None,
    tts_device: str | None = None,
) -> None:
    """Convert one source file to an M4B.

    In concurrent mode the resident llm/kokoro are passed in; otherwise models
    are loaded and unloaded around their stage (notebook-style swap).
    """
    concurrent = config.pipeline.concurrent_models
    if tts_device is None:
        tts_device = resolve_tts_device(config.tts.device)

    with tracker.stage(record, "parse"):
        metadata, all_chapters = parse_source(
            source_path,
            staging_root=config.paths.staging_dir,
            output_root=config.paths.output_dir,
        )
    record.title = metadata.title
    record.author = metadata.author
    tracker.write()

    book_idx, total_books = position if position is not None else (1, 1)
    progress = ProgressContext(
        book_title=metadata.title,
        book_idx=book_idx,
        total_books=total_books,
    )

    if position is not None:
        logger.info("")
        logger.info(
            "=== [%d/%d] %s — %s ===", position[0], position[1], metadata.title, metadata.author
        )

    m4b_path = metadata.m4b_path
    if config.output.skip_existing and m4b_path.exists():
        logger.info("Skipping '%s' — audiobook already exists: %s", metadata.title, m4b_path)
        tracker.finish_book(record, status="skipped", output_path=m4b_path)
        return

    logger.info("Source catalog (%d sections):", len(all_chapters))
    for chapter in all_chapters:
        logger.info("  [%2d] %s (%d words)", chapter.index, chapter.title, len(chapter.text.split()))

    need_llm = config.llm.cleanup or config.selection.keep_chapter_indices is None
    own_llm: LoadedLlm | None = None
    own_kokoro: Any = None

    try:
        if not concurrent and need_llm and llm is None:
            own_llm = load_llm(config.llm)
        active_llm = llm if llm is not None else own_llm

        with tracker.stage(record, "classify"):
            chapters, _decisions = select_chapters(
                active_llm.model if active_llm is not None else None,
                active_llm.tokenizer if active_llm is not None else None,
                all_chapters,
                book_title=metadata.title,
                selection=config.selection,
                staging_dir=metadata.staging_dir,
                progress=progress,
            )

        chunks = build_chunks(
            chapters,
            config.chunking.words_per_chunk,
            max_chunks_per_chapter=config.chunking.max_chunks_per_chapter,
        )
        record.chapter_count = len(chapters)
        record.chunk_count = len(chunks)
        record.word_count = sum(len(chunk.text.split()) for chunk in chunks)
        tracker.write()
        logger.info("Created %d chunk(s) @ %d words each", len(chunks), config.chunking.words_per_chunk)

        cache: dict[tuple[int, int], str] = {}
        if config.output.skip_existing:
            cache = _load_cleaned_cache(metadata.staging_dir, chunks)
            if cache:
                logger.info("Resuming: %d of %d chunk(s) already cleaned", len(cache), len(chunks))

        with ThreadPoolExecutor(max_workers=max(1, config.pipeline.ffmpeg_workers)) as executor:
            if concurrent:
                wavs_by_slug, futures = _run_concurrent(
                    llm=active_llm,
                    kokoro=kokoro,
                    chunks=chunks,
                    cache=cache,
                    config=config,
                    metadata=metadata,
                    tracker=tracker,
                    record=record,
                    executor=executor,
                    progress=progress,
                )
            else:
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
                        staging_dir=metadata.staging_dir,
                    )
                )
                if own_llm is not None:
                    unload_llm(own_llm)
                    own_llm = None
                    logger.info("Unloaded LLM to free GPU memory for Kokoro")
                own_kokoro = load_kokoro(config.tts, device=tts_device)
                wavs_by_slug, futures = _synthesize_and_encode(
                    iter(cleaned_list),
                    kokoro=own_kokoro,
                    chunks=chunks,
                    config=config,
                    metadata=metadata,
                    tracker=tracker,
                    record=record,
                    executor=executor,
                    progress=progress,
                )
            for future in futures:
                future.result()

        with tracker.stage(record, "m4b"):
            chapter_wavs = [
                (chapter.title, wavs_by_slug[chapter.slug])
                for chapter in chapters
                if wavs_by_slug.get(chapter.slug)
            ]
            build_m4b(
                m4b_path,
                chapter_wavs,
                title=metadata.title,
                author=metadata.author,
                language=metadata.language,
                cover_bytes=metadata.cover_bytes,
                bitrate=config.output.m4b_bitrate,
                chapter_silence_ms=config.output.chapter_silence_ms,
                loudnorm=config.output.loudnorm,
            )

        if not config.output.keep_wav:
            wav_root = metadata.staging_dir / "wav"
            if wav_root.exists():
                shutil.rmtree(wav_root)
                logger.info("Removed WAV directory: %s", wav_root)
        if not config.output.chapter_mp3 and not config.output.keep_wav:
            mp3_root = metadata.staging_dir / "mp3"
            if mp3_root.exists():
                shutil.rmtree(mp3_root)
                logger.info("Removed MP3 directory: %s", mp3_root)

        tracker.finish_book(record, status="ok", output_path=m4b_path)
    finally:
        if own_llm is not None:
            unload_llm(own_llm)
        if own_kokoro is not None:
            unload_kokoro(own_kokoro)


def _run_concurrent(
    *,
    llm: LoadedLlm | None,
    kokoro: Any,
    chunks: list[TextChunk],
    cache: dict[tuple[int, int], str],
    config: AppConfig,
    metadata: BookMetadata,
    tracker: RunTracker,
    record: BookRecord,
    executor: ThreadPoolExecutor,
    progress: ProgressContext,
) -> tuple[dict[str, list[Path]], list[Future]]:
    """LLM thread feeds a bounded queue; the calling thread synthesizes WAVs."""
    work_queue: queue.Queue[Any] = queue.Queue(maxsize=max(1, config.pipeline.queue_size))
    stop = threading.Event()
    producer_error: list[BaseException] = []

    def produce() -> None:
        try:
            items = _timed_persist_iter(
                iter_clean_chunks_batched(
                    llm,
                    chunks,
                    config.llm,
                    already_cleaned=cache,
                    stop=stop,
                    progress=progress,
                ),
                tracker=tracker,
                record=record,
                cache=cache,
                staging_dir=metadata.staging_dir,
            )
            for item in items:
                if not _bounded_put(work_queue, item, stop):
                    return
        except BaseException as exc:
            producer_error.append(exc)
            logger.debug("LLM producer failed", exc_info=True)
        finally:
            _bounded_put(work_queue, _SENTINEL, stop)

    producer = threading.Thread(target=produce, name="llm-cleanup", daemon=True)
    producer.start()
    try:
        result = _synthesize_and_encode(
            _queue_iter(work_queue),
            kokoro=kokoro,
            chunks=chunks,
            config=config,
            metadata=metadata,
            tracker=tracker,
            record=record,
            executor=executor,
            progress=progress,
        )
    finally:
        stop.set()
        producer.join()
    if producer_error:
        raise producer_error[0]
    return result


def _synthesize_and_encode(
    cleaned_iter: Iterator[CleanedChunk],
    *,
    kokoro: Any,
    chunks: list[TextChunk],
    config: AppConfig,
    metadata: BookMetadata,
    tracker: RunTracker,
    record: BookRecord,
    executor: ThreadPoolExecutor,
    progress: ProgressContext,
) -> tuple[dict[str, list[Path]], list[Future]]:
    """Consume cleaned chunks into WAVs; submit each finished chapter to the ffmpeg pool."""
    expected = Counter(chunk.chapter_slug for chunk in chunks)
    done: Counter[str] = Counter()
    wavs_by_slug: dict[str, list[Path]] = defaultdict(list)
    futures: list[Future] = []
    total = len(chunks)
    slug_titles = {chunk.chapter_slug: chunk.chapter_title for chunk in chunks}

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

    for cleaned in cleaned_iter:
        wav_path = (
            metadata.staging_dir / "wav" / cleaned.chapter_slug / f"{cleaned.chunk_index:04d}.wav"
        )
        if not (config.output.skip_existing and wav_path.exists()):
            start = time.perf_counter()
            synthesize_to_wav(
                kokoro,
                cleaned.cleaned_text,
                wav_path,
                voice=config.tts.voice,
                speed=config.tts.speed,
                chunk_silence_ms=config.output.chunk_silence_ms,
            )
            tracker.add_duration(record, "tts", time.perf_counter() - start)
        logger.info(
            "%s",
            progress.format(
                "tts",
                chunk_idx=cleaned.chunk_index,
                chapter_title=cleaned.chapter_title,
                total_chunks=total,
            ),
        )

        wavs_by_slug[cleaned.chapter_slug].append(wav_path)
        done[cleaned.chapter_slug] += 1
        if done[cleaned.chapter_slug] == expected[cleaned.chapter_slug] and config.output.chapter_mp3:
            mp3_path = metadata.staging_dir / "mp3" / f"{cleaned.chapter_slug}.mp3"
            chapter_title = slug_titles.get(cleaned.chapter_slug, cleaned.chapter_slug)
            futures.append(
                executor.submit(
                    encode_job, list(wavs_by_slug[cleaned.chapter_slug]), mp3_path, chapter_title
                )
            )

    return dict(wavs_by_slug), futures


def _timed_persist_iter(
    source: Iterator[CleanedChunk],
    *,
    tracker: RunTracker,
    record: BookRecord,
    cache: dict[tuple[int, int], str],
    staging_dir: Path,
) -> Iterator[CleanedChunk]:
    """Time the clean stage and persist newly cleaned chunks to cleaned.jsonl."""
    while True:
        start = time.perf_counter()
        try:
            item = next(source)
        except StopIteration:
            return
        finally:
            tracker.add_duration(record, "clean", time.perf_counter() - start)
        if (item.chapter_index, item.chunk_index) not in cache:
            _append_cleaned(staging_dir, item)
        yield item


def _cleaned_jsonl_path(staging_dir: Path, chapter_slug: str) -> Path:
    return staging_dir / "wav" / chapter_slug / "cleaned.jsonl"


def _append_cleaned(staging_dir: Path, cleaned: CleanedChunk) -> None:
    path = _cleaned_jsonl_path(staging_dir, cleaned.chapter_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "chapter_index": cleaned.chapter_index,
        "chunk_index": cleaned.chunk_index,
        "raw_hash": text_hash(cleaned.raw_text),
        "cleaned_text": cleaned.cleaned_text,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_cleaned_cache(staging_dir: Path, chunks: list[TextChunk]) -> dict[tuple[int, int], str]:
    """Cleaned text from previous runs, keyed by (chapter_index, chunk_index).

    Entries only count when their raw-text hash still matches the current
    chunk, so changed chunking or source text invalidates the cache.
    """
    expected_hashes = {(chunk.chapter_index, chunk.chunk_index): text_hash(chunk.text) for chunk in chunks}
    cache: dict[tuple[int, int], str] = {}
    for slug in {chunk.chapter_slug for chunk in chunks}:
        path = _cleaned_jsonl_path(staging_dir, slug)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                key = (int(entry["chapter_index"]), int(entry["chunk_index"]))
                if expected_hashes.get(key) == entry["raw_hash"]:
                    cache[key] = str(entry["cleaned_text"])
            except (ValueError, KeyError, TypeError):
                logger.debug("Skipping malformed cleaned.jsonl line in %s", path)
    return cache


def _bounded_put(work_queue: queue.Queue, item: Any, stop: threading.Event) -> bool:
    """Put with backpressure that still notices a dead consumer."""
    while not stop.is_set():
        try:
            work_queue.put(item, timeout=0.5)
            return True
        except queue.Full:
            continue
    return False


def _queue_iter(work_queue: queue.Queue) -> Iterator[CleanedChunk]:
    while True:
        item = work_queue.get()
        if item is _SENTINEL:
            return
        yield item


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
