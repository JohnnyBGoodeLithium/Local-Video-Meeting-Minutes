#!/usr/bin/env python3
"""把一场会议导出为无需服务、无需 LLM 的 .meetingpack.zip。

默认不带音视频；收件人解压后双击 viewer.html 即可阅读、搜索并查看纪要依据。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from markdown_it import MarkdownIt

from meeting_artifact import (
    build_evidence_document,
    load_speaker_profiles,
    markdown_with_evidence_links,
    rag_records,
)


PACK_SCHEMA = "meetingpack/v1"
MD = MarkdownIt("default", {"html": False, "linkify": True})


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(slug: str) -> tuple[str, str]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)$", slug)
    date, raw = (match.group(1), match.group(2)) if match else ("", slug)
    title = re.sub(r"[_-]+", " ", raw).strip()
    return re.sub(r"\s+", " ", title) or "未命名会议", date


def _safe_json_script(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _readme(media_mode: str) -> str:
    media_note = {
        "none": "本包未包含源音视频；时间戳仍可用于回到原系统定位。",
        "audio": "本包包含音频，可在 viewer.html 中按证据时间跳转。",
        "video": "本包包含源视频，可在 viewer.html 中按证据时间跳转。",
    }[media_mode]
    return f"""MeetingPack 离线会议查看包

使用方式
1. 解压整个 zip；不要只从压缩软件预览单个文件。
2. 双击 viewer.html。它不需要安装服务，也不会调用 LLM 或联网。
3. 纪要中的“依据”可打开对应逐字稿与页面证据。

内容
- viewer.html：开箱即用的静态查看器（数据已内嵌，file:// 可用）
- minutes.md：适合继续编辑的可读纪要，含不可见的 mm:evidence 标记
- evidence.json：结论、逐字稿、页面和人员身份的规范化关联
- rag/records.jsonl：可直接送入后续向量/全文索引的记录
- slides/：纪要与页面证据使用的页面图
- manifest.json：格式版本、内容清单、哈希和媒体策略

