/* 会议列表 + 回顾工作台 */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const WORKSPACE_KEY = "meeting-minutes:workspace:v1";

function readWorkspaceState() {
  try {
    return JSON.parse(localStorage.getItem(WORKSPACE_KEY) || "{}") || {};
  } catch (_) {
    return {};
  }
}

const workspaceState = readWorkspaceState();
const requestedView = new URLSearchParams(location.search).get("view");
const requestedViewExplicit = ["minutes", "chapters", "visuals", "quality"].includes(requestedView);
const savedTranscriptMode = ({ zh: "translated", bilingual: "comparison" })[
  workspaceState.transcriptMode] || workspaceState.transcriptMode;
const TRANSLATION_TARGETS = new Set(["zh-CN", "en"]);
const UI_LANGUAGES = new Set(["zh-CN", "en"]);

const state = {
  meetings: [],
  slug: null,
  bundle: null,
  speakers: null,   // /api/speakers 缓存
  poller: null,
  assistantRefs: [],
  assistantHistory: [],
  assistantMessages: [],
  assistantBusy: false,
  assistantNextIntent: null,
  quality: null,
  qualityFilter: "pending",
  qualityScope: "priority",
  viewMode: ["minutes", "chapters", "visuals", "quality"].includes(requestedView)
    ? requestedView : "minutes",
  selectedChapterId: null,
  selectedTopicId: null,
  selectedTopicNodeId: null,
  selectedVisualId: null,
  focus: { mode: "overview", time: null, ranges: [], topicId: null, nodeId: null,
    turnIds: [], claimIds: [], pageIds: [], source: "overview" },
  screenPreview: { visualId: null, zoomIndex: 0, returnFocus: null },
  visualFilter: "useful",
  uiLanguage: UI_LANGUAGES.has(workspaceState.uiLanguage) ? workspaceState.uiLanguage : "zh-CN",
  minutesTranslation: null,
  minutesTranslationJob: null,
  minutesTranslationPoller: null,
  topicMapTranslation: null,
  topicMapTranslationJob: null,
  topicMapTranslationPoller: null,
  transcriptMode: ["original", "translated", "comparison"].includes(savedTranscriptMode)
    ? savedTranscriptMode : "original",
  translationTarget: TRANSLATION_TARGETS.has(workspaceState.translationTarget)
    ? workspaceState.translationTarget : "zh-CN",
  translation: null,
  translationJob: null,
  translationPoller: null,
  translationProgress: { done: 0, total: 0 },
  lastTranslationFocus: null,
  lastTranslationFocusAt: 0,
  expandedOriginals: new Set(),
  evidenceBilingual: new Set(),
  workspace: {
    lastSlug: workspaceState.lastSlug || null,
    paneRatio: Math.min(68, Math.max(32, Number(workspaceState.paneRatio) || 44)),
    utilityOpen: !!workspaceState.utilityOpen,
    utilityTab: workspaceState.utilityTab === "evidence" ? "evidence" : "assistant",
    videoExpanded: !!workspaceState.videoExpanded,
    translationTargets: workspaceState.translationTargets
      && typeof workspaceState.translationTargets === "object"
      ? workspaceState.translationTargets : {},
    anchors: workspaceState.anchors && typeof workspaceState.anchors === "object"
      ? workspaceState.anchors : {},
  },
  activeJobs: [],
  jobPriorityAvailable: false,
  exportPreflight: null,
  storage: null,
  progressiveRefreshes: new Set(),
};

/* ---------- 工具 ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const UI_COPY = {
  "zh-CN": {
    title: "会议纪要", brand: "🎙 会议纪要", meetings: "会议", product: "产品介绍", settings: "设置",
    import: "＋ 导入会议", drop: "或把视频、VTT、音频拖到这里", importSettings: "导入设置",
    skipVl: "快速处理，不分析共享画面", search: "搜索会议…", transcript: "逐字稿",
    original: "原文", translated: "译文", comparison: "对照", translateTo: "译为", follow: "跟随",
    outline: "会议脉络", minutes: "会议纪要", screens: "屏幕内容", audit: "结论审计",
    assistant: "AI 对话", evidence: "证据", send: "发送",
    ask: "问这场会议，或告诉我如何修改纪要…", launcher: "问这场会议，或修改纪要…",
    expanding: "展开画面", collapsing: "收起画面", sourceMinutes: "正在显示原始语言纪要",
    translatingMinutes: "正在生成中文纪要，完成后自动切换", minutesFailed: "中文纪要生成失败，可再次切换重试",
    translatingOutline: "正在生成中文会议脉络，完成后自动切换", outlineFailed: "中文会议脉络生成失败，可再次切换重试",
  },
  en: {
    title: "Meeting Minutes", brand: "🎙 Meeting Minutes", meetings: "Meetings", product: "Product", settings: "Settings",
    import: "+ Import meeting", drop: "Drop video, VTT, or audio here", importSettings: "Import settings",
    skipVl: "Fast processing; skip shared-screen analysis", search: "Search meetings…", transcript: "Transcript",
    original: "Original", translated: "Translation", comparison: "Side by side", translateTo: "Translate to", follow: "Follow",
    outline: "Meeting map", minutes: "Minutes", screens: "Screen content", audit: "Conclusion audit",
    assistant: "AI chat", evidence: "Evidence", send: "Send",
    ask: "Ask about this meeting or request a minutes edit…", launcher: "Ask about or edit this meeting…",
    expanding: "Expand screen", collapsing: "Collapse screen", sourceMinutes: "Showing minutes in their original language",
    translatingMinutes: "Generating English minutes; this view will update automatically",
    minutesFailed: "English minutes generation failed; switch again to retry",
    translatingOutline: "Generating the English meeting map; this view will update automatically",
    outlineFailed: "English meeting-map generation failed; switch again to retry",
  },
};

function ui(key) { return UI_COPY[state.uiLanguage]?.[key] || UI_COPY["zh-CN"][key] || key; }
function isEnglishUi() { return state.uiLanguage === "en"; }

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function detectTurnLanguage(text) {
  const value = String(text || "");
  const cjk = (value.match(/[\u3400-\u9fff]/g) || []).length;
  const latin = (value.match(/[A-Za-z]/g) || []).length;
  if (cjk && latin >= 4) return "mixed";
  if (cjk) return "zh";
  if (latin) return "en";
  return "unknown";
}

function recommendedTranslationTarget(turns) {
  const languages = (turns || []).map(turn => detectTurnLanguage(turn.text))
    .filter(language => language !== "unknown");
  if (languages.length && languages.every(language => language === "zh")) return "en";
  if (languages.length && languages.every(language => language === "en")) return "zh-CN";
  return TRANSLATION_TARGETS.has(state.translationTarget) ? state.translationTarget : "zh-CN";
}

function translationTargetLabel(target = state.translationTarget) {
  if (isEnglishUi()) return target === "en" ? "English" : "Chinese";
  return target === "en" ? "英语" : "中文";
}

function sourceNeedsTranslation(sourceLanguage, target = state.translationTarget) {
  return target === "en" ? sourceLanguage !== "en" : sourceLanguage !== "zh";
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r;
}

async function jget(path) {
  const r = await api(path);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function toast(msg) {
  $("#job-status").textContent = msg;
}

function scrollInside(container, element, block = "center", smooth = true) {
  if (!container || !element) return;
  const containerBounds = container.getBoundingClientRect();
  const elementBounds = element.getBoundingClientRect();
  const top = elementBounds.top - containerBounds.top + container.scrollTop;
  const bottom = top + elementBounds.height;
  let target = top;
  if (block === "center") target = top - (container.clientHeight - elementBounds.height) / 2;
  else if (block === "nearest") {
    const visibleTop = container.scrollTop;
    const visibleBottom = visibleTop + container.clientHeight;
    if (top >= visibleTop && bottom <= visibleBottom) return;
    target = top < visibleTop ? top : bottom - container.clientHeight;
  }
  container.scrollTo({ top: Math.max(0, target), behavior: smooth ? "smooth" : "auto" });
}

function scrollTranscriptTurn(index, block = "center", smooth = true) {
  scrollInside($("#transcript"), $(`#turn-${index}`), block, smooth);
}

let workspaceSaveTimer = null;
function saveWorkspaceState() {
  clearTimeout(workspaceSaveTimer);
  workspaceSaveTimer = setTimeout(() => {
    try {
      localStorage.setItem(WORKSPACE_KEY, JSON.stringify({
        lastSlug: state.workspace.lastSlug,
        uiLanguage: state.uiLanguage,
        transcriptMode: state.transcriptMode,
        translationTarget: state.translationTarget,
        paneRatio: state.workspace.paneRatio,
        utilityOpen: state.workspace.utilityOpen,
        utilityTab: state.workspace.utilityTab,
        videoExpanded: state.workspace.videoExpanded,
        translationTargets: state.workspace.translationTargets,
        anchors: state.workspace.anchors,
      }));
    } catch (_) { /* 私密浏览或存储已满时不阻断阅读 */ }
  }, 120);
}

function applyUiLanguage() {
  const english = isEnglishUi();
  document.documentElement.lang = state.uiLanguage;
  document.title = ui("title");
  const text = (selector, value) => { const el = $(selector); if (el) el.textContent = value; };
  text(".brand", ui("brand"));
  text("#library-toggle", ui("meetings"));
  text("#product-link", ui("product"));
  text("#settings-link", ui("settings"));
  text("#pick-btn", ui("import"));
  text("#drop-hint", ui("drop"));
  text("#import-settings-label", ui("importSettings"));
  text("#skip-vl-label", ui("skipVl"));
  text("#transcript-heading", ui("transcript"));
  text('[data-transcript-mode="original"]', ui("original"));
  text('[data-transcript-mode="translated"]', ui("translated"));
  text('[data-transcript-mode="comparison"]', ui("comparison"));
  text("#translation-target-caption", ui("translateTo"));
  text("#follow-label", ui("follow"));
  text("#chapters-tab", ui("outline"));
  text("#minutes-tab", ui("minutes"));
  text("#visuals-tab", ui("screens"));
  const qualityTab = $("#quality-tab");
  if (qualityTab) qualityTab.childNodes[0].textContent = `${ui("audit")} `;
  text('[data-utility-tab="assistant"]', ui("assistant"));
  text('[data-utility-tab="evidence"]', ui("evidence"));
  text("#assistant-send", ui("send"));
  const input = $("#assistant-input");
  if (input) input.placeholder = ui("ask");
  const launcher = $("#assistant-launcher span:last-child");
  if (launcher) launcher.textContent = ui("launcher");
  const search = $("#search");
  if (search) search.placeholder = ui("search");
  $$('[data-ui-language]').forEach(button =>
    button.classList.toggle("active", button.dataset.uiLanguage === state.uiLanguage));
  $("#ui-language")?.setAttribute("aria-label", english
    ? "Interface and minutes language" : "界面与纪要语言");
}

function renderMeetingHeaderMeta() {
  const b = state.bundle;
  if (!b) return;
  $("#meeting-meta").textContent = [
    b.date,
    b.duration ? (isEnglishUi() ? `${fmt(b.duration)} duration` : `${fmt(b.duration)} 时长`) : null,
    b.speaker_count ? (isEnglishUi() ? `${b.speaker_count} speakers` : `${b.speaker_count} 位发言人`) : null,
    b.transcript?.length ? (isEnglishUi()
      ? `${b.transcript.length} transcript segments` : `${b.transcript.length} 段逐字稿`) : null,
  ].filter(Boolean).join(" · ") || (isEnglishUi() ? "Meeting record" : "会议记录");
}

function meetingAnchor() {
  if (!state.slug) return null;
  if (!state.workspace.anchors[state.slug]) state.workspace.anchors[state.slug] = {};
  return state.workspace.anchors[state.slug];
}

function rememberReadingPosition() {
  if (!state.bundle) return;
  const anchor = meetingAnchor();
  const transcriptBox = $("#transcript");
  const transcriptTurn = transcriptScrollAnchor(transcriptBox);
  if (transcriptTurn) {
    anchor.transcript = {
      index: Number(transcriptTurn.id.replace("turn-", "")),
      revision: state.bundle.transcript_revision,
    };
  }
  const minutesBox = $("#minutes");
  const bounds = minutesBox.getBoundingClientRect();
  const heading = $$("[data-reading-heading]", minutesBox)
    .find(item => item.getBoundingClientRect().bottom > bounds.top + 2);
  anchor.minutes = {
    heading: heading?.id || null,
    headingText: heading?.textContent?.trim() || null,
    scrollTop: heading ? null : Math.round(minutesBox.scrollTop),
    revision: state.bundle.minutes_revision,
  };
  saveWorkspaceState();
}

function restoreReadingPosition() {
  const anchor = state.workspace.anchors[state.slug] || {};
  requestAnimationFrame(() => {
    if (anchor.transcript?.revision === state.bundle?.transcript_revision) {
      scrollTranscriptTurn(Number(anchor.transcript.index), "start", false);
    } else {
      $("#transcript").scrollTop = 0;
    }
    const minutesBox = $("#minutes");
    if (anchor.minutes?.revision === state.bundle?.minutes_revision) {
      const heading = anchor.minutes.heading && document.getElementById(anchor.minutes.heading);
      if (heading) scrollInside($("#minutes"), heading, "start", false);
      else minutesBox.scrollTop = Number(anchor.minutes.scrollTop) || 0;
    } else {
      const sameHeading = anchor.minutes?.headingText && $$('[data-reading-heading]', minutesBox)
        .find(item => item.textContent.trim() === anchor.minutes.headingText);
      if (sameHeading) scrollInside($("#minutes"), sameHeading, "start", false);
      else minutesBox.scrollTop = 0;
    }
  });
}

/* ---------- 会议列表 ---------- */

async function loadMeetings() {
  const d = await jget("/api/meetings");
  state.meetings = d.meetings;
  renderMeetingList();
  if (!state.slug && state.meetings.length) {
    const remembered = state.meetings.find(m => m.slug === state.workspace.lastSlug);
    await loadMeeting((remembered || state.meetings[0]).slug);
  }
}

function renderMeetingList() {
  const q = $("#search").value.trim().toLowerCase();
  const ul = $("#meeting-list");
  ul.innerHTML = "";
  for (const m of state.meetings) {
    if (q && !`${m.title || ""} ${m.date || ""} ${m.slug}`.toLowerCase().includes(q)) continue;
    const li = document.createElement("li");
    li.className = "meeting-item" + (m.slug === state.slug ? " active" : "");
    const meta = [
      m.date,
      m.duration ? fmt(m.duration) : null,
      m.speaker_count ? (isEnglishUi() ? `${m.speaker_count} people` : `${m.speaker_count} 人`) : null,
      m.generation_phase && ["voice_draft_generating", "voice_draft", "visual_enrichment"].includes(m.generation_phase)
        ? (m.has_minutes ? (isEnglishUi() ? "Voice draft ready" : "语音草稿可读")
          : (isEnglishUi() ? "Generating final minutes" : "终稿生成中"))
        : m.has_minutes ? (isEnglishUi() ? "Ready to review" : "可回顾")
          : (isEnglishUi() ? "Minutes pending" : "待生成纪要"),
    ].filter(Boolean).join(" · ");
    li.innerHTML =
      `<div class="m-title">${esc(m.title || m.slug)}</div>` +
      `<div class="m-meta">${esc(meta)}</div>`;
    const del = document.createElement("button");
    del.type = "button";
    del.className = "m-del";
    del.textContent = "✕";
    del.title = "删除会议";
    del.onclick = ev => deleteMeeting(ev, m.slug);
    li.appendChild(del);
    li.onclick = () => {
      loadMeeting(m.slug);
      closeMeetingLibrary();
    };
    ul.appendChild(li);
  }
}

/* ---------- 删除会议 ---------- */

async function deleteMeeting(ev, slug) {
  ev.stopPropagation();
  const meeting = state.meetings.find(m => m.slug === slug);
  if (!confirm(`删除会议「${meeting?.title || slug}」？\n逐字稿、纪要、截图和音视频都会删除，且无法恢复。`)) return;
  const r = await api(`/api/meetings/${encodeURIComponent(slug)}/delete`, { method: "POST" });
  if (!r.ok) { toast(`删除失败: ${r.status}`); return; }
  toast(`已删除 ${slug}`);
  if (state.slug === slug) {
    state.slug = null;
    state.bundle = null;
    $("#meeting-title").textContent = "选择一场会议";
    $("#meeting-meta").textContent = "阅读纪要、追问内容并修正记录";
    $("#transcript").innerHTML = '<p class="placeholder">← 选择一场会议</p>';
    $("#minutes").innerHTML = '<p class="placeholder">纪要内容</p>';
    $("#chapters").innerHTML = '<p class="placeholder">选择会议后可查看会议脉络</p>';
    $("#visuals").innerHTML = '<p class="placeholder">选择会议后可查看屏幕内容</p>';
    $("#player-holder").innerHTML = '<p class="placeholder">选择会议后可回放</p>';
    $("#timeline").innerHTML = "";
    $("#current-chapter").classList.add("hidden");
    $("#regen-btn").disabled = true;
    $("#refine-btn").disabled = true;
    $("#export-btn").disabled = true;
    $("#storage-btn").disabled = true;
    $("#quality-tab").disabled = true;
    $("#chapters-tab").disabled = true;
    $("#visuals-tab").disabled = true;
    $("#quality-entry-btn").disabled = true;
    $("#quality-entry-btn").textContent = ui("audit");
    $$('[data-transcript-mode]').forEach(button => button.disabled = true);
    $("#translation-target").disabled = true;
    state.translation = null;
    state.translationProgress = { done: 0, total: 0 };
    state.expandedOriginals.clear();
    state.evidenceBilingual.clear();
    updateTranslationState();
    state.quality = null;
    setReviewMode("minutes");
    $("#meeting-statuses").innerHTML = "";
    $("#assistant-launcher").disabled = true;
    closeUtility();
    resetAssistant();
  }
  loadMeetings();
}

/* ---------- 会议详情 ---------- */

function player() { return $("#player-holder video") || $("#player-holder audio"); }

function statusChip(label, value, tone = "neutral", title = "") {
  return `<span class="meeting-status tone-${tone}"${title ? ` title="${esc(title)}"` : ""}>` +
    `<b>${esc(label)}</b>${esc(value)}</span>`;
}

