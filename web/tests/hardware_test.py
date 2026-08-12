#!/usr/bin/env python3
"""硬件选择逻辑的无 GPU 回归；不读取真实会议或模型。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.hardware import accelerator_backend, inference_device, inference_dtype


class FakeCuda:
    def __init__(self, available: bool, bf16: bool = False):
        self._available = available
        self._bf16 = bf16

    def is_available(self):
        return self._available

    def is_bf16_supported(self):
        return self._bf16


def fake_torch(*, available=False, cuda=None, hip=None, bf16=False):
    return SimpleNamespace(
        cuda=FakeCuda(available, bf16),
        version=SimpleNamespace(cuda=cuda, hip=hip),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
        float32="fp32", float16="fp16", bfloat16="bf16",
    )


def main():
    nvidia = fake_torch(available=True, cuda="12.4", bf16=False)
    amd = fake_torch(available=True, hip="6.2", bf16=True)
    cpu = fake_torch()
    assert accelerator_backend(nvidia) == "cuda"
    assert accelerator_backend(amd) == "rocm"
    assert accelerator_backend(cpu) == "cpu"
    assert inference_device(nvidia, indexed=True) == "cuda:0"
    assert inference_device(amd) == "cuda"
    assert inference_dtype(nvidia, "cuda:0") == "fp16"
    assert inference_dtype(amd, "cuda") == "bf16"
    assert inference_dtype(cpu, "cpu") == "fp32"
    with patch.dict(os.environ, {"MEETING_DEVICE": "cpu", "MEETING_TORCH_DTYPE": "fp32"}):
        assert inference_device(nvidia) == "cpu"
        assert inference_dtype(nvidia, "cpu") == "fp32"
    print("hardware selection: 11 assertions OK")


if __name__ == "__main__":
    main()
