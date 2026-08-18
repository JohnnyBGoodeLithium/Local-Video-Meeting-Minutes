"""MeetingPack Viewer 模板运行时启动回归。
`node --check` 只查语法，拦不住 TDZ/未定义引用这类运行时错误（真实事故：调色板
helper 定义在使用之后，导出包整页空白）。本测试用最小合成数据渲染 viewer.html，
并在无头 Chromium 里真实启动，断言正文渲染且控制台无未捕获异常。
没有 Chromium 的环境打印说明并跳过。"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))

import export_meeting  # noqa: E402

CHROME = (shutil.which("chromium") or shutil.which("chromium-browser")
          or shutil.which("google-chrome"))
if not CHROME:
    print("viewer boot: chromium not found, skipped")
    raise SystemExit(0)

EVIDENCE = {
    "schema": "meeting-minutes-evidence/v1",
    "claims": [{"id": "C0001", "text": "示例结论：本周五前提交样机计划。",
                "kind": "decision", "status": "confirmed", "confidence": "high",
                "section": "总体摘要", "turn_ids": ["T0001"], "page_ids": ["P0001"],
                "turn_indexes": [0]}],
    "actions": [],
    "sources": {
        "transcript": [{"id": "T0001", "index": 0, "speaker": "人员甲",
                        "start": 0.0, "end": 5.0, "text": "示例发言：周五前给结论。"},
                       {"id": "T0002", "index": 1, "speaker": "人员乙",
                        "start": 5.0, "end": 10.0, "text": "示例发言：我来准备材料。"},
                       {"id": "T0003", "index": 2, "speaker": "人员甲",
                        "start": 10.0, "end": 15.0, "text": "示例发言：下周再同步。"}],
        "pages": [{"id": "P0001", "number": 1, "first": 0.0, "last": 9.0,
                   "image": None, "visual_description": "示例页面：计划表。",
                   "display_status": "discussed"}],
    },
}

page = export_meeting._viewer_html(
    "合成启动测试会", "2026-01-01",
    "<h2>总体摘要</h2><p>启动冒烟正文标记</p>",
    EVIDENCE, {"schema": "test"}, {}, None, None,
    speaker_navigation_rows=[
        {"speaker": "人员甲", "selectable": True,
         "identity_basis": "session_voice_cluster"},
        {"speaker": "人员乙", "selectable": True,
         "identity_basis": "imported_transcript_label"},
        {"speaker": "短片段", "selectable": False,
         "identity_basis": "insufficient_voice_sample"},
    ])
contract_probe = b"""<script>
selectPlaybackSpeaker('\xe4\xba\xba\xe5\x91\x98\xe7\x94\xb2',false);setPlaybackScope('meeting');reviewTurn=0;stepReviewTurn(1);
const sequentialStep=reviewTurn===1;
selectPlaybackSpeaker('\xe4\xba\xba\xe5\x91\x98\xe7\x94\xb2',false);setPlaybackScope('speaker');reviewTurn=0;stepReviewTurn(1);
const speakerStep=reviewTurn===2;
selectPlaybackSpeaker(spkPin,true);focusTime(5,false);setPlaybackScope('speaker');
const inferredSpeaker=spkPin==='\xe4\xba\xba\xe5\x91\x98\xe4\xb9\x99'&&reviewTurn===1;
const shortSampleDisabled=!speakerSelectable('\xe7\x9f\xad\xe7\x89\x87\xe6\xae\xb5');
document.body.dataset.reviewContract=[sequentialStep,speakerStep,inferredSpeaker,shortSampleDisabled].join(',');
</script></body>"""
page = page.replace(b"</body>", contract_probe)

with tempfile.TemporaryDirectory() as td:
    f = Path(td) / "viewer.html"
    f.write_bytes(page)
    proc = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--enable-logging=stderr", "--v=0", "--virtual-time-budget=8000",
         "--dump-dom", f.as_uri()],
        capture_output=True, text=True, timeout=90)

assert proc.returncode == 0, proc.stderr[-300:]
assert "启动冒烟正文标记" in proc.stdout, "viewer 正文未渲染"
assert 'id="pack-version"' in proc.stdout and "Meeting Minutes v0.8.2" in proc.stdout, \
    "viewer 未显示生成器产品版本"
assert 'id="utterance-controls"' in proc.stdout and "重播本段" in proc.stdout, \
    "viewer 逐段回听控制未启动"
assert 'id="focusbar"' not in proc.stdout, "viewer 仍渲染冗余语义摘要条"
assert 'data-review-contract="true,true,true,true"' in proc.stdout, \
    "viewer 顺次/个人/当前位置选人契约不一致"
assert "Uncaught" not in proc.stderr, \
    f"viewer 启动存在未捕获异常: {proc.stderr[-500:]}"
print("viewer boot: headless runtime passed")
