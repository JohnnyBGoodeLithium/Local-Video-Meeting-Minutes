#!/usr/bin/env python3
"""用本地视觉模型分析会议现场资料，并按需快速同步正式纪要。

模型只读取会议目录内受保护的阅读副本。stdout 仅输出结构化进度和脱敏元数据，
不输出图片内容、逐字稿、路径或模型正文。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

from meeting_core import photos
from meeting_core.progress_events import failure, output_ready, phase_done
from meeting_core.progress_events import progress as progress_event
from meeting_core.resource_policy import prepare_stage
from meeting_structure import clean_model_text
from minutes_by_page import (VL_MAXTOK, chat_with_image, ensure_vl_server,
                             stop_local_model)


PHOTO_PROMPT = """这是线下会议补充拍摄的一张现场资料，可能是白板、纸面笔记、会议室展示或实物。
请详细解读画面，并严格使用以下 Markdown 结构：

## 标题
照抄画面标题；没有明确标题时用一句话概括，不要使用文件名。
## 资料类型
只写一个值：白板 / 纸面笔记 / 会议室展示 / 实物 / 其他
## 可见内容
逐条记录画面中真实可见的文字、数字、箭头、分组、表格、草图和空间关系；看不清的明确写“无法辨认”。
## 结构与关系
说明各区域、连线、顺序或因果关系；只有画面没有表达关系时写“未显示明确关系”。
## 可用于补充的上下文
用一两句话说明这张资料能补充什么背景，不要声称会议已经批准、决定或承诺了任何事项。

只根据画面中真实存在的内容回答，不根据常识补全，不输出思考过程或前后解释。"""


def _model_id(api: str) -> str:
    with urlopen(f"{api}/models", timeout=10) as response:
        models = json.loads(response.read()).get("data") or []
    if not models:
        raise RuntimeError("visual_model_missing")
    return str(models[0].get("id") or "local-vision")


def analyze(mdir: Path, photo_ids: list[str], api: str) -> tuple[int, int]:
    document = photos.load(mdir)
    by_id = {str(item.get("id") or ""): item for item in document.get("photos", [])}
    targets = [by_id[value] for value in photo_ids if value in by_id]
    if len(targets) != len(photo_ids):
        raise photos.PhotoError("现场资料不存在")
    model = _model_id(api)
    photos.set_analysis_state(mdir, photo_ids, "analyzing")
    completed = failed = 0
    progress_event("visual_understanding", done=0, total=len(targets), unit="items")
    for item in targets:
        photo_id = str(item["id"])
        image = (mdir / str(item.get("image_path") or "")).resolve()
        review_root = (mdir / "photos" / "review").resolve()
        try:
            if not image.is_file() or not image.is_relative_to(review_root):
                raise photos.PhotoError("现场资料文件路径不安全")
            raw, _usage = chat_with_image(api, model, image, VL_MAXTOK, PHOTO_PROMPT)
            description = clean_model_text(raw)
            if not description:
                raise ValueError("empty_visual_content")
            photos.set_analysis_state(mdir, [photo_id], "ready", results={photo_id: {
                "description": description,
                "model": model,
                "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }})
            completed += 1
        except Exception as exc:
            photos.set_analysis_state(mdir, [photo_id], "failed", results={photo_id: {
                "error_code": type(exc).__name__,
            }})
            failed += 1
        progress_event("visual_understanding", done=completed + failed,
                       total=len(targets), unit="items")
    if completed:
        output_ready("visuals", state="ready" if not failed else "partial")
    phase_done("visual_understanding", done=completed + failed,
               total=len(targets), unit="items")
    print(f"[meta] 现场资料视觉分析完成 {completed}/{len(targets)} 项 | 失败 {failed}",
          flush=True)
    return completed, failed


def _visual_cache_complete(mdir: Path) -> bool:
    try:
        timeline = json.loads((mdir / "slides.json").read_text(encoding="utf-8"))
        cache = json.loads((mdir / "page_desc.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    required = {int(item["page"]) for item in timeline
                if item.get("kind", "slide") == "slide" and item.get("page") is not None}
    available = {int(key) for key, value in (cache.get("desc") or {}).items()
                 if str(key).isdigit() and str(value or "").strip()}
    return bool(required) and required <= available


def _sync_command(mdir: Path) -> list[str] | None:
    python = sys.executable
    transcript = mdir / "transcript.spk.json"
    if not transcript.is_file():
        return None
    if (mdir / "slides.json").is_file():
        if not _visual_cache_complete(mdir):
            return None
        return [python, str(Path(__file__).with_name("minutes_by_page.py")), str(mdir),
                "--publish", "--reuse-vl-cache-only", "--skip-topic-map"]
    text = mdir / "transcript.txt"
    if not text.is_file():
        return None
    return [python, str(Path(__file__).with_name("summarize.py")), str(text),
            "--spk", str(transcript), "--max-tokens", "8192", "--skip-topic-map"]


def sync_minutes(mdir: Path) -> bool:
    command = _sync_command(mdir)
    if command is None:
        print("[meta] 现场资料分析已保存；当前会议尚不具备安全的纪要快速同步条件",
              flush=True)
        phase_done("final_minutes")
        return True
    progress_event("final_minutes")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        failure("PHOTO_MINUTES_SYNC_FAILED", "stage_processing_failed",
                "final_minutes", "retry_stage", exception_type="ChildProcessError")
        return False
    phase_done("final_minutes")
    output_ready("final_minutes")
    print("[meta] 正式纪要已使用现场资料解读快速同步", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="分析会议现场资料并更新正式纪要")
    parser.add_argument("mdir", type=Path)
    parser.add_argument("--photo-ids", required=True, help="逗号分隔的 F 编号")
    parser.add_argument("--sync-minutes", action="store_true")
    args = parser.parse_args()
    mdir = args.mdir.resolve()
    ids = list(dict.fromkeys(value.strip() for value in args.photo_ids.split(",")
                             if value.strip()))
    if not ids or any(not value.startswith("F") or not value[1:].isdigit() for value in ids):
        print("[error] 现场资料编号无效", file=sys.stderr)
        return 1
    known = {str(item.get("id") or "") for item in photos.load(mdir).get("photos", [])}
    if any(value not in known for value in ids):
        failure("PHOTO_INPUT_INVALID", "input_invalid", "visual_understanding",
                "requires_user_action", exception_type="PhotoError")
        print("[error] 现场资料不存在或已经删除", file=sys.stderr)
        return 1
    prepare_stage("visual", progress_phase="visual_understanding")
    api, proc = ensure_vl_server()
    if not api:
        try:
            photos.set_analysis_state(mdir, ids, "failed", results={
                value: {"error_code": "VISUAL_MODEL_START_FAILED"} for value in ids})
        except photos.PhotoError:
            pass
        failure("VISUAL_MODEL_START_FAILED", "service_unavailable",
                "visual_understanding", "retry_stage")
        return 2
    try:
        completed, _failed = analyze(mdir, ids, api)
    finally:
        stop_local_model(proc)
    if not completed:
        failure("PHOTO_ANALYSIS_FAILED", "stage_processing_failed",
                "visual_understanding", "retry_stage")
        return 3
    if args.sync_minutes and not sync_minutes(mdir):
        # 图片解读已经安全落盘；纪要同步失败时保留阶段性结果并让作业明确失败。
        return 4
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        # Job logs remain useful without leaking paths or model/prompt content.
        print(f"[error] 现场资料分析内部异常 ({type(exc).__name__})",
              file=sys.stderr, flush=True)
        raise SystemExit(5)
