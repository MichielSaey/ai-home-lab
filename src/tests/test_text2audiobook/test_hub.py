"""Tests for Hugging Face hub offline-friendly resolve helpers."""

from __future__ import annotations

import pytest

from text2audiobook.hub import is_hub_connection_error, resolve_pretrained_path


def test_is_hub_connection_error_detects_hf_max_retry() -> None:
    exc = ConnectionError(
        "(MaxRetryError('HTTPSConnectionPool(host='huggingface.co', port=443): "
        "Max retries exceeded'), '(Request ID: abc)')"
    )
    assert is_hub_connection_error(exc)


def test_is_hub_connection_error_detects_errno_16_busy() -> None:
    exc = OSError(
        "[Errno 16] Device or resource busy: failed to establish a new connection "
        "to huggingface.co"
    )
    assert is_hub_connection_error(exc)


def test_is_hub_connection_error_detects_httpx_connect_error() -> None:
    class ConnectError(Exception):
        pass

    assert is_hub_connection_error(ConnectError("All connection attempts failed"))


def test_is_hub_connection_error_sees_hub_error_behind_cache_miss_cause() -> None:
    """Cache-miss __cause__ must not hide a transient hub failure in the chain."""
    hub_exc = ConnectionError("failed to establish a new connection")

    class LocalEntryNotFoundError(Exception):
        pass

    wrapped = RuntimeError("Cannot reach Hugging Face; Last error: ...")
    wrapped.__cause__ = LocalEntryNotFoundError("incomplete cache")
    wrapped.__context__ = hub_exc
    assert is_hub_connection_error(wrapped)

    # Preferred chaining: raise from the hub error directly.
    chained = RuntimeError("Cannot reach Hugging Face")
    chained.__cause__ = hub_exc
    assert is_hub_connection_error(chained)


def test_is_hub_connection_error_rejects_offline_mode() -> None:
    class OfflineModeIsEnabled(Exception):
        pass

    assert not is_hub_connection_error(OfflineModeIsEnabled("Cannot reach server"))
    assert not is_hub_connection_error(RuntimeError("Offline mode is enabled."))


def test_is_hub_connection_error_rejects_bare_digit_false_positives() -> None:
    assert not is_hub_connection_error(RuntimeError("chunk had 500 words"))
    assert not is_hub_connection_error(RuntimeError("request id 429abcdef"))


def test_is_hub_connection_error_rejects_unrelated() -> None:
    assert not is_hub_connection_error(RuntimeError("CUDA out of memory"))
    assert not is_hub_connection_error(ValueError("bad config"))


def test_is_hub_connection_error_rejects_permanent_hf_client_errors() -> None:
    class RepositoryNotFoundError(Exception):
        pass

    class HfHubHTTPError(Exception):
        pass

    assert not is_hub_connection_error(RepositoryNotFoundError("Qwen/Nope"))
    assert not is_hub_connection_error(HfHubHTTPError("404 Client Error"))
    assert not is_hub_connection_error(
        Exception("401 Client Error for url: https://huggingface.co/api/models/x")
    )


def test_is_hub_connection_error_allows_transient_hf_http() -> None:
    class HfHubHTTPError(Exception):
        pass

    assert is_hub_connection_error(HfHubHTTPError("503 Server Error: Service Unavailable"))
    assert is_hub_connection_error(HfHubHTTPError("429 Too Many Requests"))
    assert is_hub_connection_error(HfHubHTTPError("500 Internal Server Error"))


def test_resolve_pretrained_path_uses_existing_directory(tmp_path) -> None:
    model_dir = tmp_path / "weights"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    assert resolve_pretrained_path(str(model_dir)) == str(model_dir.resolve())


def test_resolve_pretrained_path_prefers_local_cache(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_snapshot(*, repo_id: str, local_files_only: bool):
        calls.append(local_files_only)
        if local_files_only:
            return f"/cache/{repo_id}"
        raise AssertionError("should not hit the network when local succeeds")

    monkeypatch.setattr(
        "huggingface_hub.snapshot_download",
        fake_snapshot,
    )
    path = resolve_pretrained_path("Qwen/Demo", prefer_local=True, offline=False)
    assert path == "/cache/Qwen/Demo"
    assert calls == [True]


def test_resolve_pretrained_path_falls_back_to_network(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_snapshot(*, repo_id: str, local_files_only: bool):
        calls.append(local_files_only)
        if local_files_only:
            raise FileNotFoundError("cache miss")
        return f"/dl/{repo_id}"

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot)
    path = resolve_pretrained_path("Qwen/Demo", prefer_local=True, offline=False)
    assert path == "/dl/Qwen/Demo"
    assert calls == [True, False]


def test_resolve_pretrained_path_offline_raises_on_miss(monkeypatch) -> None:
    def fake_snapshot(*, repo_id: str, local_files_only: bool):
        assert local_files_only is True
        raise FileNotFoundError("cache miss")

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot)
    with pytest.raises(RuntimeError, match="Hub offline"):
        resolve_pretrained_path("Qwen/Demo", prefer_local=True, offline=True)


def test_resolve_pretrained_path_network_error_falls_back_to_local(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_snapshot(*, repo_id: str, local_files_only: bool):
        calls.append(local_files_only)
        if local_files_only and len(calls) == 1:
            raise FileNotFoundError("first local miss")
        if not local_files_only:
            raise ConnectionError("failed to establish a new connection huggingface.co")
        return f"/cache/{repo_id}"

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot)
    path = resolve_pretrained_path("Qwen/Demo", prefer_local=True, offline=False)
    assert path == "/cache/Qwen/Demo"
    assert calls == [True, False, True]
