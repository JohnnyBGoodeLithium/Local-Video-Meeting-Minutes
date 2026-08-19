"""失败作业恢复计划与可复用命令构造。

只检查资产是否存在和作业的安全元数据；不读取、返回或记录会议正文。
路由负责鉴权式参数校验与真正排队，本模块不依赖 job_store/routers。
"""

from __future__ import annotations

import os
from pathlib import Path

from deps import MEETINGS, PY, ROOT, _audio_path, _minutes_file, _video_path


LATE_UPLOAD_STAGES = {
    "生成语音草稿", "提取共享画面", "理解共享画面",
    "升级多模态纪要", "生成纪要", "构建会议脉络",
}


def meeting_dir_for_job(job: dict) -> Path | None:
    slug = str(job.get("meeting") or "")
    candidate = (MEETINGS / slug).resolve()
    if not slug or candidate.parent != MEETINGS.resolve() or not candidate.is_dir():
        return None
    return candidate


def build_minutes_command(mdir: Path, refine: str = "") -> list[str]:
    """复用现有逐字稿/VL 缓存生成纪要；不重跑 ASR 与说话人识别。"""
    if not (mdir / "transcript.spk.json").is_file():
        raise ValueError("missing_transcript")
    if (mdir / "slides.json").is_file():
        command = [str(PY), str(ROOT / "bin" / "minutes_by_page.py"),
                   str(mdir), "--publish"]
        video = _video_path(mdir)
        if video is not None:
            command += ["--video", str(video)]
        if refine:
            command += ["--refine-model", refine]
        return command
    if refine:
        raise ValueError("audio_refine_unsupported")
    if _video_path(mdir) is not None:
        # 视频尚未形成页面缓存时不能冒充纯音频会议继续；应重新导入以恢复抽帧阶段。
        raise ValueError("missing_visual_cache")
    transcript_text = mdir / "transcript.txt"
    if not transcript_text.is_file():
        raise ValueError("missing_transcript_text")
    return [str(PY), str(ROOT / "bin" / "summarize.py"), str(transcript_text),
            "--spk", str(mdir / "transcript.spk.json"), "--max-tokens", "8192"]


def build_topic_map_command(mdir: Path) -> list[str]:
    if not (mdir / "transcript.spk.json").is_file() or _minutes_file(mdir) is None:
        raise ValueError("missing_topic_sources")
    return [str(PY), str(ROOT / "bin" / "meeting_topic_map.py"), str(mdir)]


def build_retranscribe_command(mdir: Path) -> list[str]:
    if _video_path(mdir) is None and _audio_path(mdir) is None:
        raise ValueError("missing_source_media")
    return [str(PY), str(ROOT / "bin" / "retranscribe_local.py"), str(mdir)]


def _failure_category(job: dict) -> str:
    safe_log = "\n".join(str(line) for line in job.get("log", [])[-12:])
    rc = job.get("rc")
    if "服务重启，作业中断" in safe_log:
        return "interrupted"
    if rc in {-9, 137} or any(name in safe_log for name in (
            "MemoryError", "OutOfMemoryError", "CUDAError")):
        return "resource"
    if any(name in safe_log for name in (
            "TimeoutError", "URLError", "ConnectionError", "HTTPError")):
        return "transient"
    if any(name in safe_log for name in ("JSONDecodeError", "格式", "解析失败")):
        return "format"
    if "没有返回可读正文" in safe_log or "空响应" in safe_log:
        return "empty_output"
    return "pipeline"


def _retained_assets(mdir: Path | None) -> list[str]:
    if mdir is None:
        return []
    retained = []
    if _video_path(mdir) is not None or (mdir / "audio.wav").is_file() \
            or any(mdir.glob("source_audio.*")):
        retained.append("source_media")
    if any((mdir / f"source.{suffix}").is_file() for suffix in ("vtt", "docx")):
        retained.append("source_transcript")
    if (mdir / "transcript.spk.json").is_file():
        retained.append("transcript")
    if (mdir / "slides.json").is_file() or (mdir / "page_desc.json").is_file():
        retained.append("visual_cache")
    if _minutes_file(mdir) is not None:
        retained.append("minutes")
    return retained


def recovery_plan(job: dict) -> dict:
    """返回前端可展示的有限状态机，不返回日志正文或文件路径。"""
    mdir = meeting_dir_for_job(job)
    retained = _retained_assets(mdir)
    stage = str(job.get("stage") or "处理阶段")
    plan = {
        "schema": "job-recovery/v1",
        "state": "manual",
        "category": _failure_category(job),
        "mode": "manual",
        "scope": "full_import",
        "stage": stage,
        "retained": retained,
        "action": "reimport",
        "high_quality_available": False,
    }
    if job.get("status") not in {"failed", "cancelled"}:
        plan.update(state="unavailable", action="none")
        return plan
    if mdir is None:
        plan["action"] = "reimport_missing_meeting"
        return plan

    kind = str(job.get("kind") or "")
    if kind == "translation":
        artifact = str(job.get("translation_artifact") or "transcript")
        target = str(job.get("target_language") or "")
        if artifact in {"transcript", "minutes", "topic_map", "visuals"} \
                and target in {"zh-CN", "en"}:
            plan.update(state="available", mode="translation", scope=artifact,
                        action="retry_translation")
        return plan
    if kind == "topic_map":
        try:
            build_topic_map_command(mdir)
        except ValueError:
            return plan
        plan.update(state="available", mode="topic_map", scope="topic_map",
                    action="retry_stage")
        return plan
    if kind == "retranscribe":
        try:
            build_retranscribe_command(mdir)
        except ValueError:
            return plan
        plan.update(state="available", mode="retranscribe", scope="transcription",
                    action="retry_stage")
        return plan

    if kind in {"regen", "upload"}:
        if kind == "upload" and stage == "构建会议脉络":
            try:
                build_topic_map_command(mdir)
            except ValueError:
                pass
            else:
                plan.update(state="available", mode="topic_map", scope="topic_map",
                            action="retry_stage")
                return plan
        # 上传早期失败不能安全重放旧命令；只有已形成逐字稿并进入后半段才断点续跑。
        if kind == "upload" and stage not in LATE_UPLOAD_STAGES:
            return plan
        try:
            build_minutes_command(mdir)
        except ValueError:
            return plan
        refine = os.environ.get("MEETING_RECOVERY_REFINE_MODEL", "").strip()
        has_visuals = (mdir / "slides.json").is_file()
        plan.update(state="available", mode="minutes", scope="minutes",
                    action="resume_from_assets",
                    high_quality_available=bool(refine and has_visuals))
        return plan
    return plan
