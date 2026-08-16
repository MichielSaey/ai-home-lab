"""Copy or rsync a finished M4B into a Jellyfin audiobook library and trigger a scan."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from epub2audiobook.config import AppConfig, PublishConfig
from epub2audiobook.epub_io import BookMetadata
from epub2audiobook.tracking import BookRecord, RunTracker

logger = logging.getLogger(__name__)

_UNSAFE_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEFAULT_TIMEOUT_S = 30
_RSYNC_TIMEOUT_S = 600


@dataclass(frozen=True)
class PublishResult:
    dest_path: str
    notified: bool
    mode: str


def library_name(text: str, fallback: str) -> str:
    """Filesystem-safe folder/file name that keeps spaces for Jellyfin."""
    cleaned = _UNSAFE_FS.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:200] or fallback


def book_rel_dir(author: str, title: str) -> Path:
    return Path(library_name(author, "Unknown Author")) / library_name(title, "Unknown Title")


def book_rel_m4b(author: str, title: str) -> Path:
    title_name = library_name(title, "Unknown Title")
    return book_rel_dir(author, title) / f"{title_name}.m4b"


def cover_filename(cover_bytes: bytes) -> str:
    if cover_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "cover.png"
    return "cover.jpg"


def jellyfin_item_path(container_root: str, author: str, title: str) -> str:
    """Path Jellyfin should scan — must match the file inside the container."""
    rel = book_rel_m4b(author, title).as_posix()
    return f"{container_root.rstrip('/')}/{rel}"


def remote_root_from_rsync_target(target: str) -> str:
    """Host-side directory from `user@host:/path` or `/path`."""
    if ":" in target and not target.startswith("/"):
        return target.split(":", 1)[1]
    return target


def resolved_mode(config: PublishConfig) -> str:
    if config.mode in {"copy", "rsync"}:
        return config.mode
    if config.rsync_target:
        return "rsync"
    return "copy"


def resolved_container_root(config: PublishConfig) -> str | None:
    if config.container_path:
        return config.container_path.rstrip("/")
    if config.rsync_target:
        return remote_root_from_rsync_target(config.rsync_target).rstrip("/")
    if config.library_root is not None:
        return str(config.library_root).rstrip("/")
    return None


def stage_book_tree(
    dest_root: Path,
    m4b_path: Path,
    metadata: BookMetadata,
) -> Path:
    """Write Author/Title/{Title.m4b, cover.*} under dest_root. Returns the book dir."""
    rel_dir = book_rel_dir(metadata.author, metadata.title)
    book_dir = dest_root / rel_dir
    book_dir.mkdir(parents=True, exist_ok=True)

    dest_m4b = dest_root / book_rel_m4b(metadata.author, metadata.title)
    _atomic_copy(m4b_path, dest_m4b)

    if metadata.cover_bytes:
        cover_path = book_dir / cover_filename(metadata.cover_bytes)
        cover_path.write_bytes(metadata.cover_bytes)

    return book_dir


def _atomic_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".partial", dir=dest.parent)
    tmp_path = Path(tmp_name)
    try:
        os.close(fd)
        shutil.copy2(src, tmp_path)
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def copy_to_library(config: PublishConfig, m4b_path: Path, metadata: BookMetadata) -> Path:
    if config.library_root is None:
        raise ValueError("JELLYFIN_LIBRARY_ROOT is required for copy mode")
    root = Path(config.library_root)
    stage_book_tree(root, m4b_path, metadata)
    return root / book_rel_m4b(metadata.author, metadata.title)


def rsync_to_library(config: PublishConfig, m4b_path: Path, metadata: BookMetadata) -> str:
    if not config.rsync_target:
        raise ValueError("JELLYFIN_RSYNC_TARGET is required for rsync mode")
    if shutil.which("rsync") is None:
        raise RuntimeError("rsync is not installed on this host")

    rel_dir = book_rel_dir(metadata.author, metadata.title).as_posix()
    target = f"{config.rsync_target.rstrip('/')}/{rel_dir}/"
    with tempfile.TemporaryDirectory(prefix="jellyfin-publish-") as tmp:
        local_dir = stage_book_tree(Path(tmp), m4b_path, metadata)
        cmd = ["rsync", "-a", "--partial", f"{local_dir}/", target]
        logger.info("Publishing via rsync: %s", target)
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=_RSYNC_TIMEOUT_S,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"rsync failed ({completed.returncode}): {detail}")
    return f"{remote_root_from_rsync_target(config.rsync_target).rstrip('/')}/{rel_dir}"


def notify_jellyfin(config: PublishConfig, item_path: str) -> None:
    if not config.api_key:
        raise ValueError("JELLYFIN_API_KEY is not set")
    if not config.url:
        raise ValueError("JELLYFIN_URL is not set")

    url = config.url.rstrip("/") + "/Library/Media/Updated"
    payload = json.dumps(
        {"Updates": [{"Path": item_path, "UpdateType": "Created"}]}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"MediaBrowser Token={config.api_key}",
            "X-Emby-Token": config.api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_DEFAULT_TIMEOUT_S) as response:
            if response.status not in {200, 204}:
                raise RuntimeError(f"Jellyfin scan returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"Jellyfin scan failed HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Jellyfin is unreachable at {config.url}: {exc.reason}") from exc


def publish_audiobook(config: PublishConfig, m4b_path: Path, metadata: BookMetadata) -> PublishResult:
    """Transfer one finished M4B and ask Jellyfin to pick it up."""
    if not m4b_path.exists():
        raise FileNotFoundError(f"Audiobook not found: {m4b_path}")

    mode = resolved_mode(config)
    if mode == "rsync":
        dest = rsync_to_library(config, m4b_path, metadata)
        dest_file = f"{dest.rstrip('/')}/{library_name(metadata.title, 'Unknown Title')}.m4b"
    elif mode == "copy":
        dest_file = str(copy_to_library(config, m4b_path, metadata))
    else:
        raise ValueError(f"Unknown publish mode: {mode}")

    container_root = resolved_container_root(config)
    notified = False
    if config.api_key and container_root:
        item_path = jellyfin_item_path(container_root, metadata.author, metadata.title)
        notify_jellyfin(config, item_path)
        notified = True
        logger.info("Jellyfin scan requested for %s", item_path)
    elif not config.api_key:
        logger.warning("Published %s but skipped Jellyfin scan — set JELLYFIN_API_KEY", dest_file)
    else:
        logger.warning(
            "Published %s but skipped Jellyfin scan — set JELLYFIN_CONTAINER_PATH "
            "to the library root as the Jellyfin container sees it",
            dest_file,
        )

    return PublishResult(dest_path=dest_file, notified=notified, mode=mode)


def maybe_publish_book(
    config: AppConfig,
    metadata: BookMetadata,
    m4b_path: Path,
    *,
    tracker: RunTracker,
    record: BookRecord,
) -> None:
    """Best-effort Jellyfin publish. Never fails the book after a successful M4B."""
    if not config.publish.enabled:
        return
    try:
        with tracker.stage(record, "publish"):
            result = publish_audiobook(config.publish, m4b_path, metadata)
        record.publish_path = result.dest_path
        logger.info(
            "Published '%s' via %s -> %s (jellyfin scan: %s)",
            metadata.title,
            result.mode,
            result.dest_path,
            "yes" if result.notified else "no",
        )
    except Exception as exc:
        record.publish_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Publish failed for '%s': %s", metadata.title, exc)
        logger.debug("Publish failure traceback", exc_info=True)
