"""Run host ffmpeg without Nix LD_LIBRARY_PATH (avoids SIGSEGV in devenv/Jupyter)."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def ffmpeg_env() -> dict[str, str]:
    env = os.environ.copy()
    # Nix libs on LD_LIBRARY_PATH make /usr/bin/ffmpeg crash with exit code -11.
    env.pop("LD_LIBRARY_PATH", None)
    path_parts = [
        p for p in env.get("PATH", "").split(":") if "/.devenv/profile/bin" not in p
    ]
    env["PATH"] = ":".join(path_parts) if path_parts else "/usr/bin:/bin"
    return env


def ffmpeg_bin() -> str:
    ffmpeg = shutil.which("ffmpeg", path=ffmpeg_env()["PATH"])
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    return ffmpeg


def run_ffmpeg(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [ffmpeg_bin(), "-y", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, env=ffmpeg_env())
    if check and result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({result.returncode}):\n{' '.join(cmd)}\n{result.stderr}"
        )
    return result


def concat_audio_files(
    inputs: list[Path],
    output: Path,
    *,
    audio_codec: str,
    bitrate: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    if not inputs:
        raise ValueError("concat_audio_files: no input files")

    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        list_path = Path(f.name)
        for path in inputs:
            f.write(f"file '{path.resolve()}'\n")

    args = ["-f", "concat", "-safe", "0", "-i", str(list_path), "-c:a", audio_codec]
    if bitrate:
        args.extend(["-b:a", bitrate])
    if extra_args:
        args.extend(extra_args)
    args.append(str(output))

    try:
        run_ffmpeg(args)
    finally:
        list_path.unlink(missing_ok=True)
