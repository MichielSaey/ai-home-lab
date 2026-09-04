"""Logging: bare console lines (identical to the notebook prints) plus a timestamped file log."""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_LOGGER = "text2audiobook"
_CONSOLE_FORMAT = "%(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def _truncate(text: str, max_len: int = 24) -> str:
    text = " ".join(text.strip().split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _pct(done: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{min(100, round(100 * done / total))}%"


def format_progress(
    book_title: str,
    book_idx: int,
    total_books: int,
    step: str,
    *,
    chunk_idx: int | None = None,
    chapter_title: str | None = None,
    total_chunks: int | None = None,
    unit_done: int | None = None,
    chapter_idx: int | None = None,
    total_chapters: int | None = None,
    chapter_unit: int | None = None,
    chapter_units: int | None = None,
) -> str:
    """Human-readable progress line with labels and completion percent.

    Examples:
      [book 1/1 Nick Land] stage=tts unit=42/1313 (3%) chapter=12/201 Capital Escapes unit=4/8
      [book 2/5 Invisible Man] stage=classify openings
    """
    book = f"[book {book_idx}/{total_books} {_truncate(book_title, 28)}]"
    parts = [book, f"stage={step}"]

    if unit_done is not None and total_chunks is not None:
        parts.append(f"unit={unit_done}/{total_chunks} ({_pct(unit_done, total_chunks)})")
    elif chunk_idx is not None and total_chunks is not None:
        # 0-based chunk index → display as completed count when unit_done absent
        done = chunk_idx + 1
        parts.append(f"unit={done}/{total_chunks} ({_pct(done, total_chunks)})")

    if chapter_idx is not None and total_chapters is not None and chapter_title is not None:
        chapter_bit = (
            f"chapter={chapter_idx + 1}/{total_chapters} {_truncate(chapter_title)}"
        )
        if chapter_unit is not None and chapter_units is not None:
            chapter_bit += f" unit={chapter_unit}/{chapter_units}"
        parts.append(chapter_bit)
    elif chapter_title is not None:
        parts.append(f"chapter={_truncate(chapter_title)}")

    return " | ".join(parts)


@dataclass
class ProgressContext:
    """Book-level progress for unified log lines."""

    book_title: str
    book_idx: int = 1
    total_books: int = 1

    def format(
        self,
        step: str,
        *,
        chunk_idx: int | None = None,
        chapter_title: str | None = None,
        total_chunks: int | None = None,
        unit_done: int | None = None,
        chapter_idx: int | None = None,
        total_chapters: int | None = None,
        chapter_unit: int | None = None,
        chapter_units: int | None = None,
    ) -> str:
        return format_progress(
            self.book_title,
            self.book_idx,
            self.total_books,
            step,
            chunk_idx=chunk_idx,
            chapter_title=chapter_title,
            total_chunks=total_chunks,
            unit_done=unit_done,
            chapter_idx=chapter_idx,
            total_chapters=total_chapters,
            chapter_unit=chapter_unit,
            chapter_units=chapter_units,
        )


def setup_logging(
    log_file: Path | None = None, *, console_level: int = logging.INFO
) -> logging.Logger:
    """Configure the package logger.

    Console output stays byte-identical to the original notebook prints (bare
    messages on stdout); the optional per-run file log gets timestamps and
    levels. Safe to call repeatedly: handlers are replaced, not stacked.
    """
    logger = logging.getLogger(PACKAGE_LOGGER)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    logger.addHandler(console)

    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        logger.addHandler(file_handler)

    return logger
