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
from deps import (BANK_DIR, BANK_LOCK, MEETINGS, PY, ROOT, _audio_path, _hms,
                  _mmss, _mdir, _read_json, _refresh_evidence, _safe)

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
            raise HTTPException(404, "没有这条声纹")
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
        return vb.person_name(bank, person["id"]), (how if isinstance(how, str) else "新建")


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


def _rename_voice_in_meeting(mdir: Path, slug: str, voice_id: str, new_name: str) -> int:
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
    new_name, how = _bind_voice(req.voice, req.name, req.create)
    n = _rename_voice_in_meeting(mdir, slug, req.voice, new_name)
    if n:
        _refresh_evidence(mdir)
    return {"ok": True, "name": new_name, "turns": n, "how": how}


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
            count = _rename_voice_in_meeting(mdir, slug, voice["id"], display)
            changed_turns += count
            if count:
                changed_meeting_ids.add(slug)
    for slug in changed_meeting_ids:
        _refresh_evidence(MEETINGS / slug)
    return {"ok": True, "id": person_id, "display_name": person["display_name"],
            "names": person["names"], "meetings": len(changed_meeting_ids),
            "turns": changed_turns}


@router.post("/api/speakers/bind")
def bind_voice_only(req: BindReq):
    """只在声纹库层面绑定（不改任何会议）。"""
    new_name, how = _bind_voice(req.voice, req.name, req.create)
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
    """把一条声纹在本会议中的部分轮次拆出（两位声音相近者被并入同一声纹时用）：
    只对所选轮次的音频段重提嵌入 → 贪心聚类（可能不止一个人）→ 逐簇匹配库内
    其他声纹或匿名新建 → 只改派这些轮次；原声纹质心用剩余轮次自动重算校正。"""
    import numpy as np

    mdir = _mdir(slug)
    tp = mdir / "transcript.spk.json"
    turns = _read_json(tp, [])
    idx = sorted({i for i in req.turns if 0 <= i < len(turns)})
    if not idx:
        raise HTTPException(400, "没有有效轮次")
    if any(turns[i].get("voice") != req.voice for i in idx):
        raise HTTPException(400, "只能拆分同一条声纹的轮次")
    picked_set = set(idx)
    remaining = [i for i, t in enumerate(turns)
                 if t.get("voice") == req.voice and i not in picked_set]
    if not remaining:
        raise HTTPException(400, "不能拆分该声纹的全部轮次；整体改派请用绑定")
    wav = _audio_path(mdir)
    if wav is None:
        raise HTTPException(400, "会议没有可用音频，无法重提声纹")

    # 嵌入提取可能耗时几十秒，在 BANK_LOCK 外做
    ranges_of = lambda ids: [(float(turns[i].get("start", 0)),  # noqa: E731
                              float(turns[i].get("end", 0))) for i in ids]
    picked = ve.embed_ranges(wav, ranges_of(idx))
    rest = ve.embed_ranges(wav, ranges_of(remaining))
    if not len(picked) or not len(rest):
        raise HTTPException(500, "声纹嵌入提取失败")
    clusters = ve.cluster_embeddings(picked)
    n_clusters = max(clusters) + 1

    moved, results = 0, []
    with BANK_LOCK:
        bank = vb.load_bank(BANK_DIR)
        src = next((v for v in bank["voices"] if v["id"] == req.voice), None)
        if src is None:
            raise HTTPException(404, "没有这条声纹")
        src_label = str(turns[idx[0]].get("speaker") or src.get("label_hint") or req.voice)
        for k in range(n_clusters):
            member_pos = [n for n, c in enumerate(clusters) if c == k]
            members = [idx[n] for n in member_pos]
            centroid = picked[member_pos].mean(axis=0)
            match, sim = _match_voice_excluding(BANK_DIR, bank, centroid, req.voice, 0.70)
            if match is None:
                hint = f"{src_label}(拆分)" if n_clusters == 1 else f"{src_label}(拆分{k + 1})"
                match = vb.add_voice(BANK_DIR, bank, centroid, label_hint=hint, source=slug)
                matched = False
            else:
                if slug not in match.setdefault("sources", []):
                    match["sources"].append(slug)
                matched = True
            new_name = vb.display_name(bank, match)
            for i in members:
                turns[i]["voice"] = match["id"]
                turns[i]["speaker"] = new_name
            moved += len(members)
            results.append({"voice": match["id"], "name": new_name,
                            "turns": len(members), "matched": matched,
                            "similarity": round(sim, 3)})
        # 原声纹质心用剩余轮次重算，避免继续被混入的发音污染
        new_centroid = rest.mean(axis=0).astype(np.float32)
        np.save(Path(BANK_DIR) / src["emb"],
                new_centroid / (np.linalg.norm(new_centroid) + 1e-9))
        vb.save_bank(BANK_DIR, bank)

    tmp = tp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(tp)
    _rewrite_spk_md(mdir, slug, turns)
    _refresh_evidence(mdir)
    subprocess.run([str(PY), str(ROOT / "bin" / "voice_tool.py"), "sample", str(mdir)],
                   check=False, capture_output=True)
    return {"ok": True, "moved": moved, "clusters": n_clusters, "voices": results}
