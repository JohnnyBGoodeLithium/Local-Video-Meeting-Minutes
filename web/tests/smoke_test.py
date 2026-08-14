#!/usr/bin/env python3
"""meeting-web 冒烟测试。断言只看状态码/数量/元数据，绝不打印内容字段。

通常由 run_smoke.py 在独立临时目录中启动；也可手工提供 MM_TEST_* 环境变量。
"""
import io
import json
import os
import re
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

BASE = os.environ.get("MM_TEST_BASE", "http://127.0.0.1:8899")
TEST_ROOT = Path(os.environ.get("MM_TEST_ROOT", Path(__file__).resolve().parents[2])).resolve()
FAKE_BANK = Path(os.environ.get("MM_TEST_BANK", "/tmp/mm_fake_bank")).resolve()
TEST_JOBS = Path(os.environ.get("MM_TEST_JOBS", TEST_ROOT / "web/jobs")).resolve()
SMOKE = TEST_ROOT / "meetings" / "_smoke"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


def req(method, path, body=None, headers=None, raw=False):
    url = BASE + path
    data = None
    hs = dict(headers or {})
    if isinstance(body, (dict, list)):
        data = json.dumps(body).encode()
        hs["Content-Type"] = "application/json"
    elif isinstance(body, bytes):
        data = body
    r = urllib.request.Request(url, data=data, headers=hs, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            payload = resp.read()
            return resp.status, dict(resp.headers), (payload if raw else json.loads(payload))
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, dict(e.headers), (payload if raw else json.loads(payload))
        except json.JSONDecodeError:
            return e.code, dict(e.headers), payload


def multipart(path, field, filename, content, ctype):
    boundary = "----mmtestboundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return req("POST", path, body=body,
               headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})


