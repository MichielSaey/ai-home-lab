"""GPU preflight: make NVIDIA driver-side libs loadable under Nix, verify cuFFT."""

import ctypes
import logging
from pathlib import Path

from shared.cuda_bootstrap import ensure_torch_compat, ensure_triton_compat

log = logging.getLogger(__name__)

_HOST_LIB_DIRS = (
    Path("/lib/x86_64-linux-gnu"),
    Path("/usr/lib/x86_64-linux-gnu"),
    Path("/run/opengl-driver/lib"),  # NixOS hosts
)
# libcuda: CUDA driver API; ptxjitcompiler: dlopen'd by libcuda for PTX->SASS JIT,
# required by cuFFT (not by cuBLAS/cuDNN, which ship sm_86 SASS).
_DRIVER_LIBS = ("libcuda.so.1", "libnvidia-ptxjitcompiler.so.1")

__all__ = ["cuda_fft_available", "prepare_gpu_env", "resolve_tts_device"]


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


def cuda_fft_available() -> bool:
    """Return True if a minimal CUDA FFT works (Kokoro's vocoder uses torch.stft).

    Unlike shared.cuda_bootstrap.cuda_fft_available, this probe does not touch
    cufft_plan_cache.max_size (setting it to 0 can trigger false failures).
    """
    import torch

    if not torch.cuda.is_available():
        return False
    try:
        torch.fft.rfft(torch.randn(512, device="cuda"))
        torch.cuda.synchronize()
        return True
    except RuntimeError:
        return False


def prepare_gpu_env() -> bool:
    """Preload driver libs; return True if CUDA FFT (Kokoro vocoder) works."""
    _preload_driver_libs()
    ensure_torch_compat()
    ensure_triton_compat()
    ok = cuda_fft_available()
    if not ok:
        log.warning("CUDA FFT unavailable; Kokoro will fall back to CPU")
    return ok


def resolve_tts_device(requested: str) -> str:
    """Map the configured TTS device to a concrete torch device.

    "auto" picks cuda only when a minimal CUDA FFT works (Kokoro's vocoder
    needs torch.stft); "cuda" and "cpu" pass through unchanged.
    """
    if requested == "auto":
        return "cuda" if cuda_fft_available() else "cpu"
    return requested