媒体策略
{media_note}
PPT/VL 页面只能证明“页面展示了什么”，不能单独证明“会议决定了什么”。
"""


_VIEWER_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · MeetingPack</title>
<style>
:root{color-scheme:light;--bg:#f5f6f8;--panel:#fff;--text:#1f2329;--dim:#667085;--line:#e5e7eb;--blue:#315efb;--soft:#eef2ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.62 system-ui,-apple-system,"Segoe UI","PingFang SC",sans-serif}
header{height:58px;padding:0 20px;display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--line);background:#fff;position:sticky;top:0;z-index:5}
header b{font-size:16px}header span{color:var(--dim)}.app{display:grid;grid-template-columns:260px minmax(0,880px) 340px;justify-content:center;min-height:calc(100vh - 58px)}
aside{padding:18px;border-right:1px solid var(--line);background:#fafafa;min-width:0}.main{padding:28px 42px 80px;background:#fff;min-width:0}.drawer{border-left:1px solid var(--line);border-right:0}
input{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:#fff}.label{margin:18px 0 7px;color:var(--dim);font-size:12px;font-weight:650;letter-spacing:.04em}
#nav a,.result{display:block;padding:7px 8px;border-radius:7px;color:var(--text);text-decoration:none;cursor:pointer}.result:hover,#nav a:hover{background:var(--soft);color:var(--blue)}
.result small{display:block;color:var(--dim)}#media{width:100%;margin-top:12px}.main h1{font-size:25px}.main h2{margin-top:36px;padding-bottom:7px;border-bottom:1px solid var(--line)}.main h3{margin-top:28px}
.main img{max-width:100%;border:1px solid var(--line);border-radius:8px}.main table{border-collapse:collapse;max-width:100%}.main th,.main td{border:1px solid var(--line);padding:6px 9px}
.main a[href^="#mm-"]{font-size:11px;color:var(--dim);text-decoration:none;border:1px solid var(--line);border-radius:10px;padding:1px 6px;white-space:nowrap}.main a[href^="#mm-"]:hover{color:var(--blue);border-color:var(--blue)}
.empty{color:var(--dim)}.claim{padding:11px;border-radius:9px;background:var(--soft);margin-bottom:12px}.tags{display:flex;gap:5px;flex-wrap:wrap;margin:7px 0}.tag{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:10px;padding:1px 6px;background:#fff}
.source{margin:10px 0;padding:10px;border:1px solid var(--line);border-radius:8px;background:#fff}.source-head{display:flex;justify-content:space-between;gap:8px;color:var(--dim);font-size:12px}.seek{border:0;background:none;color:var(--blue);cursor:pointer;padding:0}.source img{max-width:100%;margin-top:8px;border-radius:6px}.close{display:none}
@media(max-width:1100px){.app{grid-template-columns:220px minmax(0,1fr)}.drawer{position:fixed;right:0;top:58px;bottom:0;width:min(360px,92vw);z-index:4;box-shadow:-8px 0 24px #0002;transform:translateX(105%);transition:.18s}.drawer.open{transform:none}.close{display:block;float:right}}
@media(max-width:720px){header span{display:none}.app{display:block}.left{border-right:0;border-bottom:1px solid var(--line)}.main{padding:22px 18px}.left #nav{display:none}}
</style></head><body>
<header><b id="title"></b><span id="meta"></span></header>
<div class="app"><aside class="left">
<input id="search" type="search" placeholder="搜索纪要、逐字稿、页面…"><div id="results"></div>
<div id="media-box"></div><div class="label">纪要目录</div><nav id="nav"></nav>
</aside><article class="main" id="minutes"></article>
<aside class="drawer" id="drawer"><button class="close" id="close">关闭</button><div class="label">证据</div><div id="evidence"><p class="empty">点击纪要旁的“依据”，查看逐字稿与页面来源。</p></div></aside></div>
<script id="meeting-data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('meeting-data').textContent),ev=data.evidence;
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>{n=Math.max(0,Math.floor(n||0));let h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return(h?h+':':'')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')};
$('#title').textContent=data.title;$('#meta').textContent=[data.date,data.duration?fmt(data.duration):'',data.media_path?'含媒体':'无媒体'].filter(Boolean).join(' · ');$('#minutes').innerHTML=data.minutes_html;
if(data.media_path){$('#media-box').innerHTML=`<div class="label">回放</div><${data.media_kind} id="media" controls preload="metadata" src="${esc(data.media_path)}"></${data.media_kind}>`}
const media=()=>$('#media');
function seek(t){if(!media())return;media().currentTime=t||0;media().play().catch(()=>{})}
const turns=new Map(ev.sources.transcript.map(x=>[x.id,x])),pages=new Map(ev.sources.pages.map(x=>[x.id,x])),claims=new Map(ev.claims.map(x=>[x.id,x]));
function showClaim(id){const c=claims.get(id);if(!c)return;let h=`<div class="claim"><b>${esc(c.text)}</b><div class="tags"><span class="tag">${esc(c.kind)}</span><span class="tag">${esc(c.status)}</span><span class="tag">置信度 ${esc(c.confidence)}</span></div></div>`;
 for(const tid of c.turn_ids){const t=turns.get(tid);if(!t)continue;h+=`<div class="source"><div class="source-head"><b>${esc(tid)} · ${esc(t.speaker)}</b><button class="seek" data-time="${t.start}">${fmt(t.start)}</button></div><div>${esc(t.text)}</div></div>`}
 for(const pid of c.page_ids){const p=pages.get(pid);if(!p)continue;h+=`<div class="source"><div class="source-head"><b>${esc(pid)} · 第${p.number}页</b><button class="seek" data-time="${p.first}">${fmt(p.first)}</button></div>${p.image?`<img src="${esc(p.image)}">`:''}<div>${esc(p.visual_description||'无页面文字说明')}</div></div>`}
 $('#evidence').innerHTML=h;$('#drawer').classList.add('open');document.querySelectorAll('.seek').forEach(b=>b.onclick=()=>seek(Number(b.dataset.time)))}
document.querySelectorAll('a[href^="#mm-"]').forEach(a=>a.onclick=e=>{e.preventDefault();showClaim(a.getAttribute('href').slice(4))});$('#close').onclick=()=>$('#drawer').classList.remove('open');
document.querySelectorAll('#minutes h2,#minutes h3').forEach((h,i)=>{h.id='section-'+i;let a=document.createElement('a');a.href='#'+h.id;a.textContent=(h.tagName==='H3'?'　':'')+h.textContent;$('#nav').appendChild(a)});
const records=[...ev.claims.map(x=>({type:'结论',id:x.id,text:x.text,sub:x.section})),...ev.sources.transcript.map(x=>({type:'逐字稿',id:x.id,text:x.text,sub:`${fmt(x.start)} · ${x.speaker}`})),...ev.sources.pages.filter(x=>x.visual_description).map(x=>({type:'页面',id:x.id,text:x.visual_description,sub:`第${x.number}页 · ${x.display_status==='display_only'?'仅展示':'有讨论'}`}))];
$('#search').oninput=e=>{let q=e.target.value.trim().toLowerCase(),box=$('#results');if(!q){box.innerHTML='';return}let hit=records.filter(x=>(x.text+' '+x.sub).toLowerCase().includes(q)).slice(0,30);box.innerHTML='<div class="label">搜索结果</div>'+hit.map(x=>`<div class="result" data-id="${esc(x.id)}"><b>${esc(x.type)}</b> ${esc(x.text.slice(0,100))}<small>${esc(x.sub)}</small></div>`).join('');box.querySelectorAll('.result').forEach(el=>el.onclick=()=>{let id=el.dataset.id;if(id[0]==='C')showClaim(id);else if(id[0]==='T'){let t=turns.get(id);$('#evidence').innerHTML=`<div class="source"><div class="source-head"><b>${esc(id)} · ${esc(t.speaker)}</b><button class="seek" data-time="${t.start}">${fmt(t.start)}</button></div><div>${esc(t.text)}</div></div>`;$('#drawer').classList.add('open');document.querySelector('.seek').onclick=()=>seek(t.start)}else{let p=pages.get(id);$('#evidence').innerHTML=`<div class="source"><b>${esc(id)} · 第${p.number}页</b>${p.image?`<img src="${esc(p.image)}">`:''}<div>${esc(p.visual_description)}</div></div>`;$('#drawer').classList.add('open')}})};
</script></body></html>'''


def _viewer_html(title: str, date: str, minutes_html: str, evidence: dict,
                 media_path: str | None, media_kind: str | None) -> bytes:
    duration = max((float(t.get("end", 0)) for t in evidence["sources"]["transcript"]), default=0)
    payload = {
        "title": title,
        "date": date,
        "duration": duration,
        "minutes_html": minutes_html,
        "evidence": evidence,
        "media_path": media_path,
        "media_kind": media_kind,
    }
    page = _VIEWER_TEMPLATE.replace("__TITLE__", html.escape(title)).replace(
        "__DATA__", _safe_json_script(payload))
    return page.encode("utf-8")


def export_meeting(mdir: Path, out: Path, *, bank_dir: Path | None = None,
                   media_mode: str = "none", title: str | None = None,
                   date: str | None = None) -> dict:
    mdir, out = Path(mdir).resolve(), Path(out).resolve()
    if media_mode not in {"none", "audio", "video"}:
        raise ValueError("media_mode 必须是 none/audio/video")
    minutes_path = next((mdir / n for n in ("minutes.md", "minutes.spk.md") if (mdir / n).is_file()), None)
    if minutes_path is None or not (mdir / "transcript.spk.json").is_file():
        raise ValueError("会议目录需要 minutes.md/minutes.spk.md 与 transcript.spk.json")
    minutes = minutes_path.read_text(encoding="utf-8")
    turns = _read_json(mdir / "transcript.spk.json", [])
    timeline = _read_json(mdir / "slides.json", [])
    pages = [p for p in timeline if p.get("kind", "slide") == "slide" and p.get("page") is not None]
    raw_desc = _read_json(mdir / "page_desc.json", {}).get("desc", {})
    descs = {int(k): str(v) for k, v in raw_desc.items() if str(k).isdigit()}
    profiles = load_speaker_profiles(turns, bank_dir)
    evidence = build_evidence_document(mdir, minutes, turns, pages, descs, profiles,
                                       generation={"export_rebuilt": True})
    evidence_bytes = json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")
    # 会议目录保留同一份 canonical sidecar，Web 与导出/RAG 不各自猜关联。
    (mdir / "minutes.evidence.json").write_bytes(evidence_bytes)

    inferred_title, inferred_date = _identity(mdir.name)
    title, date = title or inferred_title, inferred_date if date is None else date
    linked_markdown = markdown_with_evidence_links(minutes, evidence)
    minutes_html = MD.render(linked_markdown)
    records = rag_records(evidence, minutes)
    rag_bytes = ("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                           for r in records) + "\n").encode("utf-8")

    media_file = None
    media_arc = media_kind = None
    if media_mode == "audio":
        if not (mdir / "audio.wav").is_file():
            raise ValueError("会议没有可用的 audio.wav；可改用 --media none")
        media_file, media_arc, media_kind = mdir / "audio.wav", "media/audio.wav", "audio"
    elif media_mode == "video":
        source = _read_json(mdir / "source.json", {})
        candidate = Path(str(source.get("mp4", ""))) if source.get("mp4") else None
        if candidate and candidate.is_file():
            suffix = candidate.suffix.lower() or ".mp4"
            media_file, media_arc, media_kind = candidate, f"media/source{suffix}", "video"
        else:
            raise ValueError("会议没有可用的源视频；可改用 --media audio 或 none")

    small_files = {
        "viewer.html": _viewer_html(title, date, minutes_html, evidence, media_arc, media_kind),
        "minutes.md": minutes.encode("utf-8"),
        "evidence.json": evidence_bytes,
        "rag/records.jsonl": rag_bytes,
        "README.txt": _readme(media_mode).encode("utf-8"),
    }
    disk_files: list[tuple[Path, str]] = []
    for page in pages:
        if not page.get("image"):
            continue
        image = (mdir / "slides" / str(page["image"])).resolve()
        if image.is_file() and image.is_relative_to((mdir / "slides").resolve()):
            disk_files.append((image, f"slides/{image.name}"))
    if media_file and media_arc:
        disk_files.append((media_file, media_arc))

    manifest_files = []
    for arcname, data in small_files.items():
        manifest_files.append({"path": arcname, "bytes": len(data), "sha256": _sha256_bytes(data)})
    for path, arcname in disk_files:
        manifest_files.append({"path": arcname, "bytes": path.stat().st_size,
                               "sha256": _sha256_file(path)})
    manifest = {
        "schema": PACK_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "meeting_id": evidence["meeting_id"],
        "artifact_id": evidence["artifact_id"],
        "title": title,
        "date": date,
        "source_slug": mdir.name,
        "media": {"mode": media_mode, "included": bool(media_file), "path": media_arc},
        "counts": {"turns": len(turns), "pages": len(pages), "claims": len(evidence["claims"]),
                   "rag_records": len(records)},
        "files": sorted(manifest_files, key=lambda x: x["path"]),
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as archive:
        for arcname, data in small_files.items():
            archive.writestr(arcname, data, compress_type=zipfile.ZIP_DEFLATED)
        for path, arcname in disk_files:
            mime = mimetypes.guess_type(path.name)[0] or ""
            compression = zipfile.ZIP_STORED if mime.startswith(("video/", "audio/", "image/")) else zipfile.ZIP_DEFLATED
            archive.write(path, arcname, compress_type=compression)
        archive.writestr("manifest.json", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
    return {"path": str(out), "bytes": out.stat().st_size, **manifest["counts"],
            "media": manifest["media"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="导出无需服务/LLM 的 .meetingpack.zip")
    parser.add_argument("meeting_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--bank-dir", type=Path, default=Path(__file__).resolve().parent.parent / "speaker_bank")
    parser.add_argument("--media", choices=("none", "audio", "video"), default="none",
                        help="默认 none；分享阅读/RAG 不需要源视频")
    args = parser.parse_args()
    out = args.out or Path.cwd() / f"{args.meeting_dir.name}.meetingpack.zip"
    try:
        stats = export_meeting(args.meeting_dir, out, bank_dir=args.bank_dir, media_mode=args.media)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"导出失败: {exc}", file=sys.stderr)
        return 1
    print(f"[meta] MeetingPack: {stats['path']} | {stats['bytes']} bytes | "
          f"claims={stats['claims']} rag={stats['rag_records']} media={stats['media']['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