function renderMeetingStatuses() {
  const box = $("#meeting-statuses");
  const b = state.bundle;
  if (!box || !b) return;
  const active = state.activeJobs.find(job => job.meeting === state.slug
    && ["queued", "running"].includes(job.status));
  const documentReady = b.document_state === "ready";
  const voiceDraft = b.document_state === "draft";
  const voiceDraftFailed = !b.has_minutes && Number(b.generation?.voice_draft_rc || 0) !== 0;
  const evidenceState = b.evidence?.state || "partial";
  const evidenceLabel = evidenceState === "ready" ? (isEnglishUi() ? "Traceable" : "可核证")
    : evidenceState === "stale" ? (isEnglishUi() ? "Stale" : "已过期")
      : (isEnglishUi() ? "Partial evidence" : "部分证据");
  const evidenceTone = evidenceState === "ready" ? "good"
    : evidenceState === "stale" ? "warn" : "neutral";
  const shareReady = documentReady && Boolean(b.transcript?.length);
  box.innerHTML = [
    statusChip(isEnglishUi() ? "Document" : "资料",
      voiceDraft ? (isEnglishUi() ? "Voice draft ready" : "语音草稿可读")
      : voiceDraftFailed ? (isEnglishUi() ? "Draft failed; final running" : "草稿失败，生成终稿")
      : active ? (active.stage || (isEnglishUi() ? "Processing" : "处理中"))
      : (documentReady ? (isEnglishUi() ? "Ready" : "可阅读") : (isEnglishUi() ? "Processing" : "处理中")),
      voiceDraftFailed ? "warn" : voiceDraft || active ? "working" : (documentReady ? "good" : "neutral"),
      voiceDraft ? "口头内容已经可读，屏幕表格、数字和画面资料仍在补充"
        : voiceDraftFailed ? "文本模型没有返回可读正文；系统没有停住，正在继续生成多模态终稿" : ""),
    statusChip(isEnglishUi() ? "Evidence" : "证据", evidenceLabel, evidenceTone,
      evidenceState === "ready" ? "结论可回到逐字稿或共享画面核对" : "重新生成纪要后可补齐结构化依据"),
    statusChip(isEnglishUi() ? "Share" : "分享",
      shareReady ? (isEnglishUi() ? "Export ready" : "可导出") : (isEnglishUi() ? "Incomplete" : "待补齐"),
      shareReady ? "good" : "neutral",
      b.has_video || b.has_audio ? "可选择是否随包包含媒体" : "当前只能导出文字与屏幕内容"),
  ].join("");
}

async function loadMeeting(slug) {
  const changed = state.slug !== slug;
  state.slug = slug;
  if (changed) {
    resetAssistant();
    closeScreenPreview();
    if (state.translationPoller) clearInterval(state.translationPoller);
    state.translationPoller = null;
    state.translationJob = null;
    if (state.minutesTranslationPoller) clearInterval(state.minutesTranslationPoller);
    state.minutesTranslationPoller = null;
    state.minutesTranslationJob = null;
    if (state.topicMapTranslationPoller) clearInterval(state.topicMapTranslationPoller);
    state.topicMapTranslationPoller = null;
    state.topicMapTranslationJob = null;
  }
  renderMeetingList();
  const b = await jget(`/api/meetings/${encodeURIComponent(slug)}/bundle`);
  state.bundle = b;
  const savedTarget = state.workspace.translationTargets[slug];
  state.translationTarget = TRANSLATION_TARGETS.has(savedTarget)
    ? savedTarget : recommendedTranslationTarget(b.transcript);
  state.workspace.lastSlug = slug;
  saveWorkspaceState();
  state.quality = null;
  state.translation = null;
  state.minutesTranslation = null;
  state.topicMapTranslation = null;
  state.selectedChapterId = b.structure?.chapters?.[0]?.id || null;
  state.selectedTopicId = null;
  state.selectedTopicNodeId = null;
  state.selectedVisualId = b.structure?.visuals?.[0]?.id || null;
  state.focus = { mode: "overview", time: null, ranges: [], topicId: null, nodeId: null,
    turnIds: [], claimIds: [], pageIds: [], source: "overview" };
  state.focusSignature = null;
  state.visualFilter = "useful";
  state.expandedOriginals.clear();
  state.evidenceBilingual.clear();
  $("#meeting-title").textContent = b.title || slug;
  renderMeetingHeaderMeta();
  renderPlayer();
  renderTranscript(false);
  renderMinutes();
  renderChapters();
  renderVisuals();
  renderMeetingStatuses();
  renderAssistantSuggestions();
  const isDraft = b.document_state === "draft";
  $("#regen-btn").disabled = isDraft;
  $("#refine-btn").disabled = isDraft;
  $("#export-btn").disabled = isDraft;
  $("#storage-btn").disabled = false;
  $("#assistant-launcher").disabled = false;
  if (state.workspace.utilityOpen) openUtility(state.workspace.utilityTab);
  if (isDraft && state.viewMode === "quality") state.viewMode = "minutes";
  const topicMapReady = b.topic_map?.state === "ready"
    && (b.topic_map?.topics?.length || 0) >= 3 && b.topic_map.topics.length <= 8;
  if (changed && !requestedViewExplicit) state.viewMode = topicMapReady ? "chapters" : "minutes";
  $("#quality-tab").disabled = isDraft;
  $("#chapters-tab").disabled = !(b.transcript?.length);
  $("#visuals-tab").disabled = !(b.structure?.visuals?.length);
  $("#quality-entry-btn").disabled = isDraft;
  if (isDraft) $("#quality-entry-btn").textContent = isEnglishUi()
    ? "Audit after final minutes" : "终稿后审计结论";
  $$('[data-transcript-mode]').forEach(button => button.disabled = false);
  $("#translation-target").disabled = false;
  $("#translation-target").value = state.translationTarget;
  updateTranscriptModeButtons();
  setReviewMode(state.viewMode);
  restoreReadingPosition();
  await loadTranscriptTranslation();
  await loadTopicMapTranslation(true);
  await loadMinutesTranslation(true);
  if (!isDraft) await loadQualityReview();
  else {
    state.quality = null;
    $("#quality").innerHTML = '<div class="quality-empty"><h3>语音草稿暂不审计</h3><p>屏幕表格、数字和画面依据仍在补充，终稿后再开始结论审计。</p></div>';
  }
}

function renderPlayer() {
  const b = state.bundle;
  const holder = $("#player-holder");
  holder.innerHTML = "";
  let el;
  const hasVisualStage = !b.has_video && (b.structure?.visuals || []).some(item => item.image);
  if (hasVisualStage) {
    holder.innerHTML = `<div id="content-stage" class="content-stage"><img id="content-stage-image" alt="">` +
      `<button id="content-stage-expand" class="content-stage-expand" type="button">⌕ 放大查看</button>` +
      `<div class="content-stage-caption"><span id="content-stage-kicker">当前屏幕</span>` +
      `<b id="content-stage-title">正在定位屏幕内容</b></div></div>`;
    wireContentStage();
  }
  if (b.has_video) {
    el = document.createElement("video");
    el.src = `/api/meetings/${encodeURIComponent(state.slug)}/media/video`;
    el.controls = true;
  } else if (b.has_audio) {
    el = document.createElement("audio");
    el.src = `/api/meetings/${encodeURIComponent(state.slug)}/media/audio`;
    el.controls = true;
  } else {
    if (!hasVisualStage) holder.innerHTML = '<p class="placeholder">无媒体文件，可通过时间轴定位逐字稿与纪要</p>';
    buildTimeline(0);
    $("#playback-time").textContent = `00:00 / ${fmt(b.duration || 0)}`;
    $("#player-toggle").classList.add("hidden");
    updateFocusPresentation(true);
    return;
  }
  const box = $("#player-box");
  box.classList.toggle("compact", b.has_video && !state.workspace.videoExpanded);
  const toggle = $("#player-toggle");
  toggle.classList.toggle("hidden", !b.has_video);
  toggle.textContent = state.workspace.videoExpanded ? ui("collapsing") : ui("expanding");
  toggle.setAttribute("aria-expanded", String(state.workspace.videoExpanded));
  el.addEventListener("loadedmetadata", () => {
    buildTimeline(el.duration);
    $("#playback-time").textContent = `${fmt(el.currentTime)} / ${fmt(el.duration)}`;
  });
  el.addEventListener("timeupdate", onTimeUpdate);
  holder.appendChild(el);
  buildTimeline(b.duration || 0);
  updateFocusPresentation(true);
}

/* ---------- 时间轴（页区间分段 + 刻度 + 议题标记） ---------- */

const PAGE_COLORS = ["#4f7cff", "#22a06b", "#e2a13c", "#c25050", "#8a5cd6", "#2ba3b8", "#b8609a"];
const VISUAL_VALUE_LABELS = { high: "核心", medium: "参考", low: "低信息", unknown: "待解析" };

function visualValueLabel(visual) {
  return visual?.value_label || VISUAL_VALUE_LABELS[visual?.information_value] || "待判断";
}

function visualImageUrl(visual) {
  return visual?.image
    ? `/api/meetings/${encodeURIComponent(state.slug)}/file?path=${encodeURIComponent(`slides/${visual.image}`)}`
    : "";
}

function topicMapReady() {
  const topicMap = readingTopicMap();
  const topics = topicMap.topics || [];
  return topicMap.state === "ready" && topics.length >= 3 && topics.length <= 8;
}

function topicNode(topicId, nodeId = topicId) {
  const topic = (readingTopicMap().topics || []).find(item => item.id === topicId);
  if (!topic) return [null, null];
  return [topic, nodeId === topic.id ? topic : (topic.children || []).find(item => item.id === nodeId) || topic];
}

function visualForTime(time) {
  return (state.bundle?.structure?.visuals || []).find(visual =>
    (visual.ranges || []).some(([start, end]) => Number(start) <= time && time < Number(end))) || null;
}

function representativeVisual(pageIds = []) {
  const order = { high: 0, medium: 1, unknown: 2, low: 3 };
  return (pageIds || []).map(id => (state.bundle?.structure?.visuals || []).find(item => item.id === id))
    .filter(item => item?.image).sort((a, b) => (order[a.information_value] ?? 2) -
      (order[b.information_value] ?? 2) || Number(a.first || 0) - Number(b.first || 0))[0] || null;
}

const SCREEN_PREVIEW_ZOOMS = [0, 1.25, 1.5, 2, 3];

function screenPreviewVisuals() {
  return [...(state.bundle?.structure?.visuals || [])].filter(item => item.image)
    .sort((a, b) => Number(a.ranges?.[0]?.[0] ?? a.first ?? 0) -
      Number(b.ranges?.[0]?.[0] ?? b.first ?? 0));
}

function applyScreenPreviewZoom() {
  const image = $("#screen-preview-image");
  const button = $("#screen-preview-zoom");
  if (!image || !button) return;
  const zoom = SCREEN_PREVIEW_ZOOMS[state.screenPreview.zoomIndex] || 0;
  image.classList.toggle("zoomed", Boolean(zoom));
  image.style.width = zoom ? `${zoom * 100}%` : "auto";
  button.textContent = zoom ? `${Math.round(zoom * 100)}%` : "适应";
  $("#screen-preview-zoom-out").disabled = state.screenPreview.zoomIndex === 0;
  $("#screen-preview-zoom-in").disabled = state.screenPreview.zoomIndex === SCREEN_PREVIEW_ZOOMS.length - 1;
}

function updateScreenPreview(visual = null) {
  const mask = $("#screen-preview-mask");
  if (!mask || mask.classList.contains("hidden")) return;
  const visuals = screenPreviewVisuals();
  const source = visual || visuals.find(item => item.id === state.screenPreview.visualId);
  if (!source) return closeScreenPreview();
  const changed = state.screenPreview.visualId !== source.id;
  state.screenPreview.visualId = source.id;
  $("#screen-preview-image").src = visualImageUrl(source);
  $("#screen-preview-title").textContent = source.title || "屏幕内容";
  $("#screen-preview-kicker").textContent = source.kind === "slide"
    ? `第 ${source.page} 页` : "动态画面";
  const at = Number(source.ranges?.[0]?.[0] ?? source.first ?? 0);
  $("#screen-preview-meta").textContent = `${fmt(at)} · ${visualValueLabel(source)} · ` +
    `${source.display_status === "discussed" ? "有对应讨论" :
      source.display_status === "display_only" ? "仅展示" : "动态画面"}`;
  const index = visuals.findIndex(item => item.id === source.id);
  $("#screen-preview-prev").disabled = index <= 0;
  $("#screen-preview-next").disabled = index < 0 || index >= visuals.length - 1;
  if (changed) {
    const viewport = $("#screen-preview-viewport");
    viewport.scrollTop = 0;
    viewport.scrollLeft = 0;
  }
  applyScreenPreviewZoom();
}

function openScreenPreview(visualId = null) {
  const source = screenPreviewVisuals().find(item => item.id === visualId)
    || screenPreviewVisuals().find(item => item.id === $("#content-stage")?.dataset.visualId);
  if (!source) return;
  state.screenPreview.returnFocus = document.activeElement;
  state.screenPreview.visualId = source.id;
  state.screenPreview.zoomIndex = 0;
  $("#screen-preview-mask").classList.remove("hidden");
  document.body.classList.add("screen-preview-open");
  updateScreenPreview(source);
  $("#screen-preview-close").focus();
}

function closeScreenPreview() {
  $("#screen-preview-mask")?.classList.add("hidden");
  document.body.classList.remove("screen-preview-open");
  if (state.screenPreview.returnFocus?.isConnected) state.screenPreview.returnFocus.focus();
  state.screenPreview.returnFocus = null;
}

function changeScreenPreviewZoom(delta) {
  state.screenPreview.zoomIndex = Math.min(SCREEN_PREVIEW_ZOOMS.length - 1,
    Math.max(0, state.screenPreview.zoomIndex + delta));
  applyScreenPreviewZoom();
}

function navigateScreenPreview(delta) {
  const visuals = screenPreviewVisuals();
  const index = visuals.findIndex(item => item.id === state.screenPreview.visualId);
  const target = visuals[index + delta];
  if (!target) return;
  const at = Number(target.ranges?.[0]?.[0] ?? target.first ?? 0);
  seek(at, false);
  updateScreenPreview(target);
}

function wireContentStage() {
  const stage = $("#content-stage");
  if (!stage) return;
  stage.addEventListener("click", event => {
    if (event.target.closest("#content-stage-expand") || event.target.id === "content-stage-image"
        || event.target.closest(".content-stage-caption"))
      openScreenPreview(stage.dataset.visualId);
  });
}

function turnIndexesForIds(ids = []) {
  const wanted = new Set(ids);
  return (state.bundle?.evidence?.sources?.transcript || [])
    .filter(item => wanted.has(item.id)).map(item => Number(item.index)).filter(Number.isInteger);
}

function currentTurnIndex(time) {
  let index = -1;
  for (let i = 0; i < (state.bundle?.transcript || []).length; i++) {
    if (Number(state.bundle.transcript[i].start) <= time) index = i; else break;
  }
  return index;
}

function claimsForTurn(index) {
  if (index < 0) return [];
  return (state.bundle?.evidence?.claims || [])
    .filter(claim => (claim.turn_indexes || []).includes(index)).map(claim => claim.id);
}

function setOverviewFocus() {
  state.focus = { mode: "overview", time: null, ranges: [], topicId: null, nodeId: null,
    turnIds: [], claimIds: [], pageIds: [], source: "overview" };
  state.selectedTopicId = null;
  state.selectedTopicNodeId = null;
  state.focusSignature = null;
  updateFocusPresentation(true);
}

function setTopicFocus(topic, node = topic) {
  if (!topic || !node) return;
  state.focus = { mode: "topic", time: null, ranges: node.ranges || topic.ranges || [],
    topicId: topic.id, nodeId: node.id, turnIds: node.turn_ids || topic.turn_ids || [],
    claimIds: node.claim_ids || topic.claim_ids || [], pageIds: node.page_ids || topic.page_ids || [],
    source: "topic" };
  state.selectedTopicId = topic.id;
  state.selectedTopicNodeId = node.id;
  state.focusSignature = null;
  updateFocusPresentation(true);
}

function syncTimeFocus(time, explicit = false) {
  const value = Math.max(0, Math.min(Number(state.bundle?.duration || time), Number(time) || 0));
  const index = currentTurnIndex(value);
  const visual = visualForTime(value);
  const topic = topicMapReady() ? (readingTopicMap().topics || []).find(item =>
    (item.ranges || []).some(([start, end]) => Number(start) <= value && value < Number(end))) : null;
  const range = (topic?.ranges || []).find(([start, end]) => Number(start) <= value && value < Number(end))
    || (visual?.ranges || []).find(([start, end]) => Number(start) <= value && value < Number(end)) || [];
  const turnSource = (state.bundle?.evidence?.sources?.transcript || []).find(item => item.index === index);
  const signature = `${index}|${visual?.id || ""}|${topic?.id || ""}|${range.join("-")}`;
  state.focus = { mode: "time", time: value, ranges: range.length ? [range] : [],
    topicId: topic?.id || null, nodeId: topic?.id || null,
    turnIds: turnSource ? [turnSource.id] : [], claimIds: claimsForTurn(index),
    pageIds: visual?.id ? [visual.id] : [], source: explicit ? "jump" : "playback" };
  if (signature !== state.focusSignature || explicit) {
    state.focusSignature = signature;
    updateFocusPresentation(explicit);
  }
}

function updateContentStage(visual = null, semantic = false) {
  const stage = $("#content-stage");
  if (!stage) return;
  const image = $("#content-stage-image");
  const title = $("#content-stage-title");
  const kicker = $("#content-stage-kicker");
  const source = visual || (state.focus.mode === "topic"
    ? representativeVisual(state.focus.pageIds) : visualForTime(state.focus.time || 0));
  const url = visualImageUrl(source);
  const expand = $("#content-stage-expand");
  stage.dataset.visualId = source?.id || "";
  stage.classList.toggle("empty", !url);
  if (image) image.src = url || "";
  if (expand) expand.classList.toggle("hidden", !url);
  if (title) title.textContent = source?.title || "这一位置没有静态屏幕资料";
  if (kicker) kicker.textContent = semantic ? "论点代表画面" : source
    ? `${fmt(state.focus.time ?? source.first)} · ${source.kind === "slide" ? `第${source.page}页` : "动态画面"}`
    : "当前屏幕";
  if (!$("#screen-preview-mask")?.classList.contains("hidden") && source)
    updateScreenPreview(source);
}

