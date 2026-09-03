"""MeetingPack Viewer 模板运行时启动回归。
`node --check` 只查语法，拦不住 TDZ/未定义引用这类运行时错误（真实事故：调色板
helper 定义在使用之后，导出包整页空白）。本测试用最小合成数据渲染 viewer.html，
并在无头 Chromium 里真实启动，断言正文渲染且控制台无未捕获异常。
没有 Chromium 的环境打印说明并跳过。"""
import shutil
import subprocess
import sys
import tempfile
import copy
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "bin"))

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
                        "start": 0.0, "end": 5.0,
                        "text": "示例长发言：周五前给结论并同步后续计划。" * 40},
                       {"id": "T0002", "index": 1, "speaker": "人员乙",
                        "start": 5.0, "end": 10.0, "text": "示例发言：我来准备材料。"},
                       {"id": "T0003", "index": 2, "speaker": "人员甲",
                        "start": 10.0, "end": 15.0, "text": "示例发言：下周再同步。"}],
        "pages": [{"id": "P0001", "number": 1, "first": 0.0, "last": 9.0,
                   "image": None, "visual_description": "示例页面：计划表。",
                   "display_status": "discussed"}],
    },
}

TOPIC_MAP = {
    "state": "ready",
    "topics": [
        {"id": "M01", "title": "示例议题一", "summary": "说明第一项计划。",
         "ranges": [[0, 5]], "turn_ids": ["T0001"], "claim_ids": ["C0001"],
         "page_ids": ["P0001"],
         "children": [{"id": "N0101", "type": "decision", "title": "确认节点",
                       "summary": "这是展开后的节点说明。", "ranges": [[0, 5]],
                       "turn_ids": ["T0001"], "claim_ids": ["C0001"],
                       "page_ids": ["P0001"]}]},
        {"id": "M02", "title": "示例议题二", "summary": "说明第二项计划。",
         "ranges": [[5, 10]], "turn_ids": ["T0002"], "claim_ids": [],
         "page_ids": [], "children": []},
        {"id": "M03", "title": "示例议题三", "summary": "说明第三项计划。",
         "ranges": [[10, 15]], "turn_ids": ["T0003"], "claim_ids": [],
         "page_ids": [], "children": []},
    ],
}

page = export_meeting._viewer_html(
    "合成启动测试会", "2026-01-01",
    "<h2>总体摘要</h2><p>启动冒烟正文标记</p>",
    EVIDENCE, {"schema": "test"}, TOPIC_MAP, None, None,
    speaker_navigation_rows=[
        {"speaker": "人员甲", "selectable": True,
         "identity_basis": "session_voice_cluster"},
        {"speaker": "人员乙", "selectable": True,
         "identity_basis": "imported_transcript_label"},
        {"speaker": "短片段", "selectable": False,
         "identity_basis": "insufficient_voice_sample"},
    ])
