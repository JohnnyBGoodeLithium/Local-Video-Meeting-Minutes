#!/usr/bin/env python3
"""资源护栏只依据安全元数据决策，并保持双模型/重阶段/紧急态边界。"""

from __future__ import annotations

import sys
import tempfile
import os
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))

import meeting_core.resource_policy as rp  # noqa: E402

os.environ["MEETING_RESOURCE_GUARD"] = "1"


with tempfile.TemporaryDirectory(prefix="meeting-resource-") as tmp:
    meminfo = Path(tmp) / "meminfo"
    meminfo.write_text("MemTotal: 131072000 kB\nMemAvailable: 33554432 kB\n",
                       encoding="utf-8")
    assert rp.mem_available(meminfo) == 32 * rp.GIB

policy = rp.ResourcePolicy(
    reserve_bytes=32 * rp.GIB,
    stop_bytes=24 * rp.GIB,
    emergency_bytes=8 * rp.GIB,
    poll_seconds=0,
    wait_seconds=1,
    healthy_text_models=2,
)
assert rp._target_count("text", policy) == 2
assert rp._target_count("audio", policy) == 1
assert rp._target_count("vl", policy) == 1
assert rp._target_count("120b", policy) == 0

originals = {name: getattr(rp, name) for name in (
    "_json_request", "router_models", "model_busy", "unload_model", "mem_available")}
try:
    rp._json_request = lambda path: {"data": [
        {"id": "configured", "status": {"value": "unloaded"}},
        {"id": "resident", "status": {"value": "loaded"}},
        {"id": "starting", "status": {"value": "loading"}},
    ]}
    assert rp.router_models() == ["resident", "starting"]

    removed = []
    rp.router_models = lambda: ["minutes", "draft"]
    rp.model_busy = lambda model: model == "minutes"
    rp.unload_model = lambda model: removed.append(model) or True
    rp._preferred_models = lambda: ["minutes", "draft"]
    assert rp.trim_text_models(1, keep=["minutes"]) == ["draft"]
    assert removed == ["draft"]

    removed.clear()
    rp.router_models = lambda: ["minutes", "draft", "external"]
    rp.model_busy = lambda model: True
    assert rp.trim_text_models(1) == []
    assert rp.trim_text_models(0, emergency=True) == ["external", "draft", "minutes"]

    samples = iter([7 * rp.GIB, 7 * rp.GIB, 30 * rp.GIB, 30 * rp.GIB])
    rp.mem_available = lambda: next(samples)
    rp.router_models = lambda: ["minutes"]
    rp.model_busy = lambda model: True
    removed.clear()
    result = rp.prepare_stage("audio", keep=["minutes"], policy=policy)
    assert result["target_text_models"] == 1
    assert "minutes" in removed  # 紧急线下即使请求在途也以保护整机为先。

    rp.mem_available = lambda: 20 * rp.GIB
    rp.router_models = lambda: ["minutes", "draft"]
    rp.model_busy = lambda model: False
    removed.clear()
    status = rp.guard_once(policy=policy)
    assert status["state"] == "constrained" and status["unloaded"] == ["draft"]
finally:
    for name, value in originals.items():
        setattr(rp, name, value)

print("Resource policy: thresholds, residency limits, busy safety, and emergency release passed")
