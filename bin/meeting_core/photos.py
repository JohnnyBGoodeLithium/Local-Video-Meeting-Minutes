"""现场照片 canonical sidecar、受保护副本、分析状态与阅读投影。

照片可以补充白板、纸面笔记和线下展示，但不能独立证明会议决定。本模块只做
确定性的文件固化、EXIF 读取、时间对齐和分析结果写入；模型调用留在独立作业中。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps


SCHEMA = "meeting-photos/v1"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS = 80
MAX_FILE_BYTES = 32 * 1024 * 1024
ANALYSIS_STATES = {"not_requested", "queued", "analyzing", "ready", "failed"}
_LOCK = threading.RLock()


class PhotoError(ValueError):
    """可安全显示给用户的照片导入错误。"""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 19 and text[4] == ":" and text[7] == ":":
            return datetime.strptime(text, "%Y:%m:%d %H:%M:%S").astimezone()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()
    except (ValueError, TypeError, OSError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def empty_document() -> dict:
    return {"schema": SCHEMA, "updated_at": None, "photos": []}


def load(mdir: Path) -> dict:
    path = mdir / "meeting.photos.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return empty_document()
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return empty_document()
    photos = payload.get("photos")
    payload["photos"] = photos if isinstance(photos, list) else []
    return payload


def _safe_original_name(name: str, fallback: str) -> str:
    candidate = Path(str(name or "")).name.strip()
    if not candidate or candidate in {".", ".."}:
        return fallback
    return candidate[:180]


def _capture_time(image: Image.Image) -> tuple[datetime | None, str]:
    try:
        exif = image.getexif()
    except Exception:
        return None, "none"
    # DateTimeOriginal、DateTimeDigitized、DateTime；只使用图片内拍摄信息，
    # 不把文件 mtime 当成拍摄时间，以免下载/复制时间造成伪对齐。
    for tag in (36867, 36868, 306):
        parsed = _parse_datetime(exif.get(tag))
        if parsed:
            return parsed, "exif"
    return None, "none"


def _next_id(photos: list[dict]) -> str:
    numbers = []
    for item in photos:
        raw = str(item.get("id") or "")
        if raw.startswith("F") and raw[1:].isdigit():
            numbers.append(int(raw[1:]))
    return f"F{max(numbers, default=0) + 1:04d}"


def _alignment(
    captured: datetime | None,
    *,
    mode: str,
    duration: float,
    meeting_start: datetime | None,
    anchor_seconds: float | None,
    first_capture: datetime | None,
) -> dict:
    seconds: float | None = None
    method = "none"
    confidence = "unlocated"
    state = "unlocated"
    if mode == "capture_time" and captured and meeting_start:
        seconds = (captured - meeting_start).total_seconds()
        method, confidence, state = "exif_meeting_start", "high", "suggested"
    elif mode == "current_time" and anchor_seconds is not None:
        seconds = float(anchor_seconds)
        if captured and first_capture:
            seconds += (captured - first_capture).total_seconds()
        method, confidence, state = "manual_anchor", "medium", "confirmed"
    elif mode != "unlocated":
        raise PhotoError("照片定位方式无效")
    if seconds is not None:
        if seconds < 0 or (duration > 0 and seconds > duration):
            return {"seconds": None, "state": "unlocated", "method": "out_of_range",
                    "confidence": "unlocated"}
        seconds = round(seconds, 3)
    return {"seconds": seconds, "state": state, "method": method,
            "confidence": confidence}


def import_photos(
    mdir: Path,
    sources: Iterable[tuple[Path, str]],
    *,
    mode: str = "unlocated",
    duration: float = 0,
    meeting_start_iso: str | None = None,
    anchor_seconds: float | None = None,
) -> dict:
    """固化照片并原子更新 sidecar。

    sources 是 ``(临时文件, 原始显示文件名)``；成功后调用方可删除临时文件。
    重复内容按 sha256 去重，不创建第二个 canonical 条目。
    """
    incoming = list(sources)
    if not incoming:
        raise PhotoError("请选择至少一张照片")
    if len(incoming) > MAX_PHOTOS:
        raise PhotoError(f"一次最多导入 {MAX_PHOTOS} 张照片")
    meeting_start = _parse_datetime(meeting_start_iso)
    if mode == "capture_time" and not meeting_start:
        raise PhotoError("按拍摄时间定位时，需要填写会议开始时间")
    if mode == "current_time" and anchor_seconds is None:
        raise PhotoError("从当前播放位置排列时，缺少播放器时间")

    prepared: list[dict] = []
    for source, display_name in incoming:
        source = Path(source)
        ext = source.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise PhotoError("首版支持 JPG、PNG 和 WebP；HEIC 请先转为 JPG")
        if not source.is_file() or source.stat().st_size <= 0:
            raise PhotoError("照片文件为空或不可读取")
        if source.stat().st_size > MAX_FILE_BYTES:
            raise PhotoError("单张照片不能超过 32 MB")
        try:
            with Image.open(source) as image:
                image.verify()
            with Image.open(source) as image:
                captured, capture_source = _capture_time(image)
        except Exception as exc:
            raise PhotoError("文件不是可读取的图片") from exc
        prepared.append({
            "source": source,
            "display_name": _safe_original_name(display_name, source.name),
            "ext": ext,
            "sha256": _sha256(source),
            "captured": captured,
            "capture_source": capture_source,
        })
    captures = [item["captured"] for item in prepared if item["captured"]]
    first_capture = min(captures) if captures else None

    created: list[Path] = []
    with _LOCK:
        document = load(mdir)
        existing_hashes = {str(item.get("sha256")): item for item in document["photos"]}
        imported: list[dict] = []
        results: list[dict] = []
        try:
            for item in prepared:
                if item["sha256"] in existing_hashes:
                    existing = existing_hashes[item["sha256"]]
                    imported.append(existing)
                    results.append({"photo": existing, "duplicate": True})
                    continue
                photo_id = _next_id(document["photos"])
                original_ext = ".jpg" if item["ext"] == ".jpeg" else item["ext"]
                original_rel = Path("photos") / "original" / f"{photo_id}{original_ext}"
                review_rel = Path("photos") / "review" / f"{photo_id}.jpg"
                original_path = mdir / original_rel
                review_path = mdir / review_rel
                original_path.parent.mkdir(parents=True, exist_ok=True)
                review_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item["source"], original_path)
                created.append(original_path)
                with Image.open(item["source"]) as image:
                    review = ImageOps.exif_transpose(image).convert("RGB")
                    review.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                    temp_review = review_path.with_name(f".{review_path.name}.{os.getpid()}.tmp")
                    review.save(temp_review, format="JPEG", quality=92, optimize=True)
                    os.replace(temp_review, review_path)
                created.append(review_path)
                captured = item["captured"]
                alignment = _alignment(
                    captured, mode=mode, duration=max(0.0, float(duration or 0)),
                    meeting_start=meeting_start, anchor_seconds=anchor_seconds,
                    first_capture=first_capture)
                record = {
                    "id": photo_id,
                    "original_name": item["display_name"],
                    "original_path": original_rel.as_posix(),
                    "image_path": review_rel.as_posix(),
                    "sha256": item["sha256"],
                    "captured_at": captured.isoformat(timespec="seconds") if captured else None,
                    "capture_time_source": item["capture_source"],
                    "alignment": alignment,
                    "title": item["display_name"],
                    "description": "",
                    "analysis_state": "not_requested",
                    "imported_at": _now_iso(),
                }
                document["photos"].append(record)
                existing_hashes[item["sha256"]] = record
                imported.append(record)
                results.append({"photo": record, "duplicate": False})
            document["updated_at"] = _now_iso()
            _atomic_json(mdir / "meeting.photos.json", document)
        except Exception:
            for path in reversed(created):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
    return {
        "schema": SCHEMA,
        "imported": imported,
        "results": results,
        "created_ids": [item["photo"]["id"] for item in results if not item["duplicate"]],
        "duplicate_ids": [item["photo"]["id"] for item in results if item["duplicate"]],
        "photos": document["photos"],
    }


def set_alignment(mdir: Path, photo_id: str, seconds: float | None,
                  *, duration: float = 0) -> dict:
    with _LOCK:
        document = load(mdir)
        record = next((item for item in document["photos"]
                       if item.get("id") == photo_id), None)
        if record is None:
            raise PhotoError("现场照片不存在")
        if seconds is None:
            record["alignment"] = {"seconds": None, "state": "unlocated",
                                   "method": "manual_unlocated",
                                   "confidence": "unlocated"}
        else:
            value = float(seconds)
            if value < 0 or (duration > 0 and value > duration):
                raise PhotoError("照片时间超出会议范围")
            record["alignment"] = {"seconds": round(value, 3), "state": "confirmed",
                                   "method": "manual_position",
                                   "confidence": "medium"}
        document["updated_at"] = _now_iso()
        _atomic_json(mdir / "meeting.photos.json", document)
        return record


def set_title(mdir: Path, photo_id: str, title: str) -> dict:
    """只更新阅读标题；原文件名与内容 hash 保持不变。"""
    clean = " ".join(str(title or "").split()).strip()
    if not 1 <= len(clean) <= 120:
        raise PhotoError("现场资料标题需为 1–120 个字符")
    with _LOCK:
        document = load(mdir)
        record = next((item for item in document["photos"]
                       if item.get("id") == photo_id), None)
        if record is None:
            raise PhotoError("现场资料不存在")
        record["title"] = clean
        document["updated_at"] = _now_iso()
        _atomic_json(mdir / "meeting.photos.json", document)
        return record


def set_analysis_state(
    mdir: Path,
    photo_ids: Iterable[str],
    state: str,
    *,
    results: dict[str, dict] | None = None,
) -> list[dict]:
    """原子更新一批现场资料的视觉分析状态和受控结果。

    ``results`` 只接受由本地分析作业产生的 description/model/analyzed_at/error_code；
    原图、hash、标题和时间定位不在这里修改。
    """
    if state not in ANALYSIS_STATES:
        raise PhotoError("现场资料分析状态无效")
    wanted = list(dict.fromkeys(str(value or "").strip() for value in photo_ids))
    wanted = [value for value in wanted if value]
    if not wanted:
        raise PhotoError("请选择至少一项现场资料")
    result_map = results if isinstance(results, dict) else {}
    with _LOCK:
        document = load(mdir)
        by_id = {str(item.get("id") or ""): item for item in document["photos"]}
        missing = [value for value in wanted if value not in by_id]
        if missing:
            raise PhotoError("现场资料不存在")
        updated = []
        for photo_id in wanted:
            record = by_id[photo_id]
            payload = result_map.get(photo_id) if isinstance(result_map.get(photo_id), dict) else {}
            record["analysis_state"] = state
            if state == "ready":
                description = str(payload.get("description") or "").strip()
                if not description:
                    raise PhotoError("现场资料分析没有返回可读内容")
                record["description"] = description
                record["analysis_model"] = str(payload.get("model") or "").strip() or None
                record["analyzed_at"] = str(payload.get("analyzed_at") or _now_iso())
                record.pop("analysis_error", None)
            elif state == "failed":
                record["analysis_error"] = str(payload.get("error_code") or "analysis_failed")[:64]
            elif state in {"queued", "analyzing"}:
                record.pop("analysis_error", None)
            updated.append(dict(record))
        document["updated_at"] = _now_iso()
        _atomic_json(mdir / "meeting.photos.json", document)
        return updated


def prompt_materials(mdir: Path, turns: list[dict] | None = None) -> list[dict]:
    """投影供文本纪要使用的已分析现场资料。

    时间接近只表示上下文邻近，不是事实证明；因此这里只给出 nearby_turn_ids，
    正式决定仍必须回到逐字稿证据。
    """
    rows = []
    all_turns = turns or []
    for item in load(mdir).get("photos", []):
        description = str(item.get("description") or "").strip()
        if item.get("analysis_state") != "ready" or not description:
            continue
        alignment = item.get("alignment") if isinstance(item.get("alignment"), dict) else {}
        seconds = alignment.get("seconds")
        located = isinstance(seconds, (int, float))
        nearby = []
        if located:
            for index, turn in enumerate(all_turns):
                start = float(turn.get("start") or 0)
                end = float(turn.get("end") or start)
                if end >= float(seconds) - 120 and start <= float(seconds) + 120:
                    nearby.append(f"T{index + 1:06d}")
        rows.append({
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or item.get("original_name") or "现场资料"),
            "first": round(float(seconds), 3) if located else None,
            "alignment_state": str(alignment.get("state") or "unlocated"),
            "visual_detail": description,
            "nearby_turn_ids": nearby,
            "evidence_boundary": "visual_context_only_not_a_meeting_decision",
        })
    return rows


def analysis_revision(mdir: Path) -> str | None:
    """Hash only material facts that can enter generated text.

    Importing, queueing, or failing an unanalyzed photo must not invalidate an otherwise
    current set of minutes/evidence. Once Vision has produced readable material context,
    its title, placement, and description become source inputs and participate in staleness.
    """
    records = []
    for item in load(mdir).get("photos", []):
        description = str(item.get("description") or "").strip()
        if item.get("analysis_state") != "ready" or not description:
            continue
        alignment = item.get("alignment") if isinstance(item.get("alignment"), dict) else {}
        seconds = alignment.get("seconds")
        records.append({
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or item.get("original_name") or ""),
            "seconds": round(float(seconds), 3) if isinstance(seconds, (int, float)) else None,
            "alignment_state": str(alignment.get("state") or "unlocated"),
            "description": description,
        })
    if not records:
        return None
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


def _managed_photo_path(mdir: Path, raw: str, folder: str) -> Path:
    """把 sidecar 路径约束在当前会议的指定照片目录内。"""
    root = (mdir / "photos" / folder).resolve()
    candidate = (mdir / str(raw or "")).resolve()
    try:
        inside = candidate.is_relative_to(root)
    except AttributeError:  # pragma: no cover - Python < 3.9 compatibility
        inside = root == candidate or root in candidate.parents
    if not inside:
        raise PhotoError("现场资料文件路径不安全，未执行删除")
    return candidate


def delete_photo(mdir: Path, photo_id: str) -> dict:
    """事务式删除 sidecar 条目、受保护原图和阅读副本。

    文件先在各自受控目录内改名为 tombstone，随后原子写入 sidecar；若写入失败，
    文件会恢复原名。这样不会留下指向已删除文件的 canonical 记录。
    """
    with _LOCK:
        document = load(mdir)
        record = next((item for item in document["photos"]
                       if item.get("id") == photo_id), None)
        if record is None:
            raise PhotoError("现场资料不存在")
        managed = [
            _managed_photo_path(mdir, str(record.get("original_path") or ""), "original"),
            _managed_photo_path(mdir, str(record.get("image_path") or ""), "review"),
        ]
        moved: list[tuple[Path, Path]] = []
        try:
            for path in managed:
                if not path.is_file():
                    continue
                tombstone = path.with_name(f".{path.name}.deleting-{uuid.uuid4().hex}")
                os.replace(path, tombstone)
                moved.append((path, tombstone))
            document["photos"] = [item for item in document["photos"]
                                  if item.get("id") != photo_id]
            document["updated_at"] = _now_iso()
            _atomic_json(mdir / "meeting.photos.json", document)
        except Exception:
            for original, tombstone in reversed(moved):
                if tombstone.exists():
                    os.replace(tombstone, original)
            raise
        for _, tombstone in moved:
            try:
                tombstone.unlink()
            except OSError:
                pass
        return {"deleted": record, "photos": document["photos"]}


def project(mdir: Path) -> list[dict]:
    """投影为 Web/Viewer 通用的视觉资料项；未定位照片始终排在已定位照片之后。"""
    visuals = []
    for index, item in enumerate(load(mdir).get("photos", []), start=1):
        alignment = item.get("alignment") if isinstance(item.get("alignment"), dict) else {}
        seconds = alignment.get("seconds")
        located = isinstance(seconds, (int, float))
        title = str(item.get("title") or item.get("original_name") or f"现场照片 {index}")
        analysis_state = str(item.get("analysis_state") or "not_requested")
        status_copy = {
            "queued": "已加入视觉分析队列",
            "analyzing": "正在分析现场资料",
            "failed": "视觉分析未完成，可重新尝试",
        }.get(analysis_state, "尚未进行视觉分析")
        visuals.append({
            "id": str(item.get("id") or f"F{index:04d}"),
            "kind": "photo",
            "page": None,
            "title": title,
            "description": str(item.get("description") or ""),
            "display_description": str(item.get("description") or status_copy),
            "image": str(item.get("image_path") or ""),
            "asset_path": str(item.get("image_path") or ""),
            "original_name": str(item.get("original_name") or ""),
            "captured_at": item.get("captured_at"),
            "first": float(seconds) if located else None,
            "ranges": [[float(seconds), float(seconds) + 1.0]] if located else [],
            "turn_indexes": [],
            "display_status": "现场照片",
            "analysis_state": analysis_state,
            "information_value": "unknown",
            "value": "unknown",
            "alignment": {
                "seconds": float(seconds) if located else None,
                "state": str(alignment.get("state") or "unlocated"),
                "method": str(alignment.get("method") or "none"),
                "confidence": str(alignment.get("confidence") or "unlocated"),
            },
        })
    return sorted(visuals, key=lambda item: (
        item["first"] is None, item["first"] if item["first"] is not None else 10**12,
        item["id"]))