contract_probe = b"""<script>
const units=reviewUnits(),longUnits=units.filter(unit=>unit.turnIndex===0);
selectPlaybackSpeaker('\xe4\xba\xba\xe5\x91\x98\xe7\x94\xb2',false);setPlaybackScope('meeting');reviewTurn=longUnits[0].index;stepReviewTurn(1);
const longSegmentStep=longUnits.length>1&&reviewTurn===longUnits[1].index&&units[reviewTurn].turnIndex===0;
reviewTurn=longUnits[longUnits.length-1].index;stepReviewTurn(1);
const sequentialStep=units[reviewTurn].turnIndex===1;
selectPlaybackSpeaker('\xe4\xba\xba\xe5\x91\x98\xe7\x94\xb2',false);setPlaybackScope('speaker');reviewTurn=longUnits[longUnits.length-1].index;stepReviewTurn(1);
const speakerStep=units[reviewTurn].turnIndex===2;
selectPlaybackSpeaker(spkPin,true);focusTime(5,false);setPlaybackScope('speaker');
const inferredSpeaker=spkPin==='\xe4\xba\xba\xe5\x91\x98\xe4\xb9\x99'&&units[reviewTurn].turnIndex===1;
const shortSampleDisabled=!speakerSelectable('\xe7\x9f\xad\xe7\x89\x87\xe6\xae\xb5');
const continuationWording=document.querySelector('.turn.cont')?.textContent.includes('\xe5\x90\x8c\xe4\xb8\x80\xe5\x8f\x91\xe8\xa8\x80');
document.body.dataset.reviewContract=[longSegmentStep,sequentialStep,speakerStep,inferredSpeaker,shortSampleDisabled,continuationWording].join(',');
renderTopicMap('N0101');
const topicDetailExpanded=!!document.querySelector('.topic-detail')&&document.querySelector('.topic-detail').textContent.includes('\xe8\xbf\x99\xe6\x98\xaf\xe5\xb1\x95\xe5\xbc\x80\xe5\x90\x8e\xe7\x9a\x84\xe8\x8a\x82\xe7\x82\xb9\xe8\xaf\xb4\xe6\x98\x8e');
const nodeStaysContext=currentMode==='topic_map'&&document.querySelector('#app').classList.contains('review-mode')&&document.querySelector('#app').classList.contains('context-active');
const playerAvailableInContext=getComputedStyle(document.querySelector('.left')).display!=='none'&&getComputedStyle(document.querySelector('.main')).display!=='none'&&getComputedStyle(document.querySelector('.transcript-panel')).display==='none';
const tabsBefore=document.querySelector('#viewtabs').getBoundingClientRect().left;
const tabWidthsBefore=[...document.querySelectorAll('#viewtabs [role="tab"]')].map(tab=>tab.getBoundingClientRect().width);
document.querySelector('[data-view-seek]').click();
const timeOpensReview=currentMode==='transcript'&&document.querySelector('#app').classList.contains('review-mode');
const tabsStayPut=Math.abs(tabsBefore-document.querySelector('#viewtabs').getBoundingClientRect().left)<1;
const tabWidthsAfter=[...document.querySelectorAll('#viewtabs [role="tab"]')].map(tab=>tab.getBoundingClientRect().width);
const tabWidthsStable=tabWidthsBefore.every((width,index)=>Math.abs(width-tabWidthsAfter[index])<1);
const singleSelectedTab=document.querySelectorAll('#viewtabs [aria-selected="true"]').length===1&&document.querySelectorAll('#viewtabs .primary-tab').length===0;
const transcriptReplacesContext=getComputedStyle(document.querySelector('.left')).display!=='none'&&getComputedStyle(document.querySelector('.main')).display==='none'&&getComputedStyle(document.querySelector('.transcript-panel')).display!=='none';
renderMinutes();
const leavingTranscriptRestoresContext=currentMode==='minutes'&&getComputedStyle(document.querySelector('.main')).display!=='none'&&getComputedStyle(document.querySelector('.transcript-panel')).display==='none';
personLanesOpen=true;renderPersonLanes();
const spaciousPersonLane=parseFloat(getComputedStyle(document.querySelector('.person-lane-track')).height)>=16;
const neutralTranscriptRow=getComputedStyle(document.querySelector('.turn')).backgroundImage==='none';
document.body.dataset.topicContract=[topicDetailExpanded,nodeStaysContext,playerAvailableInContext,timeOpensReview,tabsStayPut,tabWidthsStable,singleSelectedTab,transcriptReplacesContext,leavingTranscriptRestoresContext,spaciousPersonLane,neutralTranscriptRow].join(',');
</script></body>"""
page = page.replace(b"</body>", contract_probe)
tab_probe = """
<script>
const viewbarRect=document.querySelector('.workspace-nav .viewbar').getBoundingClientRect();
const firstTabLeft=()=>document.querySelector('#viewtabs [role="tab"]').getBoundingClientRect().left;
const tabLeftBefore=firstTabLeft();
const tabsCenterRight=(tabLeftBefore-viewbarRect.left)>=viewbarRect.width*0.45;
renderTranscriptMode();renderMinutes();renderScreens();renderTopicMap();
const tabsNoJump=Math.abs(firstTabLeft()-tabLeftBefore)<1;
const noHorizontalOverflow=document.documentElement.scrollWidth<=document.documentElement.clientWidth+1;
document.body.dataset.tabContract=[tabsCenterRight,tabsNoJump,noHorizontalOverflow].join(',');
</script></body>"""
page = page.replace(b"</body>", tab_probe.encode("utf-8"))

