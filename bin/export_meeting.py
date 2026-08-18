#!/usr/bin/env python3
"""把一场会议导出为无需服务、无需 LLM 的 .meetingpack.zip。

默认不带音视频；收件人解压后双击 viewer.html 即可阅读、搜索并查看纪要依据。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from markdown_it import MarkdownIt
from PIL import Image

from meeting_artifact import (
    build_evidence_document,
    load_speaker_profiles,
    markdown_with_evidence_links,
    minutes_reading_markdown,
    rag_records,
    speaker_navigation,
    strip_visible_evidence_ids,
)
from meeting_views import evidence_integrity
from meeting_structure import clean_model_text, visual_title
import meeting_topic_map


PACK_SCHEMA = "meetingpack/v5"
MD = MarkdownIt("default", {"html": False, "linkify": True})
VIEWER_TEMPLATE_PATH = Path(__file__).with_name("meetingpack_viewer.html")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _media_source(mdir: Path, kind: str) -> Path | None:
    local_pattern = "source_video.*" if kind == "video" else "source_audio.*"
    if kind == "audio" and (mdir / "audio.wav").is_file():
        return mdir / "audio.wav"
    local = next((p for p in sorted(mdir.glob(local_pattern)) if p.is_file()), None)
    if local:
        return local
    source = _read_json(mdir / "source.json", {})
    keys = (("mp4", "video", "original_mp4") if kind == "video"
            else ("audio", "wav", "original_audio"))
    for key in keys:
        if not source.get(key):
            continue
        candidate = Path(str(source[key]))
        candidate = candidate if candidate.is_absolute() else mdir / candidate
        if candidate.is_file():
            return candidate.resolve()
    if kind == "audio":
        # 视频母版里的音轨可直接生成分享版音频，不必长期保留 PCM WAV。
        video = next((p for p in sorted(mdir.glob("source_video.*")) if p.is_file()), None)
        if video:
            return video
        for key in ("mp4", "video", "original_mp4"):
            if not source.get(key):
                continue
            candidate = Path(str(source[key]))
            candidate = candidate if candidate.is_absolute() else mdir / candidate
            if candidate.is_file():
                return candidate.resolve()
    return None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _viewer_slide_assets(mdir: Path, pages: list[dict], evidence: dict) -> dict[str, bytes]:
    """生成仅供阅读的 WebP：长边上限 1600px、quality 80。
    尺寸按 Viewer 放大预览窗（min(1500px,96vw) × min(940px,94vh)，支持 125–300% 缩放）
    设计，不按小舞台缩略图；不改会议目录中的原截图。"""
    source_by_number = {int(page["page"]): page for page in pages if page.get("page") is not None}
    assets: dict[str, bytes] = {}
    for item in evidence.get("sources", {}).get("pages", []):
        source = source_by_number.get(int(item.get("number", 0)))
        image_name = str((source or {}).get("image") or "")
        image = (mdir / "slides" / image_name).resolve()
        if not image_name or not image.is_file() or not image.is_relative_to((mdir / "slides").resolve()):
            item["image"] = None
            continue
        arcname = f"assets/slides/{item['id'].lower()}.webp"
        try:
            with Image.open(image) as opened:
                frame = opened.convert("RGB")
                frame.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                frame.save(output, "WEBP", quality=80, method=4)
                assets[arcname] = output.getvalue()
                item["image"] = arcname
        except (OSError, ValueError):
            arcname = f"assets/slides/{item['id'].lower()}{image.suffix.lower() or '.jpg'}"
            assets[arcname] = image.read_bytes()
            item["image"] = arcname
    return assets


def _optimized_media(source: Path, kind: str, temp_dir: Path) -> tuple[Path, str, str]:
    """生成分享版媒体：语音 AAC 40k；视频 720p/10fps H.264 + AAC。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("导出压缩媒体需要本机 ffmpeg")
    if kind == "audio":
        target, arcname, media_kind = temp_dir / "audio.m4a", "assets/media/audio.m4a", "audio"
        codec_args = ["-vn", "-c:a", "aac", "-ac", "1", "-ar", "16000", "-b:a", "40k"]
    else:
        target, arcname, media_kind = temp_dir / "video.mp4", "assets/media/video.mp4", "video"
        codec_args = [
            "-vf", "scale='min(1280,iw)':-2:force_original_aspect_ratio=decrease,fps=10",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "1", "-ar", "16000", "-b:a", "40k",
        ]
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(source), *codec_args, "-movflags", "+faststart", str(target)]
    completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               text=True, timeout=7200)
    if completed.returncode != 0 or not target.is_file():
        detail = (completed.stderr or "媒体压缩失败").strip().splitlines()[-1]
        raise ValueError(f"媒体压缩失败：{detail[:240]}")
    return target, arcname, media_kind


