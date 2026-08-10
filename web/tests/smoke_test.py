#!/usr/bin/env python3
"""meeting-web 冒烟测试。断言只看状态码/数量/元数据，绝不打印内容字段。

前置：先跑 make_fake_bank.py 和 make_smoke.py 重置夹具，
服务以 MEETING_WEB_BANK=/tmp/mm_fake_bank MEETING_WEB_DRYRUN=1 启动。
"""
import io
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = os.environ.get("MM_TEST_BASE", "http://127.0.0.1:8899")
FAKE_BANK = Path("/tmp/mm_fake_bank")
SMOKE = Path("/home/johnny-tcx_ultra/meeting-minutes/meetings/_smoke")
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
        if s == 200 and j["status"] in ("done", "failed"):
            return j
        time.sleep(1)
    return j


# 1. 会议列表
s, _, j = req("GET", "/api/meetings")
n = len(j.get("meetings", []))
check("GET /api/meetings → 200", s == 200, f"会议数={n}")
check("列表含 _smoke", any(m["slug"] == "_smoke" for m in j["meetings"]))

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
check("bundle minutes_html 图片已改写为 file 路由",
      f'/api/meetings/_smoke/file?path=slides/' in j.get("minutes_html", ""))

# 3. Range 请求
s, h, b = req("GET", "/api/meetings/_smoke/media/audio",
              headers={"Range": "bytes=0-1023"}, raw=True)
check("media/audio Range → 206", s == 206 and len(b) == 1024,
      f"status={s} bytes={len(b)}")
s2, _, _ = req("GET", "/api/meetings/_smoke/media/audio", raw=True)
check("media/audio 无 Range → 200", s2 == 200)
s3, _, _ = req("GET", "/api/meetings/_smoke/media/video", raw=True)
check("media/video 无源视频 → 404", s3 == 404)

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

# 6. speakers（绑定前）
s, _, j = req("GET", "/api/speakers")
check("GET /api/speakers → 200",
      s == 200 and len(j["persons"]) == 1 and len(j["voices"]) == 2,
      f"persons={len(j.get('persons', []))} voices={len(j.get('voices', []))}")

# 7. bind 候选路径（模糊名 → 409 + 候选，且不写库）
s, _, j = req("POST", "/api/meetings/_smoke/bind", {"voice": "v_9002", "name": "Alicia"})
bank_now = json.loads((FAKE_BANK / "bank.json").read_text())
v2 = next(v for v in bank_now["voices"] if v["id"] == "v_9002")
check("bind 模糊名 → 409 + 候选", s == 409 and bool((j.get("detail") or {}).get("candidates")))
check("409 时库未改", v2["person_id"] is None)

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
md_lines = (SMOKE / "transcript.spk.md").read_text().splitlines()
n_md = sum(1 for l in md_lines if "Alice Example" in l)
check("transcript.spk.md 同步改名（计数）", n_md == 2, f"md行数={n_md}")
bank_now = json.loads((FAKE_BANK / "bank.json").read_text())
v1 = next(v for v in bank_now["voices"] if v["id"] == "v_9001")
check("fake bank v_9001.person_id == p_0001", v1["person_id"] == "p_0001")
n_sample_files = len(list((SMOKE / "samples").glob("*.wav")))
check("试听片段跟随改名", (SMOKE / "samples" / "Alice_Example.wav").is_file()
      and n_sample_files == 2, f"samples={n_sample_files}")

# 9. orgchart GET/PUT（假库）
s, _, j = req("GET", "/api/orgchart")
check("GET /api/orgchart → 200", s == 200 and len(j["entries"]) == 2,
      f"entries={len(j.get('entries', []))}")
new_entries = j["entries"] + [{"name": "Eve Example", "aliases": ["Eve"], "title": "Eng",
                               "team": "BU1", "leader": "Dave Example", "note": ""}]
s, _, j = req("PUT", "/api/orgchart", {"entries": new_entries})
check("PUT /api/orgchart → 200 count=3", s == 200 and j.get("count") == 3)
s, _, j = req("GET", "/api/orgchart")
check("PUT 后 GET → 3 条", s == 200 and len(j["entries"]) == 3)
check("PUT 已落盘假库", len(json.loads((FAKE_BANK / "orgchart.json").read_text())) == 3)

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
inbox = Path("/home/johnny-tcx_ultra/meeting-minutes") / jj.get("inbox", "")
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
job_on_disk = Path("/home/johnny-tcx_ultra/meeting-minutes/web/jobs") / f"{jid}.json"
check("作业 json 已落盘(仅元数据)", job_on_disk.is_file())
if job_on_disk.is_file():
    disk = json.loads(job_on_disk.read_text())
    check("落盘作业只含元数据行(log 行均以 [ 开头)",
          all(l.lstrip().startswith("[") for l in disk.get("log", [])))

print(f"\n== {len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("FAILED:", ", ".join(FAIL))
    raise SystemExit(1)
