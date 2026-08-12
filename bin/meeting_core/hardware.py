"""GPU/CPU 与本地模型路径的可移植配置。

PyTorch 在 NVIDIA CUDA 与 AMD ROCm 上都暴露 ``torch.cuda`` API；这里把厂商
差异收口为可诊断的 backend，并为旧 NVIDIA 卡提供 fp16 回退。
"""

from __future__ import annotations

import os
from pathlib import Path


def configured_path(name: str, default: Path | str) -> Path:
    """读取可展开 ``~`` 的路径环境变量，不要求路径已经存在。"""
    return Path(os.environ.get(name, str(default))).expanduser()


def accelerator_backend(torch_module) -> str:
    """返回 cpu/cuda/rocm/mps；不读取模型或会议数据。"""
    torch = torch_module
    if torch.cuda.is_available():
        if getattr(torch.version, "hip", None):
            return "rocm"
        if getattr(torch.version, "cuda", None):
            return "cuda"
        return "cuda-compatible"
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def inference_device(torch_module, *, indexed: bool = False) -> str:
    """解析 ``MEETING_DEVICE``，默认自动选择 GPU；ROCm 仍使用 cuda 设备名。"""
    configured = os.environ.get("MEETING_DEVICE", "auto").strip().lower()
    if configured and configured != "auto":
        return configured
    backend = accelerator_backend(torch_module)
    if backend in {"cuda", "rocm", "cuda-compatible"}:
        return "cuda:0" if indexed else "cuda"
    if backend == "mps":
        return "mps"
    return "cpu"


def inference_dtype(torch_module, device: str):
    """按设备安全选 dtype，可由 ``MEETING_TORCH_DTYPE`` 覆盖。"""
    torch = torch_module
    configured = os.environ.get("MEETING_TORCH_DTYPE", "auto").strip().lower()
    aliases = {
        "float32": torch.float32, "fp32": torch.float32,
        "float16": torch.float16, "fp16": torch.float16,
        "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
    }
    if configured != "auto":
        if configured not in aliases:
            raise ValueError("MEETING_TORCH_DTYPE 仅支持 auto/fp32/fp16/bf16")
        return aliases[configured]
    if str(device).startswith("cuda"):
        bf16_supported = getattr(torch.cuda, "is_bf16_supported", lambda: False)
        return torch.bfloat16 if bf16_supported() else torch.float16
    if str(device).startswith("mps"):
        return torch.float16
    return torch.float32
