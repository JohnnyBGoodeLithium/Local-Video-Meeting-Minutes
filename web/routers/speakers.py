"""说话人与声纹库：绑定、改名、别名、合并、拆分与试听。
服务 schema：voice_bank bank schema v3、orgchart.json（无版本字段）。"""

import json
import re
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import voice_bank as vb
import voice_enroll as ve
import speaker_corrections as sc
import speaker_history as sh
import person_rename_history as prh
from deps import (BANK_DIR, BANK_LOCK, MEETINGS, PY, ROOT, SPEAKER_OP_LOCK,
                  _audio_path, _hms, _mmss, _mdir, _read_json,
                  _refresh_evidence, _safe)

router = APIRouter()


def _resolve_or_409(bank: dict, name: str, orgchart=None):
    """返回 (person, how)；未命中时抛 409(候选 + can_create 提示前端可新建)。"""
    person, how = vb.resolve_person(bank, name, orgchart=orgchart)
    if person is None:
        cands = [{"id": p.get("id"),
                  "name": p.get("display_name") or p.get("name", ""),
                  "names": p.get("names", []), "aliases": p.get("aliases", []),
                  "score": p.get("_match_score")}
                 for p in (how or [])]
        raise HTTPException(409, {"ok": False, "candidates": cands, "can_create": True,
                                  "detail": "没有精确命中：可从候选选择，或用 create=true 新建此人"})
    return person, how


def _bind_voice(voice_id: str, name: str, create: bool = False):
    """声纹 → 人。create=true 时库内精确名没有就直接新建 person。返回 (显示名, how)。"""
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        voice = next((v for v in bank["voices"] if v["id"] == voice_id), None)
        if not voice:
            raise HTTPException(404, "找不到这个声音组")
        if create:
            person, how = vb.resolve_person(bank, name)
            if person is None:
                person = vb.add_person(bank, name.strip(), display_name=name.strip())
                how = "新建"
        else:
            org = vb.load_orgchart(BANK_DIR)
            person, how = _resolve_or_409(bank, name, orgchart=org)
        voice["person_id"] = person["id"]
        vb.save_bank(BANK_DIR, bank)
        return (vb.person_name(bank, person["id"]),
                (how if isinstance(how, str) else "新建"), person["id"])


TURN_LINE_RE = re.compile(r"^\[\d{1,3}:\d{2}(?::\d{2})?\] \*\*")


def _rewrite_spk_md(mdir: Path, slug: str, turns: list):
    """按 json 重建 transcript.spk.md 正文；保留原文件头，沿用原时间格式(mm:ss / hh:mm:ss)。"""
    mp = mdir / "transcript.spk.md"
    fmt = _mmss
    head = f"# {slug} 逐字稿(具名)\n\n"
    if mp.is_file():
        lines = mp.read_text(encoding="utf-8").splitlines(keepends=True)
        i = next((k for k, l in enumerate(lines) if TURN_LINE_RE.match(l)), len(lines))
        if i < len(lines):
            head = "".join(lines[:i])
            if re.match(r"^\[\d{1,3}:\d{2}:\d{2}\]", lines[i]):
                fmt = _hms
    body = "\n\n".join(f"[{fmt(t['start'])}] **{t['speaker']}**: {t['text']}"
                       for t in turns) + "\n"
    mp.write_text(head + body, encoding="utf-8")


def _rename_voice_in_meeting(mdir: Path, slug: str, voice_id: str, new_name: str,
                             rename_sample: bool = True) -> int:
    tp = mdir / "transcript.spk.json"
    turns = _read_json(tp, [])
    old_names, n = set(), 0
    for t in turns:
        if t.get("voice") == voice_id:
            old_names.add(t.get("speaker", ""))
            t["speaker"] = new_name
            n += 1
    if n == 0:
        return 0
    tp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    _rewrite_spk_md(mdir, slug, turns)
    # 试听片段跟随改名（best-effort）
    if rename_sample:
        samples = mdir / "samples"
        for old in old_names:
            src, dst = samples / f"{_safe(old)}.wav", samples / f"{_safe(new_name)}.wav"
            if src.is_file() and not dst.exists():
                src.rename(dst)
    return n


class BindReq(BaseModel):
    voice: str
    name: str
    create: bool = False