with tempfile.TemporaryDirectory() as td:
    f = Path(td) / "viewer.html"
    f.write_bytes(page)
    proc = subprocess.run(
         [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1920,1080",
         "--enable-logging=stderr", "--v=0", "--virtual-time-budget=8000",
         "--dump-dom", f.as_uri()],
        capture_output=True, text=True, timeout=90)

assert proc.returncode == 0, proc.stderr[-300:]
assert "启动冒烟正文标记" in proc.stdout, "viewer 正文未渲染"
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
assert 'id="pack-version"' in proc.stdout and f"Meeting Minutes v{version}" in proc.stdout, \
    "viewer 未显示生成器产品版本"
assert 'data-fluent-theme="light"' in proc.stdout, "viewer 未启用共享 Fluent 浅色 token"
assert 'id="fluent-zoom-in"' in proc.stdout and "__FLUENT_" not in proc.stdout, \
    "viewer 未内联共享 Fluent 图标/基础样式"
assert "prefers-reduced-motion" in proc.stdout and ":focus-visible" in proc.stdout, \
    "viewer 缺少键盘焦点或减少动态效果合同"
assert 'id="utterance-controls"' in proc.stdout and "重播本段" in proc.stdout, \
    "viewer 逐段回听控制未启动"
assert 'id="focusbar"' not in proc.stdout, "viewer 仍渲染冗余语义摘要条"
assert 'data-review-contract="true,true,true,true,true,true"' in proc.stdout, \
    "viewer 长发言分段/顺次/个人/当前位置选人契约不一致"
assert 'data-topic-contract="true,true,true,true,true,true,true,true,true,true,true"' in proc.stdout, \
    ("viewer 全局播放器、Tab 切换与轻量人物标记契约不一致: " +
     (next((part.split('"')[1] for part in proc.stdout.split()
            if part.startswith('data-topic-contract=')), "missing")))
assert 'data-tab-contract="true,true,true"' in proc.stdout, \
    ("viewer 桌面 Tab 中间偏右/位置稳定/无横向溢出契约不一致: " +
     (next((part.split('"')[1] for part in proc.stdout.split()
            if part.startswith('data-tab-contract=')), "missing")))
assert "Uncaught" not in proc.stderr, \
    f"viewer 启动存在未捕获异常: {proc.stderr[-500:]}"

media_topic_map = copy.deepcopy(TOPIC_MAP)
media_topic_map["media_navigation"] = {
    "schema": "media-navigation/v1", "format": "monologue",
    "show_narrative_lane": True, "show_speaker_lane": False,
    "segments": [
        {"id": "N001", "role": "setup", "start": 0, "end": 5,
         "topic_id": "M01", "node_id": "N0101", "title": "合成铺垫"},
        {"id": "N002", "role": "evidence", "start": 5, "end": 15,
         "topic_id": "M02", "node_id": "M02", "title": "合成证据"},
    ],
}
media_page = export_meeting._viewer_html(
    "合成媒体启动测试", "2026-01-01", "<h2>总体摘要</h2><p>媒体正文</p>",
    EVIDENCE, {"schema": "test"}, media_topic_map, None, None,
    content_type="media", source_info={
        "schema": "media-source/v1", "kind": "public_url",
        "canonical_url": "https://example.invalid/watch?v=synthetic",
        "platform": "Example Video", "publisher": "Synthetic Publisher",
        "published_at": "2026-01-02",
    })
media_probe = b"""<script>
renderLanes();renderLegend();personLanesOpen=true;renderPersonLanes();
document.body.dataset.mediaContract=[!!document.querySelector('#lane-narrative'),!document.querySelector('#lane-spk'),document.querySelectorAll('.narrative-key').length===2,document.querySelector('#lanes-bar').hidden].join(',');
</script></body>"""
media_page = media_page.replace(b"</body>", media_probe)
with tempfile.TemporaryDirectory() as td:
    f = Path(td) / "media-viewer.html"
    f.write_bytes(media_page)
    media_proc = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--window-size=1920,1080", "--virtual-time-budget=5000", "--dump-dom", f.as_uri()],
        capture_output=True, text=True, timeout=90)
assert media_proc.returncode == 0, media_proc.stderr[-300:]
assert 'data-media-contract="true,true,true,true"' in media_proc.stdout, \
    "viewer 单人口播未切换为议题+叙事时间线"