def _identity(slug: str) -> tuple[str, str]:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)$", slug)
    date, raw = (match.group(1), match.group(2)) if match else ("", slug)
    title = re.sub(r"[_-]+", " ", raw).strip()
    return re.sub(r"\s+", " ", title) or "未命名会议", date


def _safe_json_script(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _document_language(text: str) -> str:
    visible = re.sub(r"<!--\s*mm:evidence\s+[^<>]*?\s*-->", "", text)
    cjk = len(re.findall(r"[\u3400-\u9fff]", visible))
    latin = len(re.findall(r"[A-Za-z]", visible))
    if cjk >= max(20, latin * 0.35) or (cjk and not latin):
        return "zh-CN"
    return "en"


def _minutes_languages(mdir: Path, minutes_path: Path, reading_minutes: str,
                       evidence: dict) -> tuple[str, dict[str, dict], dict[str, bytes]]:
    """收集已完成且仍绑定当前 canonical 纪要的译文；导出过程绝不调用模型。"""
    source_language = _document_language(reading_minutes)
    languages = {
        source_language: {
            "html": MD.render(markdown_with_evidence_links(
                reading_minutes, evidence, label="Evidence" if source_language == "en" else "依据")),
            "is_source": True,
        }
    }
    assets = {f"assets/minutes.{source_language}.md": reading_minutes.encode("utf-8")}
    source_revision = hashlib.sha256(minutes_path.read_bytes()).hexdigest()[:16]
    for target in ("zh-CN", "en"):
        sidecar = _read_json(mdir / f"minutes.translation.{target}.json", {})
        markdown = strip_visible_evidence_ids(str(sidecar.get("markdown") or ""))
        if (sidecar.get("schema") != "meeting-minutes-translation/v1"
                or sidecar.get("status") != "complete"
                or sidecar.get("source_revision") != source_revision or not markdown.strip()):
            continue
        languages[target] = {
            "html": MD.render(markdown_with_evidence_links(
                markdown, evidence, label="Evidence" if target == "en" else "依据")),
            "is_source": False,
        }
        assets[f"assets/minutes.{target}.md"] = markdown.encode("utf-8")
    return source_language, languages, assets


def _topic_map_languages(mdir: Path, topic_map: dict) -> tuple[dict[str, dict], dict[str, bytes]]:
    """收集与当前 Topic Map revision 一致的结构化译文；不在导出阶段调用模型。"""
    source_language = _document_language("\n".join(
        [str(topic_map.get("meeting_summary") or "")] +
        [str(value) for topic in topic_map.get("topics", [])
         for value in (topic.get("title", ""), topic.get("summary", ""))] +
        [str(value) for topic in topic_map.get("topics", []) for child in topic.get("children", [])
         for value in (child.get("title", ""), child.get("summary", ""))]))
    languages = {source_language: topic_map}
    assets = {f"assets/topic-map.{source_language}.json":
              json.dumps(topic_map, ensure_ascii=False, indent=2).encode("utf-8")}
    source_path = mdir / "meeting.topic-map.json"
    source_revision = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16] if source_path.is_file() else None
    for target in ("zh-CN", "en"):
        sidecar = _read_json(mdir / f"meeting.topic-map.translation.{target}.json", {})
        translated = sidecar.get("topic_map")
        if (sidecar.get("schema") != "meeting-topic-map-translation/v1"
                or sidecar.get("status") != "complete"
                or sidecar.get("source_revision") != source_revision
                or not isinstance(translated, dict)):
            continue
        languages[target] = translated
        assets[f"assets/topic-map.{target}.json"] = json.dumps(
            translated, ensure_ascii=False, indent=2).encode("utf-8")
    return languages, assets