@router.post("/api/meetings/{slug}/bind")
def bind_in_meeting(slug: str, req: BindReq):
    """一次交互绑定该 voice 在本会议的全部语句。"""
    mdir = _mdir(slug)
    with SPEAKER_OP_LOCK, sh.transaction(mdir, BANK_DIR, "bind"):
        new_name, how, person_id = _bind_voice(req.voice, req.name, req.create)
        n = _rename_voice_in_meeting(mdir, slug, req.voice, new_name)
        if n:
            turns = _read_json(mdir / "transcript.spk.json", [])
            indexes = [index for index, turn in enumerate(turns)
                       if turn.get("voice") == req.voice]
            sc.lock_turns(mdir, turns, indexes, person_id=person_id,
                          voice_id=req.voice, operation="bind")
            _refresh_evidence(mdir)
    return {"ok": True, "name": new_name, "turns": n, "how": how,
            "undo_available": True}


@router.get("/api/meetings/{slug}/speakers/history")
def speaker_history_status(slug: str):
    mdir = _mdir(slug)
    available = sh.latest_available(mdir, BANK_DIR)
    return {"available": bool(available),
            "operation": available[1].get("operation") if available else None,
            "created_at": available[1].get("created_at") if available else None}


@router.post("/api/meetings/{slug}/speakers/undo")
def undo_speaker_operation(slug: str):
    mdir = _mdir(slug)
    with SPEAKER_OP_LOCK:
        available = sh.latest_available(mdir, BANK_DIR)
        if available is None:
            raise HTTPException(404, "没有可撤销的说话人修改，或此后数据已经变化")
        op_dir, manifest = available
        try:
            with BANK_LOCK:
                sh.restore(op_dir, mdir, BANK_DIR, require_current=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        _refresh_evidence(mdir)
        subprocess.run([str(PY), str(ROOT / "bin" / "voice_tool.py"), "sample", str(mdir)],
                       check=False, capture_output=True)
    return {"ok": True, "operation": manifest.get("operation")}


@router.get("/api/speakers")
def list_speakers():
    bank = vb.load_bank(BANK_DIR)
    voices = [{"id": v["id"], "person_id": v.get("person_id"),
               "name": vb.display_name(bank, v),
               "label_hint": v.get("label_hint", ""),
               "sources": v.get("sources", []),
               "created": v.get("created", "")}
              for v in bank["voices"]]
    persons = [{"id": p["id"], "name": p["name"],
                "display_name": p.get("display_name") or p["name"],
                "names": p.get("names", []), "aliases": p.get("aliases", []),
                "created": p.get("created", ""),
                "voices": sum(1 for v in bank["voices"] if v.get("person_id") == p["id"])}
               for p in bank["persons"]]
    return {"persons": persons, "voices": voices}


def _voice_sample(voice_id: str) -> Path | None:
    """从声纹来源会议中找一个代表试听片段；不在 API 中暴露磁盘路径。"""
    bank = vb.load_bank(BANK_DIR)
    voice = next((v for v in bank["voices"] if v["id"] == voice_id), None)
    if voice is None:
        raise HTTPException(404, "没有这条声纹")
    candidates = [vb.display_name(bank, voice), voice.get("label_hint", ""), voice_id]
    for slug in reversed(voice.get("sources", [])):
        mdir = (MEETINGS / slug).resolve()
        if mdir.parent != MEETINGS.resolve() or not mdir.is_dir():
            continue
        for turn in _read_json(mdir / "transcript.spk.json", []):
            if turn.get("voice") == voice_id:
                candidates.insert(0, turn.get("speaker", ""))
                break
        for value in candidates:
            p = mdir / "samples" / f"{_safe(value)}.wav"
            if value and p.is_file():
                return p
    return None


@router.get("/api/speakers/{voice_id}/sample")
def speaker_sample(voice_id: str):
    p = _voice_sample(voice_id)
    if p is None:
        raise HTTPException(404, "没有可用试听片段")
    return FileResponse(p, media_type="audio/wav")


class PersonPutReq(BaseModel):
    display_name: str
    names: list[dict] = Field(default_factory=list)


def person_rename_impact(person_id: str, display_name: str) -> dict:
    display = display_name.strip()
    if not display:
        raise HTTPException(400, "首选显示名不能为空")
    bank = vb.load_bank(BANK_DIR)
    person = next((p for p in bank["persons"] if p["id"] == person_id), None)
    if person is None:
        raise HTTPException(404, "没有这个人")
    voices = [v for v in bank["voices"] if v.get("person_id") == person_id]
    voice_ids = {voice["id"] for voice in voices}
    slugs = sorted({slug for voice in voices for slug in voice.get("sources", [])})
    turns = 0
    valid_slugs = []
    for slug in slugs:
        mdir = (MEETINGS / slug).resolve()
        if mdir.parent != MEETINGS.resolve() or not mdir.is_dir():
            continue
        valid_slugs.append(slug)
        turns += sum(1 for turn in _read_json(mdir / "transcript.spk.json", [])
                     if turn.get("voice") in voice_ids)
    return {"person_id": person_id,
            "old_name": vb.person_name(bank, person_id), "new_name": display,
            "meetings": len(valid_slugs), "turns": turns, "slugs": valid_slugs,
            "model_calls": 0}


@router.put("/api/speakers/person/{person_id}")
def update_person(person_id: str, req: PersonPutReq):
    display = req.display_name.strip()
    if not display:
        raise HTTPException(400, "首选显示名不能为空")
    typed = []
    for item in req.names:
        value = str(item.get("value", "")).strip()
        if not value:
            continue
        kind = str(item.get("type", "other"))
        typed.append({"value": value,
                      "type": kind if kind in vb.NAME_TYPES else "other",
                      "verified": bool(item.get("verified", True))})
    if not any(vb.normalize_name(n["value"]) == vb.normalize_name(display) for n in typed):
        typed.append({"value": display, "type": "other", "verified": True})
    impact = person_rename_impact(person_id, display)
    with SPEAKER_OP_LOCK:
        op_dir = prh.begin(BANK_DIR, MEETINGS, person_id, impact["slugs"])
        try:
            with BANK_LOCK:
                bank = vb.load_bank(BANK_DIR)
                person = next((p for p in bank["persons"] if p["id"] == person_id), None)
                if person is None:
                    raise HTTPException(404, "没有这个人")
                person["display_name"] = display
                person["names"] = typed
                vb.normalize_person(person)
                linked_voices = [v for v in bank["voices"] if v.get("person_id") == person_id]
                vb.save_bank(BANK_DIR, bank)
            changed_turns, changed_meeting_ids = 0, set()
            for voice in linked_voices:
                for slug in voice.get("sources", []):
                    mdir = (MEETINGS / slug).resolve()
                    if mdir.parent != MEETINGS.resolve() or not mdir.is_dir():
                        continue
                    count = _rename_voice_in_meeting(mdir, slug, voice["id"], display, False)
                    changed_turns += count
                    if count:
                        changed_meeting_ids.add(slug)
            for slug in changed_meeting_ids:
                _refresh_evidence(MEETINGS / slug)
            prh.complete(op_dir, BANK_DIR, MEETINGS)
        except Exception:
            prh.rollback(op_dir, BANK_DIR, MEETINGS, require_current=False)
            raise
    return {"ok": True, "id": person_id, "display_name": person["display_name"],
            "names": person["names"], "meetings": len(changed_meeting_ids),
            "turns": changed_turns, "undo_available": True, "model_calls": 0}


def undo_person_rename(person_id: str):
    with SPEAKER_OP_LOCK:
        available = prh.latest(BANK_DIR, MEETINGS, person_id)
        if available is None:
            raise HTTPException(404, "没有可撤销的显示名称修改，或此后数据已经变化")
        op_dir, manifest = available
        try:
            with BANK_LOCK:
                prh.rollback(op_dir, BANK_DIR, MEETINGS, require_current=True)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        for slug in manifest["slugs"]:
            _refresh_evidence(MEETINGS / slug)
    return {"ok": True, "operation": "display_rename", "person_id": person_id}


@router.post("/api/speakers/bind")
def bind_voice_only(req: BindReq):
    """只在声纹库层面绑定（不改任何会议）。"""
    new_name, how, _person_id = _bind_voice(req.voice, req.name, req.create)
    return {"ok": True, "name": new_name, "how": how}


class AliasReq(BaseModel):
    person: str
    aliases: list[str]


@router.post("/api/speakers/alias")
def add_alias(req: AliasReq):
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        person, _how = vb.resolve_person(bank, req.person)  # 与 voice_tool alias 一致：不带 orgchart
        if person is None:
            raise HTTPException(404, "没找到这个人")
        for a in req.aliases:
            if a and a not in person["aliases"]:
                person["aliases"].append(a)
        vb.save_bank(BANK_DIR, bank)
        return {"ok": True, "name": vb.person_name(bank, person["id"]),
                "aliases": person["aliases"]}


class MergeReq(BaseModel):
    keep: str
    drop: list[str]


@router.post("/api/speakers/merge")
def merge_voices(req: MergeReq):
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        keep = next((v for v in bank["voices"] if v["id"] == req.keep), None)
        if not keep:
            raise HTTPException(404, f"没有这条声纹: {req.keep}")
        if not keep.get("person_id"):
            p = vb.add_person(bank, keep.get("label_hint") or keep["id"])
            keep["person_id"] = p["id"]
        merged = 0
        for did in req.drop:
            drop = next((v for v in bank["voices"] if v["id"] == did), None)
            if not drop or did == req.keep:
                continue
            drop["person_id"] = keep["person_id"]
            for s in drop.get("sources", []):
                if s not in keep.setdefault("sources", []):
                    keep["sources"].append(s)
            merged += 1
        vb.save_bank(BANK_DIR, bank)
        return {"ok": True, "merged": merged,
                "name": vb.person_name(bank, keep["person_id"])}


class VoiceReq(BaseModel):
    voice: str


@router.post("/api/speakers/unbind")
def unbind_voice(req: VoiceReq):
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        voice = next((v for v in bank["voices"] if v["id"] == req.voice), None)
        if not voice:
            raise HTTPException(404, "没有这条声纹")
        voice["person_id"] = None
        vb.save_bank(BANK_DIR, bank)
        return {"ok": True}


class SplitReq(BaseModel):
    voice: str
    turns: list[int]
    name: str = ""
    expand_similar: bool = False
    group_assignments: dict[str, dict] = Field(default_factory=dict)


class SplitPreviewReq(BaseModel):
    voice: str
    turns: list[int]
    name: str = ""


def _turn_duration(turn: dict) -> float:
    return max(0.0, float(turn.get("end", 0) or 0) - float(turn.get("start", 0) or 0))


def _representative_indexes(turns: list, indexes: list[int], limit: int = 3) -> list[int]:
    """Choose clear-enough long samples distributed across the meeting."""
    valid = sorted({index for index in indexes if 0 <= index < len(turns)},
                   key=lambda index: float(turns[index].get("start", 0) or 0))
    if len(valid) <= limit:
        return valid
    thirds = [
        valid[:max(1, (len(valid) + 2) // 3)],
        valid[len(valid) // 3:max(len(valid) // 3 + 1, (len(valid) * 2 + 2) // 3)],
        valid[(len(valid) * 2) // 3:],
    ]
    result = []
    for part in thirds:
        if not part:
            continue
        chosen = max(part, key=lambda index: (_turn_duration(turns[index]), -index))
        if chosen not in result:
            result.append(chosen)
    return result[:limit]


def _turns_summary(turns: list, indexes: list[int]) -> dict:
    stable = sorted({index for index in indexes if 0 <= index < len(turns)})
    return {"turns": len(stable),
            "duration": round(sum(_turn_duration(turns[index]) for index in stable), 3),
            "representative_turns": _representative_indexes(turns, stable)}


@router.get("/api/meetings/{slug}/speakers/{voice_id}/review")
def speaker_review_summary(slug: str, voice_id: str):
    """Read-only projection for the identity card and example-selection step."""
    mdir = _mdir(slug)
    turns = _read_json(mdir / "transcript.spk.json", [])
    indexes = [index for index, turn in enumerate(turns) if turn.get("voice") == voice_id]
    if not indexes:
        raise HTTPException(404, "当前会议没有这组发言")
    protected = sorted(sc.locked_indexes(mdir, turns) & set(indexes))
    return {"ok": True, "voice": voice_id, "indexes": indexes, "protected": protected,
            "summary": _turns_summary(turns, indexes)}


def _resolve_current_split_voice(turns: list, indexes: list[int], requested: str):
    """以磁盘上的最新逐字稿为准解析拆分来源声纹。

    浏览器可能在一次绑定/拆分后仍保留旧 bundle。只要当前所选轮次仍明确属于
    同一条声纹，就可以安全地把旧 voice 纠正为当前 voice；只有当前数据确实混合
    多条声纹时才拒绝，避免把两个人再次错误合并。
    """
    voices = {str(turns[i].get("voice") or "").strip() for i in indexes}
    if "" in voices:
        raise HTTPException(400, "所选片段缺少可导航的说话人信息，请刷新后重新选择")
    if len(voices) != 1:
        raise HTTPException(400, "所选片段当前属于多个声音组，请刷新后重新选择")
    current = next(iter(voices))
    return current, current != requested


def _existing_voice_for_person(bank: dict, turns: list, person_id: str, *,
                               source_voice: str, slug: str):
    """为人工逐轮改派选择已存在的目标声纹，不凭短音频重新猜身份。"""
    counts: dict[str, int] = {}
    for turn in turns:
        voice_id = str(turn.get("voice") or "")
        counts[voice_id] = counts.get(voice_id, 0) + 1
    candidates = [voice for voice in bank.get("voices", [])
                  if voice.get("person_id") == person_id
                  and voice.get("id") != source_voice]
    if not candidates:
        return None
    # 优先复用本会议已出现且轮次最多的已确认声纹；其次才用跨会议声纹。
    return max(candidates, key=lambda voice: (
        counts.get(str(voice.get("id") or ""), 0),
        slug in set(voice.get("sources") or []),
        str(voice.get("id") or ""),
    ))


def _resolve_group_person(bank: dict, assignment: dict | None, legacy_name: str = ""):
    assignment = assignment or {}
    name = str(assignment.get("name") or legacy_name or "").strip()
    if not name:
        return None
    create = bool(assignment.get("create"))
    if create:
        person, _how = vb.resolve_person(bank, name)
        if person is None:
            person = vb.add_person(bank, name, display_name=name)
        return person
    person, _how = _resolve_or_409(bank, name, orgchart=vb.load_orgchart(BANK_DIR))
    return person


@router.post("/api/meetings/{slug}/split/preview")
def preview_split_voice_turns(slug: str, req: SplitPreviewReq):
    """只计算高置信扩散建议；不改逐字稿、声纹库或人工锁。"""
    import numpy as np

    mdir = _mdir(slug)
    turns = _read_json(mdir / "transcript.spk.json", [])
    selected = sorted({index for index in req.turns if 0 <= index < len(turns)})
    if not selected:
        raise HTTPException(400, "没有有效轮次")
    source_voice, voice_rebased = _resolve_current_split_voice(turns, selected, req.voice)
    selected_set = set(selected)
    source_indexes = [index for index, turn in enumerate(turns)
                      if turn.get("voice") == source_voice]
    protected = sorted((sc.locked_indexes(mdir, turns) - selected_set) & set(source_indexes))
    candidates = [index for index in source_indexes
                  if index not in selected_set and index not in set(protected)]
    if req.name.strip():
        with BANK_LOCK:
            bank = vb.load_bank(BANK_DIR)
            person, _how = _resolve_or_409(
                bank, req.name.strip(), orgchart=vb.load_orgchart(BANK_DIR))
            target = _existing_voice_for_person(
                bank, turns, person["id"], source_voice=source_voice, slug=slug)
        if target is not None:
            return {"ok": True, "voice": source_voice,
                    "source_voice_rebased": voice_rebased,
                    "selected": selected, "suggested": [], "protected": protected,
                    "ambiguous": [], "threshold": None, "margin": None,
                    "direct_assignment": True,
                    "target_voice": target["id"]}
    wav = _audio_path(mdir)
    if wav is None:
        raise HTTPException(400, "会议没有可用录音，无法分析这些片段")
    picked = ve.embed_ranges(wav, [(float(turns[i].get("start", 0)),
                                    float(turns[i].get("end", 0))) for i in selected])
    if not len(picked):
        return {"ok": True, "voice": source_voice,
                "source_voice_rebased": voice_rebased,
                "selected": selected, "suggested": [], "protected": protected,
                "ambiguous": [], "threshold": None, "margin": None,
                "direct_only": True, "source_summary": _turns_summary(turns, source_indexes),
                "groups": [{"group_key": "group-1", "selected": selected,
                            "suggested": [], **_turns_summary(turns, selected),
                            "evidence_limited": True, "suggested_person": ""}]}
    clusters = ve.cluster_embeddings(picked)
    centroids = [picked[[pos for pos, value in enumerate(clusters) if value == cluster]].mean(axis=0)
                 for cluster in range(max(clusters) + 1)]
    suggested, ambiguous, suggested_by_group = [], [], {index: [] for index in range(len(centroids))}
    if candidates:
        rest = ve.embed_ranges(wav, [(float(turns[i].get("start", 0)),
                                      float(turns[i].get("end", 0))) for i in candidates])
        if len(rest):
            base = rest.mean(axis=0).astype(np.float32)
            moves, uncertain = ve.suggest_reassignments(rest, base, centroids)
            suggested = [candidates[pos] for pos, move in enumerate(moves) if move is not None]
            for pos, move in enumerate(moves):
                if move is not None and int(move) in suggested_by_group:
                    suggested_by_group[int(move)].append(candidates[pos])
            ambiguous = [candidates[pos] for pos, value in enumerate(uncertain) if value]
    groups = []
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        for cluster, centroid in enumerate(centroids):
            chosen = [selected[pos] for pos, value in enumerate(clusters) if value == cluster]
            suggested_person = ""
            match, _similarity = _match_voice_excluding(
                BANK_DIR, bank, centroid, source_voice, 0.70)
            if match is not None and match.get("person_id"):
                suggested_person = vb.display_name(bank, match)
            members = chosen + suggested_by_group.get(cluster, [])
            groups.append({"group_key": f"group-{cluster + 1}", "selected": chosen,
                           "suggested": suggested_by_group.get(cluster, []),
                           **_turns_summary(turns, members),
                           "evidence_limited": sum(_turn_duration(turns[i]) for i in chosen) < 1.0,
                           "suggested_person": suggested_person})
    return {"ok": True, "voice": source_voice, "source_voice_rebased": voice_rebased,
            "selected": selected, "suggested": suggested, "protected": protected,
            "ambiguous": ambiguous, "threshold": 0.78, "margin": 0.08,
            "direct_only": False, "source_summary": _turns_summary(turns, source_indexes),
            "groups": groups}


def _match_voice_excluding(bank_dir: Path, bank: dict, vec, exclude: str, threshold: float):
    """match_voice 的排除版：拆分出的轮次永不再匹配回它来源的那条声纹。"""
    import numpy as np
    v = np.asarray(vec, dtype=np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    best, best_sim = None, -1.0
    for entry in bank["voices"]:
        if entry["id"] == exclude:
            continue
        sim = float(np.dot(v, vb.vec_of(bank_dir, entry)))
        if sim > best_sim:
            best, best_sim = entry, sim
    if best is not None and best_sim >= threshold:
        return best, best_sim
    return None, best_sim


@router.post("/api/meetings/{slug}/split")
def split_voice_turns(slug: str, req: SplitReq):
    mdir = _mdir(slug)
    with SPEAKER_OP_LOCK, sh.transaction(mdir, BANK_DIR, "split"):
        return _split_voice_turns(slug, req, mdir)


def _split_voice_turns(slug: str, req: SplitReq, mdir: Path):
    """把一条声纹在本会议中的部分轮次拆出（两位声音相近者被并入同一声纹时用）：
    只对所选轮次的音频段重提嵌入 → 贪心聚类（可能不止一个人）→ 逐簇匹配库内
    其他声纹或匿名新建 → 默认只改派明确选择；用户另行明确要求时才扩展相似轮次。"""
    import numpy as np

    tp = mdir / "transcript.spk.json"
    turns = _read_json(tp, [])
    idx = sorted({i for i in req.turns if 0 <= i < len(turns)})
    if not idx:
        raise HTTPException(400, "没有有效轮次")
    source_voice, voice_rebased = _resolve_current_split_voice(turns, idx, req.voice)
    picked_set = set(idx)
    remaining = [i for i, t in enumerate(turns)
                 if t.get("voice") == source_voice and i not in picked_set]
    if not remaining:
        raise HTTPException(
            400, f"这个声音组在本会议只有 {len(idx)} 段且已全部选中，无需单独修复："
                 "点击该片段的人物标签，直接确认整组是谁")
    # 用户明确标记具体轮次并选择一个已有人员时，人工判断优先于声纹相似度。
    # 尤其 0 时长或极短的边界轮次没有可靠 embedding；强制重提声纹会让用户
    # 明明知道是谁却无法改正。这里只改手选轮次，不扩散、不改目标声纹质心。
    group_one = req.group_assignments.get("group-1") or {}
    direct_name = str(group_one.get("name") or req.name or "").strip()
    if direct_name and not req.expand_similar:
        with BANK_LOCK:
            bank = vb.load_bank(BANK_DIR)
            assigned_person = _resolve_group_person(bank, group_one, req.name)
            target = _existing_voice_for_person(
                bank, turns, assigned_person["id"], source_voice=source_voice, slug=slug)
            if target is not None:
                if slug not in target.setdefault("sources", []):
                    target["sources"].append(slug)
                new_name = vb.display_name(bank, target)
                for index in idx:
                    turns[index]["voice"] = target["id"]
                    turns[index]["speaker"] = new_name
                vb.save_bank(BANK_DIR, bank)

        if target is not None:
            tmp = tp.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(tp)
            _rewrite_spk_md(mdir, slug, turns)
            sc.lock_turns(mdir, turns, idx, person_id=assigned_person["id"],
                          voice_id=target["id"], operation="direct-assign")
            _refresh_evidence(mdir)
            subprocess.run([str(PY), str(ROOT / "bin" / "voice_tool.py"), "sample", str(mdir)],
                           check=False, capture_output=True)
            return {"ok": True, "moved": len(idx), "reassigned": 0,
                    "clusters": 1,
                    "voices": [{"voice": target["id"], "name": new_name,
                                "turns": len(idx), "matched": True,
                                "similarity": None, "group_key": "group-1",
                                "turn_indexes": idx}],
                    "source_voice_rebased": voice_rebased,
                    "name_applied": True, "expanded_similar": False,
                    "protected": len(sc.locked_indexes(mdir, turns) & set(remaining)),
                    "direct_assignment": True, "turn_indexes": idx}
    wav = _audio_path(mdir)
    if wav is None:
        raise HTTPException(400, "会议没有可用录音，无法分析这些片段")

    # 嵌入提取可能耗时几十秒，在 BANK_LOCK 外做
    ranges_of = lambda ids: [(float(turns[i].get("start", 0)),  # noqa: E731
                              float(turns[i].get("end", 0))) for i in ids]
    picked = ve.embed_ranges(wav, ranges_of(idx))
    rest = ve.embed_ranges(wav, ranges_of(remaining))
    if not len(picked) or not len(rest):
        raise HTTPException(422, "这些片段的声音证据不足，无法可靠形成新分组")
    clusters = ve.cluster_embeddings(picked)
    n_clusters = max(clusters) + 1
    # 半监督重排：以标记轮次建立新簇质心，再把该声纹其余轮次按“离谁近归谁”
    # 自动重排——长会议里用户只需标出少量样例，不必逐条找出所有错分轮次。
    new_cents = [picked[[n for n, c in enumerate(clusters) if c == k]].mean(axis=0)
                 for k in range(n_clusters)]
    # 人工确认过的轮次属于硬保护区：即使与新簇很相似，也不能被扩散改派。
    # 仅对未锁定的剩余轮次给出保守建议，并把结果映射回完整 rest 序列。
    protected_indexes = sc.locked_indexes(mdir, turns) - picked_set
    expandable_pos = [pos for pos, index in enumerate(remaining)
                      if index not in protected_indexes]
    moves = [None] * len(rest)
    if req.expand_similar and expandable_pos:
        suggested, _ambiguous = ve.suggest_reassignments(
            rest[expandable_pos], rest.mean(axis=0), new_cents)
        for pos, cluster in zip(expandable_pos, suggested):
            moves[pos] = cluster
    keep_rest = [n for n, mk in enumerate(moves) if mk is None]
    if not keep_rest:
        raise HTTPException(400, "调整后原声音组不再剩余发言；若整组都属于别人，请直接确认人物")

    moved, reassigned, results, lock_groups = 0, 0, [], []
    any_name_applied = False
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        src = next((v for v in bank["voices"] if v["id"] == source_voice), None)
        if src is None:
            raise HTTPException(404, "找不到当前声音组")
        src_label = str(turns[idx[0]].get("speaker") or src.get("label_hint") or source_voice)
        for k in range(n_clusters):
            key = f"group-{k + 1}"
            assignment_provided = key in req.group_assignments
            assigned_person = _resolve_group_person(
                bank, req.group_assignments.get(key), req.name)
            keep_unnamed = assignment_provided and assigned_person is None and not req.name.strip()
            any_name_applied = any_name_applied or assigned_person is not None
            member_pos = [n for n, c in enumerate(clusters) if c == k]
            moved_pos = [n for n, mk in enumerate(moves) if mk == k]
            members = [idx[n] for n in member_pos] + [remaining[n] for n in moved_pos]
            mats = [picked[member_pos]]
            if moved_pos:
                mats.append(rest[moved_pos])
            centroid = np.vstack(mats).mean(axis=0)
            match, sim = _match_voice_excluding(BANK_DIR, bank, centroid, source_voice, 0.70)
            if keep_unnamed and match is not None and match.get("person_id"):
                match = None
            if match is not None and assigned_person is not None:
                same_person = match.get("person_id") == assigned_person["id"]
                meeting_local_unbound = (not match.get("person_id")
                                         and set(match.get("sources", [])) <= {slug})
                if not same_person and not meeting_local_unbound:
                    match = None
            if match is None:
                hint = f"{src_label}(拆分)" if n_clusters == 1 else f"{src_label}(拆分{k + 1})"
                match = vb.add_voice(BANK_DIR, bank, centroid, label_hint=hint, source=slug,
                                     person_id=assigned_person["id"] if assigned_person else None)
                matched = False
            else:
                if slug not in match.setdefault("sources", []):
                    match["sources"].append(slug)
                matched = True
            if assigned_person is not None:
                match["person_id"] = assigned_person["id"]
            new_name = vb.display_name(bank, match)
            for i in members:
                turns[i]["voice"] = match["id"]
                turns[i]["speaker"] = new_name
            moved += len(members)
            reassigned += len(moved_pos)
            lock_groups.append((members, match["id"],
                                assigned_person["id"] if assigned_person else None))
            results.append({"group_key": key, "voice": match["id"], "name": new_name,
                            "turns": len(members), "matched": matched,
                            "similarity": round(sim, 3), "turn_indexes": members})
        # 原声纹质心用重排后剩余的轮次重算，避免继续被混入的发音污染
        # 已确认且跨会议复用的声纹不能被单场剩余音频覆盖全局质心。
        if not (src.get("person_id") and len(src.get("sources", [])) > 1):
            new_centroid = rest[keep_rest].mean(axis=0).astype(np.float32)
            np.save(Path(BANK_DIR) / src["emb"],
                    new_centroid / (np.linalg.norm(new_centroid) + 1e-9))
        vb.save_bank(BANK_DIR, bank)

    tmp = tp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(tp)
    _rewrite_spk_md(mdir, slug, turns)
    for members, voice_id, person_id in lock_groups:
        sc.lock_turns(mdir, turns, members,
                      person_id=person_id,
                      voice_id=voice_id, operation="split")
    _refresh_evidence(mdir)
    subprocess.run([str(PY), str(ROOT / "bin" / "voice_tool.py"), "sample", str(mdir)],
                   check=False, capture_output=True)
    return {"ok": True, "moved": moved, "reassigned": reassigned,
            "clusters": n_clusters, "voices": results,
            "source_voice_rebased": voice_rebased,
            "name_applied": any_name_applied,
            "expanded_similar": bool(req.expand_similar),
            "protected": len(protected_indexes & set(remaining)),
            "turn_indexes": sorted({index for members, _voice, _person in lock_groups
                                    for index in members})}
