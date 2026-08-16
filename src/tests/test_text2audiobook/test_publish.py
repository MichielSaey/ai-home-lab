import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from epub2audiobook.config import PublishConfig
from epub2audiobook.epub_io import BookMetadata
from epub2audiobook.publish import (
    book_rel_m4b,
    copy_to_library,
    cover_filename,
    jellyfin_item_path,
    library_name,
    notify_jellyfin,
    publish_audiobook,
    remote_root_from_rsync_target,
    resolved_container_root,
    resolved_mode,
    rsync_to_library,
)


def _metadata(tmp_path: Path, *, title="The Tenant", author="Roland Topor") -> BookMetadata:
    return BookMetadata(
        title=title,
        author=author,
        language="en",
        cover_bytes=b"\xff\xd8\xff cover",
        slug="the_tenant",
        staging_dir=tmp_path / "staging",
        m4b_path=tmp_path / "out" / "the_tenant.m4b",
    )


def test_library_name_strips_path_chars() -> None:
    assert library_name('A/B:C*?"<>|', "fallback") == "ABC"
    assert library_name("  Dune   Messiah  ", "fallback") == "Dune Messiah"
    assert library_name("...", "Unknown Title") == "Unknown Title"


def test_book_layout_author_title() -> None:
    rel = book_rel_m4b("Ursula K. Le Guin", "The Left Hand of Darkness")
    assert rel.as_posix() == "Ursula K. Le Guin/The Left Hand of Darkness/The Left Hand of Darkness.m4b"


def test_jellyfin_item_path_uses_container_root() -> None:
    path = jellyfin_item_path("/data/audiobooks", "Author", "Book")
    assert path == "/data/audiobooks/Author/Book/Book.m4b"


def test_cover_filename_from_magic() -> None:
    assert cover_filename(b"\x89PNG\r\n\x1a\nrest") == "cover.png"
    assert cover_filename(b"\xff\xd8\xffrest") == "cover.jpg"


def test_remote_root_from_rsync_target() -> None:
    assert remote_root_from_rsync_target("casaos@192.168.0.10:/mnt/media/audiobooks") == (
        "/mnt/media/audiobooks"
    )
    assert remote_root_from_rsync_target("/mnt/media/audiobooks") == "/mnt/media/audiobooks"


def test_resolved_mode_prefers_rsync_when_target_set() -> None:
    cfg = PublishConfig(mode="auto", rsync_target="user@host:/media", library_root=Path("/local"))
    assert resolved_mode(cfg) == "rsync"
    assert resolved_mode(PublishConfig(mode="copy", rsync_target="user@host:/media")) == "copy"


def test_resolved_container_root_prefers_explicit_path() -> None:
    cfg = PublishConfig(
        container_path="/data/audiobooks",
        rsync_target="user@host:/mnt/media/audiobooks",
    )
    assert resolved_container_root(cfg) == "/data/audiobooks"
    assert resolved_container_root(PublishConfig(rsync_target="user@host:/mnt/media")) == "/mnt/media"


def test_copy_to_library_writes_m4b_and_cover(tmp_path: Path) -> None:
    src = tmp_path / "book.m4b"
    src.write_bytes(b"m4b-bytes")
    library = tmp_path / "library"
    metadata = _metadata(tmp_path)
    cfg = PublishConfig(library_root=library)

    dest = copy_to_library(cfg, src, metadata)

    assert dest.exists()
    assert dest.read_bytes() == b"m4b-bytes"
    assert dest == library / "Roland Topor" / "The Tenant" / "The Tenant.m4b"
    assert (library / "Roland Topor" / "The Tenant" / "cover.jpg").read_bytes().startswith(b"\xff\xd8\xff")


def test_copy_to_library_requires_root(tmp_path: Path) -> None:
    src = tmp_path / "book.m4b"
    src.write_bytes(b"x")
    with pytest.raises(ValueError, match="JELLYFIN_LIBRARY_ROOT"):
        copy_to_library(PublishConfig(), src, _metadata(tmp_path))


def test_rsync_to_library_invokes_rsync(tmp_path: Path) -> None:
    src = tmp_path / "book.m4b"
    src.write_bytes(b"m4b-bytes")
    metadata = _metadata(tmp_path)
    cfg = PublishConfig(rsync_target="casaos@192.168.0.10:/mnt/media/audiobooks")
    completed = MagicMock(returncode=0, stderr="", stdout="")

    with (
        patch("epub2audiobook.publish.shutil.which", return_value="/usr/bin/rsync"),
        patch("epub2audiobook.publish.subprocess.run", return_value=completed) as run,
    ):
        dest = rsync_to_library(cfg, src, metadata)

    assert dest == "/mnt/media/audiobooks/Roland Topor/The Tenant"
    cmd = run.call_args.args[0]
    assert cmd[0] == "rsync"
    assert cmd[1] == "-a"
    assert cmd[-1] == "casaos@192.168.0.10:/mnt/media/audiobooks/Roland Topor/The Tenant/"