assert 'id="original-source"' in media_proc.stdout \
    and 'href="https://example.invalid/watch?v=synthetic"' in media_proc.stdout \
    and "查看原视频" in media_proc.stdout, "viewer 未投影公开来源跳转"
assert "Uncaught" not in media_proc.stderr, \
    f"viewer media 启动存在未捕获异常: {media_proc.stderr[-500:]}"


def chromium_dom(page: bytes, path: Path, *, size="1920,1080", budget=8000,
                 profile: Path | None = None) -> subprocess.CompletedProcess:
    path.write_bytes(page)
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
           f"--window-size={size}", "--enable-logging=stderr", "--v=0",
           f"--virtual-time-budget={budget}", "--dump-dom"]
    if profile:
        cmd.append(f"--user-data-dir={profile}")
    cmd.append(path.as_uri())
    return subprocess.run(cmd, capture_output=True, text=True, timeout=90)


# A/C. 匿名说话人重命名:显示层同步、底层 identity 不变、person-focus 导航与
# 播放位置保持、Esc/Enter 键盘路径、reset 恢复;最后留下 Peter 供隔离用例复用。
EVIDENCE_ALIAS = copy.deepcopy(EVIDENCE)
EVIDENCE_ALIAS["sources"]["transcript"] = [
    {"id": "T0001", "index": 0, "speaker": "Speaker A", "start": 0.0, "end": 5.0,
     "text": "示例发言：匿名声音组第一句。"},
    {"id": "T0002", "index": 1, "speaker": "人员乙", "start": 5.0, "end": 10.0,
     "text": "示例发言：具名说话人。"},
    {"id": "T0003", "index": 2, "speaker": "Speaker A", "start": 10.0, "end": 15.0,
     "text": "示例发言：匿名声音组第二句。"},
]
EVIDENCE_ALIAS["sources"]["pages"] = []
ALIAS_NAV = [
    {"speaker": "Speaker A", "selectable": True,
     "identity_basis": "session_voice_cluster"},
    {"speaker": "人员乙", "selectable": True,
     "identity_basis": "imported_transcript_label"},
]
alias_page = export_meeting._viewer_html(
    "合成别名测试会甲", "2026-01-01",
    "<h2>总体摘要</h2><p>别名冒烟正文</p>",
    EVIDENCE_ALIAS, {"schema": "test"}, TOPIC_MAP, None, None,
    speaker_navigation_rows=ALIAS_NAV)
alias_probe = """
<script>
const out=[],qa=(name,val)=>out.push(name+':'+(val?'1':'0'));
renderTranscriptMode();
focusTime(5,false);
const focusBefore=focus.time;
const renameBtn=document.querySelector('#transcript [data-rename="Speaker A"]');
qa('renameEntry',!!renameBtn);
renameBtn.click();
qa('popoverOpens',!document.querySelector('#rename-popover').hidden&&document.activeElement.id==='rename-input');
document.querySelector('#rename-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
qa('escCancels',document.querySelector('#rename-popover').hidden&&document.activeElement===document.querySelector('#transcript [data-rename="Speaker A"]'));
document.querySelector('#transcript [data-rename="Speaker A"]').click();
document.querySelector('#rename-input').value='Peter';
document.querySelector('#rename-apply').click();
const heads=[...document.querySelectorAll('#transcript .turn')];
qa('turnsShowPeter',heads.filter(el=>el.dataset.index!=='1').every(el=>el.querySelector('.turn-head b').textContent==='Peter')&&heads.filter(el=>el.dataset.index==='1').every(el=>el.querySelector('.turn-head b').textContent==='人员乙'));
qa('legendShowsPeter',[...document.querySelectorAll('#legend [data-person]')].find(b=>b.dataset.person==='Speaker A')?.textContent.includes('Peter'));
personLanesOpen=true;renderPersonLanes();
qa('laneShowsPeter',document.querySelector('#person-lanes .person-lane[data-speaker="Speaker A"] .person-lane-name')?.textContent==='Peter');
selectPlaybackSpeaker('Speaker A',false);setPlaybackScope('speaker');
qa('controlsShowPeter',document.querySelector('#utterance-controls .utterance-context b')?.textContent==='Peter');
showTurn(turns[0]);
qa('evidenceShowsPeter',document.querySelector('#evidence').textContent.includes('Peter'));
qa('focusKept',focus.time===focusBefore);
qa('identityKept',turns[0].speaker==='Speaker A'&&spkPin==='Speaker A'&&reviewUnits()[0].speaker==='Speaker A');
qa('stored',(localStorage.getItem(aliasStorageKey)||'').includes('Peter'));
selectReviewTurn(0,false);
const stepBefore=reviewTurn;stepReviewTurn(1);
qa('navigationWorks',playbackScope==='speaker'&&reviewTurn!==stepBefore&&reviewUnits()[reviewTurn].speaker==='Speaker A');
document.querySelector('#alias-reset').click();
qa('resetRestores',displaySpeaker('Speaker A')==='Speaker A'&&localStorage.getItem(aliasStorageKey)===null&&document.querySelector('#transcript .turn .turn-head b').textContent==='Speaker A');
qa('pinKeptAfterReset',spkPin==='Speaker A'&&playbackScope==='speaker');
document.querySelector('#transcript [data-rename="Speaker A"]').click();
document.querySelector('#rename-input').value='Peter';
document.querySelector('#rename-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
qa('enterApplies',displaySpeaker('Speaker A')==='Peter'&&(localStorage.getItem(aliasStorageKey)||'').includes('Peter'));
document.body.dataset.aliasContract=out.join(',');
</script></body>"""
alias_page = alias_page.replace(b"</body>", alias_probe.encode("utf-8"))

