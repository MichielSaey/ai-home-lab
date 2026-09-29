"""Hugging Face hub helpers: offline-friendly model paths and error classification."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def is_hub_connection_error(exc: BaseException) -> bool:
    """True when ``exc`` (or its cause chain) looks like a *transient* hub failure.

    Permanent client errors (404/401/403, missing repo, bad token) must not match —
    book-level retries would only burn GPU clears on an unfixable config.
    Transient HTTP outages (429/502/503/504) remain retryable.
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
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutError",
        "ProxyError",
        "SSLError",
        "MaxRetryError",
        "NewConnectionError",
        "OfflineModeIsEnabled",
    }
    transient_http_tokens = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "too many requests",
        "internal server error",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    )
    permanent_http_tokens = (
        "401",
        "403",
        "404",
        "repository not found",
        "gated repo",
        "invalid username or password",
        "unauthorized",
        "forbidden",
    )
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__
        msg = str(current).lower()

        if name in permanent_names:
            return False
        if any(token in msg for token in permanent_http_tokens):
            return False
        # HfHubHTTPError / HTTPError: only retry on rate-limit / gateway outages.
        if name in {"HfHubHTTPError", "HTTPError"}:
            return any(token in msg for token in transient_http_tokens)
        if name in transient_names:
            return True
        if any(token in msg for token in transient_http_tokens):
            return True
        if any(
            token in msg
            for token in (
                "failed to establish a new connection",
                "max retries exceeded",
                "connection refused",
                "name or service not known",
                "temporary failure in name resolution",
                "network is unreachable",
                "device or resource busy",
                "nodename nor servname",
                "offline mode is enabled",
                "connection reset by peer",
                "connection aborted",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


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
            except Exception as local_exc:
                raise RuntimeError(
                    f"Cannot reach Hugging Face for {stripped!r} and the local "
                    "cache is incomplete. Download once while online "
                    f"(or set HF_HOME to a populated cache). Last error: {exc}"
                ) from local_exc
        raise