def test_notify_jellyfin_posts_media_updated() -> None:
    cfg = PublishConfig(url="http://192.168.0.10:8096", api_key="secret-key")
    captured: dict[str, object] = {}

    class _Resp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.get_header("Authorization")
        captured["token"] = request.get_header("X-emby-token")
        captured["timeout"] = timeout
        return _Resp()

    with patch("epub2audiobook.publish.urllib.request.urlopen", side_effect=fake_urlopen):
        notify_jellyfin(cfg, "/data/audiobooks/Author/Book/Book.m4b")

    assert captured["url"] == "http://192.168.0.10:8096/Library/Media/Updated"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "Updates": [{"Path": "/data/audiobooks/Author/Book/Book.m4b", "UpdateType": "Created"}]
    }
    assert captured["auth"] == "MediaBrowser Token=secret-key"
    assert captured["token"] == "secret-key"
    assert captured["timeout"] == 30


def test_publish_audiobook_copy_and_notify(tmp_path: Path) -> None:
    src = tmp_path / "book.m4b"
    src.write_bytes(b"m4b-bytes")
    metadata = _metadata(tmp_path)
    cfg = PublishConfig(
        enabled=True,
        mode="copy",
        url="http://192.168.0.10:8096",
        api_key="k",
        library_root=tmp_path / "library",
        container_path="/data/audiobooks",
    )

    with patch("epub2audiobook.publish.notify_jellyfin") as notify:
        result = publish_audiobook(cfg, src, metadata)

    assert result.mode == "copy"
    assert result.notified is True
    assert result.dest_path.endswith("The Tenant.m4b")
    notify.assert_called_once_with(cfg, "/data/audiobooks/Roland Topor/The Tenant/The Tenant.m4b")


def test_publish_audiobook_skips_scan_without_api_key(tmp_path: Path) -> None:
    src = tmp_path / "book.m4b"
    src.write_bytes(b"m4b-bytes")
    cfg = PublishConfig(mode="copy", library_root=tmp_path / "library")

    with patch("epub2audiobook.publish.notify_jellyfin") as notify:
        result = publish_audiobook(cfg, src, _metadata(tmp_path))

    assert result.notified is False
    notify.assert_not_called()


def test_maybe_publish_does_not_raise(tmp_path: Path) -> None:
    from epub2audiobook.config import (
        AppConfig,
        ChunkingConfig,
        LlmConfig,
        OutputConfig,
        PathsConfig,
        PipelineConfig,
        SelectionConfig,
        TtsConfig,
    )
    from epub2audiobook.publish import maybe_publish_book
    from epub2audiobook.tracking import BookRecord, RunTracker

    cfg = AppConfig(
        paths=PathsConfig(),
        chunking=ChunkingConfig(),
        selection=SelectionConfig(),
        llm=LlmConfig(),
        tts=TtsConfig(),
        output=OutputConfig(),
        pipeline=PipelineConfig(),
        publish=PublishConfig(enabled=True, mode="copy", library_root=tmp_path / "missing-will-fail"),
    )
    record = BookRecord(epub_path="book.epub", title="The Tenant")
    tracker = RunTracker(tmp_path / "runs", {})
    src = tmp_path / "missing.m4b"

    maybe_publish_book(cfg, _metadata(tmp_path), src, tracker=tracker, record=record)

    assert record.publish_error is not None
    assert "FileNotFoundError" in record.publish_error


def test_maybe_publish_skips_when_disabled(tmp_path: Path) -> None:
    from epub2audiobook.config import (
        AppConfig,
        ChunkingConfig,
        LlmConfig,
        OutputConfig,
        PathsConfig,
        PipelineConfig,
        SelectionConfig,
        TtsConfig,
    )
    from epub2audiobook.publish import maybe_publish_book
    from epub2audiobook.tracking import BookRecord, RunTracker

    cfg = AppConfig(
        paths=PathsConfig(),
        chunking=ChunkingConfig(),
        selection=SelectionConfig(),
        llm=LlmConfig(),
        tts=TtsConfig(),
        output=OutputConfig(),
        pipeline=PipelineConfig(),
        publish=PublishConfig(enabled=False, library_root=tmp_path / "library"),
    )
    record = BookRecord(epub_path="book.epub")
    tracker = RunTracker(tmp_path / "runs", {})
    maybe_publish_book(cfg, _metadata(tmp_path), tmp_path / "missing.m4b", tracker=tracker, record=record)
    assert record.publish_error is None
    assert record.publish_path is None
