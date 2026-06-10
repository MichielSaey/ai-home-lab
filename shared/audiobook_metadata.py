"""Embed audiobook tags and chapter markers into M4B files."""

import tempfile
from pathlib import Path

from shared.ffmpeg_utils import run_ffmpeg


def mp3_duration_ms(path: Path) -> int:
    from mutagen.mp3 import MP3

    return round(MP3(path).info.length * 1000)


def build_chapters_ffmetadata(chapters: list[tuple[str, int]]) -> str:
    """Build ffmpeg ffmetadata chapter list from (title, duration_ms) pairs."""
    lines = [";FFMETADATA1"]
    start_ms = 0
    for title, duration_ms in chapters:
        end_ms = start_ms + duration_ms
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"title={title}",
            ]
        )
        start_ms = end_ms
    return "\n".join(lines) + "\n"


def embed_m4b_chapters(m4b_path: Path, chapters: list[tuple[str, int]]) -> None:
    """Add chapter markers to an existing M4B (stream copy, no re-encode)."""
    if not chapters:
        return

    ffmetadata = build_chapters_ffmetadata(chapters)
    with tempfile.NamedTemporaryFile("w", suffix=".ffmeta", delete=False) as f:
        f.write(ffmetadata)
        meta_path = Path(f.name)

    tmp_path = m4b_path.with_suffix(".tmp.m4b")
    try:
        run_ffmpeg(
            [
                "-i",
                str(m4b_path),
                "-f",
                "ffmetadata",
                "-i",
                str(meta_path),
                "-map_chapters",
                "1",
                "-c",
                "copy",
                str(tmp_path),
            ]
        )
        tmp_path.replace(m4b_path)
    finally:
        meta_path.unlink(missing_ok=True)
        if tmp_path.exists():
            tmp_path.unlink()


def _cover_format(cover_bytes: bytes) -> int:
    from mutagen.mp4 import MP4Cover

    if cover_bytes.startswith(b"\xff\xd8\xff"):
        return MP4Cover.FORMAT_JPEG
    if cover_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return MP4Cover.FORMAT_PNG
    return MP4Cover.FORMAT_JPEG


def tag_m4b(
    m4b_path: Path,
    *,
    title: str,
    author: str,
    language: str,
    cover_bytes: bytes | None = None,
) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(m4b_path)
    audio["\xa9nam"] = [title]
    audio["\xa9alb"] = [title]
    audio["\xa9ART"] = [author]
    audio["aART"] = [author]
    audio["\xa9wrt"] = [author]
    audio["\xa9lng"] = [language]
    audio["\xa9gen"] = ["Audiobook"]
    audio["stik"] = [2]  # Audiobook
    if cover_bytes:
        audio["covr"] = [
            MP4Cover(cover_bytes, imageformat=_cover_format(cover_bytes))
        ]
    audio.save()


def finish_m4b_audiobook(
    m4b_path: Path,
    *,
    title: str,
    author: str,
    language: str,
    cover_bytes: bytes | None,
    chapter_audio: list[tuple[str, Path]],
) -> None:
    """Embed chapter markers and ID3-style tags after the M4B is created."""
    chapter_timings = [(name, mp3_duration_ms(path)) for name, path in chapter_audio]
    embed_m4b_chapters(m4b_path, chapter_timings)
    tag_m4b(
        m4b_path,
        title=title,
        author=author,
        language=language,
        cover_bytes=cover_bytes,
    )
