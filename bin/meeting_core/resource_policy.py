"""统一内存资源准入与 llama-router 模型驻留策略。

本模块只读取系统可用内存与模型运行状态，不读取会议正文。默认策略：

* 健康状态允许两个文本模型常驻；
* ASR、说话人分离和 VL 等重阶段前收缩到一个文本模型；
* 可用内存低于安全线时，优先卸载空闲模型并等待；
* 低于紧急线时允许卸载仍在处理的模型，以避免整机失去响应。

llama-router 端点只允许 loopback，阈值和等待时间均可通过环境变量覆盖。
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


GIB = 1024 ** 3
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _env_gib(name: str, default: float) -> int:
    return int(float(os.environ.get(name, str(default))) * GIB)


@dataclass(frozen=True)
class ResourcePolicy:
    reserve_bytes: int = _env_gib("MEETING_MEMORY_RESERVE_GIB", 32)
    stop_bytes: int = _env_gib("MEETING_MEMORY_STOP_GIB", 24)
    emergency_bytes: int = _env_gib("MEETING_MEMORY_EMERGENCY_GIB", 8)
    poll_seconds: float = float(os.environ.get("MEETING_RESOURCE_POLL_SECONDS", "2"))
    wait_seconds: float = float(os.environ.get("MEETING_RESOURCE_WAIT_SECONDS", "900"))
    healthy_text_models: int = max(1, int(os.environ.get(
        "MEETING_HEALTHY_TEXT_MODELS", "2")))

    def __post_init__(self):
        if not 0 < self.emergency_bytes < self.stop_bytes <= self.reserve_bytes:
            raise ValueError("内存阈值必须满足 0 < emergency < stop <= reserve")


class ResourceUnavailableError(RuntimeError):
    """等待资源超时；由作业恢复层归类为资源不足。"""


def mem_available(path: Path = Path("/proc/meminfo")) -> int:
    """返回 MemAvailable 字节数；无法读取时返回一个安全的大值以保持可移植。"""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 1 << 60


def _router_root() -> str:
    api = os.environ.get("MEETING_LLM_API", "http://127.0.0.1:11435/v1").rstrip("/")
    parsed = urllib.parse.urlparse(api)
    if parsed.hostname not in LOOPBACK_HOSTS:
        raise ResourceUnavailableError("资源调度器只允许连接本机模型路由")
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urllib.parse.urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")


def _json_request(path: str, *, payload: dict | None = None,
                  timeout: float = 5.0) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{_router_root()}{path}", data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def router_models() -> list[str]:
    """列出当前已加载模型；路由不可用时返回空列表，不阻断非文本阶段。"""
    try:
        result = _json_request("/models")
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return []
    rows = result.get("data", result.get("models", [])) if isinstance(result, dict) else result
    models = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, str):
            models.append(row)
            continue
        if not isinstance(row, dict):
            continue
        raw_status = row.get("status") or row.get("state") or "loaded"
        if isinstance(raw_status, dict):
            raw_status = raw_status.get("value") or raw_status.get("status") or "loaded"
        status = str(raw_status).lower()
        if status in {"unloaded", "not_loaded"}:
            continue
        model = row.get("id") or row.get("model") or row.get("name")
        if model:
            models.append(str(model))
    return list(dict.fromkeys(models))


def model_busy(model: str) -> bool:
    query = urllib.parse.urlencode({"model": model, "autoload": "false"})
    try:
        result = _json_request(f"/slots?{query}")
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        # 无法证明空闲时不主动卸载，避免破坏在途请求。
        return True
    rows = result.get("slots", []) if isinstance(result, dict) else result
    if not isinstance(rows, list):
        return True
    return any(bool(row.get("is_processing")) for row in rows if isinstance(row, dict))


def unload_model(model: str) -> bool:
    try:
        _json_request("/models/unload", payload={"model": model}, timeout=20)
        return True
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        return False


def _preferred_models() -> list[str]:
    return list(dict.fromkeys(filter(None, (
        os.environ.get("MEETING_MINUTES_MODEL", "qwen3.8-27b-minutes").strip(),
        os.environ.get("MEETING_DRAFT_MODEL",
                       os.environ.get("MEETING_LLM_MODEL", "qwen3.6-35b-a3b-operator")).strip(),
    ))))


def trim_text_models(max_loaded: int, *, keep: list[str] | None = None,
                     emergency: bool = False) -> list[str]:
    """把已加载模型收缩到上限；常规模型忙时不卸载。返回已请求卸载的模型名。"""
    loaded = router_models()
    if len(loaded) <= max(0, max_loaded):
        return []
    preferred = list(dict.fromkeys((keep or []) + _preferred_models()))
    priority = {name: index for index, name in enumerate(preferred)}
    victims = sorted(loaded, key=lambda name: priority.get(name, 10_000), reverse=True)
    removed = []
    for model in victims:
        if len(loaded) - len(removed) <= max(0, max_loaded):
            break
        if not emergency and model_busy(model):
            continue
        if unload_model(model):
            removed.append(model)
    return removed


def _target_count(workload: str, policy: ResourcePolicy) -> int:
    if workload in {"exclusive", "120b"}:
        return 0
    if workload in {"audio", "asr", "diarization", "visual", "vl", "weknora_enrichment"}:
        return 1
    return policy.healthy_text_models


def prepare_stage(workload: str, *, keep: list[str] | None = None,
                  policy: ResourcePolicy | None = None) -> dict:
    """重阶段准入：收缩文本模型，并在安全内存恢复前有限等待。"""
    policy = policy or ResourcePolicy()
    target = _target_count(str(workload).lower(), policy)
    if os.environ.get("MEETING_RESOURCE_GUARD", "1") == "0":
        return {"available_bytes": mem_available(), "unloaded": [],
                "target_text_models": target, "disabled": True}
    removed = trim_text_models(target, keep=keep)
    started = time.monotonic()
    last_notice = 0.0
    while mem_available() < policy.stop_bytes:
        available = mem_available()
        emergency = available < policy.emergency_bytes
        removed += trim_text_models(0 if emergency else target, keep=keep,
                                    emergency=emergency)
        now = time.monotonic()
        if now - last_notice >= 15 or last_notice == 0:
            print(f"[meta] 等待计算资源 | 可用内存 {available / GIB:.1f} GiB"
                  f" | 目标驻留文本模型 {0 if emergency else target}", flush=True)
            last_notice = now
        if now - started >= policy.wait_seconds:
            raise ResourceUnavailableError(
                "可用内存长期低于安全线；已保留处理检查点，可释放其他模型后重试")
        time.sleep(policy.poll_seconds)
    return {"available_bytes": mem_available(), "unloaded": list(dict.fromkeys(removed)),
            "target_text_models": target}


def admit_text_model(model: str, *, policy: ResourcePolicy | None = None) -> dict:
    """文本请求发出前的准入；健康时保留双模型，低内存时只保留本次目标。"""
    policy = policy or ResourcePolicy()
    available = mem_available()
    target = policy.healthy_text_models if available >= policy.reserve_bytes else 1
    return prepare_stage("text" if target > 1 else "audio", keep=[model], policy=policy)


def guard_once(*, policy: ResourcePolicy | None = None) -> dict:
    """守护进程单次采样；只在越线时处理，不主动加载模型。"""
    policy = policy or ResourcePolicy()
    available = mem_available()
    removed: list[str] = []
    state = "healthy"
    if available < policy.emergency_bytes:
        state = "emergency"
        removed = trim_text_models(0, emergency=True)
    elif available < policy.stop_bytes:
        state = "constrained"
        removed = trim_text_models(1)
    elif available < policy.reserve_bytes:
        state = "guarded"
    return {"state": state, "available_bytes": available, "unloaded": removed,
            "loaded_models": router_models()}


def watch(*, policy: ResourcePolicy | None = None) -> None:
    policy = policy or ResourcePolicy()
    last = None
    while True:
        status = guard_once(policy=policy)
        signature = (status["state"], tuple(status["loaded_models"]))
        if signature != last or status["unloaded"]:
            print(json.dumps(status, ensure_ascii=False), flush=True)
            last = signature
        time.sleep(policy.poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="会议与知识库统一内存资源护栏")
    parser.add_argument("command", choices=("status", "prepare", "watch"))
    parser.add_argument("--workload", default="audio")
    parser.add_argument("--keep", action="append", default=[])
    args = parser.parse_args()
    if args.command == "watch":
        watch()
        return 0
    result = guard_once() if args.command == "status" else prepare_stage(
        args.workload, keep=args.keep)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