def _visuals_languages(mdir: Path, pages: list[dict]) -> tuple[dict[str, list[dict]], dict[str, bytes]]:
    """收集屏幕标题/短摘要语言版本；完整 VL 正文始终保留原文。"""
    source_pages = [{"number": int(page.get("number") or 0),
                     "title": str(page.get("title") or ""),
                     "summary": " ".join(str(page.get("visual_description") or "").split())[:240]}
                    for page in pages if int(page.get("number") or 0) > 0]
    source_language = _document_language("\n".join(
        f"{page['title']}\n{page['summary']}" for page in source_pages))
    languages = {source_language: source_pages}
    assets = {f"assets/visuals.{source_language}.json": json.dumps(
        {"pages": source_pages}, ensure_ascii=False, indent=2).encode("utf-8")}
    source_path = mdir / "page_desc.json"
    source_revision = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16] if source_path.is_file() else None
    for target in ("zh-CN", "en"):
        sidecar = _read_json(mdir / f"visuals.translation.{target}.json", {})
        translated = sidecar.get("pages")
        if (sidecar.get("schema") != "meeting-visuals-translation/v1"
                or sidecar.get("status") != "complete"
                or sidecar.get("source_revision") != source_revision
                or not isinstance(translated, list)):
            continue
        languages[target] = translated
        assets[f"assets/visuals.{target}.json"] = json.dumps(
            {"pages": translated}, ensure_ascii=False, indent=2).encode("utf-8")
    return languages, assets


def _readme(media_mode: str) -> str:
    media_note = {
        "none": "本包未包含源音视频；时间戳仍可用于回到原系统定位。",
        "audio": "本包包含 AAC 分享版音频，可在 viewer.html 中按证据时间跳转。",
        "video": "本包包含 720p/10fps 分享版视频，可在 viewer.html 中按证据时间跳转。",
    }[media_mode]
    return f"""MeetingPack 离线会议查看包

使用方式
1. 解压整个 zip；不要只从压缩软件预览单个文件。
2. 双击 viewer.html。它不需要安装服务，也不会调用 LLM 或联网。
3. 纪要中的“依据”可打开对应逐字稿与页面证据。
4. 左侧始终提供完整逐字稿；含媒体的包可点击任意时间码跳转播放。
5. 右上角可切换中文 / EN；导出前已经生成的纪要、会议脉络和屏幕标题/短摘要译文会随包带入，离线端不会调用模型。

内容
- viewer.html：开箱即用的静态查看器（数据已内嵌，file:// 可用）
- README.txt：本说明
- AGENTS.md：给 AI agent 的数据使用指引（把包拖进 agent 会话时会用到）
- assets/：其余全部依赖文件；可整体交给后续程序处理
  - minutes.md、transcript.*：常规纪要与完整逐字稿
  - evidence.json、topic-map.json：证据与整场语义脉络
  - rag/records.jsonl：可直接送入后续向量/全文索引的记录
  - slides/：屏幕内容缩略图；media/：可选音视频
  - manifest.json：格式版本、内容清单、哈希和媒体策略

媒体策略
{media_note}
PPT/VL 页面只能证明“页面展示了什么”，不能单独证明“会议决定了什么”。
"""


