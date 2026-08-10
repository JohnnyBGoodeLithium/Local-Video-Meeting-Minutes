#!/usr/bin/env python3
"""检查 meeting-minutes 的运行依赖；不读取任何会议、录音或声纹内容。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def endpoint_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="本地会议纪要环境自检（不读私有数据）")
    ap.add_argument("--profile", choices=("web", "pipeline", "all"), default="all")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results: list[dict] = []

    def add(name: str, ok: bool, required: bool, detail: str = ""):
        level = "ok" if ok else ("error" if required else "warn")
        results.append({"name": name, "status": level, "detail": detail})

    add("project_root", (ROOT / "web/server.py").is_file(), True, str(ROOT))
    add("python_venv", (ROOT / ".venv/bin/python").is_file(), True)

    if args.profile in {"web", "all"}:
        for mod in ("fastapi", "uvicorn", "aiofiles", "markdown_it", "python_multipart"):
            add(f"python:{mod}", module_exists(mod), True)
        add("binary:pdftoppm", shutil.which("pdftoppm") is not None, False,
            "仅组织架构 PDF 上传需要")

    if args.profile in {"pipeline", "all"}:
        for binary in ("ffmpeg", "ffprobe"):
            add(f"binary:{binary}", shutil.which(binary) is not None, True)
        for mod in ("numpy", "soundfile", "PIL", "torch", "qwen_asr", "pyannote.audio"):
            add(f"python:{mod}", module_exists(mod), True)
        model_paths = {
            "model:qwen3-asr": Path.home() / ".local/share/models/hf/Qwen/Qwen3-ASR-1.7B",
            "model:forced-aligner": Path.home() / ".local/share/models/hf/Qwen/Qwen3-ForcedAligner-0.6B",
            "model:pyannote": Path.home() / ".local/share/models/hf/pyannote/speaker-diarization-community-1",
            "model:miloco-vl": Path.home() / "视频/joyai-test/models/MiMo-VL-Miloco-7B_Q4_0.gguf",
        }
        for name, path in model_paths.items():
            add(name, path.exists(), name != "model:miloco-vl")

    add("service:llama-router", endpoint_ok("http://127.0.0.1:11435/v1/models"), False,
        "未运行时仅影响纪要生成与助手")

    if args.json:
        print(json.dumps({"ok": not any(r["status"] == "error" for r in results),
                          "checks": results}, ensure_ascii=False, indent=2))
    else:
        for item in results:
            detail = f" — {item['detail']}" if item["detail"] else ""
            print(f"[{item['status']}] {item['name']}{detail}")
        errors = sum(r["status"] == "error" for r in results)
        warnings = sum(r["status"] == "warn" for r in results)
        print(f"[meta] checks={len(results)} errors={errors} warnings={warnings}")
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