function updateTimelineFocus() {
  const tl = $("#timeline");
  if (!tl) return;
  $$(".tl-focus-range", tl).forEach(item => item.remove());
  const duration = Number(tl.dataset.dur || state.bundle?.duration || 1);
  for (const [start, end] of state.focus.ranges || []) {
    if (Number(end) <= Number(start)) continue;
    const range = document.createElement("div");
    range.className = "tl-focus-range";
    range.style.left = `${Number(start) / duration * 100}%`;
    range.style.width = `${Math.max(.6, (Number(end) - Number(start)) / duration * 100)}%`;
    tl.appendChild(range);
  }
}

function updateFocusedTurns(explicit = false) {
  const indexes = state.focus.mode === "time" ? [currentTurnIndex(state.focus.time || 0)]
    : turnIndexesForIds(state.focus.turnIds);
  $$(".turn.focus-related").forEach(item => item.classList.remove("focus-related"));
  for (const index of indexes) $(`#turn-${index}`)?.classList.add("focus-related");
  const target = indexes.find(index => index >= 0);
  if (explicit && target != null) scrollTranscriptTurn(target, "center", true);
}

function updateFocusedClaims() {
  const wanted = new Set(state.focus.claimIds || []);
  $$("#minutes .focus-related").forEach(item => item.classList.remove("focus-related"));
  for (const link of $$('#minutes a[href^="#mm-"]')) {
    const active = wanted.has(link.getAttribute("href").slice(4));
    link.classList.toggle("focus-related", active);
    if (active) link.closest("tr, li, p")?.classList.add("focus-related");
  }
}

function updateFocusSummary() {
  const box = $("#focus-summary");
  if (!box || !state.bundle) return;
  const focus = state.focus;
  if (focus.mode === "overview") {
    const topics = topicMapReady() ? readingTopicMap().topics.length : 0;
    box.innerHTML = `<span>整场概览</span><b>${topics ? `${topics} 个一级论点` : "按时间浏览会议"}</b>` +
      `<small>选择论点聚焦内容；点击时间才会播放</small>`;
  } else if (focus.mode === "topic") {
    const [topic, node] = topicNode(focus.topicId, focus.nodeId);
    box.innerHTML = `<span>语义聚焦</span><b>${esc(node?.title || topic?.title || "会议论点")}</b>` +
      `<small>${(focus.ranges || []).length} 个时间范围 · ${focus.claimIds.length} 条相关结论</small>` +
      (focus.claimIds.length ? `<button type="button" id="focus-show-claims">查看结论</button>` : "") +
      `<button type="button" id="focus-clear">返回整场</button>`;
  } else {
    const visual = visualForTime(focus.time || 0);
    box.innerHTML = `<span>已定位 ${fmt(focus.time)}</span><b>${esc(visual?.title || "逐字稿位置")}</b>` +
      `<small>${focus.claimIds.length ? `关联 ${focus.claimIds.length} 条结论` : "当前没有直接关联结论"}</small>` +
      (focus.claimIds.length ? `<button type="button" id="focus-show-claims">查看结论</button>` : "");
  }
  box.classList.remove("hidden");
  $("#focus-clear")?.addEventListener("click", () => { setOverviewFocus(); renderChapters(); });
  $("#focus-show-claims")?.addEventListener("click", () => {
    setReviewMode("minutes");
    requestAnimationFrame(() => scrollInside(
      $("#minutes"), $("#minutes .focus-related"), "center", true));
  });
}

function updateFocusPresentation(explicit = false) {
  const semantic = state.focus.mode === "topic";
  updateContentStage(null, semantic);
  updateTimelineFocus();
  updateFocusedTurns(explicit);
  updateFocusedClaims();
  updateFocusSummary();
}

function buildTimeline(duration) {
  const b = state.bundle || { slides: [], topics: [] };
  const tl = $("#timeline");
  tl.innerHTML = "";
  if (!duration) duration = b.duration || 1;
  tl.dataset.dur = duration;

  const played = document.createElement("div");
  played.className = "tl-played";
  tl.appendChild(played);

  // 上层：LLM 归并后的语义论点出现区间。页面/参会人变化只留在下层视觉片段。
  const topicReady = topicMapReady();
  const timelineTopics = topicReady
    ? readingTopicMap().topics.flatMap((topic, index) => (topic.ranges || []).map(range => ({
        id: topic.id, title: topic.title, summary: topic.summary, index,
        start: Number(range[0]), end: Number(range[1]), topic,
      })))
    : ((b.structure?.chapter_source === "minutes_topic" && b.structure?.chapters?.length <= 12)
      ? b.structure.chapters.map((chapter, index) => ({
          id: chapter.id, title: chapter.title, summary: chapter.summary, index,
          start: chapter.start, end: chapter.end, chapter,
        })) : []);
  for (const item of timelineTopics) {
    if (item.end <= item.start) continue;
    const block = document.createElement("div");
    block.className = "tl-chapter";
    block.dataset.topicId = item.id;
    block.style.left = (item.start / duration * 100) + "%";
    const chapterWidth = (item.end - item.start) / duration * 100;
    block.style.width = Math.max(.8, chapterWidth) + "%";
    block.title = `${fmt(item.start)}–${fmt(item.end)} ${item.title}`;
    block.innerHTML = `<span class="tl-chapter-index">${String(item.index + 1).padStart(2, "0")}</span>` +
      (chapterWidth >= 11 ? `<span class="tl-chapter-title">${esc(item.title)}</span>` : "");
    block.addEventListener("mouseenter", event => showSemanticTip(event, item));
    block.addEventListener("mousemove", moveTip);
    block.addEventListener("mouseleave", hideTip);
    block.addEventListener("click", event => {
      event.stopPropagation();
      hideTip();
      if (item.topic) openTopic(item.id, true, true, item.start);
      else openChapter(item.id, true, true);
    });
    tl.appendChild(block);
  }

  // 下层：每次连续出现的页面/摄像头视觉片段。
  for (const p of b.slides) {
    const color = p.kind === "camera" ? "#666" : PAGE_COLORS[(p.page - 1) % PAGE_COLORS.length];
    for (const [s, e] of (p.ranges || [])) {
      const seg = document.createElement("div");
      seg.className = "tl-seg";
      seg.style.left = (s / duration * 100) + "%";
      seg.style.width = Math.max(0.5, (e - s) / duration * 100) + "%";
      seg.style.background = color;
      seg.dataset.start = s;
      const occurrence = (b.structure?.segments || []).find(item =>
        item.kind === (p.kind || "slide") && item.page === (p.page ?? null)
        && Math.abs(item.start - s) < .05 && Math.abs(item.end - e) < .05);
      if (occurrence?.information_value === "low") seg.classList.add("low-information");
      const label = p.kind === "camera" ? "画面" : `第${p.page}页`;
      seg.addEventListener("mouseenter", ev => showTip(ev, p, label, s, occurrence));
      seg.addEventListener("mousemove", ev => moveTip(ev));
      seg.addEventListener("mouseleave", hideTip);
      seg.addEventListener("click", event => {
        event.stopPropagation();
        seek(s);
      });
      tl.appendChild(seg);
    }
  }
  // 分钟刻度
  const step = duration > 5400 ? 600 : duration > 1500 ? 300 : 60;
  for (let t = 0; t <= duration; t += step) {
    const tick = document.createElement("div");
    tick.className = "tl-tick";
    tick.style.left = (t / duration * 100) + "%";
    tick.title = fmt(t);
    const lab = document.createElement("span");
    lab.textContent = fmt(t);
    tick.appendChild(lab);
    tl.appendChild(tick);
  }
  // 播放头
  const head = document.createElement("div");
  head.className = "tl-head";
  tl.appendChild(head);
  updateActiveChapter(player()?.currentTime || 0);
  updateTimelineFocus();
  // 空白处点击 seek
  tl.addEventListener("click", ev => {
    if (ev.target !== tl) return;
    const r = tl.getBoundingClientRect();
    seek((ev.clientX - r.left) / r.width * duration);
  });
}

function showTip(ev, page, label, start = page.first, occurrence = null) {
  const tip = $("#tl-tip");
  let html = `<div class="tip-title">${esc(label)} · ${fmt(start)}` +
    `${occurrence ? ` · ${esc(visualValueLabel(occurrence))}` : ""}</div>`;
  if (page.image) {
    html += `<img src="/api/meetings/${encodeURIComponent(state.slug)}/file?path=${encodeURIComponent("slides/" + page.image)}">`;
  }
  tip.innerHTML = html;
  tip.classList.remove("hidden");
  moveTip(ev);
}

function showSemanticTip(ev, item) {
  const tip = $("#tl-tip");
  const visuals = state.bundle?.structure?.visuals || [];
  const source = item.topic || item.chapter || {};
  const visual = (source.page_ids || []).map(id => visuals.find(visual => visual.id === id))
    .find(visual => visual?.image && visual.information_value !== "low");
  const image = visualImageUrl(visual);
  tip.innerHTML = `<div class="tip-title">论点 ${String(item.index + 1).padStart(2, "0")} · ` +
    `${fmt(item.start)}–${fmt(item.end)}</div>` +
    `<b class="tip-heading">${esc(item.title)}</b>` +
    `<p class="tip-summary">${esc(item.summary || "点击播放并定位到会议语义脉络。")}</p>` +
    (item.topic ? `<div class="tip-metrics">${item.topic.children?.length || 0} 个结构节点 · ` +
      `${item.topic.ranges?.length || 0} 个出现区间</div>` : "") +
    (image ? `<img src="${image}" alt="">` : "");
  tip.classList.remove("hidden");
  moveTip(ev);
}

function moveTip(ev) {
  const tip = $("#tl-tip");
  tip.style.left = Math.max(8, Math.min(window.innerWidth - 292, ev.clientX + 12)) + "px";
  const above = ev.clientY - tip.offsetHeight - 14;
  tip.style.top = (above >= 8 ? above : ev.clientY + 16) + "px";
}

function hideTip() { $("#tl-tip").classList.add("hidden"); }

function seek(t, play = true) {
  syncTimeFocus(t, true);
  const p = player();
  if (p) {
    p.currentTime = t;
    if (play) p.play().catch(() => {});
  }
}

function onTimeUpdate() {
  const p = player();
  if (!p || !state.bundle) return;
  const t = p.currentTime;
  const tl = $("#timeline");
  const dur = parseFloat(tl.dataset.dur || 0);
  const head = $(".tl-head", tl);
  if (head && dur) head.style.left = (t / dur * 100) + "%";
  const played = $(".tl-played", tl);
  if (played && dur) played.style.width = (t / dur * 100) + "%";
  $("#playback-time").textContent = `${fmt(t)} / ${fmt(p.duration || dur)}`;
  updateActiveChapter(t);
  syncTimeFocus(t, false);
  // 高亮当前轮
  const turns = state.bundle.transcript;
  let cur = -1;
  for (let i = 0; i < turns.length; i++) {
    if (turns[i].start <= t) cur = i; else break;
  }
  $$(".turn.playing").forEach(el => el.classList.remove("playing"));
  if (cur >= 0) {
    const el = $(`#turn-${cur}`);
    if (el) {
      el.classList.add("playing");
      if ($("#follow").checked) scrollTranscriptTurn(cur, "nearest", true);
    }
    if (state.translationJob && cur !== state.lastTranslationFocus
        && Date.now() - state.lastTranslationFocusAt > 2500) {
      const translated = (state.translation?.turns || []).some(item => item.index === cur);
      if (!translated) {
        state.lastTranslationFocus = cur;
        state.lastTranslationFocusAt = Date.now();
        startTranscriptTranslation([cur]);
      }
    }
  }
}

function updateActiveChapter(time) {
  const topics = topicMapReady() ? readingTopicMap().topics || [] : [];
  const topic = topics.find(item => (item.ranges || []).some(([start, end]) =>
    Number(start) <= time && time < Number(end)));
  const chapters = (!topics.length && state.bundle?.structure?.chapter_source === "minutes_topic"
    && state.bundle?.structure?.chapters?.length <= 12) ? state.bundle.structure.chapters : [];
  const chapter = chapters.find(item => item.start <= time && time < item.end)
    || (time === state.bundle?.duration ? chapters.at(-1) : null);
  const current = topic || chapter;
  $$(".tl-chapter.active").forEach(item => item.classList.remove("active"));
  if (current) $$(`.tl-chapter[data-topic-id="${current.id}"]`).forEach(item => item.classList.add("active"));
  $$(".topic-map-branch.playing").forEach(item => item.classList.remove("playing"));
  if (topic) $(`.topic-map-branch[data-topic-branch="${topic.id}"]`)?.classList.add("playing");
  const label = $("#current-chapter");
  label.classList.toggle("hidden", !current);
  label.textContent = current ? current.title : "";
  label.title = current ? `${topic ? "当前论点" : "当前章节"} · ${current.title}` : "";
}

/* ---------- 转写区 ---------- */

function transcriptScrollAnchor(box) {
  const bounds = box.getBoundingClientRect();
  const turn = $$(".turn", box).find(item => item.getBoundingClientRect().bottom > bounds.top + 2);
  return turn ? { id: turn.id, offset: turn.getBoundingClientRect().top - bounds.top } : null;
}

function renderTranscript(preserveScroll = true) {
  const box = $("#transcript");
  const anchor = preserveScroll ? transcriptScrollAnchor(box) : null;
  box.innerHTML = "";
  const translations = new Map((state.translation?.turns || []).map(item => [item.index, item]));
  const sourceLanguages = new Map((state.translation?.source_languages || [])
    .map(item => [item.index, item.source_language]));
  state.bundle.transcript.forEach((t, i) => {
    const div = document.createElement("div");
    div.className = "turn";
    div.id = `turn-${i}`;
    div.dataset.index = i;
    const chipCls = t.voice ? "chip" : "chip disabled";
    const translated = translations.get(i);
    const sourceLanguage = sourceLanguages.get(i);
    const forcedComparison = state.evidenceBilingual.has(i);
    const mode = forcedComparison ? "comparison" : state.transcriptMode;
    const canTranslate = translated
      && sourceNeedsTranslation(translated.source_language, state.translationTarget);
    const showOriginal = mode === "original" || !canTranslate || mode === "comparison"
      || state.expandedOriginals.has(i);
    const showTranslation = canTranslate && mode !== "original";
    let textHtml = '<span class="turn-text">';
    if (showOriginal) {
      textHtml += `<span class="txt source-text">${esc(t.text)}</span>`;
    }
    if (showTranslation) {
      textHtml += `<span class="txt translated-text ${mode === "translated" ? "primary" : ""}">${esc(translated.translated_text)}</span>`;
      if (translated.warnings?.includes("number_mismatch"))
        textHtml += '<span class="translation-warning">数字可能需要核对</span>';
      if (mode === "translated") {
        textHtml += `<button type="button" class="toggle-turn-original" data-index="${i}">` +
          `${state.expandedOriginals.has(i) ? "收起原文" : `${esc(String(translated.source_language).toUpperCase())} 原文`}</button>`;
      }
    } else if (mode !== "original" && sourceLanguage
        && sourceNeedsTranslation(sourceLanguage, state.translationTarget)) {
      const priority = state.evidenceBilingual.has(i) ? " priority" : "";
      textHtml += `<span class="turn-translation-pending${priority}">` +
        `${priority ? "优先翻译中" : (state.translationJob ? "等待翻译" : "等待继续翻译")}</span>`;
    }
    textHtml += "</span>";
    div.innerHTML =
      `<span class="tc" title="点击跳转">[${fmt(t.start)}]</span>` +
      `<span class="${chipCls}" title="${esc(t.speaker)} · ${t.voice ? "点击绑定说话人" : "无对应声纹"}" ` +
      `aria-label="说话人：${esc(t.speaker)}">${esc(t.speaker)}</span>` +
      textHtml +
      `<button type="button" class="quote-turn" title="引用这一轮到会议助手">引用</button>`;
    $(".tc", div).onclick = () => seek(t.start);
    if (t.voice) $(".chip", div).onclick = () => openBind(t.voice, t.speaker);
    $(".quote-turn", div).onclick = ev => {
      ev.stopPropagation();
      addReferenceRange(i, i);
    };
    const toggleOriginal = $(".toggle-turn-original", div);
    if (toggleOriginal) toggleOriginal.onclick = ev => {
      ev.stopPropagation();
      if (state.expandedOriginals.has(i)) state.expandedOriginals.delete(i);
      else state.expandedOriginals.add(i);
      renderTranscript();
      scrollTranscriptTurn(i, "center", false);
    };
    box.appendChild(div);
  });
  if (!state.bundle.transcript.length)
    box.innerHTML = '<p class="placeholder">无逐字稿</p>';
  if (anchor) {
    const restored = document.getElementById(anchor.id);
    if (restored) {
      const bounds = box.getBoundingClientRect();
      box.scrollTop += restored.getBoundingClientRect().top - bounds.top - anchor.offset;
    }
  } else if (!preserveScroll) {
    box.scrollTop = 0;
  }
  updateFocusedTurns(false);
}

function updateTranscriptModeButtons() {
  $$('[data-transcript-mode]').forEach(button =>
    button.classList.toggle("active", button.dataset.transcriptMode === state.transcriptMode));
}

function updateTranslationTargetControl() {
  const control = $("#translation-target");
  if (!control) return;
  control.value = state.translationTarget;
  control.disabled = !state.slug || Boolean(state.translationJob);
}

