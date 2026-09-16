"""画面抽取方式独立于会议/媒体的内容语义；恢复时沿用已选方式。"""
import json
import os
from pathlib import Path


def configure_extraction(mdir: Path, requested: str | None = None,
                         *, media: bool = False) -> str:
    path = mdir / "meta.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    if media:
        # 媒体语义在语音草稿阶段就需要；共享屏幕抽帧不能把它改回会议。
        meta["content_type"] = "media"
    mode = requested or meta.get("visual_extraction_mode")
    if mode is None:
        mode = "media" if meta.get("content_type") == "media" else "slides"
    if mode not in {"slides", "media"}:
        raise ValueError("invalid_visual_extraction_mode")
    meta["visual_extraction_mode"] = mode
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)
    return mode