_AGENTS_MD = """# MeetingPack — Agent 使用指引

这是一个离线会议数据包。回答问题时**不要只读 `assets/minutes.md`**——那只是给人看的摘要。
按任务选择下面的数据源，事实性回答必须给出可核验依据。

## 文件地图
- `assets/evidence.json` — 结构化结论与待办（claims / actions），每条带 `turn_ids` / `page_ids` 依据。
  核验"会议决定了什么、谁要做什么"先查这里；`status` 确定性：confirmed > working_alignment > proposal > open > informational。
  `sources.transcript` 每条带 `person_id`：**同一个人跨会议、跨数据包恒定**（未绑定声纹为 null，通常是会议机），跨包对人优先用它而不是姓名字符串。
- `assets/transcript.json` — 完整逐字稿：`[{id: T000001, start, end, speaker, voice_id, page_id, text}]`。
  引用发言用 T 编号 + 时间（秒）。
- `assets/topic-map.json` — 整场语义脉络：议题树（topics → children），节点带 `turn_ids` / `ranges` / `page_ids`，
  适合回答"会议讨论了哪些议题、某议题在什么时段"。`low_value` 议题是过渡与杂项，权重放低。
- `assets/rag/records.jsonl` — 检索用记录（每行一条 JSON），可直接建向量/全文索引。
- `assets/minutes.md` — 会议纪要（人读版）；结论/待办末尾的 `mm:evidence` 注释是机器可读依据标记。
- `assets/slides/` — 屏幕页面图，`page_id`（P0001…）对应页面内容；页面只能证明"展示了什么"，不能单独证明"决定了什么"。
- `assets/manifest.json` — 格式版本、会议标题/日期、文件清单与 sha256 校验。
- `viewer.html` / `README.txt` — 人类查看器与说明，agent 无需读取。

## 回答规则
1. 事实性结论必须附依据：T 编号或 P 页码 + 时间戳；查不到依据就说"包内无此信息"，不要编。
2. 纪要与逐字稿冲突时以逐字稿为准。
3. 待办/行动以 evidence.json 中 `kind=action` 且带 turn_ids 的条目为准。
4. 措辞服从 `status`：proposal 只能写成"提议/建议"，open 只能写成"待确认/未决"，不得升格为决定。

## 常见任务菜谱

### 单场深读 / 重新摘要
先读 evidence.json 的 claims（按 kind/status 过滤）和 topic-map.json 的议题树；需要原文口气、数字、语境时按
`turn_ids` 回查 transcript.json。重新组织的摘要必须保留每条结论的状态措辞与依据编号。

### 同系列多场对比（两个及以上包一起给出时）
1. 系列判断：各包 manifest.json 的会议标题与日期；同系列会议标题通常相近，按日期排序。
2. 人对齐：用 evidence.json `sources.transcript` 的 `person_id` 连接两场的发言与结论归属；为 null 的
   按 speaker 显示名处理并注明"未绑定"。
3. 议题对齐：两场 topic-map.json 的一级议题标题做语义匹配，允许一对多。
4. 待办追踪：两场 evidence.json 的 actions 按"负责人 + 事项语义"匹配，回答"上次的待办这次推进了吗"。
5. 输出格式：每条对比结论标注"新增 / 延续 / 翻案 / 消失"，并同时引用两场的会议日期 + C 编号；
   决定被推翻时必须写明新旧两场各自的依据。

### 会后产出（跟进邮件 / 周报段落 / 任务清单）
数据源用 evidence.json 的 actions 和 confirmed / working_alignment claims。数字、日期、人名必须能回链
T/P 依据，产出中的引用附时间码；没有依据支撑的内容不要写进产出。

### 建知识库索引
用 `assets/rag/records.jsonl`：`record_type` 为 claim / transcript / slide / minutes_section。
对 `text` 建索引，其余字段作 metadata；命中 claim 后按 `evidence_ids` 精确回读对应 T/P 来源，
不要再用向量猜来源。`meeting_id` 归组同一会议的不同版本；记录 ID 以 `artifact_id` 为前缀，
逐字稿或纪要变化会产生新版本，旧记录保持不可变。`person_ids` / `speakers` 可用于按人过滤。

### 事实核对
claim → `turn_ids` / `page_ids` → transcript.json / slides/ 逐级回溯。`display_only` 页面只是"展示过"，
不等于被讨论，更不等于被决定。

## 边界
包内不含声纹向量、组织架构、原始媒体母版；无法回答语气核验、身份鉴定类问题。
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
 for(const tid of c.turn_ids){const t=turns.get(tid);if(!t)continue;h+=`<div class="source"><div class="source-head"><b>逐字稿 · ${esc(t.speaker)}</b><button class="seek" data-time="${t.start}">${fmt(t.start)}</button></div><div>${esc(t.text)}</div></div>`}
 for(const pid of c.page_ids){const p=pages.get(pid);if(!p)continue;h+=`<div class="source"><div class="source-head"><b>屏幕内容 · 第${p.number}页</b><button class="seek" data-time="${p.first}">${fmt(p.first)}</button></div>${p.image?`<img src="${esc(p.image)}">`:''}<div>${esc(p.visual_description||'无页面文字说明')}</div></div>`}
 $('#evidence').innerHTML=h;$('#drawer').classList.add('open');document.querySelectorAll('.seek').forEach(b=>b.onclick=()=>seek(Number(b.dataset.time)))}
document.querySelectorAll('a[href^="#mm-"]').forEach(a=>a.onclick=e=>{e.preventDefault();showClaim(a.getAttribute('href').slice(4))});$('#close').onclick=()=>$('#drawer').classList.remove('open');
document.querySelectorAll('#minutes h2,#minutes h3').forEach((h,i)=>{h.id='section-'+i;let a=document.createElement('a');a.href='#'+h.id;a.textContent=(h.tagName==='H3'?'　':'')+h.textContent;$('#nav').appendChild(a)});
const records=[...ev.claims.map(x=>({type:'结论',id:x.id,text:x.text,sub:x.section})),...ev.sources.transcript.map(x=>({type:'逐字稿',id:x.id,text:x.text,sub:`${fmt(x.start)} · ${x.speaker}`})),...ev.sources.pages.filter(x=>x.visual_description).map(x=>({type:'页面',id:x.id,text:x.visual_description,sub:`第${x.number}页 · ${x.display_status==='display_only'?'仅展示':'有讨论'}`}))];
$('#search').oninput=e=>{let q=e.target.value.trim().toLowerCase(),box=$('#results');if(!q){box.innerHTML='';return}let hit=records.filter(x=>(x.text+' '+x.sub).toLowerCase().includes(q)).slice(0,30);box.innerHTML='<div class="label">搜索结果</div>'+hit.map(x=>`<div class="result" data-id="${esc(x.id)}"><b>${esc(x.type)}</b> ${esc(x.text.slice(0,100))}<small>${esc(x.sub)}</small></div>`).join('');box.querySelectorAll('.result').forEach(el=>el.onclick=()=>{let id=el.dataset.id;if(id[0]==='C')showClaim(id);else if(id[0]==='T'){let t=turns.get(id);$('#evidence').innerHTML=`<div class="source"><div class="source-head"><b>逐字稿 · ${esc(t.speaker)}</b><button class="seek" data-time="${t.start}">${fmt(t.start)}</button></div><div>${esc(t.text)}</div></div>`;$('#drawer').classList.add('open');document.querySelector('.seek').onclick=()=>seek(t.start)}else{let p=pages.get(id);$('#evidence').innerHTML=`<div class="source"><b>屏幕内容 · 第${p.number}页</b>${p.image?`<img src="${esc(p.image)}">`:''}<div>${esc(p.visual_description)}</div></div>`;$('#drawer').classList.add('open')}})};
</script></body></html>'''


def _viewer_html(title: str, date: str, minutes_html: str, evidence: dict, integrity: dict,
                 topic_map: dict, media_path: str | None, media_kind: str | None,
                 source_language: str = "zh-CN",
                 minutes_languages: dict[str, dict] | None = None,
                 topic_map_languages: dict[str, dict] | None = None,
                 visuals_languages: dict[str, list[dict]] | None = None,
                 speaker_navigation_rows: list[dict] | None = None) -> bytes:
    duration = max((float(t.get("end", 0)) for t in evidence["sources"]["transcript"]), default=0)
    payload = {
        "title": title,
        "date": date,
        "duration": duration,
        "minutes_html": minutes_html,
        "source_language": source_language,
        "minutes_languages": minutes_languages or {},
        "evidence": evidence,
        "integrity": integrity,
        "topic_map": topic_map,
        "topic_map_languages": topic_map_languages or {},
        "visuals_languages": visuals_languages or {},
        "media_path": media_path,
        "media_kind": media_kind,
        "speaker_navigation": speaker_navigation_rows or [],
    }
    page = VIEWER_TEMPLATE_PATH.read_text(encoding="utf-8").replace(
        "__TITLE__", html.escape(title)).replace(
        "__DATA__", _safe_json_script(payload))
    return page.encode("utf-8")


def _transcript_markdown(turns: list[dict]) -> str:
    def stamp(value: float) -> str:
        seconds = max(0, int(value or 0))
        if seconds >= 3600:
            return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    lines = ["# 完整逐字稿", ""]
    for turn in turns:
        lines.extend([f"[{stamp(float(turn.get('start', 0)))}] **{turn.get('speaker', '未知')}**: "
                      f"{turn.get('text', '')}", ""])
    return "\n".join(lines).rstrip() + "\n"


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
    # 与在线阅读层共用同一清洗边界。不只修标题：导出 evidence、
    # Viewer 详情和 RAG 都不应携带模型 <think>/<analysis> 文本。
    descs = {int(k): clean_model_text(str(v)) for k, v in raw_desc.items()
             if str(k).isdigit()}
    profiles = load_speaker_profiles(turns, bank_dir)
    source_meta = _read_json(mdir / "source.json", {})
    transcript_format = str(source_meta.get("transcript_format") or "").lower()
    if not transcript_format:
        transcript_format = next((suffix for suffix in ("vtt", "docx")
                                  if (mdir / f"source.{suffix}").is_file()), "")
    speaker_navigation_rows = speaker_navigation(turns, profiles, transcript_format)
    evidence = build_evidence_document(mdir, minutes, turns, pages, descs, profiles,
                                       generation={"export_rebuilt": True})
    for page in evidence.get("sources", {}).get("pages", []):
        number = int(page.get("number") or 0)
        page["visual_description"] = clean_model_text(page.get("visual_description") or "")
        page["title"] = visual_title(page["visual_description"], number)
    slide_assets = _viewer_slide_assets(mdir, pages, evidence)
    evidence_bytes = json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")
    integrity = evidence_integrity(evidence)
    topic_state, ready_topic_map = meeting_topic_map.load_current_topic_map(mdir)
    topic_map = (ready_topic_map if topic_state == "ready" else {
        "schema": meeting_topic_map.SCHEMA,
        "state": topic_state,
        "meeting_summary": "",
        "topics": [],
        "stats": {"topics": 0, "children": 0},
    })
    topic_map_bytes = json.dumps(topic_map, ensure_ascii=False, indent=2).encode("utf-8")

    inferred_title, inferred_date = _identity(mdir.name)
    title, date = title or inferred_title, inferred_date if date is None else date
    # RAG 的纪要章节与 Viewer 共用“常规纪要”投影。逐页事实已经分别作为
    # claim / slide 记录进入 RAG，不能再把 canonical 逐页生成过程（包括旧会议
    # 可能残留的 reasoning 标签）重复塞进 minutes_section。
    reading_minutes = clean_model_text(minutes_reading_markdown(
        minutes, evidence, include_topic_section=False))
    linked_markdown = markdown_with_evidence_links(reading_minutes, evidence)
    minutes_html = MD.render(linked_markdown)
    source_language, minutes_languages, minutes_language_assets = _minutes_languages(
        mdir, minutes_path, reading_minutes, evidence)
    topic_map_languages, topic_map_language_assets = _topic_map_languages(mdir, topic_map)
    visuals_languages, visuals_language_assets = _visuals_languages(
        mdir, evidence.get("sources", {}).get("pages", []))
    records = rag_records(evidence, reading_minutes)
    rag_bytes = ("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                           for r in records) + "\n").encode("utf-8")

    with tempfile.TemporaryDirectory(prefix="meetingpack-export-") as temp_name:
        temp_dir = Path(temp_name)
        media_file = None
        media_arc = media_kind = None
        media_source_bytes = 0
        if media_mode == "audio":
            candidate = _media_source(mdir, "audio")
            if candidate is None:
                raise ValueError("会议没有可用音频；可改用 --media none")
            media_source_bytes = candidate.stat().st_size
            media_file, media_arc, media_kind = _optimized_media(candidate, "audio", temp_dir)
        elif media_mode == "video":
            candidate = _media_source(mdir, "video")
            if candidate is None:
                raise ValueError("会议没有可用的源视频；可改用 --media audio 或 none")
            media_source_bytes = candidate.stat().st_size
            media_file, media_arc, media_kind = _optimized_media(candidate, "video", temp_dir)

        small_files = {
            "viewer.html": _viewer_html(title, date, minutes_html, evidence, integrity, topic_map,
                                        media_arc, media_kind, source_language, minutes_languages,
                                        topic_map_languages, visuals_languages,
                                        speaker_navigation_rows),
            "README.txt": _readme(media_mode).encode("utf-8"),
            "AGENTS.md": _AGENTS_MD.encode("utf-8"),
            "assets/minutes.md": reading_minutes.encode("utf-8"),
            **minutes_language_assets,
            **topic_map_language_assets,
            **visuals_language_assets,
            "assets/transcript.json": json.dumps(turns, ensure_ascii=False, indent=2).encode("utf-8"),
            "assets/transcript.md": _transcript_markdown(turns).encode("utf-8"),
            "assets/evidence.json": evidence_bytes,
            "assets/topic-map.json": topic_map_bytes,
            "assets/rag/records.jsonl": rag_bytes,
            **slide_assets,
        }
        disk_files = [(media_file, media_arc)] if media_file and media_arc else []
        manifest_files = [
            {"path": arcname, "bytes": len(data), "sha256": _sha256_bytes(data)}
            for arcname, data in small_files.items()
        ]
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
            "media": {"mode": media_mode, "included": bool(media_file), "path": media_arc,
                      "optimized_for_sharing": bool(media_file),
                      "source_bytes": media_source_bytes,
                      "included_bytes": media_file.stat().st_size if media_file else 0},
            "evidence": integrity,
            "topic_map": {"state": topic_map.get("state"),
                          "schema": topic_map.get("schema")},
            "counts": {"turns": len(turns), "pages": len(pages),
                       "claims": len(evidence["claims"]),
                       "topics": len(topic_map.get("topics", [])), "rag_records": len(records)},
            "files": sorted(manifest_files, key=lambda x: x["path"]),
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w") as archive:
            for arcname, data in small_files.items():
                mime = mimetypes.guess_type(arcname)[0] or ""
                compression = zipfile.ZIP_STORED if mime.startswith("image/") else zipfile.ZIP_DEFLATED
                archive.writestr(arcname, data, compress_type=compression)
            for path, arcname in disk_files:
                archive.write(path, arcname, compress_type=zipfile.ZIP_STORED)
            archive.writestr("assets/manifest.json", manifest_bytes,
                             compress_type=zipfile.ZIP_DEFLATED)
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
