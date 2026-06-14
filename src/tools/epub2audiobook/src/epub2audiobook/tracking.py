"""Run tracking: per-stage timings, run.json manifests, and a cross-run ledger.

run.json is rewritten after every book so a crash mid-run keeps all finished
data; ledger.jsonl gets one summary line per book for cross-run comparison.
In concurrent mode the clean/tts/encode stages overlap, so stage durations
measure active time per stage and may sum to more than the wall clock.
"""

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

STAGES = ("parse", "classify", "clean", "tts", "encode", "m4b")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class BookRecord:
    epub_path: str
    title: str | None = None
    author: str | None = None
    status: str = "running"  # running | ok | skipped | failed
    error: str | None = None
    output_path: str | None = None
    chapter_count: int | None = None
    chunk_count: int | None = None
    word_count: int | None = None
    durations: dict[str, float] = field(default_factory=dict)
    total_seconds: float | None = None
    started_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["durations"] = {name: round(value, 3) for name, value in self.durations.items()}
        return data


class RunTracker:
    """Tracks one fire-and-forget run across all books."""

    def __init__(
        self,
        runs_dir: Path,
        config_snapshot: dict[str, Any],
        *,
        run_id: str | None = None,
    ) -> None:
        runs_dir = Path(runs_dir)
        self.run_id = run_id or self._new_run_id(runs_dir)
        self.run_dir = runs_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_json_path = self.run_dir / "run.json"
        self.log_path = self.run_dir / "run.log"
        self.ledger_path = runs_dir / "ledger.jsonl"

        self.config_snapshot = config_snapshot
        self.environment: dict[str, Any] = {}
        self.books: list[BookRecord] = []
        self.status = "running"
        self.started_at = _now_iso()
        self.finished_at: str | None = None

        self._book_starts: dict[int, float] = {}
        self._lock = threading.RLock()
        self.write()

    @staticmethod
    def _new_run_id(runs_dir: Path) -> str:
        base = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = base
        suffix = 2
        while (runs_dir / run_id).exists():
            run_id = f"{base}_{suffix}"
            suffix += 1
        return run_id

    def set_environment(self, **values: Any) -> None:
        with self._lock:
            self.environment.update(values)
        self.write()

    def start_book(self, epub_path: Path) -> BookRecord:
        record = BookRecord(epub_path=str(epub_path))
        with self._lock:
            self.books.append(record)
            self._book_starts[id(record)] = time.perf_counter()
        self.write()
        return record

    @contextmanager
    def stage(self, record: BookRecord, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.add_duration(record, name, time.perf_counter() - start)

    def add_duration(self, record: BookRecord, name: str, seconds: float) -> None:
        """Accumulate active time for a stage (thread-safe)."""
        with self._lock:
            record.durations[name] = record.durations.get(name, 0.0) + seconds

    def finish_book(
        self,
        record: BookRecord,
        *,
        status: str,
        error: str | None = None,
        output_path: Path | str | None = None,
    ) -> None:
        with self._lock:
            record.status = status
            record.error = error
            if output_path is not None:
                record.output_path = str(output_path)
            record.finished_at = _now_iso()
            start = self._book_starts.pop(id(record), None)
            if start is not None:
                record.total_seconds = round(time.perf_counter() - start, 3)
        self.write()
        self._append_ledger(record)

    def finalize(self, status: str = "completed") -> None:
        with self._lock:
            self.status = status
            self.finished_at = _now_iso()
        self.write()

    def write(self) -> None:
        """Atomically rewrite run.json with the current state."""
        with self._lock:
            payload = {
                "run_id": self.run_id,
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "environment": dict(self.environment),
                "config": self.config_snapshot,
                "books": [record.to_dict() for record in self.books],
            }
            tmp_path = self.run_json_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            tmp_path.replace(self.run_json_path)

    def _ledger_settings(self) -> dict[str, Any]:
        def section(name: str) -> dict[str, Any]:
            value = self.config_snapshot.get(name)
            return value if isinstance(value, dict) else {}

        return {
            "llm_model_id": section("llm").get("model_id"),
            "cleanup": section("llm").get("cleanup"),
            "cleanup_batch_size": section("llm").get("cleanup_batch_size"),
            "voice": section("tts").get("voice"),
            "speed": section("tts").get("speed"),
            "words_per_chunk": section("chunking").get("words_per_chunk"),
            "concurrent_models": section("pipeline").get("concurrent_models"),
            "llm_device": self.environment.get("llm_device"),
            "tts_device": self.environment.get("tts_device"),
        }

    def _append_ledger(self, record: BookRecord) -> None:
        line = {
            "run_id": self.run_id,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "epub_path": record.epub_path,
            "title": record.title,
            "author": record.author,
            "status": record.status,
            "error": record.error,
            "output_path": record.output_path,
            "chapter_count": record.chapter_count,
            "chunk_count": record.chunk_count,
            "word_count": record.word_count,
            "durations": {name: round(value, 3) for name, value in record.durations.items()},
            "total_seconds": record.total_seconds,
            "settings": self._ledger_settings(),
        }
        with self._lock:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
