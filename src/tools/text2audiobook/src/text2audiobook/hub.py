"""Hugging Face hub helpers: offline-friendly model paths and error classification."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_TRANSIENT_HTTP_RE = re.compile(
    r"(?:\b(?:429|500|502|503|504)\s+(?:client|server|error|too)|"
    r"too many requests|internal server error|bad gateway|"
    r"service unavailable|gateway timeout)",
    re.IGNORECASE,
)
_PERMANENT_HTTP_RE = re.compile(
    r"(?:\b(?:401|403|404)\s+(?:client|server|error)|"
    r"repository not found|gated repo|invalid username or password|"
    r"\bunauthorized\b|\bforbidden\b)",
    re.IGNORECASE,
)


def is_hub_connection_error(exc: BaseException) -> bool:
    """True when ``exc`` (or its cause/context graph) looks like a *transient* hub failure.

    Permanent client errors (404/401/403, missing repo, bad token) must not match —
    book-level retries would only burn GPU clears on an unfixable config.
    Transient HTTP outages (429/502/503/504) remain retryable.

    Walks both ``__cause__`` and ``__context__`` so a cache-miss ``__cause__`` does
    not hide a transient hub error elsewhere in the chain.
    """
    permanent_names = {
        "RepositoryNotFoundError",
        "RevisionNotFoundError",
        "EntryNotFoundError",
        "GatedRepoError",
        "LocalEntryNotFoundError",
        "BadRequestError",
    }
    transient_names = {
        "ConnectionError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutError",
        "ProxyError",
        "SSLError",
        "MaxRetryError",
        "NewConnectionError",
    }
    transient_conn_tokens = (
        "failed to establish a new connection",
        "all connection attempts failed",
        "max retries exceeded",
        "connection refused",
        "name or service not known",
        "temporary failure in name resolution",
        "network is unreachable",
        "device or resource busy",
        "nodename nor servname",
        "connection reset by peer",
        "connection aborted",
        "cannot reach hugging face",
    )

    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    found_transient = False

    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        name = type(current).__name__
        msg = str(current).lower()

        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)

        if name in permanent_names:
            continue
        if _PERMANENT_HTTP_RE.search(msg):
            # Permanent client status — do not treat this node as transient,
            # but keep walking for a sibling/context network failure.
            continue
        if name in {"HfHubHTTPError", "HTTPError"}:
            if _TRANSIENT_HTTP_RE.search(msg):
                found_transient = True
            continue
        if name in transient_names:
            found_transient = True
            continue
        if _TRANSIENT_HTTP_RE.search(msg):
            found_transient = True
            continue
        if any(token in msg for token in transient_conn_tokens):
            found_transient = True

    return found_transient


def resolve_pretrained_path(
    model_id: str,
    *,
    prefer_local: bool = True,
    offline: bool = False,
) -> str:
    """Resolve a hub id (or local path) to a filesystem path for ``from_pretrained``.

    Prefer the local HF cache so TTS/LLM reloads survive network blips. Falls back
    to a network fetch when the cache is missing/incomplete unless ``offline``.
    """
    stripped = str(model_id).strip()
    if not stripped:
        raise ValueError("model_id must be a non-empty Hugging Face id or local path")

    local = Path(stripped).expanduser()
    if local.exists():
        return str(local.resolve())

    from huggingface_hub import snapshot_download

    if prefer_local or offline:
        try:
            path = snapshot_download(repo_id=stripped, local_files_only=True)
            logger.debug("Using local HF cache for %s → %s", stripped, path)
            return path
        except Exception as exc:
            if offline:
                raise RuntimeError(
                    f"Hub offline: local cache incomplete for {stripped!r}. "
                    "Download the model once while online, or point model_id at a "
                    "local directory."
                ) from exc
            logger.info(
                "Local HF cache miss for %s (%s: %s); fetching from hub",
                stripped,
                type(exc).__name__,
                exc,
            )

    try:
        return snapshot_download(repo_id=stripped, local_files_only=False)
    except Exception as exc:
        if is_hub_connection_error(exc):
            try:
                path = snapshot_download(repo_id=stripped, local_files_only=True)
                logger.warning(
                    "Hub unreachable for %s; falling back to local cache → %s",
                    stripped,
                    path,
                )
                return path
            except Exception:
                # Chain from the hub/network error so book retries still classify
                # this as transient (cache-miss alone must not mask connectivity).
                raise RuntimeError(
                    f"Cannot reach Hugging Face for {stripped!r} and the local "
                    "cache is incomplete. Download once while online "
                    f"(or set HF_HOME to a populated cache). Last error: {exc}"
                ) from exc
        raise