function updateTranslationState(message = null) {
  const el = $("#translation-state");
  if (!el) return;
  const wrap = $(".translation-progress-wrap");
  const control = $("#translation-control");
  const progressBar = $("#translation-progress-bar");
  const done = state.translationProgress.done || state.translation?.translated || 0;
  const total = state.translationProgress.total || state.translation?.total || 0;
  const visible = Boolean(state.slug && (state.translationJob || state.transcriptMode !== "original"
    || state.evidenceBilingual.size));
  wrap.classList.toggle("hidden", !visible);
  const pct = total ? Math.min(100, Math.round(done / total * 100)) : 0;
  progressBar.style.width = `${pct}%`;
  if (message !== null) {
    el.textContent = message;
  } else {
    const translation = state.translation;
    if (!state.slug || !visible) el.textContent = "";
    else if (state.translationJob) el.textContent = total
      ? `${translationTargetLabel()} ${isEnglishUi() ? "translation" : "翻译"} ${done}/${total}`
      : (isEnglishUi() ? "Preparing context…" : "准备语境…");
    else if (!translation || translation.state === "missing") el.textContent = isEnglishUi() ? "Not generated" : "尚未生成";
    else if (["stale", "context_stale"].includes(translation.state)) el.textContent = isEnglishUi() ? "Update needed" : "译文需更新";
    else if (translation.state === "ready") el.textContent =
      `${translationTargetLabel()} ${isEnglishUi() ? "translation" : "译文"} ${translation.translated}/${translation.total}`;
    else if (translation.state === "cancelled") el.textContent = `${isEnglishUi() ? "Stopped" : "已停止"} ${done}/${total}`;
    else if (translation.state === "failed") el.textContent = `${isEnglishUi() ? "Failed" : "失败"} ${done}/${total}`;
    else el.textContent = total ? `${isEnglishUi() ? "Translating" : "翻译中"} ${done}/${total}` : (isEnglishUi() ? "Translating" : "翻译中");
  }
  if (state.translationJob) {
    control.textContent = isEnglishUi() ? "Stop" : "停止";
    control.classList.remove("hidden");
  } else if (visible && state.translation?.state !== "ready") {
    control.textContent = done ? (isEnglishUi() ? "Resume" : "继续") : (isEnglishUi() ? "Generate" : "生成");
    control.classList.remove("hidden");
  } else {
    control.classList.add("hidden");
  }
  updateTranslationTargetControl();
}

async function loadTranscriptTranslation() {
  if (!state.slug) return;
  try {
    state.translation = await jget(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/transcript?target=${encodeURIComponent(state.translationTarget)}`);
    state.translationProgress = {
      done: state.translation.translated || 0,
      total: state.translation.total || 0,
    };
    updateTranslationState();
    updateTranscriptModeButtons();
    renderTranscript();
    if (state.transcriptMode !== "original"
        && ["missing", "stale", "context_stale"].includes(state.translation.state))
      startTranscriptTranslation();
  } catch (e) {
    state.translation = null;
    updateTranslationState("无法读取译文");
  }
}

function setTranscriptMode(mode) {
  if (!["original", "translated", "comparison"].includes(mode)) return;
  state.transcriptMode = mode;
  saveWorkspaceState();
  updateTranscriptModeButtons();
  updateTranslationState();
  renderTranscript();
  if (mode !== "original" && state.translation?.state !== "ready")
    startTranscriptTranslation();
}

async function setTranslationTarget(target) {
  if (!TRANSLATION_TARGETS.has(target) || target === state.translationTarget
      || state.translationJob) return;
  state.translationTarget = target;
  if (state.slug) state.workspace.translationTargets[state.slug] = target;
  state.translation = null;
  state.translationProgress = { done: 0, total: 0 };
  state.expandedOriginals.clear();
  saveWorkspaceState();
  updateTranslationTargetControl();
  updateTranslationState();
  renderTranscript();
  await loadTranscriptTranslation();
}

async function startTranscriptTranslation(focusIndexes = []) {
  if (!state.slug) return;
  const focus = [...new Set(focusIndexes)].filter(Number.isInteger).slice(0, 30);
  if (state.translationJob && !focus.length) return;
  updateTranslationState(`正在准备${translationTargetLabel()}译文…`);
  try {
    const focusQuery = focus.length ? `&focus=${encodeURIComponent(focus.join(","))}` : "";
    const r = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/transcript?target=${encodeURIComponent(state.translationTarget)}${focusQuery}`,
      { method: "POST" });
    const job = await r.json();
    if (!r.ok) throw new Error(job.detail || r.status);
    if (!job.id) {
      await loadTranscriptTranslation();
      return;
    }
    state.translationJob = job.id;
    state.translationProgress = job.progress || state.translationProgress;
    updateTranslationState();
    pollTranslationJob(job.id);
  } catch (e) {
    state.translationJob = null;
    updateTranslationState(`翻译失败：${e.message}`);
  }
}

async function stopTranscriptTranslation() {
  if (!state.translationJob) return;
  const jobId = state.translationJob;
  const r = await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  if (!r.ok) {
    updateTranslationState("停止失败");
    return;
  }
  updateTranslationState("正在停止…");
}

async function refreshTranscriptTranslationPartial() {
  if (!state.slug) return;
  const latest = await jget(
    `/api/meetings/${encodeURIComponent(state.slug)}/translations/transcript?target=${encodeURIComponent(state.translationTarget)}`);
  const changed = latest.translated !== state.translation?.translated
    || latest.state !== state.translation?.state;
  state.translation = latest;
  state.translationProgress = {
    done: latest.translated || state.translationProgress.done || 0,
    total: latest.total || state.translationProgress.total || 0,
  };
  if (changed) renderTranscript();
  updateTranslationState();
}

function pollTranslationJob(jobId) {
  if (state.translationPoller) clearInterval(state.translationPoller);
  const check = async () => {
    try {
      const job = await jget(`/api/jobs/${jobId}`);
      const progress = job.progress || {};
      state.translationProgress = {
        done: progress.done || 0,
        total: progress.total || state.translation?.total || 0,
      };
      await refreshTranscriptTranslationPartial();
      if (["done", "failed", "cancelled"].includes(job.status)) {
        clearInterval(state.translationPoller);
        state.translationPoller = null;
        state.translationJob = null;
        await refreshTranscriptTranslationPartial();
        if (job.status !== "done")
          updateTranslationState(job.status === "cancelled" ? "翻译已停止，可继续" : "批次失败，可继续重试");
      }
    } catch (e) { /* 短暂网络错误留到下一轮 */ }
  };
  check();
  state.translationPoller = setInterval(check, 1800);
}

function expandEvidenceBilingual(indexes) {
  if (!state.bundle) return;
  const priorities = [];
  for (const index of indexes) {
    for (const nearby of [index - 1, index, index + 1]) {
      if (nearby >= 0 && nearby < state.bundle.transcript.length) {
        state.evidenceBilingual.add(nearby);
        priorities.push(nearby);
      }
    }
  }
  renderTranscript();
  if (state.translation?.state !== "ready") startTranscriptTranslation(priorities);
}

/* ---------- 纪要区 ---------- */

async function loadMinutesTranslation(autoStart = false) {
  if (!state.slug || !state.bundle?.has_minutes) return;
  const target = state.uiLanguage;
  try {
    const payload = await jget(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/minutes?target=${encodeURIComponent(target)}`);
    if (target !== state.uiLanguage) return;
    state.minutesTranslation = payload;
    renderMinutes();
    if (autoStart && ["missing", "stale", "context_stale", "failed", "cancelled"].includes(payload.state))
      await startMinutesTranslation();
  } catch (_) {
    state.minutesTranslation = null;
    renderMinutes();
  }
}

async function startMinutesTranslation() {
  if (!state.slug || state.minutesTranslationJob || !state.bundle?.has_minutes) return;
  const target = state.uiLanguage;
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/minutes?target=${encodeURIComponent(target)}`,
      { method: "POST" });
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || response.status);
    if (!job.id) {
      await loadMinutesTranslation(false);
      return;
    }
    state.minutesTranslationJob = job.id;
    renderMinutes();
    if (state.minutesTranslationPoller) clearInterval(state.minutesTranslationPoller);
    const check = async () => {
      try {
        const current = await jget(`/api/jobs/${job.id}`);
        if (!["done", "failed", "cancelled"].includes(current.status)) return;
        clearInterval(state.minutesTranslationPoller);
        state.minutesTranslationPoller = null;
        state.minutesTranslationJob = null;
        await loadMinutesTranslation(false);
      } catch (_) { /* 下一轮继续 */ }
    };
    state.minutesTranslationPoller = setInterval(check, 1800);
    check();
  } catch (error) {
    state.minutesTranslationJob = null;
    state.minutesTranslation = { ...(state.minutesTranslation || {}), state: "failed" };
    renderMinutes();
  }
}

function readingTopicMap() {
  const translated = state.topicMapTranslation?.target_language === state.uiLanguage
    && state.topicMapTranslation?.state === "ready"
    && state.topicMapTranslation?.topic_map;
  return translated || state.bundle?.topic_map || {};
}

async function loadTopicMapTranslation(autoStart = false) {
  if (!state.slug || state.bundle?.topic_map?.state !== "ready") {
    state.topicMapTranslation = null;
    return;
  }
  const target = state.uiLanguage;
  try {
    const payload = await jget(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/topic-map?target=${encodeURIComponent(target)}`);
    if (target !== state.uiLanguage) return;
    state.topicMapTranslation = payload;
    renderChapters();
    buildTimeline(state.bundle?.duration || player()?.duration || 0);
    updateFocusSummary();
    if (autoStart && ["missing", "stale", "failed", "cancelled"].includes(payload.state))
      await startTopicMapTranslation();
  } catch (_) {
    state.topicMapTranslation = null;
    renderChapters();
  }
}

async function startTopicMapTranslation() {
  if (!state.slug || state.topicMapTranslationJob || state.bundle?.topic_map?.state !== "ready") return;
  const target = state.uiLanguage;
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/topic-map?target=${encodeURIComponent(target)}`,
      { method: "POST" });
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || response.status);
    if (!job.id) {
      await loadTopicMapTranslation(false);
      return;
    }
    state.topicMapTranslationJob = job.id;
    renderChapters();
    if (state.topicMapTranslationPoller) clearInterval(state.topicMapTranslationPoller);
    const check = async () => {
      try {
        const current = await jget(`/api/jobs/${job.id}`);
        if (!["done", "failed", "cancelled"].includes(current.status)) return;
        clearInterval(state.topicMapTranslationPoller);
        state.topicMapTranslationPoller = null;
        state.topicMapTranslationJob = null;
        await loadTopicMapTranslation(false);
      } catch (_) { /* 下一轮继续 */ }
    };
    state.topicMapTranslationPoller = setInterval(check, 1800);
    check();
  } catch (_) {
    state.topicMapTranslationJob = null;
    state.topicMapTranslation = { ...(state.topicMapTranslation || {}), state: "failed" };
    renderChapters();
  }
}

async function setUiLanguage(language) {
  if (!UI_LANGUAGES.has(language) || language === state.uiLanguage) return;
  state.uiLanguage = language;
  state.minutesTranslation = null;
  if (state.minutesTranslationPoller) clearInterval(state.minutesTranslationPoller);
  state.minutesTranslationPoller = null;
  state.minutesTranslationJob = null;
  state.topicMapTranslation = null;
  if (state.topicMapTranslationPoller) clearInterval(state.topicMapTranslationPoller);
  state.topicMapTranslationPoller = null;
  state.topicMapTranslationJob = null;
  saveWorkspaceState();
  applyUiLanguage();
  renderMeetingList();
  renderMeetingHeaderMeta();
  renderMeetingStatuses();
  renderTranscript();
  renderMinutes();
  if (state.viewMode === "chapters") renderChapters();
  if (state.viewMode === "visuals") renderVisuals();
  if (state.viewMode === "quality") renderQualityReview();
  updateFocusSummary();
  await loadTopicMapTranslation(true);
  await loadMinutesTranslation(true);
}

function renderMinutes() {
  const box = $("#minutes");
  const draft = state.bundle?.document_state === "draft";
  const phase = state.bundle?.generation?.phase;
  const draftFailed = !state.bundle?.has_minutes
    && Number(state.bundle?.generation?.voice_draft_rc || 0) !== 0;
  const banner = draft ? (isEnglishUi()
    ? `<section class="minutes-draft-banner"><div><span>Voice draft · Ready to read</span>` +
      `<b>${phase === "visual_enrichment" ? "Adding screen context" : "Preparing screen analysis"}</b>` +
      `<p>This draft uses the transcript and speaker identities. Tables, figures, and visual context will be added to the multimodal final version. Playback, search, and Q&A are available; editing and export remain disabled.</p></div><i></i></section>`
    : `<section class="minutes-draft-banner"><div><span>语音草稿 · 已可阅读</span>` +
      `<b>${phase === "visual_enrichment" ? "正在补充屏幕资料" : "正在准备屏幕分析"}</b>` +
      `<p>当前结论来自逐字稿和说话人；页面数字、表格和画面上下文会在多模态终稿中补充。` +
      `草稿期间可以播放、搜索和追问，暂不支持修改或导出。</p></div><i></i></section>`) : "";
  const pending = draftFailed
    ? '<section class="minutes-draft-banner"><div><span>语音草稿生成失败</span><b>正在继续生成多模态终稿</b>' +
      '<p>文本模型没有返回可读正文，因此这次无法提前展示草稿；逐字稿仍可阅读和播放，终稿完成后会自动出现。</p></div><i></i></section>'
    : '<p class="placeholder">暂无纪要</p>';
  const translated = state.minutesTranslation?.target_language === state.uiLanguage
    && state.minutesTranslation?.state === "ready" && state.minutesTranslation?.html;
  const languageBanner = state.minutesTranslationJob
    ? `<div class="minutes-language-banner"><b>${esc(ui("translatingMinutes"))}</b><span>…</span></div>`
    : state.minutesTranslation?.state === "failed"
      ? `<div class="minutes-language-banner"><b>${esc(ui("minutesFailed"))}</b></div>` : "";
  box.innerHTML = languageBanner + banner + (translated || state.bundle.minutes_html || pending);
  const candidates = state.bundle?.evidence?.action_candidates || [];
  if (candidates.length) {
    const candidateHtml = `<details class="action-candidate-panel"><summary>` +
      `<span>${isEnglishUi() ? "Unverified candidates" : "待核实候选"}</span>` +
      `<b>${isEnglishUi() ? `${candidates.length} generated clues` : `另有 ${candidates.length} 条生成线索`}</b>` +
      `<small>${isEnglishUi() ? "Not linked to transcript evidence and not confirmed. Expand to inspect the original clues."
        : "尚未绑定逐字稿依据，不代表已确认；展开后可完整保留查看。"}</small></summary>` +
      `<div class="action-candidate-list">${candidates.map((item, index) =>
        `<article><i>${String(index + 1).padStart(2, "0")}</i><div><b>${esc(item.text)}</b>` +
        `<small>${isEnglishUi() ? "Owner" : "负责人"}：${esc(item.owner || (isEnglishUi() ? "Unconfirmed" : "待确认"))} · ` +
        `${isEnglishUi() ? "Due" : "期限"}：${esc(item.deadline || (isEnglishUi() ? "Unconfirmed" : "待确认"))} · ` +
        `${isEnglishUi() ? "Source status" : "原状态"}：${esc(item.original_status || (isEnglishUi() ? "Unconfirmed" : "待确认"))}</small>` +
        `</div><span>${isEnglishUi() ? "Evidence needed" : "待绑定依据"}</span></article>`
      ).join("")}</div></details>`;
    const riskHeading = $$(`h3`, box).find(item => item.textContent.trim() === "风险/待确认");
    if (riskHeading) riskHeading.insertAdjacentHTML("beforebegin", candidateHtml);
    else box.insertAdjacentHTML("beforeend", candidateHtml);
  }
  $$("h1, h2, h3", box).forEach((heading, index) => {
    heading.id = `minutes-heading-${index}`;
    heading.dataset.readingHeading = "1";
  });
  $$('a[href^="#mm-"]', box).forEach(link => {
    link.onclick = ev => {
      ev.preventDefault();
      showMinutesEvidence(link.getAttribute("href").slice(4));
    };
  });
  updateFocusedClaims();
}

function structureClaimCard(id) {
  const claim = (state.bundle?.evidence?.claims || []).find(item => item.id === id);
  if (!claim) return "";
  const status = qualityStatusNames[claim.status] || claim.status || "记录";
  const kind = qualityKindNames[claim.kind] || claim.kind || "内容";
  const action = claim.kind === "action" ? (claim.action ||
    (state.bundle?.evidence?.actions || []).find(item => item.claim_id === claim.id)) : null;
  return `<button type="button" class="structure-claim" data-structure-claim="${esc(id)}">` +
    `<span class="structure-claim-meta"><i>${esc(kind)}</i><i>${esc(status)}</i>` +
    `${claim.start != null ? `<i>${fmt(claim.start)}</i>` : ""}</span>` +
    `<b>${esc(action?.text || claim.text)}</b>` +
    (action ? `<small>负责人：${esc(action.owner || "待确认")} · 期限：${esc(action.deadline || "待确认")}` +
      `${action.status ? ` · ${esc(action.status)}` : ""}</small>` : "") +
    `</button>`;
}

function structureClaimGroup(title, ids, empty = "") {
  const cards = (ids || []).map(structureClaimCard).filter(Boolean).join("");
  if (!cards && !empty) return "";
  return `<section class="structure-group"><h3>${esc(title)} <span>${ids?.length || 0}</span></h3>` +
    (cards || `<p class="structure-empty">${esc(empty)}</p>`) + `</section>`;
}

function wireStructureClaims(box) {
  $$('[data-structure-claim]', box).forEach(button =>
    button.onclick = () => showMinutesEvidence(button.dataset.structureClaim));
}

function openChapter(chapterId, play = false) {
  if (!chapterId) return;
  state.selectedChapterId = chapterId;
  setReviewMode("chapters");
  const chapter = state.bundle?.structure?.chapters?.find(item => item.id === chapterId);
  if (play && chapter) seek(chapter.start);
}

function flowClaim(id) {
  const claim = (state.bundle?.evidence?.claims || []).find(item => item.id === id);
  if (!claim) return "";
  const action = claim.kind === "action" ? (claim.action ||
    (state.bundle?.evidence?.actions || []).find(item => item.claim_id === claim.id)) : null;
  return `<button type="button" class="meeting-flow-claim" data-structure-claim="${esc(id)}">` +
    `<b>${esc(action?.text || claim.text)}</b>` +
    `${claim.start != null ? `<small>${fmt(claim.start)} · ${isEnglishUi() ? "Verify evidence" : "核对依据"}</small>` :
      `<small>${isEnglishUi() ? "Verify evidence" : "核对依据"}</small>`}` +
    `</button>`;
}

