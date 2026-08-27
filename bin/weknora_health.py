#!/usr/bin/env python3
"""只用健康端点检查 Meeting Minutes ↔ WeKnora 交接环境，不读取知识库内容。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from meeting_core.resource_policy import GIB, mem_available, router_models  # noqa: E402


def probe(url: str, timeout: float = 4) -> dict:
    if not url:
        return {"configured": False, "ok": False}
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"configured": True, "ok": 200 <= response.status < 400,
                    "status": response.status}
    except urllib.error.HTTPError as exc:
        return {"configured": True, "ok": False, "status": exc.code}
    except (OSError, urllib.error.URLError) as exc:
        return {"configured": True, "ok": False, "error": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="检查知识库交接与共享模型资源状态")
    parser.add_argument("--meeting-health", default=os.environ.get(
        "MEETING_HEALTH_URL", "http://127.0.0.1:8899/api/health"))
    parser.add_argument("--weknora-health", default=os.environ.get(
        "MEETING_KB_HEALTH_URL", "http://127.0.0.1:8080/health"))
    args = parser.parse_args()
    status = {
        "schema": "meeting-kb-health/v1",
        "meeting_minutes": probe(args.meeting_health),
        "weknora": probe(args.weknora_health),
        "resources": {
            "available_memory_gib": round(mem_available() / GIB, 1),
            "loaded_text_models": router_models(),
        },
    }
    status["ok"] = status["meeting_minutes"]["ok"] and status["weknora"]["ok"]
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
