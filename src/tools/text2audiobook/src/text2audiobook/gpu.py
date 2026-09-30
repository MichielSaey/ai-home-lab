"""GPU preflight: make NVIDIA driver-side libs loadable under Nix, resolve TTS device."""

import ctypes
import logging
import os
from pathlib import Path

from shared.cuda_bootstrap import ensure_torch_compat, ensure_triton_compat

log = logging.getLogger(__name__)

_HOST_LIB_DIRS = (
    Path("/lib/x86_64-linux-gnu"),
    Path("/usr/lib/x86_64-linux-gnu"),
    Path("/run/opengl-driver/lib"),  # NixOS hosts
)
# libcuda: CUDA driver API; ptxjitcompiler: dlopen'd by libcuda for PTX->SASS JIT.
_DRIVER_LIBS = ("libcuda.so.1", "libnvidia-ptxjitcompiler.so.1")
_EXPANDABLE_SEGMENTS = "expandable_segments:True"

__all__ = ["cuda_available", "prepare_gpu_env", "resolve_tts_device"]


def _preload_driver_libs() -> list[str]:
    loaded: list[str] = []
    for name in _DRIVER_LIBS:
        for directory in _HOST_LIB_DIRS:
            path = directory / name
            if path.exists():
                ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
                loaded.append(str(path))
                break
        else:
            log.warning("GPU preflight: %s not found in host lib dirs", name)
    return loaded


def _ensure_expandable_segments() -> None:
    """Ask the CUDA caching allocator to reduce fragmentation across book loads.

    Must run before torch initializes the allocator. Existing user overrides of
    ``PYTORCH_CUDA_ALLOC_CONF`` that already mention ``expandable_segments`` are
    left alone.
    """
    conf = os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "").strip()
    if "expandable_segments" in conf:
        return
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = (
        f"{conf},{_EXPANDABLE_SEGMENTS}" if conf else _EXPANDABLE_SEGMENTS
    )
    log.debug("Set PYTORCH_CUDA_ALLOC_CONF=%s", os.environ["PYTORCH_CUDA_ALLOC_CONF"])


def cuda_available() -> bool:
    """Return True if torch can see a CUDA device."""
    import torch

    return bool(torch.cuda.is_available())


def prepare_gpu_env() -> bool:
    """Preload driver libs; return True if CUDA is available for TTS/LLM."""
    # Allocator knobs before any torch/CUDA init via cuda_available().
    _ensure_expandable_segments()
    _preload_driver_libs()
    ensure_torch_compat()
    ensure_triton_compat()
    ok = cuda_available()
    if not ok:
        log.warning("CUDA unavailable; TTS/LLM will fall back to CPU when device=auto")
    return ok


def resolve_tts_device(requested: str) -> str:
    """Map the configured TTS device to a concrete torch device.

    "auto" picks cuda when available; "cuda" and "cpu" pass through unchanged.
    """
    if requested == "auto":
        return "cuda" if cuda_available() else "cpu"
    return requested