const TOPIC_NODE_LABELS = {
  "zh-CN": { context: "背景", argument: "观点", counterpoint: "反方/约束", decision: "决定",
    action: "行动", open_question: "待确认", risk: "风险", evidence: "依据", discussion: "讨论" },
  en: { context: "Context", argument: "Argument", counterpoint: "Constraint", decision: "Decision",
    action: "Action", open_question: "Open question", risk: "Risk", evidence: "Evidence", discussion: "Discussion" },
};

function topicNodeLabel(type, fallback = null) {
  return TOPIC_NODE_LABELS[state.uiLanguage]?.[type]
    || fallback || (isEnglishUi() ? "Discussion" : "讨论");
}

function revealTopic(topicId, behavior = "smooth") {
  requestAnimationFrame(() => {
    const branch = $(`.topic-map-branch[data-topic-branch="${topicId}"]`);
    scrollInside($("#chapters"), branch, "center", behavior === "smooth");
  });
}

function openTopic(topicId, play = false, reveal = false, at = null) {
  const topic = readingTopicMap().topics?.find(item => item.id === topicId);
  if (!topic) return;
  setTopicFocus(topic, topic);
  setReviewMode("chapters");
  if (reveal) revealTopic(topicId);
  if (play) seek(Number.isFinite(at) ? at : Number(topic.ranges?.[0]?.[0] || 0));
}

function topicRangeText(ranges) {
  const rows = ranges || [];
  if (!rows.length) return isEnglishUi() ? "No time range" : "没有可用时间范围";
  const visible = rows.slice(0, 3).map(([start, end]) => `${fmt(start)}–${fmt(end)}`);
  return visible.join(" · ") + (rows.length > 3
    ? ` · ${isEnglishUi() ? `+${rows.length - 3} more` : `另 ${rows.length - 3} 段`}` : "");
}

function topicMapBranch(topic, index, selectedNodeId) {
  const selected = topic.id === state.selectedTopicId;
  const counts = (topic.children || []).reduce((result, child) => {
    result[child.type] = (result[child.type] || 0) + 1;
    return result;
  }, {});
  const outcome = [counts.decision ? `${counts.decision} ${isEnglishUi() ? "decisions" : "决定"}` : "",
    counts.action ? `${counts.action} ${isEnglishUi() ? "actions" : "行动"}` : "",
    (counts.risk || counts.open_question) ? `${(counts.risk || 0) + (counts.open_question || 0)} ${isEnglishUi() ? "open/risks" : "未决/风险"}` : ""]
    .filter(Boolean).join(" · ");
  return `<section class="topic-map-branch ${selected ? "selected" : ""}" ` +
    `data-topic-branch="${esc(topic.id)}"><button type="button" class="topic-map-topic-node ` +
    `${selectedNodeId === topic.id ? "active" : ""}" data-topic-select="${esc(topic.id)}">` +
    `<small>${isEnglishUi() ? "Topic" : "论点"} ${String(index + 1).padStart(2, "0")} · ` +
    `${outcome || (isEnglishUi() ? `${topic.children?.length || 0} structured nodes` : `${topic.children?.length || 0} 个结构节点`)}</small>` +
    `<b>${esc(topic.title)}</b><span>${esc(topic.summary)}</span>` +
    `<em>${esc(topicRangeText(topic.ranges))}</em></button>` +
    (selected ? `<div class="topic-map-children">${(topic.children || []).map(child =>
      `<button type="button" class="topic-map-child ${esc(child.type)} ` +
      `${selectedNodeId === child.id ? "active" : ""}" data-topic-child="${esc(child.id)}" ` +
      `data-topic-parent="${esc(topic.id)}"><small>${esc(topicNodeLabel(child.type))}</small>` +
      `<b>${esc(child.title)}</b><span>${esc(child.summary)}</span></button>`).join("")}</div>` : "") +
    `</section>`;
}

function topicDetailVisuals(node, pageMap) {
  const pages = (node.page_ids || []).map(id => pageMap.get(id)).filter(Boolean).slice(0, 4);
  if (!pages.length) return "";
  return `<section class="topic-detail-section"><h4>${isEnglishUi() ? "Related screen content" : "相关屏幕资料"} <span>${node.page_ids.length}</span></h4>` +
    `<div class="topic-detail-visuals">${pages.map(page => {
      const image = visualImageUrl(page);
      const at = Number(page.ranges?.[0]?.[0] || page.first || 0);
      return `<button type="button" data-visual-id="${esc(page.id)}" data-visual-time="${at}">` +
        (image ? `<img src="${image}" alt="">` : `<span>${isEnglishUi() ? "No image" : "无截图"}</span>`) +
        `<b>${esc(page.title)}</b></button>`;
    }).join("")}</div></section>`;
}

function topicMapDetail(topic, node, pageMap) {
  const ranges = node.ranges || topic.ranges || [];
  const claims = (node.claim_ids || []).map(flowClaim).filter(Boolean).join("");
  return `<section class="topic-map-detail"><header><div><span>${esc(
    node.id === topic.id ? (isEnglishUi() ? "Primary topic" : "一级论点") :
      topicNodeLabel(node.type, isEnglishUi() ? "Structured node" : "结构节点"))}</span>` +
    `<h3>${esc(node.title)}</h3></div><small>${esc(topic.title)}</small></header>` +
    `<p>${esc(node.summary || topic.summary)}</p>` +
    `<div class="topic-detail-ranges">${ranges.map(([start, end], index) =>
      `<button type="button" data-topic-play="${start}">▶ ${fmt(start)}–${fmt(end)}` +
      `${index === 0 ? (isEnglishUi() ? " Play from here" : " 从这里播放") : ""}</button>`).join("")}</div>` +
    (claims ? `<section class="topic-detail-section"><h4>${isEnglishUi() ? "Related conclusions and evidence" : "相关结论与依据"} <span>${node.claim_ids.length}</span></h4>` +
      `<div class="topic-detail-claims">${claims}</div></section>` : "") +
    topicDetailVisuals(node, pageMap) + `</section>`;
}

async function startTopicMapGeneration(button) {
  button.disabled = true;
  const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/topic-map`,
    { method: "POST" });
  const job = await response.json();
  if (!response.ok) {
    button.disabled = false;
    toast(`${isEnglishUi() ? "Meeting-map generation failed" : "生成会议脉络失败"}：${job.detail || response.status}`);
    return;
  }
  button.textContent = isEnglishUi() ? "Synthesizing the whole meeting…" : "正在归纳整场会议…";
  toast(isEnglishUi() ? `Meeting-map job ${job.id} queued` : `会议脉络作业 ${job.id} 已排队`);
  pollJob(job.id, async current => {
    if (current.status === "done") {
      toast(isEnglishUi() ? "Meeting map generated" : "整场会议脉络已生成");
      await loadMeeting(state.slug);
    } else if (["failed", "cancelled"].includes(current.status)) {
      button.disabled = false;
      button.textContent = isEnglishUi() ? "Regenerate meeting map" : "重新生成会议脉络";
      toast(isEnglishUi() ? `Meeting-map job ${current.status}` : `会议脉络作业 ${current.status}`);
    }
  });
}

function renderChapters() {
  const box = $("#chapters");
  const topicMap = readingTopicMap();
  const topics = topicMap.topics || [];
  if (state.bundle?.document_state === "draft") {
    box.innerHTML = isEnglishUi()
      ? `<div class="topic-map-empty"><span>Voice draft is ready</span>` +
        `<h3>The meeting map will follow the multimodal final minutes</h3>` +
        `<p>Tables, figures, and screen context are still being added. The map is generated after the final evidence stabilizes.</p></div>`
      : `<div class="topic-map-empty"><span>语音草稿已可阅读</span>` +
        `<h3>会议脉络将在多模态终稿后生成</h3>` +
        `<p>系统正在补充屏幕表格、数字和视觉上下文。为避免基于不完整资料提前固化论点，` +
        `Topic Map 会在终稿证据稳定后自动生成。</p></div>`;
    return;
  }
  if (!topicMapReady()) {
    const stale = topicMap.state === "stale";
    const invalid = topicMap.state === "ready" && topics.length;
    box.innerHTML = `<div class="topic-map-empty"><span>${isEnglishUi() ? "AI semantic synthesis" : "AI 语义归纳"}</span>` +
      `<h3>${isEnglishUi()
        ? (stale ? "Meeting content changed; update the map" : invalid
          ? `${topics.length} primary topics need to be synthesized again` : "No meeting-wide semantic map yet")
        : (stale ? "会议内容变化，需要更新脉络" : invalid
          ? `当前有 ${topics.length} 个一级论点，需要重新归纳` : "还没有整场会议语义脉络")}</h3>` +
      `<p>${isEnglishUi()
        ? "The system synthesizes the transcript, speakers, conclusion evidence, and screen content into 3–8 primary topics. Screenshot or attendee changes do not become nodes by themselves."
        : "系统会读取逐字稿、说话人、结论依据和屏幕资料，先做大尺度内容归纳，再合并为 3–8 个一级论点。截图和参会人变化不会直接成为节点。"}</p>` +
      `<button type="button" id="topic-map-generate" class="primary">${isEnglishUi()
        ? (stale || invalid ? "Update meeting map" : "Generate meeting map")
        : (stale || invalid ? "更新会议脉络" : "生成会议脉络")}</button></div>`;
    $("#topic-map-generate", box).onclick = event => startTopicMapGeneration(event.currentTarget);
    return;
  }
  const selectedTopic = topics.find(item => item.id === state.selectedTopicId) || null;
  const allNodes = selectedTopic ? [selectedTopic, ...(selectedTopic.children || [])] : [];
  const selectedNode = allNodes.find(item => item.id === state.selectedTopicNodeId) || selectedTopic;
  const pageMap = new Map((state.bundle?.structure?.visuals || []).map(item => [item.id, item]));
  const claims = state.bundle?.evidence?.claims || [];
  const confirmed = claims.filter(item => item.status === "confirmed").length;
  const actions = state.bundle?.evidence?.actions?.length || 0;
  const unresolved = claims.filter(item => item.status === "open" || item.kind === "open_question").length;
  const languageBanner = state.topicMapTranslationJob
    ? `<div class="minutes-language-banner"><b>${esc(ui("translatingOutline"))}</b><span>…</span></div>`
    : state.topicMapTranslation?.state === "failed"
      ? `<div class="minutes-language-banner"><b>${esc(ui("outlineFailed"))}</b></div>` : "";
  box.innerHTML = languageBanner + `<article class="topic-map-view"><header class="topic-map-head"><div>` +
    `<span>${isEnglishUi() ? `AI meeting-wide synthesis · ${topics.length} primary topics` : `AI 全场语义归纳 · ${topics.length} 个一级论点`}</span>` +
    `<h2>${esc(state.bundle?.title || (isEnglishUi() ? "Meeting map" : "会议脉络"))}</h2>` +
    `<p>${esc(topicMap.meeting_summary || (isEnglishUi()
      ? "Organized by arguments, disagreements, decisions, and actions; screens remain evidence."
      : "按整场会议的论点、分歧、结论和行动组织；页面只作为证据。"))}</p>` +
    `<div class="topic-overview-stats"><button type="button" data-overview-target="minutes">` +
    `<b>${confirmed}</b><span>${isEnglishUi() ? "Confirmed conclusions" : "已确认结论"}</span></button><button type="button" data-overview-target="minutes">` +
    `<b>${actions}</b><span>${isEnglishUi() ? "Verifiable actions" : "可核验待办"}</span></button><button type="button" data-overview-target="minutes">` +
    `<b>${unresolved}</b><span>${isEnglishUi() ? "Open questions" : "未决问题"}</span></button></div>` +
    `</div><button type="button" id="topic-map-refresh">${isEnglishUi() ? "Regenerate" : "重新归纳"}</button></header>` +
    `<div class="topic-map-canvas"><div class="topic-map-root-wrap"><button type="button" class="topic-map-root" id="topic-map-overview">` +
    `<small>${isEnglishUi() ? "Whole meeting" : "整场会议"}</small><b>${esc(state.bundle?.title || (isEnglishUi() ? "Meeting" : "会议"))}</b>` +
    `<span>${isEnglishUi() ? `${topics.length} topics · ${topicMap.stats?.children || 0} structured nodes` :
      `${topics.length} 个论点 · ${topicMap.stats?.children || 0} 个结构节点`}</span></button></div>` +
    `<div class="topic-map-branches">${topics.map((topic, index) =>
      topicMapBranch(topic, index, selectedNode?.id)).join("")}</div></div>` +
    (selectedTopic && selectedNode ? topicMapDetail(selectedTopic, selectedNode, pageMap) :
      `<div class="topic-overview-hint"><b>${isEnglishUi() ? "Scan the whole structure, then select a topic" : "先看整场结构，再选择一个论点"}</b>` +
      `<span>${isEnglishUi() ? "Selecting a node focuses its transcript, screens, and conclusions without starting playback." :
        "选择节点只聚焦相关逐字稿、画面和结论；不会自动播放。"}</span></div>`) + `</article>`;
  $$('[data-topic-select]', box).forEach(button => button.onclick = () => {
    const topic = topics.find(item => item.id === button.dataset.topicSelect);
    setTopicFocus(topic, topic);
    renderChapters();
    revealTopic(state.selectedTopicId);
  });
  $$('[data-topic-child]', box).forEach(button => button.onclick = () => {
    const topic = topics.find(item => item.id === button.dataset.topicParent);
    const child = (topic?.children || []).find(item => item.id === button.dataset.topicChild);
    setTopicFocus(topic, child);
    renderChapters();
    revealTopic(state.selectedTopicId);
  });
  $("#topic-map-overview", box).onclick = () => { setOverviewFocus(); renderChapters(); };
  $$('[data-overview-target="minutes"]', box).forEach(button => button.onclick = () => setReviewMode("minutes"));
  $$('[data-topic-play]', box).forEach(button => button.onclick = () =>
    seek(Number(button.dataset.topicPlay)));
  $$('[data-visual-id]', box).forEach(button => button.onclick = () =>
    openVisual(button.dataset.visualId));
  $("#topic-map-refresh", box).onclick = event => startTopicMapGeneration(event.currentTarget);
  wireStructureClaims(box);
  $$(".tl-chapter.selected").forEach(item => item.classList.remove("selected"));
  $$(`.tl-chapter[data-topic-id="${state.selectedTopicId}"]`).forEach(item => item.classList.add("selected"));
  updateActiveChapter(player()?.currentTime || 0);
}

function openVisual(visualId, time = null) {
  if (!visualId) return;
  const target = state.bundle?.structure?.visuals?.find(item => item.id === visualId);
  if (target?.information_value === "low") state.visualFilter = "all";
  state.selectedVisualId = visualId;
  setReviewMode("visuals");
  if (Number.isFinite(time)) seek(time);
}

function renderVisuals() {
  const box = $("#visuals");
  const allVisuals = state.bundle?.structure?.visuals || [];
  if (!allVisuals.length) {
    box.innerHTML = '<div class="structure-empty-state"><h3>没有屏幕内容</h3><p>这场会议仍可通过会议纪要和逐字稿回顾。</p></div>';
    return;
  }
  const useful = allVisuals.filter(item => item.information_value !== "low");
  if (!useful.length) state.visualFilter = "all";
  const visuals = state.visualFilter === "useful" && useful.length ? useful : allVisuals;
  const selected = visuals.find(item => item.id === state.selectedVisualId) || visuals[0];
  state.selectedVisualId = selected.id;
  const status = selected.display_status === "discussed" ? "有对应讨论"
    : selected.display_status === "display_only" ? "仅展示" : "动态画面";
  const image = visualImageUrl(selected);
  box.innerHTML = `<div class="structure-layout visual-layout"><nav class="structure-list visual-list" aria-label="屏幕内容">` +
    `<div class="structure-list-head visual-list-head"><div><b>屏幕内容</b><span>${allVisuals.length} 项</span></div>` +
    `<div class="visual-filter"><button type="button" data-visual-filter="useful" ` +
    `class="${state.visualFilter === "useful" ? "active" : ""}">重点 ${useful.length}</button>` +
    `<button type="button" data-visual-filter="all" class="${state.visualFilter === "all" ? "active" : ""}">` +
    `全部 ${allVisuals.length}</button></div></div>` +
    visuals.map(visual => {
      const visualImage = visualImageUrl(visual);
      const visualStatus = visual.display_status === "discussed" ? "有讨论" :
        visual.display_status === "display_only" ? "仅展示" : "动态画面";
      return `<button type="button" class="visual-nav-card ${visual.id === selected.id ? "active" : ""} ` +
      `${visual.information_value === "low" ? "low-information" : ""}" ` +
      `data-visual-select="${esc(visual.id)}"><span class="visual-nav-thumb">` +
      (visualImage ? `<img src="${visualImage}" alt="">` : `<i>无截图</i>`) +
      `</span><span class="visual-nav-copy"><small>${fmt(visual.first)} · ` +
      `${visual.kind === "slide" ? `第${visual.page}页` : "摄像头"}</small>` +
      `<b>${esc(visual.title)}</b><span><i class="visual-value ${esc(visual.information_value || "unknown")}">` +
      `${esc(visualValueLabel(visual))}</i><em>${esc(visualStatus)}</em></span></span></button>`;
    }).join("") +
    `</nav><article class="structure-detail visual-detail">` +
    `<header class="structure-detail-head"><div><span>屏幕 · ${esc(status)} · ${esc(visualValueLabel(selected))}</span>` +
    `<h2>${esc(selected.title)}</h2></div></header>` +
    `<div class="visual-value-note ${esc(selected.information_value || "unknown")}"><b>${esc(visualValueLabel(selected))}</b>` +
    `<span>${esc(selected.value_reason || "尚未判断这张画面的信息价值。")}</span></div>` +
    (selected.analysis_state === "pending" ? `<div class="visual-reprocess pending">屏幕解析仍在进行，完成前不会判断这页的内容价值。</div>` :
      selected.needs_reprocess ? `<div class="visual-reprocess">页面解析没有得到可读正文，已标记为需要重新解析；当前不会将它判为低信息。</div>` : "") +
    `<div class="visual-ranges">${(selected.ranges || []).map(([start, end]) =>
      `<button type="button" data-visual-seek="${start}">${fmt(start)}–${fmt(end)}</button>`).join("")}</div>` +
    (image ? `<img class="visual-hero" data-preview-visual="${esc(selected.id)}" src="${image}" ` +
      `alt="${esc(selected.title)}" title="点击放大查看">` :
      `<div class="visual-no-image">该片段没有静态页面截图</div>`) +
    `<section class="visual-description"><h3>屏幕内容解读</h3>` +
    `<p class="visual-boundary">仅说明画面展示内容，不代表会议作出了决定。</p>` +
    `<div>${selected.description_html || esc(selected.description || "当前画面没有可用的 VL 详细解读。")}</div></section>` +
    structureClaimGroup("相关会议内容", selected.claim_ids) +
    `</article></div>`;
  $$('[data-visual-select]', box).forEach(button => button.onclick = () => {
    state.selectedVisualId = button.dataset.visualSelect;
    renderVisuals();
  });
  $$('[data-visual-filter]', box).forEach(button => button.onclick = () => {
    state.visualFilter = button.dataset.visualFilter;
    renderVisuals();
  });
  $$('[data-visual-seek]', box).forEach(button =>
    button.onclick = () => seek(Number(button.dataset.visualSeek)));
  $$('[data-preview-visual]', box).forEach(image =>
    image.onclick = () => openScreenPreview(image.dataset.previewVisual));
  wireStructureClaims(box);
}

