"""Chapter encoding and M4B assembly: AAC directly from chunk WAVs, chapter markers, tags.

Chapter encoding and M4B assembly; durations computed from WAV sample counts.
"""

import logging
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from text2audiobook.logging_setup import ProgressContext
from shared.ffmpeg_utils import concat_audio_files, run_ffmpeg

logger = logging.getLogger(__name__)
SAMPLE_RATE = 24_000


def wav_duration_ms(path: Path) -> int:
    info = sf.info(str(path))
    return round(info.frames / info.samplerate * 1000)


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


def _loudnorm_filter() -> str:
    return "loudnorm=I=-16:TP=-1.5:LRA=11"


def _audio_filter_args(loudnorm: bool) -> list[str]:
    if not loudnorm:
        return []
    return ["-af", _loudnorm_filter()]


def make_silence_wav(duration_ms: int, path: Path, *, sample_rate: int = SAMPLE_RATE) -> Path:
    """Write a mono silence WAV of the given duration."""
    frames = max(0, round(duration_ms * sample_rate / 1000))
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros(frames, dtype=np.float32), sample_rate)
    return path


def encode_chapter_mp3(
    wav_paths: list[Path],
    mp3_path: Path,
    *,
    bitrate: str = "128k",
    loudnorm: bool = False,
    progress: ProgressContext | None = None,
    chapter_title: str | None = None,
) -> Path:
    """Concatenate one chapter's chunk WAVs into an MP3 side artifact."""
    concat_audio_files(
        wav_paths,
        mp3_path,
        audio_codec="libmp3lame",
        bitrate=bitrate,
        extra_args=_audio_filter_args(loudnorm),
    )
    if progress is not None:
        logger.info("%s", progress.format("encode mp3", chapter_title=chapter_title))
    else:
        logger.info("Chapter MP3: %s (%d chunk(s))", mp3_path, len(wav_paths))
    return mp3_path


def _flatten_chapter_wavs(
    chapter_wavs: list[tuple[str, list[Path]]],
    *,
    chapter_silence_ms: int,
    temp_dir: Path,
) -> tuple[list[Path], list[tuple[str, int]]]:
    """Interleave chapter WAVs with optional silence gaps for M4B concat."""
    all_wavs: list[Path] = []
    chapter_timings: list[tuple[str, int]] = []
    silence_path: Path | None = None
    if chapter_silence_ms > 0:
        sample_rate = SAMPLE_RATE
        for _, paths in chapter_wavs:
            if paths:
                sample_rate = int(sf.info(str(paths[0])).samplerate)
                break
        silence_path = temp_dir / "chapter_gap.wav"
        make_silence_wav(chapter_silence_ms, silence_path, sample_rate=sample_rate)

    for index, (chapter_title, paths) in enumerate(chapter_wavs):
        if not paths:
            continue
        duration_ms = sum(wav_duration_ms(path) for path in paths)
        all_wavs.extend(paths)
        if silence_path is not None and index < len(chapter_wavs) - 1:
            all_wavs.append(silence_path)
            duration_ms += chapter_silence_ms
        chapter_timings.append((chapter_title, duration_ms))

    return all_wavs, chapter_timings


def build_m4b(
    m4b_path: Path,
    chapter_wavs: list[tuple[str, list[Path]]],
    *,
    title: str,
    author: str,
    language: str,
    cover_bytes: bytes | None,
    bitrate: str = "64k",
    chapter_silence_ms: int = 0,
    loudnorm: bool = False,
) -> Path:
    """Encode the M4B directly from chapter WAV lists (single AAC encode),
    then embed chapter markers (durations from WAV sample counts) and tags."""
    with tempfile.TemporaryDirectory() as tmp:
        all_wavs, chapter_timings = _flatten_chapter_wavs(
            chapter_wavs,
            chapter_silence_ms=chapter_silence_ms,
            temp_dir=Path(tmp),
        )
        if not all_wavs:
            raise RuntimeError("No chapter WAV files to combine")

        extra_args = ["-movflags", "+faststart", *_audio_filter_args(loudnorm)]
        concat_audio_files(
            all_wavs,
            m4b_path,
            audio_codec="aac",
            bitrate=bitrate,
            extra_args=extra_args,
        )
    embed_m4b_chapters(m4b_path, chapter_timings)
    tag_m4b(m4b_path, title=title, author=author, language=language, cover_bytes=cover_bytes)

    logger.info("Audiobook ready: %s", m4b_path)
    logger.info("  title:    %s", title)
    logger.info("  author:   %s", author)
    logger.info("  language: %s", language)
    logger.info("  cover:    %s", "yes" if cover_bytes else "no")
    logger.info("  chapters: %d (with markers)", len(chapter_wavs))
    return m4b_path
