"""Bootstrap CUDA driver and torch compat for Nix/devenv shells."""

import ctypes
import os
import shutil
from pathlib import Path


def ensure_cuda_driver() -> None:
    for libcuda in (
        Path("/lib/x86_64-linux-gnu/libcuda.so.1"),
        Path("/usr/lib/x86_64-linux-gnu/libcuda.so.1"),
        Path("/run/opengl-driver/lib/libcuda.so.1"),
    ):
        if libcuda.exists():
            ctypes.CDLL(str(libcuda), mode=ctypes.RTLD_GLOBAL)
            return


def ensure_torch_compat() -> None:
    import torch

    # transformers>=5.10 imports torch.float8_e8m0fnu at load time (torch 2.7+).
    if not hasattr(torch, "float8_e8m0fnu"):
        torch.float8_e8m0fnu = torch.float8_e4m3fn


def cuda_fft_available() -> bool:
    """Return True if a minimal CUDA FFT works (Kokoro's vocoder uses torch.stft)."""
    import torch

    if not torch.cuda.is_available():
        return False
    try:
        torch.backends.cuda.cufft_plan_cache.max_size = 0
        torch.fft.rfft(torch.randn(512, device="cuda"))
        return True
    except RuntimeError:
        return False


def ensure_triton_compat() -> None:
    if not os.environ.get("TRITON_LIBCUDA_PATH"):
        for path in (
            "/lib/x86_64-linux-gnu",
            "/usr/lib/x86_64-linux-gnu",
            "/run/opengl-driver/lib",
        ):
            if Path(path, "libcuda.so.1").exists():
                os.environ["TRITON_LIBCUDA_PATH"] = path
                break

    # bitsandbytes/triton compile CUDA helpers at import; host gcc can SIGSEGV under Nix.
    if not os.environ.get("CC"):
        for candidate in (shutil.which("gcc"), shutil.which("cc")):
            if candidate and "/nix/store/" in candidate:
                os.environ["CC"] = candidate
                break
    if not os.environ.get("CXX"):
        for candidate in (shutil.which("g++"), shutil.which("c++")):
            if candidate and "/nix/store/" in candidate:
                os.environ["CXX"] = candidate
                break