function setReviewMode(mode) {
  const allowed = new Set(["minutes", "chapters", "visuals", "quality"]);
  state.viewMode = allowed.has(mode) ? mode : "minutes";
  if (state.viewMode === "chapters" && !state.bundle?.transcript?.length)
    state.viewMode = "minutes";
  if (state.viewMode === "visuals" && !state.bundle?.structure?.visuals?.length)
    state.viewMode = "minutes";
  for (const id of ["minutes", "chapters", "visuals", "quality"])
    $(`#${id}`).classList.toggle("hidden", state.viewMode !== id);
  for (const id of ["minutes", "chapters", "visuals", "quality"])
    $(`#${id}-tab`).classList.toggle("active", state.viewMode === id);
  if (state.viewMode === "chapters") renderChapters();
  if (state.viewMode === "visuals") renderVisuals();
  if (state.viewMode === "quality") renderQualityReview();
}

function showMinutesEvidence(claimId) {
  const claim = (state.bundle?.evidence?.claims || []).find(c => c.id === claimId);
  if (!claim) return;
  expandEvidenceBilingual(claim.turn_indexes || []);
  const turns = (claim.turn_indexes || []).map(i => ({ i, t: state.bundle.transcript[i] })).filter(x => x.t);
  const pageNumbers = (claim.page_ids || []).map(id => Number(id.slice(1))).filter(Number.isFinite);
  const pages = pageNumbers.map(n => state.bundle.slides.find(p => p.page === n)).filter(Boolean);
  let html = `<div class="evidence-claim">${esc(claim.text)}</div>` +
    `<div class="evidence-tags"><span>${esc(claim.kind)}</span><span>${esc(claim.status)}</span>` +
    `<span>置信度 ${esc(claim.confidence)}</span></div>`;
  for (const { i, t } of turns) {
    html += `<div class="evidence-source"><div><b>${esc(t.speaker)}</b>` +
      `<button type="button" class="evidence-seek" data-index="${i}">${fmt(t.start)}</button></div>` +
      `<p>${esc(t.text)}</p></div>`;
  }
  for (const p of pages) {
    const image = p.image
      ? `/api/meetings/${encodeURIComponent(state.slug)}/file?path=${encodeURIComponent("slides/" + p.image)}` : "";
    html += `<div class="evidence-source"><div><b>第${p.page}页</b>` +
      `<button type="button" class="evidence-page-seek" data-time="${p.first || 0}">${fmt(p.first)}</button></div>` +
      (image ? `<img src="${image}" alt="第${p.page}页">` : "") + `</div>`;
  }
  $("#evidence-body").innerHTML = html;
  openUtility("evidence");
  $$(".evidence-seek", $("#evidence-body")).forEach(btn => btn.onclick = () => {
    const index = Number(btn.dataset.index);
    highlightTurns([index]);
    seek(state.bundle.transcript[index]?.start || 0);
  });
  $$(".evidence-page-seek", $("#evidence-body")).forEach(btn =>
    btn.onclick = () => seek(Number(btn.dataset.time || 0)));
}

/* ---------- 会议结论审计 ---------- */

const qualityStatusNames = {
  confirmed: "已确认决定",
  working_alignment: "方向共识",
  proposal: "提议",
  open: "待解决",
  informational: "信息记录",
};

const qualityKindNames = {
  decision: "决定",
  alignment: "共识",
  proposal: "提议",
  action: "行动项",
  discussion: "讨论",
  purpose: "主旨",
  open_question: "待决问题",
};

function qualityLabelName(id) {
  return state.quality?.labels?.find(item => item.id === id)?.label || id || "";
}

function updateQualityIndicators() {
  const summary = state.quality?.priority_summary || state.quality?.summary || {};
  const pending = summary.pending || 0;
  const total = summary.total || 0;
  const evidenceReady = state.quality?.evidence_state === "ready";
  $("#quality-badge").textContent = pending;
  $("#quality-badge").classList.toggle("hidden", pending === 0);
  $("#quality-entry-btn").classList.toggle("evidence-missing", !evidenceReady);
  $("#quality-entry-btn").textContent = !evidenceReady
    ? (isEnglishUi() ? "Conclusion evidence incomplete" : "结论依据待补全") : !total
    ? (isEnglishUi() ? "No conclusions to audit" : "暂无可审计结论") : pending
    ? `${isEnglishUi() ? "Audit conclusions" : "审计会议结论"} · ${pending}`
    : (total ? (isEnglishUi() ? "View audit results" : "查看审计结果") : ui("audit"));
}

async function loadQualityReview() {
  if (!state.slug) return;
  try {
    state.quality = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/quality`);
    updateQualityIndicators();
    renderQualityReview();
  } catch (e) {
    state.quality = null;
    $("#quality").innerHTML = '<p class="placeholder">无法读取本地审计记录</p>';
  }
}

function qualityClaimVisible(claim) {
  if (state.qualityScope === "priority" && !claim.audit_priority) return false;
  const filter = state.qualityFilter;
  if (filter === "pending") return !claim.review;
  if (filter === "issues") {
    const label = claim.review?.label;
    return label && !["correct", "cannot_judge"].includes(label);
  }
  if (filter === "passed") return claim.review?.label === "correct";
  return true;
}

function qualityClaimKind(claim) {
  if (claim.kind === "action" && !claim.formal_action)
    return claim.status === "informational" ? "过程记录" : "行动线索（未入待办）";
  return qualityKindNames[claim.kind] || claim.kind;
}

function renderQualityReview() {
  const box = $("#quality");
  const quality = state.quality;
  if (!box || !quality) return;
  if (quality.evidence_state !== "ready") {
    const reason = quality.evidence_state === "stale"
      ? "纪要或逐字稿已经变化，现有依据已过期。"
      : "这场会议还没有结构化的结论依据。";
    box.innerHTML = `<div class="quality-empty"><h3>暂时无法审计结论</h3><p>${esc(reason)}</p>` +
      `<p class="dim">请先重新生成纪要；审计界面不会调用模型，也不会修改正式纪要。</p></div>`;
    return;
  }
  const allSummary = quality.summary || {};
  const prioritySummary = quality.priority_summary || allSummary;
  if (!allSummary.total) {
    box.innerHTML = `<div class="quality-empty"><h3>还没有可审计的结构化结论</h3>` +
      `<p>这份旧纪要没有 claim 级依据标记，需要重新生成一次带依据的纪要。</p>` +
      `<p class="dim">打开结论审计不会运行模型，也不会改变现有纪要。</p></div>`;
    return;
  }
  const s = state.qualityScope === "priority" ? prioritySummary : allSummary;
  const pct = s.total ? Math.round((s.reviewed / s.total) * 100) : 0;
  const filters = [
    ["pending", `待审计 ${s.pending || 0}`],
    ["issues", `存疑 ${s.issues || 0}`],
    ["passed", `可信 ${s.passed || 0}`],
    ["all", `全部 ${s.total || 0}`],
  ];
  let html = `<section class="quality-summary">` +
    `<div class="quality-summary-head"><div><b>会议结论审计</b>` +
    `<p>默认只核对决定、共识、正式行动、风险与未决问题；背景记录仍保留在“全部证据”。</p></div>` +
    `<strong>${s.reviewed || 0}/${s.total || 0}</strong></div>` +
    `<div class="quality-progress"><i style="width:${pct}%"></i></div>` +
    `<div class="quality-metrics"><span>完成 ${pct}%</span><span class="issue">问题 ${s.issues || 0}</span>` +
    `<span>待定 ${s.uncertain || 0}</span><span>过期 ${s.stale || 0}</span>` +
    `<span>逐字稿依据 ${s.with_transcript_evidence || 0}/${s.total || 0}</span></div>` +
    `<div class="quality-scope"><button type="button" data-quality-scope="priority" ` +
    `class="${state.qualityScope === "priority" ? "active" : ""}">重点结论 ${prioritySummary.total || 0}</button>` +
    `<button type="button" data-quality-scope="all" class="${state.qualityScope === "all" ? "active" : ""}">` +
    `全部证据 ${allSummary.total || 0}</button></div>` +
    `<div class="quality-filters">${filters.map(([id, label]) =>
      `<button type="button" data-quality-filter="${id}" class="${state.qualityFilter === id ? "active" : ""}">${label}</button>`
    ).join("")}</div></section>`;

  const claims = quality.claims.filter(qualityClaimVisible);
  if (!claims.length) {
    const emptyTitle = state.qualityScope === "priority" && !(prioritySummary.total || 0)
      ? "没有需要优先审计的重点结论"
      : state.qualityFilter === "pending" ? "这一轮结论已经审计完成" : "此筛选下没有条目";
    html += `<div class="quality-empty"><h3>${emptyTitle}</h3>` +
      `<p class="dim">可以切换范围或筛选，查看保留的背景事实与既有判断。</p></div>`;
  }
  for (const claim of claims) {
    const review = claim.review;
    const stale = claim.previous_review;
    const status = qualityStatusNames[claim.status] || claim.status;
    const kind = qualityClaimKind(claim);
    html += `<article class="quality-card ${review ? `reviewed label-${esc(review.label)}` : ""}" data-quality-claim="${esc(claim.id)}">` +
      `<div class="quality-card-head"><div class="quality-tags"><span>${esc(status)}</span><span>${esc(kind)}</span>` +
      `<span class="${claim.has_transcript_evidence ? "has-evidence" : "missing-evidence"}">` +
      `${claim.turn_ids?.length || 0} 段原文</span><span>${claim.page_ids?.length || 0} 页画面</span></div>` +
      `<button type="button" class="quality-evidence">核对依据</button></div>` +
      `<div class="quality-claim-text">${esc(claim.text)}</div>` +
      (claim.speakers?.length ? `<div class="quality-speakers">发言：${esc(claim.speakers.join("、"))}</div>` : "") +
      (stale ? `<div class="quality-stale">相关内容有变化，原判断“${esc(qualityLabelName(stale.label))}”已失效，请重新核对。</div>` : "") +
      `<div class="quality-labels">${quality.labels.map(item =>
        `<button type="button" data-quality-label="${esc(item.id)}" title="快捷键 ${esc(item.shortcut)}" ` +
        `class="${review?.label === item.id ? "selected" : ""}"><kbd>${esc(item.shortcut)}</kbd>${esc(item.label)}</button>`
      ).join("")}</div>` +
      `<details class="quality-note" ${review?.note ? "open" : ""}><summary>补充说明（可选）</summary>` +
      `<textarea maxlength="1000" rows="2" placeholder="例如：原文是建议语气，尚未确认…">${esc(review?.note || "")}</textarea>` +
      (review ? `<button type="button" class="quality-save-note">保存说明</button>` : `<span class="dim">选择判断时会一并保存</span>`) +
      `</details>` +
      (review ? `<div class="quality-result">已记录：${esc(qualityLabelName(review.label))}</div>` : "") +
      `</article>`;
  }
  box.innerHTML = html;
  $$('[data-quality-scope]', box).forEach(button => {
    button.onclick = () => {
      state.qualityScope = button.dataset.qualityScope;
      renderQualityReview();
    };
  });
  $$('[data-quality-filter]', box).forEach(button => {
    button.onclick = () => {
      state.qualityFilter = button.dataset.qualityFilter;
      renderQualityReview();
    };
  });
  $$(".quality-card", box).forEach(card => {
    const claim = quality.claims.find(item => item.id === card.dataset.qualityClaim);
    if (!claim) return;
    $(".quality-evidence", card).onclick = () => showMinutesEvidence(claim.id);
    $$('[data-quality-label]', card).forEach(button => {
      button.onclick = () => saveQualityReview(
        claim, button.dataset.qualityLabel, $("textarea", card)?.value || "", button);
    });
    const saveNote = $(".quality-save-note", card);
    if (saveNote) saveNote.onclick = () => saveQualityReview(
      claim, claim.review.label, $("textarea", card)?.value || "", saveNote);
  });
}

async function saveQualityReview(claim, label, note, button) {
  if (!state.slug || !claim) return;
  button.disabled = true;
  try {
    const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/quality/claims/${encodeURIComponent(claim.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label, note, claim_fingerprint: claim.fingerprint }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.status);
    state.quality = data;
    updateQualityIndicators();
    renderQualityReview();
    toast(`已记录：${qualityLabelName(label)}`);
  } catch (e) {
    button.disabled = false;
    toast(`审计记录失败：${e.message}`);
  }
}

function qualityShortcut(event) {
  if (state.viewMode !== "quality" || !state.quality || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest("input, textarea, select, button")) return;
  const label = state.quality.labels.find(item => item.shortcut === event.key);
  const card = $("#quality .quality-card");
  if (!label || !card) return;
  const claim = state.quality.claims.find(item => item.id === card.dataset.qualityClaim);
  if (!claim) return;
  event.preventDefault();
  const trigger = $(`[data-quality-label="${label.id}"]`, card);
  saveQualityReview(claim, label.id, $("textarea", card)?.value || "", trigger);
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(value > 100 * 1024 * 1024 ? 0 : 1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

async function openExportDialog() {
  if (!state.slug) return;
  $(".more-menu")?.removeAttribute("open");
  $("#export-mask").classList.remove("hidden");
  $("#export-confirm").disabled = true;
  $("#export-preflight").innerHTML = '<p class="placeholder">正在检查证据、页面与媒体…</p>';
  try {
    state.exportPreflight = await jget(
      `/api/meetings/${encodeURIComponent(state.slug)}/export/preflight`);
    renderExportPreflight();
  } catch (error) {
    $("#export-preflight").innerHTML = `<div class="export-warning">无法检查导出内容（${esc(error.message)}）</div>`;
  }
}

function closeExportDialog() {
  $("#export-mask").classList.add("hidden");
}

function renderExportPreflight() {
  const data = state.exportPreflight;
  if (!data) return;
  const evidenceNames = { ready: "可核证", stale: "依据已过期", partial: "部分证据" };
  const options = [
    ["none", "轻量包", "纪要、脉络、屏幕资料与证据", true],
    ["audio", "分享版音频", `${data.media.audio.format || "AAC"}，可按证据跳转`, data.media.audio.available],
    ["video", "分享版视频", `${data.media.video.format || "720p"}，保留屏幕可读性`, data.media.video.available],
  ];
  const html = `<div class="export-facts">` +
    `<span><b>${esc(evidenceNames[data.evidence.state] || "部分证据")}</b>${data.evidence.linked_claims}/${data.evidence.claims} 条结论有链接</span>` +
    `<span><b>${data.content.transcript_turns}</b>段逐字稿</span>` +
    `<span><b>${data.content.pages}</b>页共享画面</span></div>` +
    `<div class="export-options">${options.map(([id, title, detail, available], index) =>
      `<label class="export-option ${available ? "" : "disabled"}">` +
      `<input type="radio" name="export-media" value="${id}" ${index === 0 ? "checked" : ""} ${available ? "" : "disabled"}>` +
      `<span><b>${title}</b><small>${detail}</small></span>` +
      `<strong>约 ${formatBytes(data.estimated_bytes[id])}</strong></label>`).join("")}</div>` +
    (data.evidence.state === "ready" ? "" :
      '<div class="export-warning">当前包仍可阅读，但部分结论不能回到原文核对。建议重新生成纪要后再正式分享。</div>') +
    '<p class="export-note">包顶层只有 <code>viewer.html</code>、<code>README.txt</code> 和 <code>assets/</code>。音视频是分享压缩版，项目中的原始母版不会被修改。</p>';
  $("#export-preflight").innerHTML = html;
  $("#export-confirm").disabled = false;
}

function exportMeeting(media = "none") {
  if (!state.slug) return;
  closeExportDialog();
  const a = document.createElement("a");
  a.href = `/api/meetings/${encodeURIComponent(state.slug)}/export?media=${encodeURIComponent(media)}`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast(media === "none" ? "正在生成离线查看包（默认不含音视频）…" : `正在生成含${media === "video" ? "视频" : "音频"}的查看包…`);
}

async function openStorageDialog() {
  if (!state.slug) return;
  $(".more-menu")?.removeAttribute("open");
  $("#storage-mask").classList.remove("hidden");
  $("#storage-clean").disabled = true;
  $("#storage-content").innerHTML = '<p class="placeholder">正在计算会议占用…</p>';
  try {
    state.storage = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/storage`);
    renderStorageDialog();
  } catch (error) {
    $("#storage-content").innerHTML = `<div class="export-warning">无法读取存储信息（${esc(error.message)}）</div>`;
  }
}

function closeStorageDialog() {
  $("#storage-mask").classList.add("hidden");
}