alias_b_page = export_meeting._viewer_html(
    "合成别名测试会乙", "2026-01-02",
    "<h2>总体摘要</h2><p>别名隔离正文</p>",
    EVIDENCE_ALIAS, {"schema": "test"}, TOPIC_MAP, None, None,
    speaker_navigation_rows=ALIAS_NAV)
isolation_probe = """
<script>
document.body.dataset.isolationContract=[displaySpeaker('Speaker A')==='Speaker A',!document.querySelector('#transcript').textContent.includes('Peter'),localStorage.getItem(aliasStorageKey)===null,aliasStorageKey.startsWith('meetingpack:speaker-aliases:')].join(',');
</script></body>"""
alias_b_page = alias_b_page.replace(b"</body>", isolation_probe.encode("utf-8"))

with tempfile.TemporaryDirectory() as td:
    profile = Path(td) / "shared-profile"
    alias_proc = chromium_dom(alias_page, Path(td) / "alias-viewer.html", profile=profile)
    assert alias_proc.returncode == 0, alias_proc.stderr[-300:]
    alias_contract = next((part.split('"')[1] for part in alias_proc.stdout.split()
                           if part.startswith('data-alias-contract=')), "missing")
    assert alias_contract != "missing" and all(
        item.endswith(":1") for item in alias_contract.split(",")), \
        f"viewer 匿名说话人重命名契约不一致: {alias_contract}"
    assert "Uncaught" not in alias_proc.stderr, \
        f"viewer alias 启动存在未捕获异常: {alias_proc.stderr[-500:]}"
    # B. alias 按包指纹隔离:同 profile 下另一场会议的 Speaker A 不受影响
    isolation_proc = chromium_dom(alias_b_page, Path(td) / "alias-b-viewer.html",
                                  profile=profile)
    assert isolation_proc.returncode == 0, isolation_proc.stderr[-300:]
    assert 'data-isolation-contract="true,true,true,true"' in isolation_proc.stdout, \
        ("viewer 显示名按包隔离契约不一致: " +
         (next((part.split('"')[1] for part in isolation_proc.stdout.split()
                if part.startswith('data-isolation-contract=')), "missing")))

