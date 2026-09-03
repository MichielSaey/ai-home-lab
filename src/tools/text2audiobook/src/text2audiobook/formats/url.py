"""URL (.url) and local HTML source readers."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from text2audiobook.formats.html_extract import (
    parse_html_document,
    title_from_filename,
)
from text2audiobook.io import BookMetadata, Chapter

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_DEFAULT_TIMEOUT = 60.0
_USER_AGENT = "text2audiobook/0.1 (+https://github.com/MichielSaey/ai-home-lab)"


def parse_url_file(path: Path) -> tuple[str, str | None]:
    """Return (url, optional_title) from a .url file.

    Line 1: http(s) URL (required).
    Line 2: optional title override.
    """
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        raise ValueError(f"Empty .url file: {path}")
    url = lines[0]
    if not _URL_RE.match(url):
        raise ValueError(f"First non-empty line must be an http(s) URL in {path}: {url!r}")
    title = lines[1] if len(lines) > 1 else None
    return url, title


def _cache_path(staging_root: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    cache_dir = Path(staging_root) / "_url_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{digest}.html"


def fetch_url(url: str, *, cache_path: Path, force: bool = False) -> bytes:
    if cache_path.exists() and not force:
        logger.info("Using cached HTML for %s (%s)", url, cache_path)
        return cache_path.read_bytes()

    logger.info("Fetching %s", url)
    with httpx.Client(
        follow_redirects=True,
        timeout=_DEFAULT_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        content = response.content

    cache_path.write_bytes(content)
    return content


def _fallback_title_for_url(url: str) -> str:
    host = urlparse(url).hostname or "web"
    return host.replace("www.", "")


def read_url(
    url: str,
    *,
    staging_root: Path,
    output_root: Path,
    title_override: str | None = None,
    fallback_title: str | None = None,
    force_fetch: bool = False,
) -> tuple[BookMetadata, list[Chapter]]:
    cache_path = _cache_path(staging_root, url)
    html = fetch_url(url, cache_path=cache_path, force=force_fetch)
    fallback = fallback_title or _fallback_title_for_url(url)
    return parse_html_document(
        html,
        staging_root=staging_root,
        output_root=output_root,
        fallback_title=fallback,
        title_override=title_override,
    )


def write_url_source(directory: Path, url: str, *, stem: str | None = None) -> Path:
    """Write a ``.url`` file for CLI ``--url`` and return its path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if stem is None:
        host = urlparse(url).hostname or "source"
        stem = host.replace("www.", "").replace(".", "_")
    path = directory / f"{stem}.url"
    suffix = 2
    while path.exists():
        path = directory / f"{stem}_{suffix}.url"
        suffix += 1
    path.write_text(url.strip() + "\n", encoding="utf-8")
    return path


class HtmlReader:
    @property
    def suffixes(self) -> frozenset[str]:
        return frozenset({".html", ".htm"})

    def read(
        self, path: Path, *, staging_root: Path, output_root: Path, force_fetch: bool = False
    ) -> tuple[BookMetadata, list[Chapter]]:
        html = path.read_bytes()
        del force_fetch
        return parse_html_document(
            html,
            staging_root=staging_root,
            output_root=output_root,
            fallback_title=title_from_filename(path),
        )


class UrlReader:
    @property
    def suffixes(self) -> frozenset[str]:
        return frozenset({".url"})

    def read(
        self, path: Path, *, staging_root: Path, output_root: Path, force_fetch: bool = False
    ) -> tuple[BookMetadata, list[Chapter]]:
        url, title_override = parse_url_file(path)
        return read_url(
            url,
            staging_root=staging_root,
            output_root=output_root,
            title_override=title_override,
            fallback_title=title_from_filename(path),
            force_fetch=force_fetch,
        )
