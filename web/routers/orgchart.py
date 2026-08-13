"""组织架构：orgchart.json 读写、参考文件上传与 VL 提取草稿。
服务 schema：orgchart.json / orgchart_draft.json 条目（无版本字段）。"""

import json
import re
import subprocess
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import voice_bank as vb
from deps import (BANK_DIR, BANK_LOCK, ORG_FILE_EXT, ORG_FILES, PY, ROOT,
                  _read_json, _safe)
from job_store import EXEC, _new_job, _run_pipeline

router = APIRouter()


def _org_entry_id(name: str, index: int) -> str:
    return "o_" + uuid.uuid5(uuid.NAMESPACE_URL, f"meeting-org:{index}:{name}").hex[:12]


def _normalize_org_entries(raw_entries: list[dict]) -> list[dict]:
    """兼容 leader=姓名的旧数据，并为图编辑器补稳定节点/上级 ID。"""
    entries, used = [], set()
    for index, raw in enumerate(raw_entries):
        name = str(raw.get("name", "")).strip()
        node_id = str(raw.get("id", "")).strip() or _org_entry_id(name, index)
        if node_id in used:
            node_id = _org_entry_id(name, index)
        used.add(node_id)
        entries.append({
            "id": node_id,
            "person_id": str(raw.get("person_id", "")).strip() or None,
            "name": name,
            "aliases": [str(a).strip() for a in raw.get("aliases", []) if str(a).strip()],
            "title": str(raw.get("title", "")).strip(),
            "team": str(raw.get("team", "")).strip(),
            "manager_id": str(raw.get("manager_id", "")).strip() or None,
            "leader": str(raw.get("leader", "")).strip(),
            "leader_raw": str(raw.get("leader_raw", raw.get("leader", ""))).strip(),
            "status": str(raw.get("status", "")).strip(),
            "source_pages": [int(x) for x in raw.get("source_pages", [])
                             if isinstance(x, (int, float, str)) and str(x).isdigit()],
            "conflicts": [str(x) for x in raw.get("conflicts", []) if str(x).strip()],
            "note": str(raw.get("note", "")).strip(),
        })
    by_id = {e["id"]: e for e in entries}
    by_name: dict[str, list[str]] = {}
    for e in entries:
        by_name.setdefault(vb.normalize_name(e["name"]), []).append(e["id"])
        for alias in e["aliases"]:
            by_name.setdefault(vb.normalize_name(alias), []).append(e["id"])
    for e in entries:
        if e["manager_id"] not in by_id:
            e["manager_id"] = None
        if not e["manager_id"] and e["leader"]:
            matches = list(dict.fromkeys(by_name.get(vb.normalize_name(e["leader"]), [])))
            if len(matches) == 1 and matches[0] != e["id"]:
                e["manager_id"] = matches[0]
        if e["manager_id"]:
            e["leader"] = by_id[e["manager_id"]]["name"]
        if not e["status"]:
            e["status"] = "conflict" if e["conflicts"] else (
                "unresolved" if e["leader_raw"] and not e["manager_id"] else "confirmed")
    return entries


@router.get("/api/orgchart")
def get_orgchart():
    entries = _normalize_org_entries(vb.load_orgchart(BANK_DIR))
    bank = vb.load_bank(BANK_DIR)
    valid_person_ids = {p["id"] for p in bank["persons"]}
    placed = {e["person_id"] for e in entries if e.get("person_id") in valid_person_ids}
    # 旧 Org Chart 没有 person_id：只按唯一的已确认名称精确关联，不做任何模糊合并。
    for entry in entries:
        if entry.get("person_id") in valid_person_ids:
            continue
        person, _how = vb.resolve_person(bank, entry["name"])
        if person is not None:
            entry["person_id"] = person["id"]
            placed.add(person["id"])
    unplaced = [{"id": p["id"], "display_name": p.get("display_name") or p["name"],
                 "name": p["name"], "names": p.get("names", [])}
                for p in bank["persons"] if p["id"] not in placed]
    return {"entries": entries, "unplaced_people": unplaced}


class OrgPut(BaseModel):
    entries: list[dict]


