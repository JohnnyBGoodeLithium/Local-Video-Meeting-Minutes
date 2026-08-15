"""会议存储盘点与可再生缓存清理。

所有候选路径都必须解析到会议目录内；这样即使 ``slides`` 或 ``.rag`` 被替换成
符号链接，盘点与清理也不会读取或删除会议目录外的文件。
"""

from __future__ import annotations

from pathlib import Path


def _owned_file(path: Path, meeting_dir: Path) -> bool:
    """仅接受真实位于会议目录内的普通非符号链接文件。"""
    try:
        return (path.is_file() and not path.is_symlink()
                and path.resolve().is_relative_to(meeting_dir.resolve()))
    except OSError:
        return False


def _owned_files(paths, meeting_dir: Path) -> list[Path]:
    return [path for path in paths if _owned_file(path, meeting_dir)]


def _file_size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            # 文件可能在盘点期间被另一个本地进程移除；下次请求会得到最新值。
            continue
    return total


def meeting_storage(meeting_dir: Path) -> dict:
    """按母版、阅读资产、可再生缓存返回逻辑大小，不暴露会议正文。"""
    meeting_dir = meeting_dir.resolve()
    all_files = _owned_files(meeting_dir.rglob("*"), meeting_dir)
    original = sorted({
        *[path for pattern in ("source_video.*", "source_audio.*")
          for path in _owned_files(meeting_dir.glob(pattern), meeting_dir)],
        *(_owned_files([meeting_dir / "source.vtt"], meeting_dir)),
    })
    # 兼容旧录音会议：没有独立母版时，audio.wav 本身必须被保护。
    if not any(path.name.startswith(("source_video.", "source_audio.")) for path in original):
        audio = meeting_dir / "audio.wav"
        if _owned_file(audio, meeting_dir):
            original.append(audio)

    canonical_media = any(path.name.startswith(("source_video.", "source_audio."))
                          for path in original)
    cache_groups: list[dict] = []
    work_audio = meeting_dir / "audio.wav"
    if (canonical_media and _owned_file(work_audio, meeting_dir)
            and _owned_file(meeting_dir / "transcript.spk.json", meeting_dir)):
        cache_groups.append({"id": "work_audio", "label": "模型 PCM 工作音轨",
                             "files": [work_audio], "regenerates_from": "原始母版"})
    slides_dir = meeting_dir / "slides"
    full_frames = (_owned_files(slides_dir.glob("full_*"), meeting_dir)
                   if slides_dir.is_dir() and not slides_dir.is_symlink() else [])
    if full_frames and _owned_file(meeting_dir / "page_desc.json", meeting_dir):
        cache_groups.append({"id": "vl_frames", "label": "VL 高分辨率工作帧",
                             "files": sorted(full_frames), "regenerates_from": "原始母版"})
    rag_dir = meeting_dir / ".rag"
    rag_files = (_owned_files(rag_dir.rglob("*"), meeting_dir)
                 if rag_dir.is_dir() and not rag_dir.is_symlink() else [])
    if rag_files:
        cache_groups.append({"id": "rag", "label": "本地检索索引",
                             "files": rag_files, "regenerates_from": "逐字稿与证据"})
    topic_work = meeting_dir / ".topic-map-work.json"
    if _owned_file(topic_work, meeting_dir):
        cache_groups.append({"id": "topic_work", "label": "会议脉络生成检查点",
                             "files": [topic_work], "regenerates_from": "逐字稿与证据"})

    original_set = set(original)
    cache_set = {path for group in cache_groups for path in group["files"]}
    reading = [path for path in all_files if path not in original_set and path not in cache_set]
    original_bytes = _file_size(original)
    reading_bytes = _file_size(reading)
    cache_bytes = _file_size(list(cache_set))
    return {
        "schema": "meeting-storage/v1",
        "logical_bytes": original_bytes + reading_bytes + cache_bytes,
        "original": {"bytes": original_bytes, "files": len(original), "protected": True},
        "reading": {"bytes": reading_bytes, "files": len(reading)},
        "cache": {
            "bytes": cache_bytes, "files": len(cache_set), "reclaimable": bool(cache_set),
            "groups": [{"id": group["id"], "label": group["label"],
                        "bytes": _file_size(group["files"]), "files": len(group["files"]),
                        "regenerates_from": group["regenerates_from"]}
                       for group in cache_groups],
        },
        "policy": {
            "original": "受保护，不会被智能清理删除",
            "reading": "默认保留，支持离线阅读与证据核对",
            "cache": "可从母版或文本证据重新生成；当前由用户触发清理",
        },
    }


def clean_meeting_cache(meeting_dir: Path) -> dict:
    """删除盘点确认过的缓存；任何目录外或符号链接目标均不触碰。"""
    meeting_dir = meeting_dir.resolve()
    before = meeting_storage(meeting_dir)
    removed_files = 0
    for group in before["cache"]["groups"]:
        if group["id"] == "work_audio":
            targets = [meeting_dir / "audio.wav"]
        elif group["id"] == "vl_frames":
            targets = _owned_files((meeting_dir / "slides").glob("full_*"), meeting_dir)
        elif group["id"] == "rag":
            rag_dir = meeting_dir / ".rag"
            targets = (_owned_files(rag_dir.rglob("*"), meeting_dir)
                       if rag_dir.is_dir() and not rag_dir.is_symlink() else [])
        elif group["id"] == "topic_work":
            targets = [meeting_dir / ".topic-map-work.json"]
        else:
            targets = []
        for target in targets:
            if _owned_file(target, meeting_dir):
                target.unlink()
                removed_files += 1
        if group["id"] == "rag":
            rag_dir = meeting_dir / ".rag"
            if rag_dir.is_dir() and not rag_dir.is_symlink():
                # 只移除已清空的真实目录；不使用递归删除，避免检查后的路径替换
                # 把新出现或越界的内容一并带走。
                directories = [path for path in rag_dir.rglob("*")
                               if path.is_dir() and not path.is_symlink()]
                for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                try:
                    rag_dir.rmdir()
                except OSError:
                    pass
    after = meeting_storage(meeting_dir)
    return {"ok": True, "removed_files": removed_files,
            "reclaimed_logical_bytes": max(0, before["logical_bytes"] - after["logical_bytes"]),
            "storage": after}
