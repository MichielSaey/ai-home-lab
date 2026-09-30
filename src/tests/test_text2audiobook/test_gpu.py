"""GPU preflight helpers."""

from __future__ import annotations


def test_prepare_gpu_env_sets_expandable_segments(monkeypatch) -> None:
    from text2audiobook import gpu

    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)
    monkeypatch.delenv("PYTORCH_ALLOC_CONF", raising=False)
    monkeypatch.setattr(gpu, "_preload_driver_libs", lambda: [])
    monkeypatch.setattr(gpu, "ensure_torch_compat", lambda: None)
    monkeypatch.setattr(gpu, "ensure_triton_compat", lambda: None)
    monkeypatch.setattr(gpu, "cuda_available", lambda: False)

    assert gpu.prepare_gpu_env() is False
    assert "expandable_segments:True" in gpu.os.environ["PYTORCH_CUDA_ALLOC_CONF"]


def test_prepare_gpu_env_preserves_existing_expandable_segments(monkeypatch) -> None:
    from text2audiobook import gpu

    monkeypatch.setenv(
        "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:False,max_split_size_mb:128"
    )
    monkeypatch.delenv("PYTORCH_ALLOC_CONF", raising=False)
    monkeypatch.setattr(gpu, "_preload_driver_libs", lambda: [])
    monkeypatch.setattr(gpu, "ensure_torch_compat", lambda: None)
    monkeypatch.setattr(gpu, "ensure_triton_compat", lambda: None)
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)

    assert gpu.prepare_gpu_env() is True
    assert (
        gpu.os.environ["PYTORCH_CUDA_ALLOC_CONF"]
        == "expandable_segments:False,max_split_size_mb:128"
    )


def test_prepare_gpu_env_appends_when_other_conf_present(monkeypatch) -> None:
    from text2audiobook import gpu

    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:64")
    monkeypatch.delenv("PYTORCH_ALLOC_CONF", raising=False)
    monkeypatch.setattr(gpu, "_preload_driver_libs", lambda: [])
    monkeypatch.setattr(gpu, "ensure_torch_compat", lambda: None)
    monkeypatch.setattr(gpu, "ensure_triton_compat", lambda: None)
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)

    assert gpu.prepare_gpu_env() is True
    assert (
        gpu.os.environ["PYTORCH_CUDA_ALLOC_CONF"]
        == "max_split_size_mb:64,expandable_segments:True"
    )


def test_prepare_gpu_env_appends_legacy_alloc_conf(monkeypatch) -> None:
    from text2audiobook import gpu

    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)
    monkeypatch.setenv("PYTORCH_ALLOC_CONF", "max_split_size_mb:64")
    monkeypatch.setattr(gpu, "_preload_driver_libs", lambda: [])
    monkeypatch.setattr(gpu, "ensure_torch_compat", lambda: None)
    monkeypatch.setattr(gpu, "ensure_triton_compat", lambda: None)
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)

    assert gpu.prepare_gpu_env() is True
    assert gpu.os.environ.get("PYTORCH_CUDA_ALLOC_CONF") is None
    assert (
        gpu.os.environ["PYTORCH_ALLOC_CONF"]
        == "max_split_size_mb:64,expandable_segments:True"
    )


def test_prepare_gpu_env_respects_legacy_expandable_segments(monkeypatch) -> None:
    from text2audiobook import gpu

    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF", raising=False)
    monkeypatch.setenv("PYTORCH_ALLOC_CONF", "expandable_segments:False")
    monkeypatch.setattr(gpu, "_preload_driver_libs", lambda: [])
    monkeypatch.setattr(gpu, "ensure_torch_compat", lambda: None)
    monkeypatch.setattr(gpu, "ensure_triton_compat", lambda: None)
    monkeypatch.setattr(gpu, "cuda_available", lambda: True)

    assert gpu.prepare_gpu_env() is True
    assert gpu.os.environ.get("PYTORCH_CUDA_ALLOC_CONF") is None
    assert gpu.os.environ["PYTORCH_ALLOC_CONF"] == "expandable_segments:False"