def make_pdf() -> bytes:
    """最小合法单页 PDF（正确 xref，poppler 可渲）。"""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs)+1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def poll_job(jid, timeout=60):
    deadline = time.time() + timeout
    j = {}
    while time.time() < deadline:
        s, _, j = req("GET", f"/api/jobs/{jid}")
        if s == 200 and j["status"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(1)
    return j


# 1. 健康检查与会议列表
s, _, health = req("GET", "/api/health")
check("GET /api/health → 200 + dry-run + local assistant",
      s == 200 and health.get("ok") is True and health.get("dry_run") is True
      and health.get("assistant", {}).get("local_only") is True
      and health.get("assistant", {}).get("rag") == "meeting-rag/evidence-hybrid-v1"
      and health.get("assistant", {}).get("retrieval_models", {}).get("mode") == "lexical")
s, headers, page = req("GET", "/", raw=True)
cache_control = next((value for key, value in headers.items()
                      if key.lower() == "cache-control"), "")
check("首页显式展示结论审计和会议脉络入口且禁止缓存旧壳",
      s == 200 and b'quality-entry-btn' in page and b'quality-tab' in page
      and "结论审计".encode() in page and "会议脉络".encode() in page
      and "屏幕内容".encode() in page and "完整纪要".encode() not in page
      and b'data-transcript-mode="comparison"' in page
      and b'id="translation-target"' in page
      and b'id="ui-language"' in page and b'data-ui-language="en"' in page
      and b'id="chapters-tab"' in page and b'id="visuals-tab"' in page
      and b'utility-panel' in page and b'pane-resizer' in page
      and b'export-preflight' in page and b'href="/static/product.html"' in page
      and "no-store" in cache_control)
s, _, app_js = req("GET", "/static/app.js", raw=True)
check("渐进纪要失败时明确等待终稿，不把空纪要误报为草稿可读",
      s == 200 and "语音草稿生成失败".encode() in app_js
      and "草稿失败，生成终稿".encode() in app_js
      and b'(m.has_minutes ?' in app_js
      and "待核实候选".encode() in app_js)
check("在线端以合格会议脉络为第一眼，并共享时间聚焦状态",
      b'requestedViewExplicit' in app_js and b'setTopicFocus' in app_js
      and b'id="focus-summary"' in page
      and b'updateFocusPresentation' in app_js and b'content-stage' in app_js)
check("时间码跳转只滚动内容面板，不带动整页丢失播放器",
      b'function scrollInside' in app_js and b'function scrollTranscriptTurn' in app_js
      and b'scrollIntoView' not in app_js)
check("在线屏幕舞台支持放大、缩放和相邻屏幕键盘导航",
      b'id="screen-preview-mask"' in page and b'openScreenPreview' in app_js
      and b'navigateScreenPreview' in app_js and b'SCREEN_PREVIEW_ZOOMS' in app_js
      and b'20260814p38' in page)
check("英文会议脉络同步本地化时间轴悬浮层与 Focus 辅助文案",
      b'"Meeting overview"' in app_js and b'"Semantic focus"' in app_js
      and b'structured nodes' in app_js and b'occurrences' in app_js
      and b'"Topic screen"' in app_js and b'"View conclusions"' in app_js)
check("结论审计默认聚焦重点结论并保留全部证据入口",
      "重点结论".encode() in app_js and "全部证据".encode() in app_js
      and b'qualityScope' in app_js and b'audit_priority' in app_js)
s, product_headers, product_page = req("GET", "/product", raw=True)
product_cache = next((value for key, value in product_headers.items()
                      if key.lower() == "cache-control"), "")
check("产品介绍页突出人员身份核心、证据核心和技术架构",
      s == 200 and b'Meeting Identity Core' in product_page
      and '人员身份核心'.encode() in product_page
      and '多模态证据核心'.encode() in product_page
      and b'id="architecture"' in product_page
      and b'href="/"' in product_page and "no-store" in product_cache)
s, _, j = req("GET", "/api/meetings")
n = len(j.get("meetings", []))
check("GET /api/meetings → 200 且只见隔离夹具", s == 200 and n == 1, f"会议数={n}")
check("列表含 _smoke", any(m["slug"] == "_smoke" for m in j["meetings"]))
smoke_item = next((m for m in j["meetings"] if m["slug"] == "_smoke"), {})
check("会议列表含可读标题与人数元数据",
      smoke_item.get("title") == "smoke" and smoke_item.get("speaker_count") == 2)

# 2. bundle
s, _, j = req("GET", "/api/meetings/_smoke/bundle")
check("GET bundle → 200", s == 200)
check("bundle 结构数量",
      len(j.get("transcript", [])) == 3 and len(j.get("slides", [])) == 2
      and len(j.get("topics", [])) == 2 and len(j.get("samples", [])) == 2
      and j.get("has_audio") is True and j.get("has_video") is False
      and len(j.get("minutes_html", "")) > 0 and j.get("duration") == 10.0,
      f"turns={len(j.get('transcript', []))} slides={len(j.get('slides', []))} "
      f"topics={len(j.get('topics', []))} samples={len(j.get('samples', []))}")
check("bundle 带逐字稿/纪要 revision",
      bool(j.get("transcript_revision")) and bool(j.get("minutes_revision")))
check("bundle 含可读会议身份元数据",
      j.get("title") == "smoke" and j.get("speaker_count") == 2)
check("bundle 提供逻辑页、连续视觉片段和语义章节三层结构",
      j.get("structure", {}).get("schema") == "meeting-structure/v2"
      and len(j.get("structure", {}).get("segments", [])) == 2
      and len(j.get("structure", {}).get("chapters", [])) == 1
      and len(j.get("structure", {}).get("visuals", [])) == 2
      and all(visual.get("information_value") in {"high", "medium", "low"}
              for visual in j.get("structure", {}).get("visuals", []))
      and all(visual.get("description_html")
              for visual in j.get("structure", {}).get("visuals", [])))
check("bundle 提供整场语义 Topic Map，而不是按截图生成节点",
      j.get("topic_map", {}).get("schema") == "meeting-topic-map/v2"
      and j.get("topic_map", {}).get("state") == "ready"
      and len(j.get("topic_map", {}).get("topics", [])) == 3
      and all(len(topic.get("children", [])) == 2
              for topic in j.get("topic_map", {}).get("topics", []))
      and len(j.get("topic_map", {}).get("topics", []))
      != len(j.get("structure", {}).get("visuals", [])))
check("bundle 常规纪要不再重复铺开逐页详情",
      "分页详情" not in j.get("minutes_html", "")
      and "假页面一" not in j.get("minutes_html", "")
      and "总体摘要" in j.get("minutes_html", ""))
check("bundle 提供可点击纪要依据且 HTML 不泄露机器标记",
      len(j.get("evidence", {}).get("claims", [])) == 3
      and j.get("document_state") == "ready"
      and j.get("evidence", {}).get("state") == "ready"
      and isinstance(j.get("evidence", {}).get("action_candidates"), list)
      and '#mm-C00001' in j.get("minutes_html", "")
      and 'mm:evidence' not in j.get("minutes_html", ""))

# 2a. 存储分层：母版/阅读资产受保护，智能清理仅移除可再生工作帧
s, _, storage_before = req("GET", "/api/meetings/_smoke/storage")
cache_ids = {group.get("id") for group in storage_before.get("cache", {}).get("groups", [])}
check("存储接口区分受保护母版、阅读资产和可再生缓存",
      s == 200 and storage_before.get("schema") == "meeting-storage/v1"
      and storage_before.get("original", {}).get("protected") is True
      and storage_before.get("reading", {}).get("bytes", 0) > 0
      and "vl_frames" in cache_ids)
s, _, cleaned = req("POST", "/api/meetings/_smoke/storage/cleanup")
check("智能清理只删除白名单缓存并保留会议核心文件",
      s == 200 and cleaned.get("reclaimed_logical_bytes", 0) > 0
      and not (SMOKE / "slides" / "full_01.jpg").exists()
      and (SMOKE / "audio.wav").is_file()
      and (SMOKE / "minutes.md").is_file()
      and (SMOKE / "meeting.topic-map.json").is_file())

# 2b. 本地结论审计：逐条标签、乐观锁、隐私最小化与汇总
minutes_before_quality = (SMOKE / "minutes.md").read_text()
s, _, quality = req("GET", "/api/meetings/_smoke/quality")
quality_claims = quality.get("claims", [])
check("结论审计初始为 3 条待判断",
      s == 200 and quality.get("evidence_state") == "ready"
      and quality.get("summary", {}).get("total") == 3
      and quality.get("summary", {}).get("pending") == 3
      and quality.get("priority_summary", {}).get("total") == 0
      and quality.get("labels", [])[0].get("label") == "结论与依据一致")
first = quality_claims[0] if quality_claims else {}
s, _, quality = req("PUT", "/api/meetings/_smoke/quality/claims/C00001", {
    "label": "correct", "note": "合成验收说明",
    "claim_fingerprint": first.get("fingerprint"),
})
check("结论审计记录可信项并更新进度",
      s == 200 and quality.get("summary", {}).get("reviewed") == 1
      and quality.get("summary", {}).get("passed") == 1)
s, _, _ = req("PUT", "/api/meetings/_smoke/quality/claims/C00002", {
    "label": "wrong_evidence", "note": "",
    "claim_fingerprint": "stale-fingerprint",
})
check("结论审计拒绝过期结论指纹", s == 409)
second = next((claim for claim in quality_claims if claim.get("id") == "C00002"), {})
s, _, quality = req("PUT", "/api/meetings/_smoke/quality/claims/C00002", {
    "label": "wrong_evidence", "note": "合成问题说明",
    "claim_fingerprint": second.get("fingerprint"),
})
evaluation_path = TEST_ROOT / "evaluations" / "_smoke.json"
evaluation_disk = json.loads(evaluation_path.read_text()) if evaluation_path.is_file() else {}
events = evaluation_disk.get("events", [])
check("结论审计记录问题分类且不改正式纪要",
      s == 200 and quality.get("summary", {}).get("issues") == 1
      and (SMOKE / "minutes.md").read_text() == minutes_before_quality)
check("本地评测文件只存指纹/标签，不复制 claim 正文",
      evaluation_disk.get("schema") == "meeting-minutes-evaluation/v1"
      and len(events) == 2 and all("text" not in event for event in events))

# 2c. 渐进式纪要：语音草稿可读/追问，但暂停审计、修改、脉络和导出。
generation_path = SMOKE / "meeting.generation.json"
generation_path.write_text(json.dumps({
    "schema": "meeting-generation/v1", "phase": "visual_enrichment",
    "voice_draft_revision": "synthetic-draft",
}), encoding="utf-8")
try:
    s, _, draft_bundle = req("GET", "/api/meetings/_smoke/bundle")
    sq, _, draft_quality = req("GET", "/api/meetings/_smoke/quality")
    se, _, _ = req("PUT", "/api/meetings/_smoke/quality/claims/C00001", {
        "label": "correct", "note": "", "claim_fingerprint": first.get("fingerprint"),
    })
    st, _, _ = req("POST", "/api/meetings/_smoke/topic-map")
    sx, _, _ = req("GET", "/api/meetings/_smoke/export?media=none")
    sp, _, draft_preflight = req("GET", "/api/meetings/_smoke/export/preflight")
    check("语音草稿通过 bundle 可读且暴露明确阶段",
          s == 200 and draft_bundle.get("document_state") == "draft"
          and draft_bundle.get("generation", {}).get("phase") == "visual_enrichment")
    check("草稿阶段暂停结论审计、Topic Map 和导出",
          sq == 200 and draft_quality.get("evidence_state") == "draft"
          and draft_quality.get("summary", {}).get("total") == 0
          and se == 409 and st == 409 and sx == 409
          and sp == 200 and draft_preflight.get("document_state") == "draft")
    s_resume, _, resume_job = req("POST", "/api/meetings/_smoke/regen_minutes")
    resume_done = poll_job(resume_job.get("id")) if resume_job.get("id") else resume_job
    check("服务中断后的视觉补充阶段可复用现有资产续跑",
          s_resume == 200 and resume_job.get("kind") == "regen"
          and resume_done.get("status") == "done")
finally:
    generation_path.unlink(missing_ok=True)

# 2d. 上下文翻译 sidecar：异步生成，不覆盖原始逐字稿
transcript_before_translation = (SMOKE / "transcript.spk.json").read_text()
s, _, translation_before = req(
    "GET", "/api/meetings/_smoke/translations/transcript?target=zh-CN")
check("逐字稿中文翻译初始为 missing", s == 200 and translation_before.get("state") == "missing")
s, _, translation_job = req(
    "POST", "/api/meetings/_smoke/translations/transcript?target=zh-CN&focus=2")
translation_done = poll_job(translation_job.get("id")) if translation_job.get("id") else translation_job
s, _, translated = req(
    "GET", "/api/meetings/_smoke/translations/transcript?target=zh-CN")
translated_turns = translated.get("turns", [])
check("逐字稿中文翻译后台作业完成并覆盖全部 T ID",
      translation_job.get("focus_turn_indexes") == [2]
      and translation_done.get("status") == "done" and s == 200
      and translated.get("state") == "ready" and len(translated_turns) == 3
      and [item.get("id") for item in translated_turns] == ["T000001", "T000002", "T000003"])
check("翻译识别英文/中英混合轮次且不覆盖原文",
      translated_turns[1].get("source_language") == "en"
      and translated_turns[2].get("source_language") == "mixed"
      and (SMOKE / "transcript.spk.json").read_text() == transcript_before_translation)
translation_disk = json.loads((SMOKE / "transcript.translation.zh-CN.json").read_text())
check("翻译 sidecar 绑定逐字稿与会议语境 revision",
      translation_disk.get("schema") == "meeting-transcript-translation/v1"
      and translation_disk.get("source_revision")
      and translation_disk.get("context_revision"))
s, _, english_before = req(
    "GET", "/api/meetings/_smoke/translations/transcript?target=en")
s2, _, english_job = req(
    "POST", "/api/meetings/_smoke/translations/transcript?target=en")
english_done = poll_job(english_job.get("id")) if english_job.get("id") else english_job
s3, _, english = req(
    "GET", "/api/meetings/_smoke/translations/transcript?target=en")
check("逐字稿支持独立的英语目标语言 sidecar",
      s == 200 and english_before.get("state") == "missing"
      and s2 == 200 and english_done.get("status") == "done" and s3 == 200
      and english.get("state") == "ready" and english.get("target_language") == "en"
      and len(english.get("turns", [])) == 3
      and (SMOKE / "transcript.translation.en.json").is_file())

# 2e. 阅读语言：界面语言与 revision-bound 纪要译文一起切换。
minutes_before_translation = (SMOKE / "minutes.md").read_text()
s, _, minutes_en_before = req("GET", "/api/meetings/_smoke/translations/minutes?target=en")
s2, _, minutes_en_job = req("POST", "/api/meetings/_smoke/translations/minutes?target=en")
minutes_en_done = poll_job(minutes_en_job.get("id")) if minutes_en_job.get("id") else minutes_en_job
s3, _, minutes_en = req("GET", "/api/meetings/_smoke/translations/minutes?target=en")
check("纪要英语译文独立生成、保留依据链接且不覆盖 canonical 纪要",
      s == 200 and minutes_en_before.get("state") == "missing"
      and s2 == 200 and minutes_en_done.get("status") == "done" and s3 == 200
      and minutes_en.get("state") == "ready" and "Meeting Minutes" in minutes_en.get("html", "")
      and "#mm-C00001" in minutes_en.get("html", "")
      and (SMOKE / "minutes.md").read_text() == minutes_before_translation
      and (SMOKE / "minutes.translation.en.json").is_file())
s, _, minutes_zh = req("GET", "/api/meetings/_smoke/translations/minutes?target=zh-CN")
check("纪要目标语言与原文一致时即时返回且不制造冗余 sidecar",
      s == 200 and minutes_zh.get("state") == "ready" and minutes_zh.get("is_source") is True
      and not (SMOKE / "minutes.translation.zh-CN.json").exists())

s, _, topic_en_before = req("GET", "/api/meetings/_smoke/translations/topic-map?target=en")
s2, _, topic_en_job = req("POST", "/api/meetings/_smoke/translations/topic-map?target=en")
topic_en_done = poll_job(topic_en_job.get("id")) if topic_en_job.get("id") else topic_en_job
s3, _, topic_en = req("GET", "/api/meetings/_smoke/translations/topic-map?target=en")
canonical_topic = json.loads((SMOKE / "meeting.topic-map.json").read_text())
translated_topic = topic_en.get("topic_map") or {}
check("会议脉络英语译文保持节点、时间与证据 linkage，不覆盖 canonical",
      s == 200 and topic_en_before.get("state") == "missing"
      and s2 == 200 and topic_en_done.get("status") == "done" and s3 == 200
      and topic_en.get("state") == "ready"
      and translated_topic.get("topics", [{}])[0].get("title", "").startswith("English:")
      and translated_topic.get("topics", [{}])[0].get("id") == canonical_topic["topics"][0]["id"]
      and translated_topic.get("topics", [{}])[0].get("ranges") == canonical_topic["topics"][0]["ranges"]
      and translated_topic.get("topics", [{}])[0].get("claim_ids") == canonical_topic["topics"][0]["claim_ids"]
      and (SMOKE / "meeting.topic-map.translation.en.json").is_file())

# 2f. MeetingPack 默认不带媒体，解压后 viewer.html 可直接 file:// 打开
evidence_before_export = (SMOKE / "minutes.evidence.json").read_bytes()
s, _, preflight = req("GET", "/api/meetings/_smoke/export/preflight")
check("导出预检只返回内容状态、数量、媒体和预计体积",
      s == 200 and preflight.get("evidence", {}).get("state") == "ready"
      and preflight.get("evidence", {}).get("claims") == 3
      and preflight.get("content", {}).get("transcript_turns") == 3
      and preflight.get("media", {}).get("audio", {}).get("available") is True
      and preflight.get("media", {}).get("video", {}).get("available") is False
      and preflight.get("media", {}).get("audio", {}).get("format") == "AAC 40kbps"
      and preflight.get("estimated_bytes", {}).get("audio", 0)
      > preflight.get("estimated_bytes", {}).get("none", 0)
      and "transcript" not in preflight and "path" not in str(preflight))
s, h, pack_bytes = req("GET", "/api/meetings/_smoke/export?media=none", raw=True)
pack = zipfile.ZipFile(io.BytesIO(pack_bytes)) if s == 200 else None
names = set(pack.namelist()) if pack else set()
required = {"viewer.html", "README.txt", "assets/minutes.md", "assets/transcript.json",
            "assets/transcript.md", "assets/evidence.json",
            "assets/topic-map.json", "assets/rag/records.jsonl", "assets/manifest.json",
            "assets/slides/p0001.webp", "assets/slides/p0002.webp"}
check("导出 MeetingPack → 标准文件齐全且默认无音视频",
      s == 200 and required <= names and not any(n.startswith("assets/media/") for n in names)
      and "assets/views.json" not in names
      and {name.split("/", 1)[0] for name in names} == {"viewer.html", "README.txt", "assets"})
if pack:
    manifest = json.loads(pack.read("assets/manifest.json"))
    evidence = json.loads(pack.read("assets/evidence.json"))
    exported_topic_map = json.loads(pack.read("assets/topic-map.json"))
    viewer = pack.read("viewer.html").decode("utf-8")
    rag = [json.loads(line) for line in pack.read("assets/rag/records.jsonl").decode("utf-8").splitlines()]
else:
    manifest, evidence, exported_topic_map, viewer, rag = {}, {}, {}, "", []
check("MeetingPack v5 manifest/evidence/RAG/Topic Map 共享稳定 linkage",
      manifest.get("schema") == "meetingpack/v5"
      and evidence.get("schema") == "meeting-minutes-evidence/v1"
      and evidence.get("claims", [{}])[0].get("turn_ids") == ["T000001", "T000002"]
      and any(r.get("record_type") == "claim" and r.get("evidence_ids") for r in rag)
      and manifest.get("evidence", {}).get("state") == "ready"
      and exported_topic_map.get("state") == "ready"
      and len(exported_topic_map.get("topics", [])) == 3)
check("MeetingPack 分享纪要采用常规阅读版，逐页事实仍在 evidence/RAG",
      "分页详情" not in (pack.read("assets/minutes.md").decode("utf-8") if pack else "")
      and any(record.get("record_type") == "slide" for record in rag))
check("viewer 为无外链、自包含且可浏览逐字稿/媒体/脉络/屏幕的静态页面",
      'id="meeting-data"' in viewer and "fetch(" not in viewer
      and "http://" not in viewer and "https://" not in viewer
      and 'id="transcript"' in viewer and 'id="scrub"' in viewer
      and "会议脉络" in viewer and "屏幕内容" in viewer
      and "candidatePanel" in viewer and 'id="language-switch"' in viewer
      and "minutes_languages" in viewer)
check("MeetingPack 携带已生成双语纪要并可离线切换",
      "assets/minutes.en.md" in names and "assets/minutes.zh-CN.md" in names
      and "Meeting Minutes" in viewer and "data-language=\"en\"" in viewer)
check("MeetingPack 携带结构化会议脉络译文并同步本地化脉络 UI",
      "assets/topic-map.en.json" in names and "assets/topic-map.zh-CN.json" in names
      and "topic_map_languages" in viewer and "Related conclusions and evidence" in viewer
      and "English:" in viewer)
check("Viewer 只保留三个阅读入口，合格会议脉络默认且层级最高",
      "管理层 ·" not in viewer and "执行层 ·" not in viewer
      and "{id:'topic_map',title:u('会议脉络','Meeting map'),primary:ready}" in viewer
      and "function topicMapReady" in viewer and "if(topicReady)renderTopicMap();else renderMinutes();" in viewer)
check("Viewer 无视频也用屏幕舞台联动时间、逐字稿和结论 Focus",
      "media-stage" in viewer and "focusbar" in viewer and "focus-range" in viewer
      and "function focusTime" in viewer and "function focusTopic" in viewer
      and "applyClaimFocus" in viewer and "focus-show-claims" in viewer and "focus-pulse" in viewer)
check("Viewer 屏幕舞台支持离线放大、缩放和相邻屏幕导航",
      'id="screen-preview"' in viewer and "function openScreenPreview" in viewer
      and "function navigatePreview" in viewer and "previewZooms" in viewer)
exported_pages = evidence.get("sources", {}).get("pages", [])
all_export_text = viewer + json.dumps(evidence, ensure_ascii=False) + json.dumps(rag, ensure_ascii=False)
check("导出层清理 VL 推理文本，并使用与在线端一致的屏幕标题",
      "<think" not in all_export_text.lower()
      and "不应进入导出包" not in all_export_text
      and exported_pages and exported_pages[0].get("title") == "合成页面一。页面展示蓝色测试背景，不代表会议结论。")
check("导出是只读操作，不重写会议 canonical evidence",
      (SMOKE / "minutes.evidence.json").read_bytes() == evidence_before_export)
minutes_before_legacy_export = (SMOKE / "minutes.md").read_text()
(SMOKE / "minutes.md").write_text(
    re.sub(r"<!--\s*mm:evidence\s+.*?-->", "", minutes_before_legacy_export))
try:
    sl, _, legacy_pack_bytes = req("GET", "/api/meetings/_smoke/export?media=none", raw=True)
    legacy_pack = zipfile.ZipFile(io.BytesIO(legacy_pack_bytes)) if sl == 200 else None
    legacy_manifest = json.loads(legacy_pack.read("assets/manifest.json")) if legacy_pack else {}
    check("旧纪要无 marker → 仍打包完整逐字稿但显式标记 partial",
          sl == 200 and legacy_manifest.get("evidence", {}).get("state") == "partial"
          and legacy_manifest.get("counts", {}).get("turns") == 3
          and {"assets/transcript.json", "assets/transcript.md"} <= set(legacy_pack.namelist()))
finally:
    (SMOKE / "minutes.md").write_text(minutes_before_legacy_export)
s, _, audio_pack_bytes = req("GET", "/api/meetings/_smoke/export?media=audio", raw=True)
audio_names = set(zipfile.ZipFile(io.BytesIO(audio_pack_bytes)).namelist()) if s == 200 else set()
audio_pack = zipfile.ZipFile(io.BytesIO(audio_pack_bytes)) if s == 200 else None
audio_manifest = json.loads(audio_pack.read("assets/manifest.json")) if audio_pack else {}
check("MeetingPack 音频使用分享版 AAC，且不打包 16k PCM WAV",
      s == 200 and "assets/media/audio.m4a" in audio_names
      and "assets/media/audio.wav" not in audio_names
      and audio_manifest.get("media", {}).get("optimized_for_sharing") is True
      and audio_manifest.get("media", {}).get("included_bytes", 10**9)
      < audio_manifest.get("media", {}).get("source_bytes", 0))

# 3. Range 请求
s, h, b = req("GET", "/api/meetings/_smoke/media/audio",
              headers={"Range": "bytes=0-1023"}, raw=True)
check("media/audio Range → 206", s == 206 and len(b) == 1024,
      f"status={s} bytes={len(b)}")
s2, _, _ = req("GET", "/api/meetings/_smoke/media/audio", raw=True)
check("media/audio 无 Range → 200", s2 == 200)
s3, _, _ = req("GET", "/api/meetings/_smoke/media/video", raw=True)
check("media/video 无源视频 → 404", s3 == 404)

# 3a. 兼容旧录音会议：本地 audio.wav 缺失时回退到 source.json
audio_path = SMOKE / "audio.wav"
legacy_path = SMOKE / "legacy-source.wav"
source_before = (SMOKE / "source.json").read_text()
audio_path.replace(legacy_path)
(SMOKE / "source.json").write_text(json.dumps({"wav": str(legacy_path)}))
try:
    sb, _, legacy_bundle = req("GET", "/api/meetings/_smoke/bundle")
    sa, _, legacy_bytes = req("GET", "/api/meetings/_smoke/media/audio",
                              headers={"Range": "bytes=0-127"}, raw=True)
    check("旧录音缺 audio.wav 时回退 source.json 并支持 Range",
          sb == 200 and legacy_bundle.get("has_audio") is True
          and sa == 206 and len(legacy_bytes) == 128)
finally:
    legacy_path.replace(audio_path)
    (SMOKE / "source.json").write_text(source_before)

# 4. file 白名单（../_smoke/ 归一化后仍在会议目录内 → 200 是正确行为）
s, _, _ = req("GET", "/api/meetings/_smoke/file?path=slides/page1.png", raw=True)
check("file slides/page1.png → 200", s == 200)
s, _, _ = req("GET", "/api/meetings/_smoke/file?path=../_smoke/audio.wav", raw=True)
check("file 迂回 ../_smoke/ 仍解析在会议目录内 → 200", s == 200)
s, _, _ = req("GET", "/api/meetings/_smoke/file?path=../../README.md", raw=True)
check("file 穿越出会议目录 ../../ → 404", s == 404)
s, _, _ = req("GET", "/api/meetings/_smoke/file?path=../../../etc/hostname", raw=True)
check("file 穿越出项目根 → 404", s == 404)

# 5. 试听片段（按名 / 按 voice id）
s, _, _ = req("GET", "/api/meetings/_smoke/samples/Alice.wav", raw=True)
check("samples/Alice.wav → 200", s == 200)
s, _, _ = req("GET", "/api/meetings/_smoke/samples/v_9001.wav", raw=True)
check("samples/v_9001.wav（voice→显示名映射）→ 200", s == 200)
s, _, _ = req("GET", "/api/speakers/v_9001/sample", raw=True)
check("后台声纹试听接口 → 200", s == 200)

# 6. speakers（绑定前）
s, _, j = req("GET", "/api/speakers")
check("GET /api/speakers → 200",
      s == 200 and len(j["persons"]) == 1 and len(j["voices"]) == 2,
      f"persons={len(j.get('persons', []))} voices={len(j.get('voices', []))}")
check("人员 API 提供首选显示名和类型化名称",
      j["persons"][0].get("display_name") == "Alice Example"
      and bool(j["persons"][0].get("names")))
backup_bank = json.loads((FAKE_BANK / "bank.pre-v3.backup.json").read_text())
check("声纹库 v2→v3 迁移保留一次性原始备份", backup_bank.get("schema") == 2)

# 7. bind 候选路径（模糊名 → 409 + 候选，且不写库）
s, _, j = req("POST", "/api/meetings/_smoke/bind", {"voice": "v_9002", "name": "Alicia"})
bank_now = json.loads((FAKE_BANK / "bank.json").read_text())
v2 = next(v for v in bank_now["voices"] if v["id"] == "v_9002")
check("bind 模糊名 → 409 + 候选", s == 409 and bool((j.get("detail") or {}).get("candidates")))
check("409 时库未改", v2["person_id"] is None)
s, _, _ = req("POST", "/api/meetings/_smoke/bind",
              {"voice": "v_9002", "name": "Alice Exampl"})
check("高相似但非精确名称也只返回候选，不强绑", s == 409)

# 8. bind 正常路径：v_9001 → Alice Example（库内精确命中）
s, _, j = req("POST", "/api/meetings/_smoke/bind", {"voice": "v_9001", "name": "Alice Example"})
check("POST bind → 200 ok", s == 200 and j.get("ok") is True and j.get("turns") == 2,
      f"turns={j.get('turns')}")
turns = json.loads((SMOKE / "transcript.spk.json").read_text())
n_renamed = sum(1 for t in turns
                if t.get("voice") == "v_9001" and t["speaker"] == "Alice Example")
n_left = sum(1 for t in turns if t.get("voice") == "v_9001" and t["speaker"] != "Alice Example")
check("v_9001 全部轮次改名", n_renamed == 2 and n_left == 0,
      f"renamed={n_renamed} left={n_left}")
s, _, quality_after_bind = req("GET", "/api/meetings/_smoke/quality")
check("相关逐字稿/身份变化后旧审计自动过期",
      s == 200 and quality_after_bind.get("summary", {}).get("stale") == 2
      and quality_after_bind.get("summary", {}).get("reviewed") == 0)
s, _, translation_after_bind = req(
    "GET", "/api/meetings/_smoke/translations/transcript?target=zh-CN")
check("逐字稿或身份变化后旧译文自动过期",
      s == 200 and translation_after_bind.get("state") == "stale"
      and not translation_after_bind.get("turns"))
md_lines = (SMOKE / "transcript.spk.md").read_text().splitlines()
n_md = sum(1 for l in md_lines if "Alice Example" in l)
check("transcript.spk.md 同步改名（计数）", n_md == 2, f"md行数={n_md}")
bank_now = json.loads((FAKE_BANK / "bank.json").read_text())
v1 = next(v for v in bank_now["voices"] if v["id"] == "v_9001")
check("fake bank v_9001.person_id == p_0001", v1["person_id"] == "p_0001")
n_sample_files = len(list((SMOKE / "samples").glob("*.wav")))
check("试听片段跟随改名", (SMOKE / "samples" / "Alice_Example.wav").is_file()
      and n_sample_files == 2, f"samples={n_sample_files}")

# 8a. 每个人独立首选显示名 + 国际化类型名称，并同步已有逐字稿标签
s, _, identity = req("PUT", "/api/speakers/person/p_0001", {
    "display_name": "Alice E.",
    "names": [
        {"value": "艾丽丝", "type": "chinese", "verified": True},
        {"value": "Ai Li Si", "type": "pinyin", "verified": True},
        {"value": "Alice Example", "type": "english_display", "verified": True},
    ],
})
turns = json.loads((SMOKE / "transcript.spk.json").read_text())
check("更新首选显示名 → 保存类型化名称并同步已有逐字稿",
      s == 200 and identity.get("display_name") == "Alice E."
      and identity.get("turns") == 2
      and sum(t["speaker"] == "Alice E." for t in turns) == 2)
s, _, speakers_after_identity = req("GET", "/api/speakers")
alice_identity = next(p for p in speakers_after_identity["persons"] if p["id"] == "p_0001")
check("中文名/全拼/英文显示名归属同一稳定人员 ID",
      s == 200 and {n["type"] for n in alice_identity["names"]}
      >= {"chinese", "pinyin", "english_display"})
s, _, _ = req("GET", "/api/speakers/v_9001/sample", raw=True)
check("首选显示名变更后后台试听仍可用", s == 200)

# 8b. 未命中姓名显式新建，并同步当前会议
s, _, j = req("POST", "/api/meetings/_smoke/bind",
              {"voice": "v_9002", "name": "Charlie Example", "create": True})
check("bind create=true → 新建并改当前会议", s == 200 and j.get("how") == "新建"
      and j.get("turns") == 1)

# 8c. 声纹按轮拆分：负路径校验在嵌入提取之前，不加载模型、不写库
s, _, bundle_for_split = req("GET", "/api/meetings/_smoke/bundle")
turns_for_split = bundle_for_split.get("transcript", [])
idx_by_voice = {}
for n, t in enumerate(turns_for_split):
    idx_by_voice.setdefault(t.get("voice"), []).append(n)
s, _, _ = req("POST", "/api/meetings/_smoke/split", {"voice": "v_9001", "turns": []})
check("split 空轮次 → 400", s == 400)
s, _, _ = req("POST", "/api/meetings/_smoke/split",
              {"voice": "v_9001",
               "turns": [idx_by_voice["v_9001"][0], idx_by_voice["v_9002"][0]]})
check("split 跨声纹轮次 → 400", s == 400)
s, _, _ = req("POST", "/api/meetings/_smoke/split",
              {"voice": "v_9002", "turns": idx_by_voice["v_9002"]})
check("split 该声纹全部轮次 → 400（整体改派走绑定）", s == 400)
bank_after_split = json.loads((FAKE_BANK / "bank.json").read_text())
check("split 负路径不改写声纹库",
      len(bank_after_split["voices"]) == 2)

# 9. orgchart GET/PUT（假库）
s, _, j = req("GET", "/api/orgchart")
check("GET /api/orgchart → 200", s == 200 and len(j["entries"]) == 2,
      f"entries={len(j.get('entries', []))}")
check("新建人员不会被相似 Org Chart 姓名强行合并，进入待放置区",
      any(p.get("display_name") == "Charlie Example"
          for p in j.get("unplaced_people", [])))
new_entries = j["entries"] + [{"name": "Eve Example", "aliases": ["Eve"], "title": "Eng",
                               "team": "BU1", "leader": "Dave Example", "note": ""}]
s, _, j = req("PUT", "/api/orgchart", {"entries": new_entries})
check("PUT /api/orgchart → 200 count=3", s == 200 and j.get("count") == 3)
s, _, j = req("GET", "/api/orgchart")
check("PUT 后 GET → 3 条", s == 200 and len(j["entries"]) == 3)
check("PUT 已落盘假库", len(json.loads((FAKE_BANK / "orgchart.json").read_text())) == 3)
by_name = {e["name"]: e for e in j["entries"]}
check("Org Chart 使用稳定节点 ID 和 manager_id",
      bool(by_name["Eve Example"].get("id"))
      and by_name["Eve Example"].get("manager_id") == by_name["Dave Example"].get("id"))
cycle_entries = json.loads(json.dumps(j["entries"]))
cycle_by_name = {e["name"]: e for e in cycle_entries}
cycle_by_name["Alice Example"]["manager_id"] = cycle_by_name["Dave Example"]["id"]
cycle_by_name["Dave Example"]["manager_id"] = cycle_by_name["Alice Example"]["id"]
s, _, _ = req("PUT", "/api/orgchart", {"entries": cycle_entries})
check("Org Chart 拒绝循环汇报关系", s == 400)
missing_manager = json.loads(json.dumps(j["entries"]))
missing_manager[0]["manager_id"] = "o_missing"
s, _, _ = req("PUT", "/api/orgchart", {"entries": missing_manager})
check("Org Chart 拒绝不存在的上级节点", s == 400)

# 10. orgchart 参考文件（小 PDF → pdftoppm 页图）
s, _, j = multipart("/api/orgchart/files", "file", "Fake_Org.pdf", make_pdf(), "application/pdf")
check("POST /api/orgchart/files (PDF) → 200", s == 200 and j.get("pages", 0) >= 1,
      f"pages={j.get('pages')}")
s, _, j = req("GET", "/api/orgchart/files")
check("GET /api/orgchart/files → 200 含上传件",
      s == 200 and any(f["name"] == "Fake_Org" and f["pages"] >= 1 for f in j["files"]))
s, h, b = req("GET", "/api/orgchart/files/Fake_Org/page/1", raw=True)
check("GET page/1 → 200 且是 PNG",
      s == 200 and b[:8] == b"\x89PNG\r\n\x1a\n", f"status={s}")

# 11. 上传路由：合成 wav → 音频管线作业（dry-run 校验脚本调用链）
wav_bytes = (SMOKE / "audio.wav").read_bytes()
s, _, j = multipart("/api/upload", "files", "smoke_upload.wav", wav_bytes, "audio/wav")
check("POST /api/upload (wav) → 200 作业创建", s == 200 and j.get("status") == "queued",
      f"route={j.get('route')}")
jid = j.get("id")
jj = poll_job(jid)
check("作业状态流转 queued→…→done", jj["status"] == "done" and jj["rc"] == 0,
      f"status={jj.get('status')} rc={jj.get('rc')}")
check("作业调用了正确脚本 bin/run_all.py",
      jj.get("cmd", ["", ""])[1].endswith("bin/run_all.py") and jj.get("route") == "audio")
check("后台作业保留虚拟环境 Python，不解析成系统解释器",
      ".venv/bin/python" in jj.get("cmd", [""])[0])
inbox = TEST_ROOT / jj.get("inbox", "")
check("上传文件已存 recordings/inbox/<jobid>/",
      inbox.is_dir() and len(list(inbox.iterdir())) == 1)
check("作业预测了会议目录名", bool(jj.get("meeting")))

# 12. regen（dry-run）
s, _, j = req("POST", "/api/meetings/_smoke/regen_minutes")
check("POST regen_minutes → 200 作业创建", s == 200 and j.get("kind") == "regen")
jj = poll_job(j["id"])
check("regen 作业 done(dry-run)", jj["status"] == "done"
      and (jj.get("result") or {}).get("dry_run") is True)

# 13. jobs 列表
s, _, j = req("GET", "/api/jobs")
check("GET /api/jobs → 200", s == 200 and len(j.get("jobs", [])) >= 2,
      f"jobs={len(j.get('jobs', []))}")
job_on_disk = TEST_JOBS / f"{jid}.json"
check("作业 json 已落盘(仅元数据)", job_on_disk.is_file())
if job_on_disk.is_file():
    disk = json.loads(job_on_disk.read_text())
    check("落盘作业只含元数据行(log 行均以 [ 开头)",
          all(l.lstrip().startswith("[") for l in disk.get("log", [])))

# 14. 上传校验失败不留下半上传目录
inbox_root = TEST_ROOT / "recordings" / "inbox"
before_dirs = len(list(inbox_root.iterdir())) if inbox_root.is_dir() else 0
s, _, _ = multipart("/api/upload", "files", "bad.txt", b"not allowed", "text/plain")
after_dirs = len(list(inbox_root.iterdir())) if inbox_root.is_dir() else 0
check("非法上传 → 400 且不留孤儿目录", s == 400 and after_dirs == before_dirs,
      f"before={before_dirs} after={after_dirs}")

# 15. 等待任务可插队/取消（dry-run delay 保证后两条仍在队列）
wav_bytes = (SMOKE / "audio.wav").read_bytes()
s1, _, j1 = multipart("/api/upload", "files", "queue_a.wav", wav_bytes, "audio/wav")
s2, _, j2 = multipart("/api/upload", "files", "queue_b.wav", wav_bytes, "audio/wav")
s3, _, j3 = multipart("/api/upload", "files", "queue_c.wav", wav_bytes, "audio/wav")
sp, _, priority = req("POST", f"/api/jobs/{j3.get('id')}/prioritize")
sl, _, queue_state = req("GET", "/api/jobs")
queued = sorted(
    [job for job in queue_state.get("jobs", []) if job.get("status") == "queued"],
    key=lambda job: job.get("queue_position", 999))
check("等待作业支持手动优先且 API 返回实际队列顺序",
      s1 == 200 and s2 == 200 and s3 == 200 and sp == 200 and sl == 200
      and priority.get("queue_position") == 1
      and queue_state.get("capabilities", {}).get("job_priority") is True
      and queued and queued[0].get("id") == j3.get("id")
      and queued[0].get("priority_boost") is True)
sc, _, jc = req("POST", f"/api/jobs/{j2.get('id')}/cancel")
cancelled = poll_job(j2.get("id"))
check("排队作业取消 → cancelled", s1 == 200 and s2 == 200 and sc == 200
      and jc.get("ok") is True and cancelled.get("status") == "cancelled")
poll_job(j1.get("id"))
poll_job(j3.get("id"))

# 16. 结构化逐字稿引用问答（dry-run 不调用真实模型）
s, _, bundle = req("GET", "/api/meetings/_smoke/bundle")
rs, _, retrieved = req("POST", "/api/meetings/_smoke/rag/search", {
    "query": "评审的结论和页面是什么？",
    "turn_indexes": [],
})
retrieved_types = {source.get("type") for source in retrieved.get("sources", [])}
check("meeting RAG → 统一召回结论/逐字稿/页面并返回可跳转来源",
      rs == 200 and retrieved.get("version") == "meeting-rag/evidence-hybrid-v1"
      and retrieved.get("evidence_state") == "ready"
      and retrieved.get("retrieval_mode") == "lexical"
      and {"claim", "transcript", "slide"} <= retrieved_types
      and any(source.get("turn_indexes") for source in retrieved.get("sources", [])))
chat_body = {
    "message": "这里做了什么决定？",
    "turn_indexes": [0, 1],
    "transcript_revision": bundle.get("transcript_revision"),
    "history": [],
}
s, _, chat = req("POST", "/api/meetings/_smoke/assistant/chat", chat_body)
check("assistant/chat → RAG 回答 + 可点击来源", s == 200 and "【R1】" in chat.get("answer", "")
      and bool(chat.get("sources")) and chat["sources"][0].get("turn_indexes")
      and chat.get("retrieval", {}).get("version") == "meeting-rag/evidence-hybrid-v1")
stale = dict(chat_body, transcript_revision="stale-revision")
s, _, _ = req("POST", "/api/meetings/_smoke/assistant/chat", stale)
check("assistant/chat 拒绝过期逐字稿引用", s == 409)

# 流式问答：SSE 帧序 meta → delta* → done，dry-run 回答一致；过期引用在流开始前 409
s, _, raw = req("POST", "/api/meetings/_smoke/assistant/chat/stream", chat_body, raw=True)
frames = [json.loads(line[5:].strip()) for line in raw.decode().splitlines()
          if line.startswith("data:")]
types = [f.get("type") for f in frames]
check("assistant/chat/stream → SSE meta/delta/done",
      s == 200 and types and types[0] == "meta" and "delta" in types
      and types[-1] == "done" and "【R1】" in frames[-1].get("answer", "")
      and bool(frames[0].get("sources")))
s, _, _ = req("POST", "/api/meetings/_smoke/assistant/chat/stream", stale, raw=True)
check("assistant/chat/stream 过期引用在流开始前 409", s == 409)

# 17. 纪要修改必须 preview → revision 校验 → apply → 可安全撤销，并生成历史版本
minutes_before_edit = (SMOKE / "minutes.md").read_text()
edit_body = {
    "message": "根据引用补充总体摘要",
    "turn_indexes": [0, 1],
    "transcript_revision": bundle.get("transcript_revision"),
    "minutes_revision": bundle.get("minutes_revision"),
    "target_heading": "## 总体摘要",
}
s, _, preview = req("POST", "/api/meetings/_smoke/assistant/edit/preview", edit_body)
check("assistant/edit/preview → 结构化 diff", s == 200 and preview.get("proposal_id")
      and preview.get("target_heading") == "## 总体摘要" and preview.get("diff"),
      f"status={s} detail={preview.get('detail', '')}")
s, _, applied = req("POST", "/api/meetings/_smoke/assistant/edit/apply",
                    {"proposal_id": preview.get("proposal_id")})
history_files = list((SMOKE / ".history" / "minutes").glob("*.md"))
check("assistant/edit/apply → 写入 + 自动版本备份", s == 200 and applied.get("ok") is True
      and len(history_files) == 1)
s, _, _ = req("POST", "/api/meetings/_smoke/assistant/edit/apply",
              {"proposal_id": preview.get("proposal_id")})
check("同一修改提案不能重复应用", s == 409)
s, _, undone = req("POST", "/api/meetings/_smoke/assistant/edit/undo",
                   {"proposal_id": preview.get("proposal_id")})
history_files = list((SMOKE / ".history" / "minutes").glob("*.md"))
check("assistant/edit/undo → 恢复原纪要并保留修改后版本",
      s == 200 and undone.get("ok") is True
      and (SMOKE / "minutes.md").read_text() == minutes_before_edit
      and len(history_files) == 2)
s, _, _ = req("POST", "/api/meetings/_smoke/assistant/edit/undo",
              {"proposal_id": preview.get("proposal_id")})
check("同一修改只能撤销一次", s == 409)

# 18. 删除只作用于隔离数据根，并清理声纹来源引用
s, _, deleted = req("POST", "/api/meetings/_smoke/delete")
check("删除隔离会议 → 目录移除", s == 200 and deleted.get("ok") is True and not SMOKE.exists())
check("删除会议 → 同步移除本地审计记录",
      deleted.get("evaluation_removed") is True and not evaluation_path.exists())
bank_after_delete = json.loads((FAKE_BANK / "bank.json").read_text())
check("删除会议 → 清理声纹 sources", all("_smoke" not in v.get("sources", [])
      for v in bank_after_delete["voices"]))

print(f"\n== {len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("FAILED:", ", ".join(FAIL))
    raise SystemExit(1)