function renderStorageDialog() {
  const data = state.storage;
  if (!data) return;
  const groups = data.cache?.groups || [];
  $("#storage-content").innerHTML = `<div class="storage-total"><span>本会议逻辑占用</span>` +
    `<strong>${formatBytes(data.logical_bytes)}</strong><small>CoW/Reflink 共享的数据块可能使实际物理占用更低</small></div>` +
    `<div class="storage-buckets">` +
    `<section><span class="storage-dot original"></span><div><b>原始母版</b><small>${esc(data.policy?.original || "受保护")}</small></div><strong>${formatBytes(data.original?.bytes)}</strong></section>` +
    `<section><span class="storage-dot reading"></span><div><b>阅读资产</b><small>${esc(data.policy?.reading || "默认保留")}</small></div><strong>${formatBytes(data.reading?.bytes)}</strong></section>` +
    `<section><span class="storage-dot cache"></span><div><b>可再生缓存</b><small>${esc(data.policy?.cache || "可重新生成")}</small></div><strong>${formatBytes(data.cache?.bytes)}</strong></section></div>` +
    (groups.length ? `<div class="storage-groups"><b>本次智能清理范围</b>${groups.map(group =>
      `<div><span>${esc(group.label)}<small>${esc(group.regenerates_from)}可恢复 · ${group.files} 个文件</small></span>` +
      `<strong>${formatBytes(group.bytes)}</strong></div>`).join("")}</div>` :
      `<div class="storage-clean-empty">目前没有可安全清理的缓存。原始母版、逻辑页面、逐字稿和纪要均未计入清理范围。</div>`);
  $("#storage-clean").disabled = !data.cache?.reclaimable;
  $("#storage-clean").textContent = data.cache?.reclaimable
    ? `智能清理 · 约 ${formatBytes(data.cache.bytes)}` : "没有可清理缓存";
}

async function cleanMeetingStorage() {
  if (!state.slug || !state.storage?.cache?.reclaimable) return;
  const amount = formatBytes(state.storage.cache.bytes);
  if (!confirm(`清理约 ${amount} 可再生缓存？\n原始母版、逐字稿、纪要、Topic Map 和阅读页面不会删除；重新处理时会再次生成缓存。`)) return;
  const button = $("#storage-clean");
  button.disabled = true;
  button.textContent = "正在清理…";
  try {
    const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/storage/cleanup`,
      { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || response.status);
    state.storage = result.storage;
    renderStorageDialog();
    toast(`已清理 ${formatBytes(result.reclaimed_logical_bytes)} 可再生缓存`);
    await loadMeeting(state.slug);
  } catch (error) {
    button.disabled = false;
    toast(`清理失败：${error.message}`);
  }
}

/* ---------- 本地会议助手：右侧智能栏 + 结构化逐字稿引用 ---------- */

function openUtility(tab = "assistant") {
  const selected = tab === "evidence" ? "evidence" : "assistant";
  state.workspace.utilityOpen = true;
  state.workspace.utilityTab = selected;
  $("#utility-panel").classList.remove("hidden");
  $("#content-shell").classList.add("utility-open");
  $("#assistant-pane").classList.toggle("hidden", selected !== "assistant");
  $("#evidence-pane").classList.toggle("hidden", selected !== "evidence");
  $$('[data-utility-tab]').forEach(button => {
    const active = button.dataset.utilityTab === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  if (selected === "assistant") renderAssistantSuggestions();
  saveWorkspaceState();
}

function closeUtility() {
  state.workspace.utilityOpen = false;
  $("#utility-panel")?.classList.add("hidden");
  $("#content-shell")?.classList.remove("utility-open");
  saveWorkspaceState();
}

function setAssistantThread(open) {
  if (open) openUtility("assistant");
  else closeUtility();
}

function renderAssistantSuggestions() {
  const box = $("#assistant-suggestions");
  if (!box) return;
  if (!state.bundle) {
    box.innerHTML = "";
    return;
  }
  const draft = state.bundle.document_state === "draft";
  const hasClaims = Boolean(state.bundle.evidence?.claims?.length);
  const suggestions = hasClaims
    ? ["这次确认了什么？", "有哪些行动项和负责人？", "还有哪些问题没有解决？"]
    : ["按原文梳理这场会议的讨论主题"];
  box.innerHTML = (draft ? '<p class="assistant-draft-note">当前可以追问语音草稿；修改命令将在多模态终稿后开放。</p>' : "") + suggestions.map(item =>
    `<button type="button" data-assistant-suggestion="${esc(item)}">${esc(item)}</button>`).join("");
  $$('[data-assistant-suggestion]', box).forEach(button => {
    button.onclick = () => {
      openUtility("assistant");
      $("#assistant-input").value = button.dataset.assistantSuggestion;
      $("#assistant-input").focus();
    };
  });
}

function resetAssistant() {
  state.assistantRefs = [];
  state.assistantHistory = [];
  state.assistantMessages = [];
  state.assistantBusy = false;
  state.assistantNextIntent = null;
  if ($("#assistant-refs")) renderAssistantRefs();
  if ($("#assistant-messages")) renderAssistantMessages();
  if ($("#assistant-input")) {
    $("#assistant-input").value = "";
    $("#assistant-input").placeholder = "问这场会议，或告诉我如何修改纪要…";
  }
  renderAssistantSuggestions();
}

function referenceGroups() {
  const indexes = [...new Set(state.assistantRefs)].sort((a, b) => a - b);
  const groups = [];
  for (const idx of indexes) {
    if (!groups.length || idx !== groups[groups.length - 1].at(-1) + 1) groups.push([idx]);
    else groups[groups.length - 1].push(idx);
  }
  return groups;
}

function addReferenceRange(start, end, intent = null) {
  if (!state.bundle) return;
  const lo = Math.max(0, Math.min(start, end));
  const hi = Math.min(state.bundle.transcript.length - 1, Math.max(start, end));
  for (let i = lo; i <= hi; i++) state.assistantRefs.push(i);
  state.assistantRefs = [...new Set(state.assistantRefs)].sort((a, b) => a - b).slice(0, 30);
  state.assistantNextIntent = intent;
  renderAssistantRefs();
  openUtility("assistant");
  if (intent === "edit") {
    $("#assistant-input").placeholder = "说明要怎样把这段内容更新到纪要…";
  } else if (intent === "ask") {
    $("#assistant-input").placeholder = "针对这段逐字稿提问…";
  }
  $("#assistant-input").focus();
}

function renderAssistantRefs() {
  const box = $("#assistant-refs");
  if (!box) return;
  box.innerHTML = "";
  if (!state.bundle || !state.assistantRefs.length) return;
  for (const group of referenceGroups()) {
    const turns = group.map(i => state.bundle.transcript[i]).filter(Boolean);
    if (!turns.length) continue;
    const card = document.createElement("div");
    card.className = "assistant-ref";
    const speakers = [...new Set(turns.map(t => t.speaker))];
    const excerpt = turns.map(t => t.text).join(" ").slice(0, 120);
    card.innerHTML =
      `<button type="button" class="ref-remove" title="移除引用">×</button>` +
      `<b>逐字稿 ${fmt(turns[0].start)}–${fmt(turns.at(-1).end)}</b>` +
      `<span class="dim">${esc(speakers.join("、"))} · ${turns.length}轮</span>` +
      `<span class="ref-excerpt">${esc(excerpt)}${excerpt.length >= 120 ? "…" : ""}</span>`;
    $(".ref-remove", card).onclick = () => {
      const removing = new Set(group);
      state.assistantRefs = state.assistantRefs.filter(i => !removing.has(i));
      renderAssistantRefs();
    };
    card.onclick = ev => {
      if (ev.target.closest(".ref-remove")) return;
      highlightTurns(group);
      seek(turns[0].start);
    };
    box.appendChild(card);
  }
}

function highlightTurns(indexes) {
  $$(".turn.referenced").forEach(el => el.classList.remove("referenced"));
  if (!indexes?.length) return;
  for (const i of indexes) $(`#turn-${i}`)?.classList.add("referenced");
  scrollTranscriptTurn(indexes[0], "center", true);
}

function addAssistantMessage(message) {
  state.assistantMessages.push(message);
  renderAssistantMessages();
}

function citedText(text, sources) {
  const ids = new Set((sources || []).map(s => s.id));
  return esc(text).replace(/【([RT]\d+)】/g, (all, id) =>
    ids.has(id) ? `<button type="button" class="source-link" data-source="${id}">${all}</button>` : all);
}

function showAssistantSource(source) {
  const indexes = source?.turn_indexes || [];
  const turns = indexes.map(index => ({ index, turn: state.bundle?.transcript?.[index] }))
    .filter(item => item.turn);
  let html = `<div class="evidence-claim">${esc(source?.label || source?.id || "助手引用")}</div>`;
  for (const { index, turn } of turns) {
    html += `<div class="evidence-source"><div><b>${esc(turn.speaker)}</b>` +
      `<button type="button" class="evidence-seek" data-index="${index}">${fmt(turn.start)}</button></div>` +
      `<p>${esc(turn.text)}</p></div>`;
  }
  if (!turns.length) html += '<p class="placeholder">这条引用没有可定位的逐字稿片段。</p>';
  $("#evidence-body").innerHTML = html;
  $$(".evidence-seek", $("#evidence-body")).forEach(button => button.onclick = () => {
    const index = Number(button.dataset.index);
    highlightTurns([index]);
    seek(state.bundle.transcript[index]?.start || 0);
  });
  openUtility("evidence");
}

function renderAssistantMessages() {
  const box = $("#assistant-messages");
  if (!box) return;
  if (!state.assistantMessages.length) {
    box.innerHTML = '<p class="placeholder">你可以直接追问整场会议；引用逐字稿后，回答和修改会优先使用这些内容。</p>';
    return;
  }
  box.innerHTML = "";
  for (const msg of state.assistantMessages) {
    const el = document.createElement("div");
    el.className = `assistant-msg ${msg.role}`;
    el.innerHTML = `<div class="msg-role">${msg.role === "user" ? "你" : "助手"}</div>` +
      `<div class="msg-body">${citedText(msg.content, msg.sources)}</div>`;
    if (msg.proposal) {
      const p = msg.proposal;
      if (p.status === "applied") {
        el.innerHTML += `<div class="edit-card edit-result"><span class="applied">已更新会议纪要</span>` +
          `<button type="button" class="undo-edit" data-id="${esc(p.proposal_id)}">撤销</button></div>`;
      } else if (p.status === "undone") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">这次修改已撤销，纪要已恢复。</span></div>';
      } else if (p.status === "cancelled") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">这次修改已取消。</span></div>';
      } else if (p.status === "superseded") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">正在继续调整，旧方案不会写入。</span></div>';
      } else {
        el.innerHTML +=
          `<div class="edit-card">` +
          `<div class="edit-card-kicker">准备更新 · ${esc(p.target_heading)}</div>` +
          `<div class="edit-summary">${esc(p.summary || "已根据要求整理修改")}</div>` +
          `<div class="edit-actions">` +
          `<button type="button" class="apply-edit primary" data-id="${esc(p.proposal_id)}">保存到纪要</button>` +
          `<button type="button" class="adjust-edit">继续调整</button>` +
          `<button type="button" class="dismiss-edit">取消</button>` +
          `</div>` +
          `<div class="edit-after"><span>修改后</span><pre>${esc(p.after || "")}</pre></div>` +
          `<details><summary>查看完整修改与原内容</summary>` +
          `<div class="compare-label">完整修改后</div><pre>${esc(p.after || "")}</pre>` +
          `<div class="compare-label">修改前</div><pre>${esc(p.before || "")}</pre></details></div>`;
      }
    }
    $$(".source-link", el).forEach(btn => {
      btn.onclick = () => {
        const src = (msg.sources || []).find(s => s.id === btn.dataset.source);
        if (!src) return;
        const indexes = src.turn_indexes || [];
        highlightTurns(indexes);
        if (src.start != null) seek(src.start);
        showAssistantSource(src);
      };
    });
    const apply = $(".apply-edit", el);
    if (apply) apply.onclick = () => applyAssistantEdit(apply.dataset.id, apply);
    const undo = $(".undo-edit", el);
    if (undo) undo.onclick = () => undoAssistantEdit(undo.dataset.id, undo);
    const adjust = $(".adjust-edit", el);
    if (adjust) adjust.onclick = () => {
      const p = msg.proposal;
      const msgIndex = state.assistantMessages.indexOf(msg);
      const original = state.assistantMessages.slice(0, msgIndex).reverse()
        .find(item => item.role === "user")?.content || p.summary || "修改纪要";
      p.status = "superseded";
      state.assistantNextIntent = "edit";
      renderAssistantMessages();
      $("#assistant-input").value = `${original}\n请继续调整：`;
      $("#assistant-input").focus();
    };
    const dismiss = $(".dismiss-edit", el);
    if (dismiss) dismiss.onclick = () => {
      msg.proposal.status = "cancelled";
      renderAssistantMessages();
    };
    box.appendChild(el);
  }
  box.scrollTop = box.scrollHeight;
}

function inferAssistantIntent(message) {
  if (state.assistantNextIntent) return state.assistantNextIntent;
  const editPatterns = [
    /(写入|加入|添加|补充|更新|同步).{0,10}(纪要|总结|行动项|决定|结论)/,
    /(纪要|总结|行动项|决定|结论).{0,10}(改成|改为|修改|改写|润色|精简|删除|移除|补充|更新)/,
    /^(请)?(帮我|把|将)?\s*(修改|改写|润色|精简|删除|移除|补充|更新)/,
    /(请|帮我).{0,8}(修改|改写|补充|更新|写入|加入|删除|润色)/,
    /(把|将).{0,20}(改成|改为|写入|加入|补充到|删除)/,
  ];
  return editPatterns.some(pattern => pattern.test(message)) ? "edit" : "ask";
}

function assistantError(detail) {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.detail === "string") return detail.detail;
  return "请求失败";
}

async function sendAssistant() {
  if (!state.slug || state.assistantBusy) return;
  const input = $("#assistant-input");
  const message = input.value.trim();
  if (!message) return;
  const intent = inferAssistantIntent(message);
  if (intent === "edit" && state.bundle?.document_state === "draft") {
    state.assistantNextIntent = null;
    addAssistantMessage({ role: "user", content: message, sources: [] });
    addAssistantMessage({ role: "assistant", content: "当前是语音草稿，屏幕表格和画面依据还在补充。等多模态终稿替换完成后再修改，避免这次编辑被终稿覆盖。", sources: [] });
    input.value = "";
    setAssistantThread(true);
    return;
  }
  state.assistantNextIntent = null;
  const common = {
    message,
    turn_indexes: state.assistantRefs,
    transcript_revision: state.bundle.transcript_revision,
  };
  const path = intent === "edit"
    ? `/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/preview`
    : `/api/meetings/${encodeURIComponent(state.slug)}/assistant/chat`;
  const body = intent === "edit"
    ? { ...common, minutes_revision: state.bundle.minutes_revision }
    : { ...common, history: state.assistantHistory.slice(-8) };
  addAssistantMessage({ role: "user", content: message, sources: [] });
  setAssistantThread(true);
  input.value = "";
  input.placeholder = "问这场会议，或告诉我如何修改纪要…";
  state.assistantBusy = true;
  $("#assistant-send").disabled = true;
  $("#assistant-state").textContent = intent === "edit" ? "正在生成修改预览…" : "正在查找证据并回答…";
  try {
    const r = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(assistantError(j.detail));
    if (intent === "edit") {
      addAssistantMessage({
        role: "assistant",
        content: "我整理了一项纪要更新，请确认后再保存。",
        sources: j.sources || [],
        proposal: j,
      });
    } else {
      addAssistantMessage({ role: "assistant", content: j.answer, sources: j.sources || [] });
      state.assistantHistory.push({ role: "user", content: message });
      state.assistantHistory.push({ role: "assistant", content: j.answer });
      state.assistantHistory = state.assistantHistory.slice(-8);
    }
  } catch (e) {
    addAssistantMessage({ role: "assistant", content: `无法完成：${e.message}`, sources: [] });
  } finally {
    state.assistantBusy = false;
    $("#assistant-send").disabled = false;
    $("#assistant-state").textContent = "";
  }
}

async function applyAssistantEdit(proposalId, button) {
  button.disabled = true;
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id: proposalId }),
  });
  const j = await r.json();
  if (!r.ok) {
    button.disabled = false;
    addAssistantMessage({ role: "assistant", content: `应用失败：${assistantError(j.detail)}`, sources: [] });
    return;
  }
  state.bundle = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
  renderMinutes();
  const msg = state.assistantMessages.find(item => item.proposal?.proposal_id === proposalId);
  if (msg) msg.proposal.status = "applied";
  renderAssistantMessages();
}

async function undoAssistantEdit(proposalId, button) {
  button.disabled = true;
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/undo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id: proposalId }),
  });
  const j = await r.json();
  if (!r.ok) {
    button.disabled = false;
    addAssistantMessage({ role: "assistant", content: `撤销失败：${assistantError(j.detail)}`, sources: [] });
    return;
  }
  state.bundle = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
  renderMinutes();
  const msg = state.assistantMessages.find(item => item.proposal?.proposal_id === proposalId);
  if (msg) msg.proposal.status = "undone";
  renderAssistantMessages();
}

