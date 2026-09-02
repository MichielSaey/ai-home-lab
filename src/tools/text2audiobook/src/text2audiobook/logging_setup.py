"""Logging: bare console lines (identical to the notebook prints) plus a timestamped file log."""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_LOGGER = "text2audiobook"
_CONSOLE_FORMAT = "%(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def _truncate(text: str, max_len: int = 10) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


def format_progress(
    book_title: str,
    book_idx: int,
    total_books: int,
    step: str,
    *,
    chunk_idx: int | None = None,
    chapter_title: str | None = None,
    total_chunks: int | None = None,
) -> str:
    """Unified progress prefix: [Book/idx/total] [chunk|Chapter|total] step."""
    book_part = f"[{_truncate(book_title)}/{book_idx}/{total_books}]"
    if chunk_idx is not None and chapter_title is not None and total_chunks is not None:
        chunk_part = f"[{chunk_idx}|{_truncate(chapter_title)}|{total_chunks}]"
        return f"{book_part} {chunk_part} {step}"
    if chapter_title is not None:
        return f"{book_part} [{_truncate(chapter_title)}] {step}"
    return f"{book_part} {step}"


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
    ) -> str:
        return format_progress(
            self.book_title,
            self.book_idx,
            self.total_books,
            step,
            chunk_idx=chunk_idx,
            chapter_title=chapter_title,
            total_chunks=total_chunks,
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