@router.put("/api/orgchart")
def put_orgchart(req: OrgPut):
    """保存图关系；服务端验证上级存在、自指和环路。"""
    supplied_ids = [str(e.get("id", "")).strip() for e in req.entries if e.get("id")]
    if len(supplied_ids) != len(set(supplied_ids)):
        raise HTTPException(400, "存在重复节点 ID")
    supplied_id_set = set(supplied_ids)
    for raw in req.entries:
        raw_manager_id = raw.get("manager_id")
        manager_id = str(raw_manager_id).strip() if raw_manager_id else ""
        if manager_id and manager_id not in supplied_id_set:
            name = str(raw.get("name", "")).strip() or "未命名节点"
            raise HTTPException(400, f"{name} 的上级节点不存在")
    entries = _normalize_org_entries(req.entries)
    if any(not e["name"] for e in entries):
        raise HTTPException(400, "存在空名字条目")
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        manager_id = e.get("manager_id")
        if manager_id and manager_id not in by_id:
            raise HTTPException(400, f"{e['name']} 的上级节点不存在")
        if manager_id == e["id"]:
            raise HTTPException(400, f"{e['name']} 不能成为自己的上级")
        seen, cursor = set(), e["id"]
        while cursor:
            if cursor in seen:
                raise HTTPException(400, "组织架构存在循环汇报关系")
            seen.add(cursor)
            cursor = by_id.get(cursor, {}).get("manager_id")
    with BANK_LOCK:
        BANK_DIR.mkdir(parents=True, exist_ok=True)
        (BANK_DIR / "orgchart.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "count": len(entries)}


@router.post("/api/orgchart/files")
async def upload_org_file(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ORG_FILE_EXT:
        raise HTTPException(400, f"不支持的文件类型: {ext}")
    stem = _safe(Path(file.filename).stem) or "file"
    d = ORG_FILES / stem
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("page-*.*"):
        p.unlink()
    orig = d / f"original{ext}"
    async with aiofiles.open(orig, "wb") as out:
        while chunk := await file.read(1 << 20):
            await out.write(chunk)
    if ext == ".pdf":
        rc = subprocess.run(["pdftoppm", "-png", "-r", "110", str(orig), str(d / "page")],
                            capture_output=True).returncode
        pages = len(list(d.glob("page-*.png")))
        if rc != 0 or pages == 0:
            raise HTTPException(500, "PDF 渲染失败")
    else:
        orig.replace(d / f"page-1{ext}")
        pages = 1
    return {"ok": True, "name": stem, "pages": pages}


@router.get("/api/orgchart/files")
def list_org_files():
    out = []
    if ORG_FILES.is_dir():
        for d in sorted(ORG_FILES.iterdir(), key=lambda p: p.name):
            if not d.is_dir():
                continue
            orig = next(iter(d.glob("original.*")), None)
            pages = [p for p in d.glob("page-*.*")
                     if re.fullmatch(r"page-\d+\..+", p.name)]
            out.append({"name": d.name, "pages": len(pages),
                        "kind": "pdf" if orig and orig.suffix == ".pdf" else "image"})
    return {"files": out}


@router.get("/api/orgchart/files/{name}/page/{n}")
def org_file_page(name: str, n: int):
    d = (ORG_FILES / _safe(name)).resolve()
    if not d.is_dir() or not d.is_relative_to(ORG_FILES.resolve()):
        raise HTTPException(404, "文件不存在")
    for p in d.glob("page-*.*"):
        m = re.fullmatch(r"page-(\d+)\..+", p.name)
        if m and int(m.group(1)) == n:
            return FileResponse(p)
    raise HTTPException(404, "没有这一页")


class ExtractReq(BaseModel):
    name: str


@router.post("/api/orgchart/extract")
def extract_orgchart(req: ExtractReq):
    """VL 逐页提取参考文件里的人名/层级 → orgchart_draft.json(人工检查后保存)。"""
    d = (ORG_FILES / _safe(req.name)).resolve()
    if not d.is_dir() or not d.is_relative_to(ORG_FILES.resolve()):
        raise HTTPException(404, "没有这个参考文件")
    if not list(d.glob("page-*.png")):
        raise HTTPException(400, "该文件没有渲染页图")
    cmd = [str(PY), str(ROOT / "bin" / "orgchart_extract.py"), _safe(req.name)]
    job = _new_job("orgchart_extract", meeting=req.name, cmd=cmd)
    resp = dict(job)
    EXEC.submit(_run_pipeline, job)
    return resp


@router.get("/api/orgchart/draft")
def orgchart_draft():
    p = BANK_DIR / "orgchart_draft.json"
    if not p.is_file():
        return {"entries": [], "has_draft": False}
    return {"entries": _normalize_org_entries(_read_json(p, [])), "has_draft": True}