function setupTranscriptSelection() {
  $("#transcript").addEventListener("mouseup", () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    const startEl = (range.startContainer.nodeType === 1
      ? range.startContainer : range.startContainer.parentElement)?.closest?.(".turn");
    const endEl = (range.endContainer.nodeType === 1
      ? range.endContainer : range.endContainer.parentElement)?.closest?.(".turn");
    if (!startEl || !endEl) return;
    const rect = range.getBoundingClientRect();
    const pop = $("#quote-pop");
    pop.dataset.start = startEl.dataset.index;
    pop.dataset.end = endEl.dataset.index;
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 290, rect.right + 8))}px`;
    pop.style.top = `${Math.max(8, rect.top - 36)}px`;
    pop.classList.remove("hidden");
  });
  $$("#quote-pop [data-intent]").forEach(btn => {
    btn.onclick = () => {
      const pop = $("#quote-pop");
      addReferenceRange(Number(pop.dataset.start), Number(pop.dataset.end), btn.dataset.intent);
      pop.classList.add("hidden");
      window.getSelection()?.removeAllRanges();
    };
  });
  document.addEventListener("mousedown", ev => {
    if (!ev.target.closest("#quote-pop") && !ev.target.closest("#transcript"))
      $("#quote-pop").classList.add("hidden");
  });
}

async function regenMinutes(refineModel) {
  if (!state.slug) return;
  const qs = refineModel ? `?refine=${encodeURIComponent(refineModel)}` : "";
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/regen_minutes${qs}`,
    { method: "POST" });
  const job = await r.json();
  if (!r.ok) { toast(`重生成失败: ${job.detail || r.status}`); return; }
  toast(`纪要${refineModel ? "精修" : "重生成"}作业 ${job.id} 已排队…`);
  pollJob(job.id, j => {
    if (j.status === "done") {
      toast(`纪要${refineModel ? "精修" : "重生成"}完成 (${job.id})`);
      loadMeeting(state.slug);
    } else if (j.status === "failed" || j.status === "cancelled") {
      toast(`作业 ${job.id} ${j.status}，详情见 /api/jobs/${job.id}`);
    } else {
      toast(`作业 ${job.id} ${j.status}…`);
    }
  });
}

/* ---------- 说话人绑定弹框 ---------- */

async function ensureSpeakers() {
  if (!state.speakers) state.speakers = await jget("/api/speakers");
  return state.speakers;
}

async function openBind(voice, name) {
  $("#bind-voice").textContent = voice;
  $("#bind-name").textContent = name;
  $("#bind-input").value = "";
  $("#bind-cands").innerHTML = "";
  const sp = await ensureSpeakers();
  $("#person-list").innerHTML =
    sp.persons.flatMap(p => (p.names || [{ value: p.name }])
      .map(n => `<option value="${esc(n.value)}">${esc(p.display_name || p.name)}</option>`)).join("");
  const sample = $("#bind-sample");
  sample.src = `/api/speakers/${encodeURIComponent(voice)}/sample`;
  sample.onerror = () => { sample.style.display = "none"; };
  sample.style.display = "";
  $("#bind-mask").classList.remove("hidden");
  $("#bind-input").focus();
  $("#bind-ok").onclick = () => doBind(voice);
}

function closeBind() { $("#bind-mask").classList.add("hidden"); }

async function doBind(voice, create) {
  const name = $("#bind-input").value.trim();
  if (!name) return;
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/bind`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice, name, create: !!create }),
  });
  const j = await r.json();
  if (r.status === 409) {
    // 未精确命中 → 展示候选(点击回填) + “新建此人”按钮
    const d = j.detail || {};
    const cands = d.candidates || [];
    let html = cands.length
      ? "候选：" + cands.map(c =>
        `<button type="button" class="cand" data-name="${esc(c.name)}">${esc(c.name)}</button>`).join("")
      : "库里没有这个名字。";
    html += `<button type="button" id="bind-create" class="cand create">新建「${esc(name)}」</button>`;
    $("#bind-cands").innerHTML = html;
    $$("#bind-cands .cand[data-name]").forEach(btn =>
      btn.onclick = () => { $("#bind-input").value = btn.dataset.name; });
    const cb = $("#bind-create");
    if (cb) cb.onclick = () => doBind(voice, true);
    return;
  }
  if (!r.ok) { toast(`绑定失败: ${j.detail || r.status}`); return; }
  closeBind();
  state.speakers = null;  // 库已变，刷新缓存
  resetAssistant();       // 逐字稿 revision 已变化，旧引用作废
  toast(`已绑定为 ${j.name}（${j.turns} 轮）`);
  await loadMeeting(state.slug);  // 逐字稿立即更新
}

/* ---------- 上传与作业 ---------- */

async function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  if ($("#skip-vl") && $("#skip-vl").checked) fd.append("no_vl", "1");
  const r = await api("/api/upload", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) { toast(`上传被拒: ${j.detail || r.status}`); return; }
  toast(`作业 ${j.id} (${j.route}) 已创建，目标会议 ${j.meeting}`);
  let draftOpened = false;
  pollJob(j.id, async jj => {
    const logs = (jj.log || []).map(String);
    if (!draftOpened && logs.some(line => line.includes("语音草稿已可阅读"))) {
      draftOpened = true;
      state.progressiveRefreshes.add(`${j.id}:draft`);
      toast("语音草稿已可阅读，正在补充屏幕资料…");
      await loadMeetings();
      if (state.bundle) rememberReadingPosition();
      await loadMeeting(j.meeting);
      return;
    }
    if (jj.status === "done") {
      const key = `${j.id}:final`;
      if (state.progressiveRefreshes.has(key)) return;
      state.progressiveRefreshes.add(key);
      toast(`作业 ${j.id} 完成，已升级为多模态终稿`);
      if (state.bundle) rememberReadingPosition();
      await loadMeetings();
      if (state.slug === j.meeting || draftOpened) await loadMeeting(j.meeting);
    } else if (jj.status === "failed") {
      toast(`作业 ${j.id} 失败 (rc=${jj.rc})`);
    } else {
      toast(`作业 ${j.id} (${j.route}): ${jj.status}`);
    }
  });
}

function pollJob(id, onUpdate) {
  if (state.poller) clearInterval(state.poller);
  state.poller = setInterval(async () => {
    try {
      const j = await jget(`/api/jobs/${id}`);
      onUpdate(j);
      if (["done", "failed", "cancelled"].includes(j.status)) {
        clearInterval(state.poller);
        state.poller = null;
      }
    } catch (e) { /* 网络抖动忽略 */ }
  }, 2000);
}

/* ---------- 作业队列面板 ---------- */

async function pollJobs() {
  try {
    const d = await jget("/api/jobs");
    state.jobPriorityAvailable = d.capabilities?.job_priority === true;
    renderJobs(d.jobs);
  } catch (e) { /* 忽略 */ }
}

function renderJobs(jobs) {
  const ul = $("#jobs-list");
  if (!ul) return;
  const activeJobs = jobs.filter(j => j.status === "queued" || j.status === "running")
    .sort((a, b) => a.status === b.status
      ? Number(a.queue_position || 9999) - Number(b.queue_position || 9999)
      : a.status === "running" ? -1 : 1);
  const activeMeetings = new Set(activeJobs.map(job => job.meeting).filter(Boolean));
  const recentFailures = jobs.filter(j => j.status === "failed"
    && !activeMeetings.has(j.meeting)
    && Date.now() / 1000 - Number(j.finished || j.created || 0) < 60 * 60).slice(0, 2);
  const visibleJobs = [...activeJobs, ...recentFailures]
    .filter((job, index, all) => all.findIndex(item => item.id === job.id) === index);
  state.activeJobs = activeJobs;
  $("#jobs-panel").classList.toggle("hidden", visibleJobs.length === 0);
  $(".jobs-head").textContent = activeJobs.length
    ? (isEnglishUi() ? "Processing" : "正在处理") : (isEnglishUi() ? "Recent failures" : "最近处理失败");
  ul.innerHTML = "";
  for (const j of visibleJobs.slice(0, 8)) {
    const li = document.createElement("li");
    const active = j.status === "queued" || j.status === "running";
    const meeting = state.meetings.find(item => item.slug === j.meeting);
    const name = meeting?.title || j.meeting || "会议处理";
    const kindLabel = j.kind === "translation"
      ? `${translationTargetLabel(j.target_language)} ${j.translation_artifact === "minutes"
        ? (isEnglishUi() ? "minutes" : "纪要") : (isEnglishUi() ? "transcript" : "逐字稿")} ${isEnglishUi() ? "translation" : "翻译"}`
      : j.kind === "regen" ? "生成纪要" : j.kind === "topic_map" ? "生成会议脉络"
      : j.kind === "upload" ? "会议处理" : "";
    const progress = j.progress?.total
      ? ` ${j.progress.done || 0}/${j.progress.total}` : "";
    const lastLog = String(j.log?.at(-1) || "");
    const voiceDraftFailed = (j.log || []).some(line => String(line).includes("语音草稿生成失败"));
    const stepMatch = lastLog.match(/^\[(\d+)\/(\d+)\]/);
    const step = stepMatch ? ` ${stepMatch[1]}/${stepMatch[2]}` : "";
    const vlPage = lastLog.match(/^\[meta\] VL 第(\d+)页/);
    const vlTotal = [...(j.log || [])].reverse()
      .map(line => String(line).match(/逻辑页\s+(\d+)\s+页/)).find(Boolean);
    const liveProgress = vlPage && vlTotal ? ` ${vlPage[1]}/${vlTotal[1]}` : (progress || step);
    const liveStage = /语音草稿|voice draft/i.test(lastLog) ? "生成语音草稿"
      : /多模态纪要|升级多模态|补充屏幕资料/i.test(lastLog) ? "升级多模态纪要"
      : /topic map|会议脉络|论点/i.test(lastLog) ? "构建会议脉络"
      : /抽屏幕|逻辑页/.test(lastLog) ? "提取共享画面"
      : /生成按页纪要|生成.*纪要|结构化输入|总体摘要|页块|分页详情/.test(lastLog) ? "生成会议纪要"
      : /声纹库|声纹/.test(lastLog) ? "确认人员身份"
      : /解析 VTT|对齐姓名/.test(lastLog) ? "对齐参会者"
      : j.stage;
    const elapsed = j.status === "running" && j.started
      ? ` · 已运行 ${fmt(Date.now() / 1000 - j.started)}` : "";
    const queueLabel = j.status === "queued" && j.queue_position
      ? (j.priority_boost ? "优先 · 下一项" : `队列第 ${j.queue_position}`) : "";
    const status = j.status === "queued" ? `${kindLabel ? `${kindLabel} · ` : ""}等待处理` +
        `${queueLabel ? ` · ${queueLabel}` : ""}`
      : j.status === "failed" ? `失败 · ${liveStage || "处理阶段"}`
      : `${kindLabel ? `${kindLabel} · ` : ""}${liveStage || "处理中"}${liveProgress}` +
        `${voiceDraftFailed ? " · 草稿未生成" : ""}${elapsed}`;
    li.classList.toggle("job-failed", j.status === "failed");
    li.innerHTML =
      `<span class="j-name" title="${esc(j.id)}">${esc(name)}</span>` +
      `<span class="j-st st-${esc(j.status)}">${esc(status)}</span>`;
    if (active) {
      const actions = document.createElement("div");
      actions.className = "j-actions";
      if (state.jobPriorityAvailable && j.status === "queued"
          && (!j.priority_boost || Number(j.queue_position) > 1)) {
        const priority = document.createElement("button");
        priority.type = "button";
        priority.className = "j-priority";
        priority.textContent = "优先";
        priority.title = "排到当前运行任务之后；不会中断正在运行的任务";
        priority.onclick = async () => {
          const response = await api(`/api/jobs/${j.id}/prioritize`, { method: "POST" });
          if (!response.ok) {
            const detail = await response.json();
            toast(`调整失败：${detail.detail || response.status}`);
          } else {
            toast(`${name} 已设为下一项`);
          }
          pollJobs();
        };
        actions.appendChild(priority);
      }
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "j-cancel";
      cancel.textContent = "取消";
      cancel.onclick = async () => {
        await api(`/api/jobs/${j.id}/cancel`, { method: "POST" });
        pollJobs();
      };
      actions.appendChild(cancel);
      li.appendChild(actions);
    }
    li.title = (j.log || []).slice(-1)[0] || j.id;
    ul.appendChild(li);
  }
  renderMeetingStatuses();
}

/* ---------- 事件 ---------- */

function setPaneRatio(value) {
  state.workspace.paneRatio = Math.min(68, Math.max(32, Number(value) || 44));
  $("#review-grid").style.setProperty("--transcript-ratio", `${state.workspace.paneRatio}%`);
  $("#pane-resizer").setAttribute("aria-valuenow", String(Math.round(state.workspace.paneRatio)));
  saveWorkspaceState();
}

function setMeetingLibrary(open) {
  document.body.classList.toggle("library-open", open);
  $("#library-toggle").setAttribute("aria-expanded", String(open));
  $("#library-scrim").classList.toggle("hidden", !open);
}

function closeMeetingLibrary() { setMeetingLibrary(false); }

function setupPaneResizer() {
  const handle = $("#pane-resizer");
  const grid = $("#review-grid");
  setPaneRatio(state.workspace.paneRatio);
  let dragging = false;
  handle.addEventListener("pointerdown", event => {
    if (window.innerWidth <= 820) return;
    dragging = true;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing-panes");
    event.preventDefault();
  });
  handle.addEventListener("pointermove", event => {
    if (!dragging) return;
    const bounds = grid.getBoundingClientRect();
    setPaneRatio((event.clientX - bounds.left) / bounds.width * 100);
  });
  const finish = event => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove("resizing-panes");
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
  };
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  handle.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    setPaneRatio(state.workspace.paneRatio + (event.key === "ArrowRight" ? 2 : -2));
  });
}

function screenPreviewShortcut(event) {
  if ($("#screen-preview-mask")?.classList.contains("hidden")) return;
  if (event.key === "Escape") closeScreenPreview();
  else if (event.key === "ArrowLeft") navigateScreenPreview(-1);
  else if (event.key === "ArrowRight") navigateScreenPreview(1);
  else if (["+", "="].includes(event.key)) changeScreenPreviewZoom(1);
  else if (event.key === "-") changeScreenPreviewZoom(-1);
  else return;
  event.preventDefault();
  event.stopImmediatePropagation();
}

function init() {
  applyUiLanguage();
  $$('[data-ui-language]').forEach(button =>
    button.onclick = () => setUiLanguage(button.dataset.uiLanguage));
  $("#search").addEventListener("input", renderMeetingList);
  $("#regen-btn").onclick = () => regenMinutes("");
  $("#refine-btn").onclick = () => {
    if (confirm("用 122B 大模型整体重写纪要？首次调用需加载模型(数分钟)，且会挤占常驻模型。"))
      regenMinutes("qwen3.5-122b-a10b-planner");
  };
  $("#export-btn").onclick = openExportDialog;
  $("#storage-btn").onclick = openStorageDialog;
  $("#minutes-tab").onclick = () => setReviewMode("minutes");
  $("#chapters-tab").onclick = () => setReviewMode("chapters");
  $("#visuals-tab").onclick = () => setReviewMode("visuals");
  $("#quality-tab").onclick = () => setReviewMode("quality");
  $("#quality-entry-btn").onclick = () => setReviewMode("quality");
  $("#translation-control").onclick = () => {
    if (state.translationJob) stopTranscriptTranslation();
    else startTranscriptTranslation([...state.evidenceBilingual]);
  };
  $$('[data-transcript-mode]').forEach(button => {
    button.onclick = () => setTranscriptMode(button.dataset.transcriptMode);
  });
  $("#translation-target").onchange = event => setTranslationTarget(event.target.value);
  document.addEventListener("keydown", qualityShortcut);
  $("#bind-cancel").onclick = closeBind;
  $("#bind-mask").addEventListener("click", e => { if (e.target.id === "bind-mask") closeBind(); });

  $("#assistant-launcher").onclick = () => openUtility("assistant");
  $("#utility-close").onclick = closeUtility;
  $$('[data-utility-tab]').forEach(button =>
    button.onclick = () => openUtility(button.dataset.utilityTab));
  $("#assistant-send").onclick = sendAssistant;
  $("#assistant-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendAssistant();
    }
  });
  setupTranscriptSelection();
  setupPaneResizer();
  $("#library-toggle").onclick = () =>
    setMeetingLibrary(!document.body.classList.contains("library-open"));
  $("#library-scrim").onclick = closeMeetingLibrary;
  $("#transcript").addEventListener("scroll", rememberReadingPosition, { passive: true });
  $("#minutes").addEventListener("scroll", rememberReadingPosition, { passive: true });
  $("#player-toggle").onclick = () => {
    state.workspace.videoExpanded = !state.workspace.videoExpanded;
    $("#player-box").classList.toggle("compact", !state.workspace.videoExpanded);
    $("#player-toggle").textContent = state.workspace.videoExpanded ? ui("collapsing") : ui("expanding");
    $("#player-toggle").setAttribute("aria-expanded", String(state.workspace.videoExpanded));
    saveWorkspaceState();
  };

  $("#export-close").onclick = closeExportDialog;
  $("#export-cancel").onclick = closeExportDialog;
  $("#export-confirm").onclick = () => {
    const media = $('input[name="export-media"]:checked', $("#export-preflight"))?.value || "none";
    exportMeeting(media);
  };
  $("#export-mask").addEventListener("click", event => {
    if (event.target.id === "export-mask") closeExportDialog();
  });
  $("#storage-close").onclick = closeStorageDialog;
  $("#storage-cancel").onclick = closeStorageDialog;
  $("#storage-clean").onclick = cleanMeetingStorage;
  $("#storage-mask").addEventListener("click", event => {
    if (event.target.id === "storage-mask") closeStorageDialog();
  });
  $("#screen-preview-close").onclick = closeScreenPreview;
  $("#screen-preview-prev").onclick = () => navigateScreenPreview(-1);
  $("#screen-preview-next").onclick = () => navigateScreenPreview(1);
  $("#screen-preview-zoom-out").onclick = () => changeScreenPreviewZoom(-1);
  $("#screen-preview-zoom-in").onclick = () => changeScreenPreviewZoom(1);
  $("#screen-preview-zoom").onclick = () => {
    state.screenPreview.zoomIndex = 0;
    applyScreenPreviewZoom();
  };
  $("#screen-preview-mask").addEventListener("click", event => {
    if (event.target.id === "screen-preview-mask") closeScreenPreview();
  });
  $("#screen-preview-image").ondblclick = () => {
    state.screenPreview.zoomIndex = state.screenPreview.zoomIndex ? 0 : 3;
    applyScreenPreviewZoom();
  };
  document.addEventListener("keydown", screenPreviewShortcut, { capture: true });

  const dz = $("#dropzone");
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", e => {
    e.preventDefault();
    dz.classList.remove("over");
    uploadFiles(e.dataTransfer.files);
  });
  $("#pick-btn").onclick = () => $("#file-input").click();
  $("#file-input").addEventListener("change", e => uploadFiles(e.target.files));

  pollJobs();
  setInterval(pollJobs, 4000);
  loadMeetings();
}

document.addEventListener("DOMContentLoaded", init);