# D. audio-only 与 video 的 media workspace 保持稳定垂直尺寸:
# 关键元素(tabs/searchbox/timeline/逐字稿)纵向位置不允许结构性跳动。
layout_probe = """
<script>
document.body.dataset.layoutTops=['#viewtabs','.searchbox','#scrub','#transcript-panel'].map(sel=>Math.round(document.querySelector(sel).getBoundingClientRect().top)).join(',');
document.body.dataset.shellClass=document.querySelector('#media-stage-shell')?.className||'missing';
</script></body>"""
layout_pages = {}
for name, media_path, media_kind in (("video", "media/video.mp4", "video"),
                                     ("audio", "media/audio.mp3", "audio")):
    layout_page = export_meeting._viewer_html(
        "合成布局测试会", "2026-01-01",
        "<h2>总体摘要</h2><p>布局冒烟正文</p>",
        EVIDENCE, {"schema": "test"}, TOPIC_MAP, media_path, media_kind,
        speaker_navigation_rows=[
            {"speaker": "人员甲", "selectable": True,
             "identity_basis": "session_voice_cluster"},
            {"speaker": "人员乙", "selectable": True,
             "identity_basis": "imported_transcript_label"}])
    layout_pages[name] = layout_page.replace(b"</body>", layout_probe.encode("utf-8"))
with tempfile.TemporaryDirectory() as td:
    layout_tops, shell_classes = {}, {}
    for name, layout_page in layout_pages.items():
        layout_proc = chromium_dom(layout_page, Path(td) / f"layout-{name}.html")
        assert layout_proc.returncode == 0, layout_proc.stderr[-300:]
        layout_tops[name] = [int(x) for x in next(
            part.split('"')[1] for part in layout_proc.stdout.split()
            if part.startswith('data-layout-tops=')).split(",")]
        shell_classes[name] = re.search(r'data-shell-class="([^"]*)"',
                                        layout_proc.stdout).group(1)
    assert "video" in shell_classes["video"] and "audio-only" in shell_classes["audio"], \
        f"viewer media-stage-shell 契约缺失: {shell_classes}"
    labels = ["viewtabs", "searchbox", "timeline", "transcript-panel"]
    deltas = {label: abs(a - b) for label, a, b in
              zip(labels, layout_tops["video"], layout_tops["audio"])}
    assert deltas["viewtabs"] <= 2 and deltas["searchbox"] <= 2 \
        and deltas["transcript-panel"] <= 2, \
        f"viewer 导航区位置随 media 类型跳动: {deltas}"
    assert deltas["timeline"] <= 48, \
        f"viewer 时间线位置在 audio/video 之间跳动超过 48px: {deltas}"
    print(f"viewer layout: audio/video 关键元素 top 差值 {deltas}")

# F. 390px 移动端:无横向溢出、Tab 可用、rename popover 不超出视口。
mobile_page = export_meeting._viewer_html(
    "合成启动测试会", "2026-01-01",
    "<h2>总体摘要</h2><p>启动冒烟正文标记</p>",
    EVIDENCE, {"schema": "test"}, TOPIC_MAP, None, None,
    speaker_navigation_rows=[
        {"speaker": "人员甲", "selectable": True,
         "identity_basis": "session_voice_cluster"},
        {"speaker": "人员乙", "selectable": True,
         "identity_basis": "imported_transcript_label"}])
mobile_probe = """
<script>
const noOverflow=document.documentElement.scrollWidth<=document.documentElement.clientWidth+1;
document.querySelector('#viewtabs [data-mode="transcript"]').click();
const tabSwitched=currentMode==='transcript';
document.querySelector('#transcript [data-rename]').click();
const pop=document.querySelector('#rename-popover'),rect=pop.getBoundingClientRect();
const popoverUsable=!pop.hidden&&rect.left>=-1&&rect.right<=window.innerWidth+1&&document.activeElement.id==='rename-input';
document.querySelector('#rename-cancel').click();
document.body.dataset.mobileContract=[noOverflow,tabSwitched,popoverUsable].join(',');
</script></body>"""
mobile_page = mobile_page.replace(b"</body>", mobile_probe.encode("utf-8"))
with tempfile.TemporaryDirectory() as td:
    mobile_proc = chromium_dom(mobile_page, Path(td) / "mobile-viewer.html",
                               size="390,844")
    assert mobile_proc.returncode == 0, mobile_proc.stderr[-300:]
    assert 'data-mobile-contract="true,true,true"' in mobile_proc.stdout, \
        ("viewer 移动端契约不一致: " +
         (next((part.split('"')[1] for part in mobile_proc.stdout.split()
                if part.startswith('data-mobile-contract=')), "missing")))

print("viewer boot: headless runtime passed")
