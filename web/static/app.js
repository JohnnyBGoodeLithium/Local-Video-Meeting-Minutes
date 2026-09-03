import { contentTypeOf, safeSourceUrl }
  from "./modules/media-source.js?v=20260903p114";
import { buildUploadFormData, enqueueMediaUrl, isSingleLocalVideo }
  from "./modules/imports.js?v=20260903p114";
import { jobDisplayName, jobTaskLabel, selectJobPanel }
  from "./modules/jobs.js?v=20260903p114";
import { jobPresentation }
  from "./modules/job-progress.js?v=20260903p114";
import { closeJobSheet, renderCompactJob, renderJobSheet, renderProcessingBanner }
  from "./modules/job-progress-view.js?v=20260903p114";
import { chooseInitialItem, deepLinkSeconds, filterLibrary, sortLibrary }
  from "./modules/library.js?v=20260903p114";
import { adjacentReviewUnit, defaultReviewUnits, nearestReviewUnit,
  reviewIndexesFor, reviewUnitForTurn as findReviewUnitForTurn, turnEnd }
  from "./modules/player-navigation.js?v=20260903p114";
import { nextSearchCursor, pendingReviewByTurn, transcriptSearchHits }
  from "./modules/transcript.js?v=20260903p114";
import { renderTranscriptView }
  from "./modules/transcript-view.js?v=20260903p114";
import { availableViewerMedia, exportSizeState, formatBytes, meetingExportHref, normalizeExportProfile,
  packExportHref }
  from "./modules/export.js?v=20260903p114";
import { claimAction, claimIdsForTurn, evidenceSources, minutesState, normalizeReviewMode,
  resolveMinutesView, turnIndexAtTime, turnIndexesForSourceIds }
  from "./modules/minutes.js?v=20260903p114";
import { renderMinutesView }
  from "./modules/minutes-view.js?v=20260903p114";
import { beginExampleSelection, beginIdentity, buildCorrectionApplyPayload,
  correctionSummary, createSpeakerCorrectionState, representativeTurns,
  resetSpeakerCorrection, setGroupAssignment, setIncludeSuggested, setPreview,
  toggleExample, withCorrectionError }
  from "./modules/speaker-correction.js?v=20260903p114";
import { renderCorrectionSheet, renderIdentityPopover }
  from "./modules/speaker-correction-view.js?v=20260903p114";
import { beginPhotoImport, createPhotoImportState, hydratePhotoCaptureTimes,
  markPhotoImportResult, photoUploadSpec, releasePhotoImport, removePhotoImportItem,
  setPhotoMeetingStart, setPhotoPositionMode, togglePhotoTimeSettings,
  withPhotoImportBusy, withPhotoImportError, formatPhotoBytes }
  from "./modules/photo-import.js?v=20260903p114";
import { renderPhotoImport }
  from "./modules/photo-import-view.js?v=20260903p114";
import { mountLiveContext }
  from "./modules/live-context-view.js?v=20260903p114";

/* 会议列表 + 回顾工作台（装配入口；领域规则逐步迁往 modules/） */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const WORKSPACE_KEY = "meeting-minutes:workspace:v1";
let liveContextView = null;

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
  assistantSlug: null,
  quality: null,
  qualityFilter: "pending",
  qualityScope: "priority",
  viewMode: ["minutes", "chapters", "visuals", "quality"].includes(requestedView)
    ? requestedView : "minutes",
  selectedChapterId: null,
  selectedTopicId: null,
  selectedTopicNodeId: null,
  selectedVisualId: null,
  focus: { mode: "overview", time: null, ranges: [], topicId: null, nodeId: null, person: null,
    turnIds: [], claimIds: [], pageIds: [], source: "overview" },
  screenPreview: { visualId: null, zoomIndex: 0, returnFocus: null },
  speakerColorCache: null,
  legendShowAll: false,
  personLanes: false,
  personLanesAll: false,
  speakerPin: null,
  speakerHover: null,
  reviewTurnIndex: null,
  playbackScope: "meeting",
  transcriptSearch: null,
  reviewUnits: [],
  speakerCorrection: createSpeakerCorrectionState(),
  speakerCorrectionReview: null,
  speakerCorrectionChoice: "",
  visualFilter: "useful",
  uiLanguage: UI_LANGUAGES.has(workspaceState.uiLanguage) ? workspaceState.uiLanguage : "zh-CN",
  minutesTranslation: null,
  minutesTranslationJob: null,
  minutesTranslationPoller: null,
  topicMapTranslation: null,
  topicMapTranslationJob: null,
  topicMapTranslationPoller: null,
  visualsTranslation: null,
  visualsTranslationJob: null,
  visualsTranslationPoller: null,
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
    meetingSort: ["imported", "meeting", "updated"].includes(workspaceState.meetingSort)
      ? workspaceState.meetingSort : "imported",
    contentType: workspaceState.contentType === "media" ? "media" : "meeting",
    translationTargets: workspaceState.translationTargets
      && typeof workspaceState.translationTargets === "object"
      ? workspaceState.translationTargets : {},
    minutesViews: workspaceState.minutesViews && typeof workspaceState.minutesViews === "object"
      ? workspaceState.minutesViews : {},
    anchors: workspaceState.anchors && typeof workspaceState.anchors === "object"
      ? workspaceState.anchors : {},
  },
  activeJobs: [],
  jobs: [],
  jobPriorityAvailable: false,
  jobPreemptionAvailable: false,
  jobRecoveryAvailable: false,
  jobHideAvailable: false,
  jobSheet: { jobId: null, mode: null, returnFocus: null, options: {} },
  bundleLoadedAt: 0,
  refreshedArtifactJobs: new Set(),
  bundleRefreshInFlight: false,
  exportPreflight: null,
  exportRelated: [],
  storage: null,
  progressiveRefreshes: new Set(),
  transcriptReview: null,
  transcriptEditIndex: null,
  photoImport: createPhotoImportState(),
  pendingPhotoEntry: "materials",
  pendingPhotoReturnFocus: null,
  photoRenameId: null,
  photoDeleteTarget: null,
  photoDeleteReturnFocus: null,
  knowledgePreflight: null,
};

/* ---------- 工具 ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const UI_COPY = {
  "zh-CN": {
    title: "会议纪要", brand: "🎙 会议纪要", meetings: "会议", product: "产品介绍", knowledgeBase: "知识库", settings: "设置",
    import: "导入会议", importMedia: "导入媒体视频", drop: "或拖入视频 + VTT/DOCX，或单个音视频",
    dropMedia: "或拖入一个本地视频", importSettings: "导入设置",
    mediaUrlDivider: "或粘贴公开视频链接", mediaUrlPlaceholder: "YouTube、Bilibili 或公开网页视频链接",
    mediaUrlSubmit: "解析链接", mediaUrlHint: "将获取平台标题、发布者和发布时间；不导入播放列表或直播",
    sourceLink: "↗ 查看原视频",
    processingMode: "处理方式", fullAnalysis: "完整分析",
    fullAnalysisDetail: "先提供逐字稿和语音草稿，再理解画面并生成完整结果",
    skipVl: "快速纪要", fastAnalysisDetail: "跳过画面理解，但仍生成纪要和会议脉络；之后可以补充",
    ignoreTranscript: "忽略附带逐字稿，改用本地语音识别",
    search: "搜索会议…", sortImported: "最近导入", sortMeeting: "会议时间", sortUpdated: "最近更新", transcript: "逐字稿",
    original: "原文", translated: "译文", comparison: "对照", translateTo: "译为", follow: "跟随",
    outline: "会议脉络", minutes: "会议纪要", screens: "画面与资料", audit: "核对关键结论",
    assistant: "AI 对话", evidence: "证据", send: "发送", restructure: "✦ 重组纪要",
    restructurePlaceholder: "描述你希望的栏目、顺序、读者和详略，例如：先给管理层结论，再按项目列进展、分歧、风险和有依据的待办。",
    ask: "问这场会议，或告诉我如何修改纪要…", launcher: "问这场会议，或修改纪要…",
    expanding: "展开画面", collapsing: "收起画面", sourceMinutes: "正在显示原始语言纪要",
    translatingMinutes: "正在生成中文纪要，完成后自动切换", minutesFailed: "中文纪要生成失败，可再次切换重试",
    translatingOutline: "正在生成中文会议脉络，完成后自动切换", outlineFailed: "中文会议脉络生成失败，可再次切换重试",
    speakerPinTip: "悬停在主时间轴只看他的发言，点击钉住",
    gapTip: "议题未覆盖，点击跳转",
    transitionTip: "过渡或等待，点击跳转",
    unclassifiedTip: "尚未归入议题，点击跳转",
    seekHint: "点击跳转；悬停查看发言构成", othersChip: "其他", collapseChip: "收起",
    expandLanes: "说话人视图 ▸", collapseLanes: "说话人视图 ▾", expandRestLanes: "展开其余",
    allSpeakers: "全部说话人", fullMeeting: "顺次播放", speakerOnly: "仅听此人",
    previousUtterance: "上一段", replayUtterance: "重播本段", nextUtterance: "下一段",
    clearSpeaker: "取消人物", utteranceUnit: "个核听段落",
    bindAction: "绑定", legendBindAction: "未绑定声纹：点「绑定」为其指定人员",
    speakerUnavailable: "当前声音过短，未形成可用声音簇，不能按人播放",
    undoSpeaker: "撤销上次说话人修改",
    lowValueHint: "过渡或低讨论密度时段", continued: "同一发言",
    contentTypeMeeting: "会议", contentTypeMedia: "媒体",
    emptyMeetingList: "暂无会议，从上方导入后在这里阅读",
    emptyMediaList: "暂无媒体条目；可在条目的“更多”菜单标记为媒体视频",
  },
  en: {
    title: "Meeting Minutes", brand: "🎙 Meeting Minutes", meetings: "Meetings", product: "Product", knowledgeBase: "Knowledge base", settings: "Settings",
    import: "Import meeting", importMedia: "Import media video", drop: "Drop video + VTT/DOCX, or one media file",
    dropMedia: "Or drop one local video", importSettings: "Import settings",
    mediaUrlDivider: "or paste a public video URL", mediaUrlPlaceholder: "YouTube, Bilibili, or a public web video URL",
    mediaUrlSubmit: "Parse URL", mediaUrlHint: "Retrieves platform title, publisher, and publish date; playlists and live streams are not supported",
    sourceLink: "↗ Open original video",
    processingMode: "Processing mode", fullAnalysis: "Full analysis",
    fullAnalysisDetail: "Makes the transcript and voice draft available first, then understands visuals and creates the complete result",
    skipVl: "Fast minutes", fastAnalysisDetail: "Skips visual understanding but still creates minutes and a meeting map; visuals can be added later",
    ignoreTranscript: "Ignore attached transcript and use local speech recognition",
    search: "Search meetings…", sortImported: "Recently imported", sortMeeting: "Meeting time", sortUpdated: "Recently updated", transcript: "Transcript",
    original: "Original", translated: "Translation", comparison: "Side by side", translateTo: "Translate to", follow: "Follow",
    outline: "Meeting map", minutes: "Minutes", screens: "Visuals & Materials", audit: "Review key conclusions",
    assistant: "AI chat", evidence: "Evidence", send: "Send", restructure: "✦ Restructure",
    restructurePlaceholder: "Describe the sections, order, audience, and level of detail you want, for example: executive decisions first, then progress, disagreements, risks, and evidenced actions by project.",
    ask: "Ask about this meeting or request a minutes edit…", launcher: "Ask about or edit this meeting…",
    expanding: "Expand screen", collapsing: "Collapse screen", sourceMinutes: "Showing minutes in their original language",
    translatingMinutes: "Generating English minutes; this view will update automatically",
    minutesFailed: "English minutes generation failed; switch again to retry",
    translatingOutline: "Generating the English meeting map; this view will update automatically",
    outlineFailed: "English meeting-map generation failed; switch again to retry",
    speakerPinTip: "Hover to isolate this speaker on the timeline; click to pin",
    gapTip: "Not covered by topics; click to jump",
    transitionTip: "Transition or waiting; click to jump",
    unclassifiedTip: "Not yet classified into a topic; click to jump",
    seekHint: "Click to jump; hover for speaker mix", othersChip: "Others", collapseChip: "Collapse",
    expandLanes: "Speaker view ▸", collapseLanes: "Speaker view ▾",
    expandRestLanes: "Show the remaining", bindAction: "Bind",
    allSpeakers: "All speakers", fullMeeting: "Full meeting", speakerOnly: "Speaker only",
    previousUtterance: "Previous", replayUtterance: "Replay", nextUtterance: "Next",
    clearSpeaker: "Clear person", utteranceUnit: "review segments",
    legendBindAction: "No voiceprint bound: use “Bind” to assign a person",
    speakerUnavailable: "This sample is too short to form a usable voice cluster",
    undoSpeaker: "Undo last speaker change",
    lowValueHint: "Transitional or low-density segment", continued: "Same utterance",
    contentTypeMeeting: "Meetings", contentTypeMedia: "Media",
    emptyMeetingList: "No meetings yet; import one above to start reading",
    emptyMediaList: "No media items yet; use “Mark as media” in an item's More menu",
  },
};

function ui(key) { return UI_COPY[state.uiLanguage]?.[key] || UI_COPY["zh-CN"][key] || key; }
function isEnglishUi() { return state.uiLanguage === "en"; }

/* 内容类型标签字典：media 与 meeting 共用管线/索引/导出，只在面向用户的措辞上分流。
   后续批次扩展媒体语义（媒体版纪要、画面截取）时优先在这里加键。 */
const CONTENT_TYPE_LABELS = {
  meeting: {
    "zh-CN": { recordNoun: "会议记录", speakerCount: n => `${n} 位发言人`,
               renameTitle: "修改会议名称", markAction: "标记为媒体视频",
               outline: "会议脉络", minutes: "会议纪要", screens: "画面与资料", audit: "核对关键结论" },
    en: { recordNoun: "Meeting record", speakerCount: n => `${n} speakers`,
          renameTitle: "Rename meeting", markAction: "Mark as media",
          outline: "Meeting map", minutes: "Minutes", screens: "Visuals & Materials", audit: "Review key conclusions" },
  },
  media: {
    "zh-CN": { recordNoun: "媒体记录", speakerCount: n => `${n} 位出镜`,
               renameTitle: "修改标题", markAction: "标记为会议",
               outline: "论证脉络", minutes: "分析纪要", screens: "画面解析", audit: "核对关键依据" },
    en: { recordNoun: "Media record", speakerCount: n => `${n} on camera`,
          renameTitle: "Rename title", markAction: "Mark as meeting",
          outline: "Argument map", minutes: "Analysis", screens: "Visual analysis", audit: "Review key sources" },
  },
};
function contentLabel(type, key, ...args) {
  const lang = CONTENT_TYPE_LABELS[type]?.[state.uiLanguage] ? state.uiLanguage : "zh-CN";
  const value = CONTENT_TYPE_LABELS[type]?.[lang]?.[key] ?? CONTENT_TYPE_LABELS.meeting[lang]?.[key];
  return typeof value === "function" ? value(...args) : (value ?? key);
}

function applyContentTypeCopy() {
  const type = contentTypeOf(state.bundle);
  const text = (selector, value) => { const element = $(selector); if (element) element.textContent = value; };
  text("#chapters-tab", contentLabel(type, "outline"));
  text("#minutes-tab", contentLabel(type, "minutes"));
  text("#visuals-tab", contentLabel(type, "screens"));
  const qualityTab = $("#quality-tab");
  if (qualityTab) qualityTab.childNodes[0].textContent = `${contentLabel(type, "audit")} `;
}

function applyImportMode() {
  const media = state.workspace.contentType === "media";
  const pick = $("#pick-btn span");
  if (pick) pick.textContent = ui(media ? "importMedia" : "import");
  const hint = $("#drop-hint");
  if (hint) hint.textContent = ui(media ? "dropMedia" : "drop");
  $("#media-url-import")?.classList.toggle("hidden", !media);
  const fileInput = $("#file-input");
  if (fileInput) {
    fileInput.accept = media ? "video/*" : "video/*,audio/*,.vtt,.docx";
    fileInput.multiple = !media;
  }
  const ignore = $("#ignore-transcript")?.closest("label");
  if (ignore) ignore.classList.toggle("hidden", media);
  const sort = $("#meeting-sort");
  if (sort?.options?.length > 1) sort.options[1].textContent = media
    ? (isEnglishUi() ? "Publish date" : "发布时间") : ui("sortMeeting");
  const search = $("#search");
  if (search) search.placeholder = media
    ? (isEnglishUi() ? "Search media, platform, or publisher…" : "搜索媒体、平台或发布者…")
    : ui("search");
}

const KEYWORD_KIND_LABELS = {
  "zh-CN": { product: "产品", project: "项目", topic: "议题", organization: "组织", other: "其他" },
  en: { product: "Product", project: "Project", topic: "Topic", organization: "Org", other: "Other" },
};
function keywordKindLabel(kind) {
  return KEYWORD_KIND_LABELS[state.uiLanguage]?.[kind]
    || KEYWORD_KIND_LABELS[state.uiLanguage]?.other || "";
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function fmtListTimestamp(value) {
  const date = new Date(Number(value || 0) * 1000);
  if (!Number.isFinite(date.getTime())) return "";
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}-${day} ${hour}:${minute}`;
}

function defaultTranslationTarget() {
  // 译文目标默认值跟随界面语言；用户手动改过后写入 workspace.translationTargets，不再跟随。
  return state.uiLanguage === "en" ? "en" : "zh-CN";
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
        meetingSort: state.workspace.meetingSort,
        contentType: state.workspace.contentType,
        translationTargets: state.workspace.translationTargets,
        minutesViews: state.workspace.minutesViews,
        anchors: state.workspace.anchors,
      }));
    } catch (_) { /* 私密浏览或存储已满时不阻断阅读 */ }
  }, 120);
}

function applyUiLanguage() {
  const english = isEnglishUi();
  liveContextView?.setLanguage(english ? "en" : "zh-CN");
  document.documentElement.lang = state.uiLanguage;
  document.title = ui("title");
  const text = (selector, value) => { const el = $(selector); if (el) el.textContent = value; };
  text(".brand", ui("brand"));
  text("#library-toggle", ui("meetings"));
  text("#product-link", ui("product"));
  text("#knowledge-base-link", ui("knowledgeBase"));
  text("#settings-link span", ui("settings"));
  text("#pick-btn span", ui("import"));
  text("#undo-speaker-btn", ui("undoSpeaker"));
  text("#drop-hint", ui("drop"));
  text("#import-settings-label", ui("importSettings"));
  text("#processing-mode-label", ui("processingMode"));
  text("#analysis-mode-full-label", ui("fullAnalysis"));
  text("#analysis-mode-full-detail", ui("fullAnalysisDetail"));
  text("#skip-vl-label", ui("skipVl"));
  text("#processing-mode-help", ui("fastAnalysisDetail"));
  text("#ignore-transcript-label", ui("ignoreTranscript"));
  text(".import-divider span", ui("mediaUrlDivider"));
  text("#media-url-submit", ui("mediaUrlSubmit"));
  text("#media-url-hint", ui("mediaUrlHint"));
  $("#media-url-input")?.setAttribute("placeholder", ui("mediaUrlPlaceholder"));
  text("#source-link", ui("sourceLink"));
  text("#transcript-heading", ui("transcript"));
  text('[data-transcript-mode="original"]', ui("original"));
  text('[data-transcript-mode="translated"]', ui("translated"));
  text('[data-transcript-mode="comparison"]', ui("comparison"));
  text("#translation-target-caption", ui("translateTo"));
  text("#follow-label", ui("follow"));
  applyContentTypeCopy();
  text("#restructure-minutes", ui("restructure"));
  text("#restore-minutes", isEnglishUi() ? "Restore previous" : "恢复上一版");
  const minutesView = $("#minutes-view");
  if (minutesView?.options?.length) minutesView.options[0].textContent = isEnglishUi()
    ? "Standard minutes" : "标准纪要";
  text('[data-utility-tab="assistant"]', ui("assistant"));
  text('[data-utility-tab="evidence"]', ui("evidence"));
  text("#assistant-send", ui("send"));
  const input = $("#assistant-input");
  if (input) input.placeholder = state.assistantNextIntent === "restructure"
    ? ui("restructurePlaceholder") : ui("ask");
  const launcher = $("#assistant-launcher span:last-child");
  if (launcher) launcher.textContent = ui("launcher");
  const search = $("#search");
  if (search) search.placeholder = ui("search");
  text("#transcript-edit-title", english
    ? "Listen and correct the original-language transcript"
    : "核听并修正原语言逐字稿");
  text(".transcript-edit-help", english
    ? "Correct against the audio. Do not translate or polish. Minutes, outline, translations, and search will be marked for update."
    : "请按实际音频修正，不翻译、不润色。保存后，纪要、脉络、翻译和检索会标记为待同步。");
  text("#transcript-edit-play", english ? "▶ Play segment" : "▶ 播放本段");
  text("#transcript-edit-cancel", english ? "Cancel" : "取消");
  text("#transcript-edit-save", english ? "Save correction" : "保存修正");
  $("#transcript-edit-text")?.setAttribute("aria-label", english
    ? "Corrected original-language transcript" : "修正后的原语言逐字稿");
  const sort = $("#meeting-sort");
  if (sort) {
    sort.options[0].textContent = ui("sortImported");
    sort.options[1].textContent = ui("sortMeeting");
    sort.options[2].textContent = ui("sortUpdated");
    sort.setAttribute("aria-label", isEnglishUi() ? "Meeting order" : "会议排序");
  }
  $$("#content-type-tabs [data-content-type]").forEach(button => {
    const active = button.dataset.contentType === state.workspace.contentType;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.textContent = ui(button.dataset.contentType === "media"
      ? "contentTypeMedia" : "contentTypeMeeting");
  });
  $("#content-type-tabs")?.setAttribute("aria-label", isEnglishUi() ? "Content type" : "内容类型");
  applyImportMode();
  const contentTypeBtn = $("#content-type-btn");
  if (contentTypeBtn) {
    contentTypeBtn.textContent = contentLabel(contentTypeOf(state.bundle), "markAction");
    contentTypeBtn.title = isEnglishUi()
      ? "Only changes the library classification; content is not reprocessed"
      : "只改变库内分类，不重新处理内容";
  }
  const photoButton = $("#photo-import-btn");
  if (photoButton) {
    photoButton.textContent = english ? "Add meeting materials…" : "添加现场资料…";
    photoButton.title = english
      ? "Add photos of whiteboards, paper notes, room displays, or physical objects"
      : "补充白板、纸面笔记、会议室展示或实物照片";
  }
  updatePhotoCurrentButton(Number(player()?.currentTime || 0));
  text("#photo-import-title", english ? "Add meeting materials" : "添加现场资料");
  text("#photo-import-summary", english
    ? "Add whiteboards, paper notes, room displays, or physical objects that the recording did not capture clearly."
    : "补充视频中没有清楚记录的白板、纸面笔记、会议室展示或实物照片。");
  $("#photo-import-close")?.setAttribute("aria-label", english ? "Close" : "关闭");
  text("#photo-import-cancel", english ? "Cancel" : "取消");
  text("#photo-import-confirm", state.photoImport.busy
    ? (english ? "Importing…" : "正在导入…")
    : (english ? "Import materials" : "导入现场资料"));
  text("#photo-delete-title", english ? "Delete this meeting material?" : "删除这项现场资料？");
  text("#photo-delete-description", english
    ? "The protected original and reading copy will both be removed. Other meeting content is not affected."
    : "受保护原图和阅读副本会一并删除，其他会议内容不受影响。");
  text("#photo-delete-cancel", english ? "Cancel" : "取消");
  text("#photo-delete-confirm", english ? "Delete material" : "删除现场资料");
  if (!$("#photo-import-mask")?.classList.contains("hidden")) renderPhotoImportDialog();
  const publishButton = $("#knowledge-publish-btn");
  if (publishButton) {
    publishButton.textContent = english ? "Publish to knowledge base…" : "发布到知识库…";
    publishButton.title = english
      ? "Publish or update the current revision in the configured knowledge base"
      : "将当前版本发布或更新到已配置的知识库";
  }
  $$('[data-ui-language]').forEach(button => {
    const active = button.dataset.uiLanguage === state.uiLanguage;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $("#ui-language")?.setAttribute("aria-label", english
    ? "Interface and minutes language" : "界面与纪要语言");
}

async function loadProductVersion() {
  const version = $("#product-version");
  try {
    const health = await jget("/api/health");
    liveContextView?.setEnabled(health.features?.live_context === true);
    const value = String(health.product?.version || "").trim();
    const knowledgeBase = health.integrations?.knowledge_base || {};
    const knowledgeLink = $("#knowledge-base-link");
    if (knowledgeLink && knowledgeBase.configured && knowledgeBase.url) {
      knowledgeLink.href = knowledgeBase.url;
      knowledgeLink.classList.remove("hidden");
    } else {
      knowledgeLink?.classList.add("hidden");
    }
    if (!value) return;
    version.textContent = `v${value}`;
    version.title = `产品版本 v${value} · 前端构建 ${SCRIPT_BUILD || "-"}`;
    version.classList.remove("hidden");
    document.querySelector(".brand")?.setAttribute(
      "title", `Meeting Minutes v${value} · 构建 ${SCRIPT_BUILD || "-"}`);
  } catch (_) {
    version.classList.add("hidden");
  }
}

function renderMeetingHeaderMeta() {
  const b = state.bundle;
  if (!b) return;
  const type = contentTypeOf(b);
  $("#rename-btn").title = contentLabel(type, "renameTitle");
  const contentTypeBtn = $("#content-type-btn");
  if (contentTypeBtn) contentTypeBtn.textContent = contentLabel(type, "markAction");
  const box = $("#meeting-meta");
  const source = b.source_info || {};
  box.textContent = [
    type === "media" ? source.platform : null,
    type === "media" ? source.publisher : null,
    type === "media" ? source.published_at : b.date,
    b.duration ? (isEnglishUi() ? `${fmt(b.duration)} duration` : `${fmt(b.duration)} 时长`) : null,
    type === "meeting" && b.speaker_count ? contentLabel(type, "speakerCount", b.speaker_count) : null,
    b.transcript?.length ? (isEnglishUi()
      ? `${b.transcript.length} transcript segments` : `${b.transcript.length} 段逐字稿`) : null,
  ].filter(Boolean).join(" · ") || contentLabel(type, "recordNoun");
  // 关键字只是元信息行尾部的纯文本词；悬停才提示可点，避免界面新增视觉块。
  const keywords = b.keywords?.state === "ready" ? (b.keywords.keywords || []) : [];
  for (const item of keywords.slice(0, 5)) {
    const text = String(item?.text || "").trim();
    if (!text) continue;
    box.appendChild(document.createTextNode(" · "));
    const token = document.createElement("span");
    token.className = "keyword-token";
    token.textContent = text;
    token.title = isEnglishUi()
      ? `${keywordKindLabel(item.kind)} keyword — click to search the transcript`
      : `${keywordKindLabel(item.kind)}关键字 — 点击在逐字稿中搜索`;
    token.onclick = () => searchTranscriptKeyword(text);
    box.appendChild(token);
  }
  const sourceLink = $("#source-link");
  const sourceUrl = safeSourceUrl(b);
  if (sourceLink) {
    sourceLink.classList.toggle("hidden", !sourceUrl);
    if (sourceUrl) sourceLink.href = sourceUrl;
    else sourceLink.removeAttribute("href");
    sourceLink.textContent = ui("sourceLink");
  }
}

function searchTranscriptKeyword(text) {
  const input = $("#transcript-search");
  if (!input || input.disabled) return;
  input.value = text;
  applyTranscriptSearch();
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
    const params = new URLSearchParams(location.search);
    const linked = params.get("meeting");
    // 外链深链（如知识库文档的时间码链接）：?meeting=<slug>&t=<秒>，支持小数秒；
    // t 非数、负数或超出会议时长时忽略，只打开会议不定位。
    const initial = chooseInitialItem(state.meetings, {
      linked,
      remembered: state.workspace.lastSlug,
      contentType: state.workspace.contentType,
      order: state.workspace.meetingSort,
    });
    await loadMeeting(initial.slug);
    const deepLinkSeek = deepLinkSeconds(params.get("t"), state.bundle?.duration);
    if (linked && deepLinkSeek != null) {
      seek(deepLinkSeek);
    }
  }
}

function orderedMeetings() {
  return sortLibrary(state.meetings, state.workspace.meetingSort);
}

function renderMeetingList() {
  const q = $("#search").value.trim().toLowerCase();
  const ul = $("#meeting-list");
  const order = state.workspace.meetingSort;
  const contentType = state.workspace.contentType;
  ul.innerHTML = "";
  let shown = 0;
  const visibleMeetings = filterLibrary(orderedMeetings(), { contentType, query: q });
  for (const m of visibleMeetings) {
    const source = m.source_info || {};
    shown += 1;
    const li = document.createElement("li");
    li.className = "meeting-item" + (m.slug === state.slug ? " active" : "");
    const statusText = m.generation_phase && ["voice_draft_generating", "voice_draft", "visual_enrichment"].includes(m.generation_phase)
      ? (m.has_minutes ? (isEnglishUi() ? "Voice draft ready" : "语音草稿可读")
        : (isEnglishUi() ? "Generating final minutes" : "终稿生成中"))
      : m.has_minutes ? (isEnglishUi() ? "Ready to review" : "可回顾")
        : (isEnglishUi() ? "Minutes pending" : "待生成纪要");
    const meta = contentType === "media" ? [
      order === "imported" && m.imported_at
        ? `${isEnglishUi() ? "Imported" : "导入"} ${fmtListTimestamp(m.imported_at)}` : null,
      order === "updated" && m.updated_at
        ? `${isEnglishUi() ? "Updated" : "更新"} ${fmtListTimestamp(m.updated_at)}` : null,
      source.platform,
      source.publisher,
      source.published_at || m.date,
      m.duration ? fmt(m.duration) : source.duration ? fmt(source.duration) : null,
      statusText,
    ].filter(Boolean) : [
      order === "imported" && m.imported_at
        ? `${isEnglishUi() ? "Imported" : "导入"} ${fmtListTimestamp(m.imported_at)}` : null,
      order === "updated" && m.updated_at
        ? `${isEnglishUi() ? "Updated" : "更新"} ${fmtListTimestamp(m.updated_at)}` : null,
      m.date,
      m.duration ? fmt(m.duration) : null,
      m.speaker_count ? (contentTypeOf(m) === "media"
        ? contentLabel("media", "speakerCount", m.speaker_count)
        : (isEnglishUi() ? `${m.speaker_count} people` : `${m.speaker_count} 人`)) : null,
      statusText,
    ].filter(Boolean);
    // 关键字作为列表卡元信息的普通灰字词，帮助区分同系列会议；不单独占行。
    for (const text of (m.keywords || []).slice(0, 3)) meta.push(String(text));
    const metaText = meta.join(" · ");
    li.innerHTML =
      `<div class="m-title">${esc(m.title || m.slug)}</div>` +
      `<div class="m-meta">${esc(metaText)}</div>`;
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
  if (!shown && !q) {
    // 当前类型下没有内容：沿用 placeholder 风格给一句可操作的提示。
    const empty = document.createElement("li");
    empty.className = "placeholder";
    empty.textContent = ui(contentType === "media" ? "emptyMediaList" : "emptyMeetingList");
    ul.appendChild(empty);
  }
}

/* ---------- 重新分类：会议 ↔ 媒体 ---------- */

async function toggleContentType() {
  if (!state.slug || !state.bundle) return;
  const current = contentTypeOf(state.bundle);
  const target = current === "media" ? "meeting" : "media";
  $(".more-menu")?.removeAttribute("open");
  state.bundle.content_type = target;  // 乐观更新，失败回滚
  renderMeetingHeaderMeta();
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/content-type`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_type: target }),
  });
  if (!r.ok) {
    state.bundle.content_type = current;
    renderMeetingHeaderMeta();
    const err = await r.json().catch(() => null);
    toast(`${isEnglishUi() ? "Reclassification failed" : "重新分类失败"}: ${err?.detail || r.status}`);
    return;
  }
  toast(target === "media"
    ? (isEnglishUi() ? "Marked as media" : "已标记为媒体视频")
    : (isEnglishUi() ? "Marked as meeting" : "已标记为会议"));
  loadMeetings();
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
    state.transcriptReview = null;
    closePhotoImportDialog();
    closePhotoDeleteDialog();
    closeTranscriptEdit();
    $("#transcript-review-bar")?.classList.add("hidden");
    $("#meeting-title").textContent = "选择一场会议";
    $("#rename-btn").classList.add("hidden");
    $("#transcript-search").value = "";
    $("#transcript-search").disabled = true;
    $("#transcript-search-count").textContent = "";
    state.transcriptSearch = null;
    state.speakerCorrection = resetSpeakerCorrection();
    state.speakerCorrectionReview = null;
    state.speakerCorrectionChoice = "";
    renderSpeakerCorrectionUI();
    $("#meeting-meta").textContent = "阅读纪要、追问内容并修正记录";
    $("#source-link")?.classList.add("hidden");
    $("#transcript").innerHTML = '<p class="placeholder">← 选择一场会议</p>';
    $("#minutes").innerHTML = '<p class="placeholder">纪要内容</p>';
    $("#chapters").innerHTML = '<p class="placeholder">选择会议后可查看会议脉络</p>';
    $("#visuals").innerHTML = '<p class="placeholder">选择会议后可查看画面与资料</p>';
    $("#player-holder").innerHTML = '<p class="placeholder">选择会议后可回放</p>';
    $("#timeline").innerHTML = "";
    $("#speaker-legend").innerHTML = "";
    $("#media-narrative-legend").innerHTML = "";
    $("#media-narrative-legend").classList.add("hidden");
    $("#person-lanes").innerHTML = "";
    $("#person-lanes").classList.add("hidden");
    state.personLanes = false;
    state.personLanesAll = false;
    state.speakerPin = null;
    state.speakerHover = null;
    state.reviewTurnIndex = null;
    state.playbackScope = "meeting";
    state.legendShowAll = false;
    state.speakerColorCache = null;
    $("#utterance-controls").innerHTML = "";
    updatePhotoCurrentButton(0);
    $("#utterance-controls").classList.add("hidden");
    $("#current-chapter").classList.add("hidden");
    $("#regen-btn").disabled = true;
    $("#retranscribe-btn").disabled = true;
    $("#refine-btn").disabled = true;
    $("#export-btn").disabled = true;
    $("#knowledge-publish-btn").disabled = true;
    $("#storage-btn").disabled = true;
    $("#quality-tab").disabled = true;
    $("#chapters-tab").disabled = true;
    $("#visuals-tab").disabled = true;
    $("#quality-entry-btn").disabled = true;
    $("#quality-entry-btn").textContent = ui("audit");
    $("#quality-entry-btn").classList.add("hidden");
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
    try { localStorage.removeItem(ASSISTANT_KEY_PREFIX + slug); } catch (_) { /* 忽略 */ }
  }
  loadMeetings();
}

/* ---------- 会议改名 ---------- */

function startRename() {
  if (!state.slug || !state.bundle) return;
  const h1 = $("#meeting-title");
  const btn = $("#rename-btn");
  if ($("#rename-input")) return;
  const current = state.bundle.title || state.slug;
  const input = document.createElement("input");
  input.id = "rename-input";
  input.className = "rename-input";
  input.type = "text";
  input.maxLength = 80;
  input.value = current;
  h1.classList.add("hidden");
  btn.classList.add("hidden");
  h1.parentNode.insertBefore(input, h1.nextSibling);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const title = input.value.trim();
    input.remove();
    h1.classList.remove("hidden");
    btn.classList.remove("hidden");
    if (!save || !title || title === current) { h1.textContent = current; return; }
    h1.textContent = title;  // 乐观更新, 失败回滚
    const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    if (!r.ok) {
      h1.textContent = current;
      const err = await r.json().catch(() => null);
      toast(`改名失败: ${err?.detail || r.status}`);
      return;
    }
    state.bundle.title = title;
    toast("已改名");
    loadMeetings();
  };
  input.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

/* ---------- 逐字稿搜索 ---------- */

function applyTranscriptSearch(keepCurrent = false) {
  const input = $("#transcript-search");
  const count = $("#transcript-search-count");
  const query = (input?.value || "").trim().toLowerCase();
  const previous = keepCurrent ? (state.transcriptSearch?.current ?? -1) : -1;
  state.transcriptSearch = { query, hits: [], current: -1 };
  $$("#transcript .turn.search-hit, #transcript .turn.search-current")
    .forEach(el => el.classList.remove("search-hit", "search-current"));
  if (!query || !state.bundle?.transcript?.length) {
    if (count) count.textContent = "";
    return;
  }
  state.transcriptSearch.hits = transcriptSearchHits(state.bundle.transcript, query);
  const hits = state.transcriptSearch.hits;
  hits.forEach(i => document.getElementById(`turn-${i}`)?.classList.add("search-hit"));
  if (!hits.length) {
    if (count) count.textContent = "无匹配";
    return;
  }
  if (previous >= 0) {
    // 重渲染后的重标记: 恢复命中位置, 不滚动打扰阅读。
    state.transcriptSearch.current = Math.min(previous, hits.length - 1);
    document.getElementById(`turn-${hits[state.transcriptSearch.current]}`)
      ?.classList.add("search-current");
    if (count) count.textContent = `${state.transcriptSearch.current + 1}/${hits.length}`;
  } else {
    stepTranscriptMatch(1);
  }
}

function stepTranscriptMatch(direction) {
  const search = state.transcriptSearch;
  if (!search || !search.hits.length) return;
  search.current = nextSearchCursor(search.current, search.hits.length, direction);
  $$("#transcript .turn.search-current").forEach(el => el.classList.remove("search-current"));
  const turnIndex = search.hits[search.current];
  const el = document.getElementById(`turn-${turnIndex}`);
  if (el) {
    el.classList.add("search-current");
    scrollInside($("#transcript"), el, "center", true);
  }
  const count = $("#transcript-search-count");
  if (count) count.textContent = `${search.current + 1}/${search.hits.length}`;
}

async function loadSpeakerHistoryStatus() {
  const button = $("#undo-speaker-btn");
  if (!button || !state.slug) return;
  try {
    const status = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/speakers/history`);
    button.disabled = !status.available;
  } catch (_) {
    button.disabled = true;
  }
}

async function undoSpeakerOperation() {
  if (!state.slug) return;
  const button = $("#undo-speaker-btn");
  button.disabled = true;
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/speakers/undo`, { method: "POST" });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || response.status);
    state.speakers = null;
    resetAssistant();
    $(".more-menu")?.removeAttribute("open");
    toast("已撤销上次说话人修改");
    await loadMeeting(state.slug);
  } catch (error) {
    toast(`撤销失败：${error.message}`);
    await loadSpeakerHistoryStatus();
  }
}

/* ---------- 会议详情 ---------- */

function player() { return $("#player-holder video") || $("#player-holder audio"); }

function voiceDraftFailureCopy(rc) {
  const code = Number(rc || 0);
  if (code === 3) return isEnglishUi()
    ? { title: "The text model returned no readable body; the multimodal final is still running.",
        detail: "The transcript remains available for reading and playback. The final minutes will appear automatically." }
    : { title: "文本模型没有返回可读正文；系统仍在生成多模态终稿。",
        detail: "逐字稿仍可阅读和播放，终稿完成后会自动出现。" };
  if (code === 2) return isEnglishUi()
    ? { title: "The local text-model request failed; the multimodal final is still running.",
        detail: "This affects only the early draft. The transcript and final-generation pipeline remain available." }
    : { title: "本地文本模型请求失败；系统仍在生成多模态终稿。",
        detail: "这只影响提前展示的草稿，逐字稿和终稿生成流程仍然可用。" };
  return isEnglishUi()
    ? { title: "The voice-draft step hit an internal error; the multimodal final is still running.",
        detail: "This was not an empty model response. The transcript remains available, and the final minutes will appear automatically." }
    : { title: "语音草稿阶段发生内部异常；系统仍在生成多模态终稿。",
        detail: "这不是模型空正文；逐字稿仍可阅读和播放，终稿完成后会自动出现。" };
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
  const draftFailure = voiceDraftFailureCopy(b.generation?.voice_draft_rc);
  const enrichment = b.generation?.enrichment || {};
  const voiceOnly = b.visual_analysis?.mode === "skipped_by_user"
    || b.generation?.result_mode === "voice_only"
    || (b.visual_analysis?.upgrade_available
      && Number(b.visual_analysis?.available || 0) === 0);
  const finalNeedsReview = documentReady && !voiceOnly
    && enrichment.quality_state === "review_needed";
  const unresolved = Number(enrichment.unresolved_material_claims || 0);
  const qualityTitle = finalNeedsReview
    ? (isEnglishUi()
      ? `${unresolved} material voice-draft item(s) were not matched in the multimodal final. They may have been merged, corrected, or omitted; verify them in Conclusion Audit.`
      : `语音草稿中有 ${unresolved} 条重要事项未在多模态终稿中找到对应投影；可能被合并、纠正或遗漏，请到“核对关键结论”检查。`)
    : "";
  const evidenceState = b.evidence?.state || "partial";
  const evidenceLabel = evidenceState === "ready" ? (isEnglishUi() ? "Traceable" : "可核证")
    : evidenceState === "stale" ? (isEnglishUi() ? "Stale" : "已过期")
      : (isEnglishUi() ? "Partial evidence" : "部分证据");
  const evidenceTone = evidenceState === "ready" ? "good"
    : evidenceState === "stale" ? "warn" : "neutral";
  const shareReady = Boolean(b.transcript?.length);
  if (active) {
    box.replaceChildren();
    return;
  }
  let text = "";
  let tone = "neutral";
  let title = "";
  if (voiceDraft) {
    text = isEnglishUi()
      ? "Voice draft readable · transcript and speaker playback available"
      : "语音草稿可读 · 逐字稿与说话人跳播已经可用";
    tone = "working";
  } else if (voiceDraftFailed) {
    text = draftFailure.title;
    title = draftFailure.detail;
    tone = "warn";
  } else if (voiceOnly && documentReady) {
    text = isEnglishUi()
      ? "Fast minutes and meeting map are ready · visual understanding has not run"
      : "快速纪要与会议脉络可读 · 尚未运行画面理解";
    tone = "good";
  } else if (finalNeedsReview) {
    text = isEnglishUi() ? "Final minutes need review · evidence remains traceable"
      : "终稿待复核 · 结论仍可回到原声与画面";
    title = qualityTitle;
    tone = "warn";
  } else if (documentReady && evidenceState === "ready" && shareReady) {
    text = isEnglishUi()
      ? "Final minutes readable · conclusions trace back to source audio and visuals · ready to export"
      : "正式纪要可读 · 结论可以回到原声与画面 · 可以导出";
    tone = "good";
  } else if (documentReady) {
    text = isEnglishUi() ? `Final minutes readable · ${evidenceLabel}`
      : `正式纪要可读 · ${evidenceLabel}`;
    tone = evidenceTone;
  } else if (shareReady) {
    text = isEnglishUi() ? "Transcript readable · minutes are not ready"
      : "逐字稿可读 · 纪要尚未完成";
  }
  box.innerHTML = text
    ? `<span class="meeting-readiness tone-${esc(tone)}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</span>`
      + (voiceOnly && b.visual_analysis?.upgrade_available
        ? `<button type="button" class="meeting-inline-action" data-visual-upgrade>${isEnglishUi()
          ? "Add visual analysis" : "补充画面分析"}</button>` : "")
    : "";
  wireVisualUpgrade(box);
}

function renderTranscriptReviewBar() {
  const box = $("#transcript-review-bar");
  const review = state.bundle?.transcript_review;
  if (!box || !review || !state.bundle?.transcript?.length) {
    box?.classList.add("hidden");
    return;
  }
  const summary = review.summary || {};
  const automatic = Number(summary.auto_corrected || 0);
  const pending = Number(summary.pending || 0);
  const human = Number(summary.human_corrected || 0);
  const syncPending = review.downstream_state === "sync_pending";
  if (!automatic && !pending && !human && !syncPending) {
    box.classList.add("hidden");
    return;
  }
  const parts = [];
  if (automatic) parts.push(isEnglishUi() ? `${automatic} audio-confirmed correction(s)` : `已自动音频复核 ${automatic} 处`);
  if (human) parts.push(isEnglishUi() ? `${human} human correction(s)` : `人工修正 ${human} 处`);
  if (pending) parts.push(isEnglishUi() ? `${pending} need listening` : `${pending} 处待核听`);
  box.innerHTML = `<strong>${isEnglishUi() ? "Original transcript" : "原语言逐字稿"}</strong>` +
    `<span>${esc(parts.join(" · ") || (isEnglishUi() ? "Clean" : "已复核"))}</span>` +
    (syncPending ? `<span class="review-sync" title="${isEnglishUi()
      ? "Uses the saved visual analysis and does not run the vision model again"
      : "复用已有画面解读，不会重新运行视觉模型"}">${isEnglishUi()
      ? "Minutes need syncing after transcript edits"
      : "逐字稿有新修正，纪要待同步"}</span>` : "") +
    `<span class="review-spacer"></span>` +
    (pending ? `<button type="button" data-review-action="pending">${isEnglishUi() ? "Review" : "开始核听"}</button>` : "") +
    (review.undo_available ? `<button type="button" data-review-action="undo">${isEnglishUi() ? "Undo last edit" : "撤销上次文本修正"}</button>` : "") +
    (syncPending ? `<button type="button" data-review-action="sync">${isEnglishUi() ? "Quick sync" : "快速同步纪要"}</button>` : "");
  box.classList.remove("hidden");
  $("[data-review-action='pending']", box)?.addEventListener("click", () => {
    const item = review.pending?.[0];
    if (Number.isInteger(item?.turn_index)) openTranscriptEdit(item.turn_index, item);
  });
  $("[data-review-action='undo']", box)?.addEventListener("click", undoTranscriptEdit);
  $("[data-review-action='sync']", box)?.addEventListener("click", syncMinutes);
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
    if (state.visualsTranslationPoller) clearInterval(state.visualsTranslationPoller);
    state.visualsTranslationPoller = null;
    state.visualsTranslationJob = null;
  }
  renderMeetingList();
  const b = await jget(`/api/meetings/${encodeURIComponent(slug)}/bundle`);
  state.bundle = b;
  applyContentTypeCopy();
  state.transcriptReview = b.transcript_review || null;
  state.bundleLoadedAt = Date.now() / 1000;
  const savedTarget = state.workspace.translationTargets[slug];
  state.translationTarget = TRANSLATION_TARGETS.has(savedTarget)
    ? savedTarget : defaultTranslationTarget();
  state.workspace.lastSlug = slug;
  saveWorkspaceState();
  state.quality = null;
  state.translation = null;
  state.minutesTranslation = null;
  state.topicMapTranslation = null;
  state.visualsTranslation = null;
  state.selectedChapterId = b.structure?.chapters?.[0]?.id || null;
  state.selectedTopicId = null;
  state.selectedTopicNodeId = null;
  state.selectedVisualId = b.structure?.visuals?.[0]?.id || null;
  state.focus = { mode: "overview", time: null, ranges: [], topicId: null, nodeId: null, person: null,
    turnIds: [], claimIds: [], pageIds: [], source: "overview" };
  state.focusSignature = null;
  state.personLanes = false;
  state.personLanesAll = false;
  state.speakerPin = null;
  state.speakerHover = null;
  state.reviewTurnIndex = null;
  state.playbackScope = "meeting";
  state.legendShowAll = false;
  state.speakerColorCache = null;
  state.visualFilter = contentTypeOf(b) === "media" ? "all" : "useful";
  state.expandedOriginals.clear();
  state.evidenceBilingual.clear();
  $("#meeting-title").textContent = b.title || slug;
  $("#rename-btn").classList.remove("hidden");
  const transcriptSearch = $("#transcript-search");
  transcriptSearch.disabled = !(b.transcript?.length);
  if (changed) { transcriptSearch.value = ""; state.transcriptSearch = null;
    $("#transcript-search-count").textContent = "";
    state.speakerCorrection = resetSpeakerCorrection();
    state.speakerCorrectionReview = null;
    state.speakerCorrectionChoice = "";
    renderSpeakerCorrectionUI(); }
  renderMeetingHeaderMeta();
  renderPlayer();
  renderTranscript(false);
  renderTranscriptReviewBar();
  renderMinutes();
  renderChapters();
  renderVisuals();
  renderMeetingStatuses();
  renderAssistantSuggestions();
  if (changed) restoreAssistant();  // 刷新/重开浏览器后恢复同 revision 的对话
  const isDraft = b.document_state === "draft";
  $("#regen-btn").disabled = isDraft;
  const canRetranscribe = !isDraft && (b.has_video || b.has_audio);
  $("#retranscribe-btn").disabled = !canRetranscribe;
  loadSpeakerHistoryStatus();
  $("#retranscribe-btn").title = canRetranscribe
    ? "保留原始母版和旧版本，使用当前 ASR provider 与最新术语上下文重建逐字稿及下游内容"
    : "需要保留可读取的音频或视频母版";
  $("#refine-btn").disabled = isDraft;
  $("#export-btn").disabled = !(b.transcript?.length);
  $("#knowledge-publish-btn").disabled = !(b.transcript?.length);
  $("#storage-btn").disabled = false;
  $("#content-type-btn").disabled = false;
  $("#photo-import-btn").disabled = contentTypeOf(b) !== "meeting";
  updatePhotoCurrentButton(0);
  $("#assistant-launcher").disabled = false;
  if (state.workspace.utilityOpen) openUtility(state.workspace.utilityTab);
  if (isDraft && state.viewMode === "quality") state.viewMode = "minutes";
  const topicMapReady = b.topic_map?.state === "ready"
    && (b.topic_map?.topics?.length || 0) >= 3;
  if (changed && !requestedViewExplicit) state.viewMode = contentTypeOf(b) === "media"
    ? "chapters" : (topicMapReady ? "chapters" : "minutes");
  $("#quality-tab").disabled = isDraft;
  $("#chapters-tab").disabled = !(b.transcript?.length);
  $("#visuals-tab").disabled = contentTypeOf(b) === "media" && !(b.structure?.visuals?.length);
  $("#quality-entry-btn").disabled = isDraft;
  $("#quality-entry-btn").classList.add("hidden");
  $$('[data-transcript-mode]').forEach(button => button.disabled = false);
  $("#translation-target").disabled = false;
  $("#translation-target").value = state.translationTarget;
  updateTranscriptModeButtons();
  setReviewMode(state.viewMode);
  restoreReadingPosition();
  await loadTranscriptTranslation();
  await loadTopicMapTranslation(true);
  await loadMinutesTranslation(true);
  await loadVisualsTranslation(true);
  if (!isDraft) await loadQualityReview();
  else {
    state.quality = null;
    $("#quality").innerHTML = `<div class="quality-empty"><h3>${isEnglishUi()
      ? "Key conclusions are not reviewed during the voice draft"
      : "语音草稿暂不核对关键结论"}</h3><p>${isEnglishUi()
      ? "Screen tables, figures, and visual evidence are still being added. Review key conclusions after the final minutes are ready."
      : "屏幕表格、数字和画面依据仍在补充，终稿完成后再核对关键结论。"}</p></div>`;
  }
}

function renderPlayer() {
  const b = state.bundle;
  const holder = $("#player-holder");
  holder.innerHTML = "";
  updatePhotoCurrentButton(0);
  let el;
  const hasVisualStage = !b.has_video && (b.structure?.visuals || []).some(item => item.image);
  if (hasVisualStage) {
    holder.innerHTML = `<div id="content-stage" class="content-stage"><img id="content-stage-image" alt="">` +
      `<button id="content-stage-expand" class="content-stage-expand" type="button">⌕ ${isEnglishUi() ? "Expand" : "放大查看"}</button>` +
      `<div class="content-stage-caption"><span id="content-stage-kicker">${isEnglishUi() ? "Current screen" : "当前屏幕"}</span>` +
      `<b id="content-stage-title">${isEnglishUi() ? "Locating screen content" : "正在定位屏幕内容"}</b></div></div>`;
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
    if (!hasVisualStage) holder.innerHTML = `<p class="placeholder">${isEnglishUi()
      ? "No media file; use the timeline to locate the transcript and minutes"
      : "无媒体文件，可通过时间轴定位逐字稿与纪要"}</p>`;
    buildTimeline(0);
    $("#playback-time").textContent = `00:00 / ${fmt(b.duration || 0)}`;
    updatePhotoCurrentButton(0);
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
    // 媒体时长可能短于会议跨度(导出裁剪/音频抽离),时间轴始终覆盖逐字稿全程。
    buildTimeline(Math.max(el.duration || 0, b.duration || 0));
    $("#playback-time").textContent = `${fmt(el.currentTime)} / ${fmt(el.duration)}`;
    updatePhotoCurrentButton(el.currentTime);
  });
  el.addEventListener("timeupdate", onTimeUpdate);
  holder.appendChild(el);
  buildTimeline(b.duration || 0);
  updateFocusPresentation(true);
}

/* ---------- 时间轴（Topic 全覆盖车道 + 说话人泳道 + 刻度） ---------- */

// 调色板唯一真源是 style.css 的 --speaker-N / --topic-N token（theme.css 可整体覆盖）；
// JS 用 getComputedStyle 读取，下面是读不到时的兜底值（与默认主题一致）。
const SPEAKER_COLOR_FALLBACK = ["#e57b45", "#d45a8c", "#43b978", "#e0aa3e", "#d75d5d", "#a176dd", "#31a9c2", "#92ad3f"];
// 议题配色：一级议题按序号取色，时间轴块与右侧脉络"议题 NN"标签同色；low_value 保持灰蓝弱化。
const TOPIC_COLOR_FALLBACK = ["#3b6eea", "#5476d9", "#6a75c9", "#397fbd", "#318d9d", "#4384a8", "#6779b8", "#526d96"];
let paletteCache = null;
function palettes() {
  if (!paletteCache) {
    const cs = getComputedStyle(document.documentElement);
    const read = (prefix, fallback) =>
      fallback.map((fb, i) => cs.getPropertyValue(`--${prefix}-${i + 1}`).trim() || fb);
    paletteCache = { topics: read("topic", TOPIC_COLOR_FALLBACK),
                     speakers: read("speaker", SPEAKER_COLOR_FALLBACK) };
  }
  return paletteCache;
}
function topicColor(index) {
  const colors = palettes().topics;
  return colors[index % colors.length];
}
const VISUAL_VALUE_LABELS = {
  "zh-CN": { high: "核心", medium: "参考", low: "低信息", unknown: "待解析" },
  en: { high: "Key", medium: "Reference", low: "Low information", unknown: "Pending" },
};

function visualValueLabel(visual) {
  return VISUAL_VALUE_LABELS[state.uiLanguage]?.[visual?.information_value]
    || visual?.value_label || (isEnglishUi() ? "Pending review" : "待判断");
}

function visualImageUrl(visual) {
  const path = visual?.asset_path || (visual?.image ? `slides/${visual.image}` : "");
  return path
    ? `/api/meetings/${encodeURIComponent(state.slug)}/file?path=${encodeURIComponent(path)}`
    : "";
}

function topicMapReady() {
  const topicMap = readingTopicMap();
  const topics = topicMap.topics || [];
  return topicMap.state === "ready" && topics.length >= 3;
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
  $("#screen-preview-title").textContent = visualReadingCopy(source).title;
  $("#screen-preview-kicker").textContent = source.kind === "slide"
    ? (isEnglishUi() ? `Page ${source.page}` : `第 ${source.page} 页`) : source.kind === "photo"
      ? (isEnglishUi() ? "Meeting material" : "现场资料") : (isEnglishUi() ? "Dynamic screen" : "动态画面");
  const rawAt = source.ranges?.[0]?.[0] ?? source.first;
  const at = rawAt == null ? Number.NaN : Number(rawAt);
  $("#screen-preview-meta").textContent = source.kind === "photo"
    ? `${Number.isFinite(at) ? fmt(at) : (isEnglishUi() ? "Unlocated" : "未定位")} · ${isEnglishUi() ? "Meeting material" : "现场资料"}`
    : `${Number.isFinite(at) ? fmt(at) : (isEnglishUi() ? "Unlocated" : "未定位")} · ${visualValueLabel(source)} · ` +
      `${source.display_status === "discussed" ? (isEnglishUi() ? "Discussed" : "有对应讨论") :
        source.display_status === "display_only" ? (isEnglishUi() ? "Display only" : "仅展示") : (isEnglishUi() ? "Dynamic screen" : "动态画面")}`;
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
  const at = Number(target.ranges?.[0]?.[0] ?? target.first);
  if (Number.isFinite(at)) seek(at, false);
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
  return turnIndexesForSourceIds(state.bundle?.evidence?.sources?.transcript, ids);
}

function currentTurnIndex(time) {
  return turnIndexAtTime(state.bundle?.transcript, time);
}

function claimsForTurn(index) {
  return claimIdsForTurn(state.bundle?.evidence?.claims, index);
}

function setOverviewFocus() {
  state.focus = { mode: "overview", time: null, ranges: [], topicId: null, nodeId: null, person: null,
    turnIds: [], claimIds: [], pageIds: [], source: "overview" };
  state.selectedTopicId = null;
  state.selectedTopicNodeId = null;
  state.focusSignature = null;
  updateFocusPresentation(true);
}

function setTopicFocus(topic, node = topic) {
  if (!topic || !node) return;
  state.focus = { mode: "topic", time: null, ranges: node.ranges || topic.ranges || [],
    topicId: topic.id, nodeId: node.id, person: null, turnIds: node.turn_ids || topic.turn_ids || [],
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
    topicId: topic?.id || null, nodeId: topic?.id || null, person: null,
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
  if (title) title.textContent = source ? visualReadingCopy(source).title : (isEnglishUi()
    ? "No static screen content at this position" : "这一位置没有静态屏幕资料");
  if (kicker) kicker.textContent = semantic ? (isEnglishUi() ? "Topic screen" : "议题代表画面") : source
    ? `${fmt(state.focus.time ?? source.first)} · ${source.kind === "slide"
      ? (isEnglishUi() ? `Page ${source.page}` : `第${source.page}页`)
      : (isEnglishUi() ? "Dynamic screen" : "动态画面")}`
    : (isEnglishUi() ? "Current screen" : "当前屏幕");
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

async function updatePhotoAlignment(photoId, seconds) {
  if (!state.slug || !photoId) return;
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/photos/${encodeURIComponent(photoId)}/alignment`,
      { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seconds: Number.isFinite(seconds) ? seconds : null }) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || response.status);
    const visual = (state.bundle?.structure?.visuals || []).find(item => item.id === photoId);
    if (visual) {
      const aligned = payload.photo?.alignment || {};
      visual.alignment = aligned;
      visual.first = Number.isFinite(aligned.seconds) ? aligned.seconds : null;
      visual.ranges = Number.isFinite(aligned.seconds)
        ? [[aligned.seconds, aligned.seconds + 1]] : [];
    }
    buildTimeline(Number(state.bundle?.duration || player()?.duration || 1));
    if (state.viewMode === "visuals") renderVisuals(true);
    toast(Number.isFinite(seconds)
      ? `${isEnglishUi() ? "Photo aligned at" : "照片已定位到"} ${fmt(seconds)}`
      : (isEnglishUi() ? "Photo left unlocated" : "照片已设为未定位"));
  } catch (error) {
    toast(`${isEnglishUi() ? "Photo alignment failed" : "照片定位失败"}：${error.message}`);
  }
}

async function refreshPhotoMaterials() {
  if (!state.slug || !state.bundle) return;
  const refreshed = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
  state.bundle.photos = refreshed.photos || [];
  state.bundle.structure = state.bundle.structure || {};
  state.bundle.structure.visuals = refreshed.structure?.visuals || [];
  if (!(state.bundle.structure.visuals || []).some(item => item.id === state.selectedVisualId))
    state.selectedVisualId = state.bundle.structure.visuals.find(item => item.kind === "photo")?.id
      || state.bundle.structure.visuals[0]?.id || null;
  buildTimeline(Number(state.bundle.duration || player()?.duration || 1));
  if (state.viewMode === "visuals") renderVisuals(true);
  $("#visuals-tab").disabled = false;
}

async function savePhotoTitle(photoId, title) {
  const clean = String(title || "").trim();
  if (!clean) return;
  const response = await api(
    `/api/meetings/${encodeURIComponent(state.slug)}/photos/${encodeURIComponent(photoId)}`,
    { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: clean }) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || response.status);
  const visual = (state.bundle?.structure?.visuals || []).find(item => item.id === photoId);
  if (visual) visual.title = payload.photo?.title || clean;
  state.photoRenameId = null;
  renderVisuals(true);
  toast(isEnglishUi() ? "Material title updated" : "现场资料标题已更新");
}

function openPhotoDeleteDialog(photoId, title, trigger) {
  state.photoDeleteTarget = { id: photoId, title };
  state.photoDeleteReturnFocus = trigger || document.activeElement;
  const description = $("#photo-delete-description");
  if (description) description.textContent = isEnglishUi()
    ? `“${title}” and both its protected original and reading copy will be removed. Other meeting content is not affected.`
    : `“${title}”的受保护原图和阅读副本会一并删除，其他会议内容不受影响。`;
  $("#photo-delete-mask")?.classList.remove("hidden");
  $("#photo-delete-cancel")?.focus();
}

function closePhotoDeleteDialog() {
  $("#photo-delete-mask")?.classList.add("hidden");
  const returnFocus = state.photoDeleteReturnFocus;
    state.photoDeleteTarget = null;
  state.photoDeleteReturnFocus = null;
  if (returnFocus?.isConnected) returnFocus.focus();
}

async function deletePhotoMaterial() {
  const target = state.photoDeleteTarget;
  if (!state.slug || !target?.id) return;
  const button = $("#photo-delete-confirm");
  button.disabled = true;
  button.textContent = isEnglishUi() ? "Deleting…" : "正在删除…";
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/photos/${encodeURIComponent(target.id)}`,
      { method: "DELETE" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || response.status);
    state.bundle.structure.visuals = (state.bundle.structure?.visuals || [])
      .filter(item => item.id !== target.id);
    state.bundle.photos = (state.bundle.photos || []).filter(item => item.id !== target.id);
    state.selectedVisualId = state.bundle.structure.visuals[0]?.id || null;
    closePhotoDeleteDialog();
    buildTimeline(Number(state.bundle.duration || player()?.duration || 1));
    renderVisuals();
    toast(isEnglishUi() ? "Meeting material deleted" : "现场资料已删除");
  } catch (error) {
    toast(`${isEnglishUi() ? "Delete failed" : "删除失败"}：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = isEnglishUi() ? "Delete material" : "删除现场资料";
  }
}

function renderPhotoMarkers(timeline, duration) {
  const photos = (state.bundle?.structure?.visuals || []).filter(
    visual => visual.kind === "photo" && visual.alignment?.seconds != null
      && Number.isFinite(Number(visual.alignment.seconds)));
  for (const photo of photos) {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "tl-photo-marker";
    marker.dataset.photoId = photo.id;
    marker.style.left = `${Number(photo.alignment.seconds) / duration * 100}%`;
    marker.title = `${fmt(photo.alignment.seconds)} · ${photo.title || (isEnglishUi() ? "Meeting material" : "现场资料")}`;
    marker.setAttribute("aria-label", marker.title);
    marker.addEventListener("click", event => {
      event.stopPropagation();
      openVisual(photo.id, Number(photo.alignment.seconds));
    });
    timeline.appendChild(marker);
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
    box.innerHTML = `<span>${isEnglishUi() ? "Meeting overview" : "整场概览"}</span>` +
      `<b>${topics ? (isEnglishUi() ? `${topics} primary topics` : `${topics} 个一级议题`)
        : (isEnglishUi() ? "Browse by time" : "按时间浏览会议")}</b>` +
      `<small>${isEnglishUi() ? "Select a topic to focus; click a time to play" :
        "选择议题聚焦内容；点击时间才会播放"}</small>`;
  } else if (focus.mode === "topic") {
    const [topic, node] = topicNode(focus.topicId, focus.nodeId);
    box.innerHTML = `<span>${isEnglishUi() ? "Semantic focus" : "语义聚焦"}</span>` +
      `<b>${esc(node?.title || topic?.title || (isEnglishUi() ? "Meeting topic" : "会议议题"))}</b>` +
      `<small>${isEnglishUi() ? `${(focus.ranges || []).length} time ranges · ${focus.claimIds.length} related conclusions` :
        `${(focus.ranges || []).length} 个时间范围 · ${focus.claimIds.length} 条相关结论`}</small>` +
      (focus.claimIds.length ? `<button type="button" id="focus-show-claims">${isEnglishUi() ? "View conclusions" : "查看结论"}</button>` : "") +
      `<button type="button" id="focus-clear">${isEnglishUi() ? "Back to overview" : "返回整场"}</button>`;
  } else {
    const visual = visualForTime(focus.time || 0);
    box.innerHTML = `<span>${isEnglishUi() ? "Located at" : "已定位"} ${fmt(focus.time)}</span>` +
      `<b>${esc(visual ? visualReadingCopy(visual).title : (isEnglishUi() ? "Transcript position" : "逐字稿位置"))}</b>` +
      `<small>${focus.claimIds.length ? (isEnglishUi() ? `${focus.claimIds.length} related conclusions` : `关联 ${focus.claimIds.length} 条结论`)
        : (isEnglishUi() ? "No directly related conclusions" : "当前没有直接关联结论")}</small>` +
      (focus.claimIds.length ? `<button type="button" id="focus-show-claims">${isEnglishUi() ? "View conclusions" : "查看结论"}</button>` : "");
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
  applySpeakerFocus();
}

function buildTimeline(duration) {
  const b = state.bundle || { transcript: [], slides: [] };
  const tl = $("#timeline");
  tl.innerHTML = "";
  if (!duration) duration = b.duration || 1;
  tl.dataset.dur = duration;

  const played = document.createElement("div");
  played.className = "tl-played";
  tl.appendChild(played);

  // 上层 Topic 车道：LLM 归并后的语义议题出现区间，未覆盖时间用灰色间隙块铺满。
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
  const covered = [];
  for (const item of timelineTopics) {
    if (item.end <= item.start) continue;
    covered.push([item.start, item.end]);
    const block = document.createElement("div");
    block.className = "tl-chapter" + (item.topic?.low_value ? " tl-chapter-low" : "");
    if (!item.topic?.low_value) block.style.background = topicColor(item.index) + "b8";
    block.dataset.topicId = item.id;
    block.style.left = (item.start / duration * 100) + "%";
    const chapterWidth = (item.end - item.start) / duration * 100;
    block.style.width = Math.max(.8, chapterWidth) + "%";
    block.title = `${fmt(item.start)}–${fmt(item.end)} ${item.title}` +
      (item.topic?.low_value ? `（${ui("lowValueHint")}）` : "");
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
  const navigationGaps = topicReady
    ? (readingTopicMap().navigation_segments || [])
      .filter(segment => segment.kind !== "topic")
      .flatMap(segment => (segment.ranges || []).map(range => ({
        start: Number(range[0]), end: Number(range[1]), kind: segment.kind,
      }))).filter(item => item.end > item.start).sort((a, b2) => a.start - b2.start)
    : [];
  // v3 明确区分模型判定的过渡段和仍待归类的内容；旧图或纯静音仍显示普通间隙。
  const appendGap = (start, end, kind = "gap") => {
    if (end - start < 0.5) return;
    const gap = document.createElement("div");
    gap.className = `tl-gap tl-gap-${kind}`;
    gap.style.left = (start / duration * 100) + "%";
    gap.style.width = ((end - start) / duration * 100) + "%";
    const tip = kind === "transition" ? ui("transitionTip")
      : kind === "unclassified" ? ui("unclassifiedTip") : ui("gapTip");
    gap.title = `${fmt(start)}–${fmt(end)} ${tip}`;
    gap.addEventListener("click", event => {
      event.stopPropagation();
      seek((start + end) / 2);
    });
    tl.appendChild(gap);
  };
  const appendGapParts = (start, end) => {
    let gapCursor = start;
    for (const item of navigationGaps) {
      if (item.end <= start || item.start >= end) continue;
      const itemStart = Math.max(start, item.start);
      const itemEnd = Math.min(end, item.end);
      appendGap(gapCursor, itemStart);
      appendGap(itemStart, itemEnd, item.kind);
      gapCursor = Math.max(gapCursor, itemEnd);
    }
    appendGap(gapCursor, end);
  };
  let cursor = 0;
  for (const [start, end] of covered.sort((a, b2) => a[0] - b2[0])) {
    appendGapParts(cursor, start);
    cursor = Math.max(cursor, end);
  }
  appendGapParts(cursor, duration);

  // 媒体按内容形态切换第二维：单人口播看叙事作用，访谈保留人物，混合内容两者都显示。
  const mediaNav = mediaNavigation();
  const narrative = isMediaContent() && mediaNav?.show_narrative_lane
    && mediaNav.segments?.length;
  const speakers = !isMediaContent() || !mediaNav || mediaNav.show_speaker_lane;
  tl.classList.toggle("media-hybrid", Boolean(narrative && speakers));
  if (narrative) renderNarrativeLane(tl, duration, 29);
  if (speakers) renderSpeakerLane(tl, duration, narrative ? 47 : 29);
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
  renderPhotoMarkers(tl, duration);
  // 播放头
  const head = document.createElement("div");
  head.className = "tl-head";
  tl.appendChild(head);
  updateActiveChapter(player()?.currentTime || 0);
  updateTimelineFocus();
  renderSpeakerLegend();
  renderNarrativeLegend();
  renderPersonLanes();
  applySpeakerFocus();
  // 空白处点击 seek
  tl.addEventListener("click", ev => {
    if (ev.target !== tl) return;
    const r = tl.getBoundingClientRect();
    seek((ev.clientX - r.left) / r.width * duration);
  });
}

function legacyUnboundSpeaker(name) {
  const compact = String(name || "").replace(/\s+/g, "").toLowerCase();
  return !compact || String(name).includes("(声音")
    || ["未知", "未具名", "unknown"].includes(compact)
    || /^(说话人|speaker)\d+$/.test(compact);
}

function speakerNavigation(name) {
  return (state.bundle?.speaker_navigation || [])
    .find(item => item.speaker === name) || null;
}

// 新包以服务端身份投影为准；旧包保留名称启发式，保证向后兼容。
function isSelectableSpeaker(name) {
  const navigation = speakerNavigation(name);
  return navigation ? navigation.selectable === true : !legacyUnboundSpeaker(name);
}

function isUnboundSpeaker(name) {
  const navigation = speakerNavigation(name);
  if (!navigation) return legacyUnboundSpeaker(name);
  return ["session_voice_cluster", "insufficient_voice_sample"]
    .includes(navigation.identity_basis);
}

// 每个说话人的发言时长统计(秒)；turn 缺 end 时用下一轮开始或整场时长补齐。
function speakerStats() {
  const transcript = state.bundle?.transcript || [];
  const duration = Number(state.bundle?.duration || 0);
  const stats = new Map();
  transcript.forEach((turn, index) => {
    if (!turn.speaker) return;
    const start = Number(turn.start) || 0;
    const end = Number(turn.end ?? transcript[index + 1]?.start ?? duration) || start;
    stats.set(turn.speaker, (stats.get(turn.speaker) || 0) + Math.max(0, end - start));
  });
  const total = [...stats.values()].reduce((sum, value) => sum + value, 0) || 1;
  return { stats, total };
}

// 说话人按发言占比降序（已绑定者在前，未绑定/会议机沉底），图例/节奏条/逐人车道共用。
function speakerOrderByShare() {
  const { stats } = speakerStats();
  const names = [...stats.keys()];
  const bound = names.filter(name => !isUnboundSpeaker(name))
    .sort((a, b2) => (stats.get(b2) || 0) - (stats.get(a) || 0));
  const unbound = names.filter(name => isUnboundSpeaker(name));
  return { bound, unbound };
}

// 说话人确定性取色：按发言占比降序从固定调色板分配；未绑定/会议机不参与配色，统一灰色。
function speakerColorMap() {
  const transcript = state.bundle?.transcript || [];
  const cacheKey = `${state.slug}|${state.bundle?.transcript_revision || ""}|${transcript.length}`;
  if (state.speakerColorCache?.key !== cacheKey) {
    const { bound } = speakerOrderByShare();
    const colors = palettes().speakers;
    state.speakerColorCache = { key: cacheKey,
      map: new Map(bound.map((name, index) => [name, colors[index % colors.length]])) };
  }
  return state.speakerColorCache.map;
}

function speakerColor(speaker) {
  return speakerColorMap().get(speaker) || "#8a93a8";
}

// 节奏条：按渲染宽度分桶(约 2px/桶,上限 360)，每桶染该时间窗发言时长最长者的颜色。
function renderSpeakerLane(tl, duration, top = 29) {
  $$(".tl-spk-lane", tl).forEach(item => item.remove());
  const transcript = state.bundle?.transcript || [];
  if (!transcript.length || !duration) return;
  const lane = document.createElement("div");
  lane.className = "tl-spk-lane";
  lane.style.top = `${top}px`;
  lane.style.bottom = "2px";
  const width = tl.clientWidth || 0;
  const bucketCount = Math.max(24, Math.min(360, Math.round(width / 2) || 180));
  // 预展开每轮的时间跨度，桶窗口按序推进指针，避免 O(桶×轮) 全量扫描。
  const spans = transcript.map((turn, index) => ({
    speaker: turn.speaker || (isEnglishUi() ? "Unknown" : "未知"),
    start: Number(turn.start) || 0,
    end: Number(turn.end ?? transcript[index + 1]?.start ?? duration) || Number(turn.start) || 0,
  }));
  let cursor = 0;
  for (let i = 0; i < bucketCount; i++) {
    const winStart = i / bucketCount * duration;
    const winEnd = (i + 1) / bucketCount * duration;
    while (cursor < spans.length && spans[cursor].end <= winStart) cursor += 1;
    const shares = new Map();
    for (let j = cursor; j < spans.length && spans[j].start < winEnd; j++) {
      const overlap = Math.min(winEnd, spans[j].end) - Math.max(winStart, spans[j].start);
      if (overlap > 0) shares.set(spans[j].speaker, (shares.get(spans[j].speaker) || 0) + overlap);
    }
    if (!shares.size) continue;  // 无发言空桶，露出底色
    const dominant = [...shares.entries()].sort((a, b2) => b2[1] - a[1])[0][0];
    const seg = document.createElement("div");
    seg.className = "tl-spk-seg";
    seg.dataset.speaker = dominant;
    seg.style.left = (i / bucketCount * 100) + "%";
    seg.style.width = (100 / bucketCount + 0.2) + "%";  // 重叠覆盖桶间像素缝，避免白线
    seg.style.background = speakerColor(dominant);
    seg.addEventListener("mouseenter", event =>
      showSpeakerTip(event, { speaker: dominant, start: winStart, end: winEnd }));
    seg.addEventListener("mousemove", moveTip);
    seg.addEventListener("mouseleave", hideTip);
    seg.addEventListener("click", event => {
      event.stopPropagation();
      hideTip();
      seek(winStart);
    });
    lane.appendChild(seg);
  }
  tl.appendChild(lane);
}

const MEDIA_NARRATIVE_ROLES = {
  setup: { zh: "铺垫", en: "Setup", color: "#7c8aa5" },
  thesis: { zh: "观点", en: "Claim", color: "#4f7cff" },
  explanation: { zh: "讲解", en: "Explanation", color: "#5d6f91" },
  evidence: { zh: "证据", en: "Evidence", color: "#169b72" },
  demo: { zh: "演示", en: "Demo", color: "#8358d8" },
  caveat: { zh: "质疑/限制", en: "Caveat", color: "#d58a1f" },
  conclusion: { zh: "结论", en: "Conclusion", color: "#13829b" },
};

function isMediaContent() { return contentTypeOf(state.bundle) === "media"; }
function mediaNavigation() {
  // 角色与时间范围是 canonical 导航数据，语言切换只翻译显示文案，不能被翻译
  // sidecar 覆盖或丢失。
  const value = state.bundle?.topic_map?.media_navigation;
  return value?.schema === "media-navigation/v1" ? value : null;
}
function mediaShowsSpeakers() {
  const value = mediaNavigation();
  return !isMediaContent() || !value || value.show_speaker_lane !== false;
}
function narrativeRoleLabel(role) {
  const item = MEDIA_NARRATIVE_ROLES[role] || MEDIA_NARRATIVE_ROLES.explanation;
  return isEnglishUi() ? item.en : item.zh;
}
function renderNarrativeLane(tl, duration, top = 29) {
  $$(".tl-narrative-lane", tl).forEach(item => item.remove());
  const value = mediaNavigation();
  if (!value?.segments?.length || !duration) return;
  const lane = document.createElement("div");
  lane.className = "tl-narrative-lane";
  lane.style.top = `${top}px`;
  for (const segment of value.segments) {
    const start = Number(segment.start) || 0, end = Number(segment.end) || start;
    if (end <= start) continue;
    const role = MEDIA_NARRATIVE_ROLES[segment.role] || MEDIA_NARRATIVE_ROLES.explanation;
    const block = document.createElement("div");
    block.className = "tl-narrative-seg";
    block.style.left = `${start / duration * 100}%`;
    block.style.width = `${Math.max(.7, (end - start) / duration * 100)}%`;
    block.style.background = role.color;
    block.title = `${fmt(start)}–${fmt(end)} · ${narrativeRoleLabel(segment.role)}` +
      (segment.title ? ` · ${segment.title}` : "");
    if ((end - start) / duration >= .07)
      block.innerHTML = `<span>${esc(narrativeRoleLabel(segment.role))}</span>`;
    block.onclick = event => { event.stopPropagation(); seek(start); };
    lane.appendChild(block);
  }
  tl.appendChild(lane);
}

function renderNarrativeLegend() {
  const box = $("#media-narrative-legend"), value = mediaNavigation();
  if (!box) return;
  if (!isMediaContent() || !value?.show_narrative_lane || !value.segments?.length) {
    box.innerHTML = ""; box.classList.add("hidden"); return;
  }
  const firstByRole = new Map();
  value.segments.forEach(segment => {
    if (!firstByRole.has(segment.role)) firstByRole.set(segment.role, segment);
  });
  box.innerHTML = [...firstByRole].map(([roleName, segment]) => {
    const role = MEDIA_NARRATIVE_ROLES[roleName] || MEDIA_NARRATIVE_ROLES.explanation;
    return `<button type="button" data-narrative-start="${Number(segment.start) || 0}">` +
      `<i style="background:${role.color}"></i>${esc(narrativeRoleLabel(roleName))}</button>`;
  }).join("");
  $$('[data-narrative-start]', box).forEach(button =>
    button.onclick = () => seek(Number(button.dataset.narrativeStart) || 0));
  box.classList.remove("hidden");
}

// 相邻同说话人轮次合并为连续块；turn 缺 end 时用下一轮开始或整场时长补齐。
function speakerRuns() {
  const transcript = state.bundle?.transcript || [];
  const duration = Number(state.bundle?.duration || 0);
  const runs = [];
  transcript.forEach((turn, index) => {
    const start = Number(turn.start) || 0;
    const end = Number(turn.end ?? transcript[index + 1]?.start ?? duration) || start;
    const last = runs[runs.length - 1];
    if (last && last.speaker === turn.speaker) {
      last.end = Math.max(last.end, end);
      last.turnIndexes.push(index);
    } else {
      runs.push({ speaker: turn.speaker || (isEnglishUi() ? "Unknown" : "未知"),
        start, end, turnIndexes: [index] });
    }
  });
  return runs;
}

function showSpeakerTip(ev, run) {
  const tip = $("#tl-tip");
  const transcript = state.bundle?.transcript || [];
  const stats = new Map();
  let total = 0;
  transcript.forEach((turn, index) => {
    const start = Number(turn.start) || 0;
    const end = Number(turn.end ?? transcript[index + 1]?.start ?? run.end) || start;
    const overlap = Math.min(run.end, end) - Math.max(run.start, start);
    if (overlap > 0) {
      stats.set(turn.speaker, (stats.get(turn.speaker) || 0) + overlap);
      total += overlap;
    }
  });
  if (!total) {  // 轮次没有 end 时按窗口内轮次数估算构成
    for (const turn of transcript) {
      const start = Number(turn.start) || 0;
      if (start >= run.start && start < run.end) {
        stats.set(turn.speaker, (stats.get(turn.speaker) || 0) + 1);
        total += 1;
      }
    }
  }
  const parts = [...stats.entries()].sort((a, b2) => b2[1] - a[1])
    .map(([name, share]) => `${esc(name)} ${Math.round(share / (total || 1) * 100)}%`).join(" · ");
  tip.innerHTML = `<div class="tip-title">${fmt(run.start)}–${fmt(run.end)} · ${ui("seekHint")}</div>` +
    `<b class="tip-heading">${esc(run.speaker)}</b>` +
    (parts ? `<p class="tip-summary">${parts}</p>` : "");
  tip.classList.remove("hidden");
  moveTip(ev);
}

/* ---------- 人物图例、逐人车道与人物 Focus ---------- */

const LEGEND_TOP_N = 6;   // 直接显示:占比 ≥5% 或前 6 名(并集)
const PERSON_LANES_TOP_N = 6;  // 逐人车道默认展开前 6 人

function legendChip(speaker, pct) {
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "speaker-chip";
  chip.dataset.speaker = speaker;
  chip.innerHTML = `<i style="background:${speakerColor(speaker)}"></i>${esc(speaker)}<small>${pct}%</small>`;
  chip.title = ui("speakerPinTip");
  chip.addEventListener("mouseenter", () => { state.speakerHover = speaker; applySpeakerFocus(); });
  chip.addEventListener("mouseleave", () => { state.speakerHover = null; applySpeakerFocus(); });
  chip.addEventListener("click", () => {
    selectPlaybackSpeaker(speaker, true);
  });
  return chip;
}

function renderSpeakerLegend() {
  const box = $("#speaker-legend");
  if (!box) return;
  const transcript = state.bundle?.transcript || [];
  box.innerHTML = "";
  if (!transcript.length || !mediaShowsSpeakers()) {
    box.innerHTML = ""; box.classList.add("hidden"); return;
  }
  const { stats, total } = speakerStats();
  const { bound, unbound } = speakerOrderByShare();
  const pct = name => Math.round((stats.get(name) || 0) / total * 100);
  const direct = bound.filter((name, index) => index < LEGEND_TOP_N || (stats.get(name) || 0) / total >= 0.05);
  const rest = bound.filter(name => !direct.includes(name));

  // 逐人车道开关已移到车道区块右下角的独立按钮（renderLanesToggle），不再混入图例 chips。
  for (const name of direct) box.appendChild(legendChip(name, pct(name)));
  if (rest.length) {
    if (state.legendShowAll) for (const name of rest) box.appendChild(legendChip(name, pct(name)));
    const more = document.createElement("button");
    more.type = "button";
    more.className = "speaker-chip legend-more";
    more.textContent = state.legendShowAll
      ? ui("collapseChip") : `${ui("othersChip")}(${rest.length})`;
    more.addEventListener("click", () => {
      state.legendShowAll = !state.legendShowAll;
      renderSpeakerLegend();
      applySpeakerFocus();
    });
    box.appendChild(more);
  }
  // 未绑定/会议机：灰色斜纹沉底；有声音簇时可本场跳播，无声音簇时才禁选。
  for (const name of unbound) {
    const selectable = isSelectableSpeaker(name);
    const chip = document.createElement("span");
    chip.className = "speaker-chip unbound" + (selectable ? "" : " disabled");
    chip.dataset.speaker = name;
    if (!selectable) chip.setAttribute("aria-disabled", "true");
    chip.title = selectable ? ui("speakerPinTip") : ui("speakerUnavailable");
    chip.innerHTML = `<i></i>${esc(name)}<small>${pct(name)}%</small>`;
    if (selectable) {
      chip.addEventListener("mouseenter", () => { state.speakerHover = name; applySpeakerFocus(); });
      chip.addEventListener("mouseleave", () => { state.speakerHover = null; applySpeakerFocus(); });
      chip.addEventListener("click", () => selectPlaybackSpeaker(name, true));
    }
    const turn = transcript.find(item => item.speaker === name && item.voice);
    if (turn) {
      const bind = document.createElement("button");
      bind.type = "button";
      bind.className = "chip-bind";
      bind.textContent = ui("bindAction");
      bind.addEventListener("click", event => {
        event.stopPropagation();
        openBind(turn.voice, name);
      });
      chip.appendChild(bind);
    }
    box.appendChild(chip);
  }
  box.classList.remove("hidden");
  renderLanesToggle();
}

// 逐人车道开关：独立按钮，固定在车道区块右下角（收起时贴在图例行下方），与人物 chips 视觉区分。
function renderLanesToggle() {
  const bar = $("#person-lanes-bar");
  const btn = $("#person-lanes-toggle");
  if (!bar || !btn) return;
  if (!mediaShowsSpeakers()) { bar.classList.add("hidden"); return; }
  if (!(state.bundle?.transcript || []).length) { bar.classList.add("hidden"); return; }
  btn.textContent = state.personLanes ? ui("collapseLanes") : ui("expandLanes");
  btn.setAttribute("aria-expanded", String(state.personLanes));
  btn.onclick = () => {
    state.personLanes = !state.personLanes;
    renderLanesToggle();
    renderPersonLanes();
    applySpeakerFocus();
  };
  bar.classList.remove("hidden");
}

// 逐人展开车道：轨道名选择人物，发言块选择人物+当前发言并播放；会议机行沉底。
function renderPersonLanes() {
  const box = $("#person-lanes");
  if (!box) return;
  box.innerHTML = "";
  if (!mediaShowsSpeakers()) {
    box.classList.add("hidden");
    $("#person-lanes-bar")?.classList.add("hidden");
    return;
  }
  if (!state.personLanes || !(state.bundle?.transcript || []).length) {
    box.classList.add("hidden");
    return;
  }
  const duration = Number($("#timeline")?.dataset.dur || state.bundle?.duration || 1);
  const { bound, unbound } = speakerOrderByShare();
  const shown = state.personLanesAll ? bound : bound.slice(0, PERSON_LANES_TOP_N);
  const hiddenCount = bound.length - shown.length;
  const runs = speakerRuns();
  const appendRow = speaker => {
    const selectable = isSelectableSpeaker(speaker);
    const row = document.createElement("div");
    row.className = "person-lane" + (isUnboundSpeaker(speaker) ? " unbound" : "")
      + (selectable ? "" : " disabled");
    row.dataset.speaker = speaker;
    const label = document.createElement("button");
    label.type = "button";
    label.className = "person-lane-name";
    label.textContent = speaker;
    label.title = selectable ? speaker : ui("speakerUnavailable");
    label.disabled = !selectable;
    if (selectable)
      label.addEventListener("click", () => selectPlaybackSpeaker(speaker, true));
    row.appendChild(label);
    const track = document.createElement("div");
    track.className = "person-lane-track";
    for (const run of runs) {
      if (run.speaker !== speaker || run.end <= run.start) continue;
      const block = document.createElement("div");
      block.className = "pl-block";
      block.dataset.turnIndexes = run.turnIndexes.join(",");
      block.style.left = (run.start / duration * 100) + "%";
      block.style.width = Math.max(.5, (run.end - run.start) / duration * 100) + "%";
      block.style.background = speakerColor(speaker);
      block.title = `${fmt(run.start)}–${fmt(run.end)} ${speaker}`;
      if (selectable) {
        block.addEventListener("click", event => {
          event.stopPropagation();
          selectPlaybackSpeaker(speaker, false);
          const unit = reviewUnitForTurn(run.turnIndexes[0]);
          if (unit != null) selectReviewTurn(unit, true);
        });
      } else {
        block.title = `${block.title} · ${ui("speakerUnavailable")}`;
      }
      track.appendChild(block);
    }
    row.appendChild(track);
    box.appendChild(row);
  };
  shown.forEach(appendRow);
  unbound.forEach(appendRow);   // 会议机行沉底
  if (hiddenCount > 0) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "person-lanes-more";
    more.textContent = `${ui("expandRestLanes")} ${hiddenCount} ${isEnglishUi() ? "people" : "人"}`;
    more.addEventListener("click", () => {
      state.personLanesAll = true;
      renderPersonLanes();
      applySpeakerFocus();
    });
    box.appendChild(more);
  }
  box.classList.remove("hidden");
}

// 说话人隔离：悬停临时预览、点击钉住；只调暗主时间轴与他人车道，不动逐字稿滚动与 Focus 摘要。
function applySpeakerFocus() {
  const person = state.speakerHover || state.speakerPin;
  $("#timeline")?.classList.toggle("person-focus", Boolean(person));
  $$("#timeline .tl-spk-seg").forEach(block =>
    block.classList.toggle("dimmed", Boolean(person) && block.dataset.speaker !== person));
  $("#person-lanes")?.classList.toggle("person-focus", Boolean(person));
  $$("#person-lanes .person-lane").forEach(row =>
    row.classList.toggle("dimmed", Boolean(person) && row.dataset.speaker !== person));
  $$("#person-lanes .person-lane").forEach(row =>
    row.classList.toggle("selected", Boolean(state.speakerPin)
      && row.dataset.speaker === state.speakerPin));
  $$("#speaker-legend .speaker-chip").forEach(chip =>
    chip.classList.toggle("active", Boolean(person) && chip.dataset.speaker === person));
  renderUtteranceControls();
  updateReviewHighlights();
}

function reviewTurnEnd(index) {
  return turnEnd(state.bundle?.transcript, state.bundle?.duration, index);
}

function reviewSpeaker() {
  return state.playbackScope === "speaker" ? state.speakerPin : null;
}

function reviewUnitList() {
  if (state.reviewUnits?.length) return state.reviewUnits;
  return defaultReviewUnits(state.bundle?.transcript, state.bundle?.duration);
}

function reviewIndexes(speaker = reviewSpeaker()) {
  return reviewIndexesFor(reviewUnitList(), speaker);
}

function reviewUnitForTurn(turnIndex, time = null) {
  return findReviewUnitForTurn(reviewUnitList(), turnIndex, time);
}

function playbackPosition() {
  const p = player();
  if (p) return Number(p.currentTime) || 0;
  return Number(state.focus?.time) || 0;
}

function nearestReviewTurn(speaker = reviewSpeaker(), time = playbackPosition()) {
  const units = reviewUnitList();
  const indexes = reviewIndexes(speaker);
  return nearestReviewUnit(units, indexes, time);
}

function ensureReviewTurn() {
  const allowed = reviewIndexes();
  if (!allowed.length) {
    state.reviewTurnIndex = null;
    return null;
  }
  if (!allowed.includes(state.reviewTurnIndex))
    state.reviewTurnIndex = nearestReviewTurn();
  return state.reviewTurnIndex;
}

function selectPlaybackSpeaker(speaker, toggle = false) {
  if (speaker && !isSelectableSpeaker(speaker)) return;
  const next = toggle && state.speakerPin === speaker ? null : speaker;
  state.speakerPin = next;
  if (!next) state.playbackScope = "meeting";
  state.reviewTurnIndex = nearestReviewTurn(state.playbackScope === "speaker" ? next : null);
  applySpeakerFocus();
}

function selectReviewTurn(index, play = true) {
  const unit = reviewUnitList()[index];
  if (!unit) return;
  if (state.playbackScope === "speaker" && state.speakerPin
      && unit.speaker !== state.speakerPin) return;
  state.reviewTurnIndex = index;
  updateReviewHighlights();
  renderUtteranceControls();
  seek(unit.start, play);
}

function stepReviewTurn(delta) {
  const indexes = reviewIndexes();
  const current = ensureReviewTurn();
  const target = adjacentReviewUnit(indexes, current, delta);
  if (target != null) selectReviewTurn(target, true);
}

function setPlaybackScope(scope) {
  const units = reviewUnitList();
  if (scope === "speaker" && !state.speakerPin) {
    const current = nearestReviewTurn(null);
    if (current == null || !units[current]) return;
    if (!isSelectableSpeaker(units[current].speaker)) return;
    state.speakerPin = units[current].speaker;
  }
  state.playbackScope = scope;
  state.reviewTurnIndex = nearestReviewTurn(reviewSpeaker());
  applySpeakerFocus();
  if (scope === "speaker") {
    const p = player();
    const current = ensureReviewTurn();
    if (p && !p.paused && current != null) {
      const time = Number(p.currentTime) || 0;
      const unit = units[current];
      if (unit && (time < unit.start - 0.05 || time >= unit.end - 0.05))
        selectReviewTurn(current, true);
    }
  }
}

function renderUtteranceControls() {
  const box = $("#utterance-controls");
  const transcript = state.bundle?.transcript || [];
  if (!box || !transcript.length) {
    box?.classList.add("hidden");
    return;
  }
  const indexes = reviewIndexes();
  const current = ensureReviewTurn();
  const unit = reviewUnitList()[current];
  const position = Math.max(0, indexes.indexOf(current));
  const speaker = state.speakerPin;
  const inferredSpeaker = speaker || unit?.speaker;
  const speakerModeDisabled = !inferredSpeaker || !isSelectableSpeaker(inferredSpeaker);
  const label = reviewSpeaker() || ui("allSpeakers");
  const at = current == null ? 0 : position + 1;
  const currentTime = !unit ? "" : " · " + fmt(unit.start);
  const scopeLabel = isEnglishUi() ? "Playback range" : "播放范围";
  const html = [
    '<span class="utterance-context"><b>', esc(label), '</b><small>',
    at, '/', indexes.length, ' ', ui("utteranceUnit"), currentTime, '</small></span>',
    '<span class="utterance-modes" role="group" aria-label="', scopeLabel, '">',
    '<button type="button" data-playback-scope="meeting" class="',
    state.playbackScope === "meeting" ? "active" : "", '">', ui("fullMeeting"), '</button>',
    '<button type="button" data-playback-scope="speaker" class="',
    state.playbackScope === "speaker" ? "active" : "", '" ',
    speakerModeDisabled ? `disabled title="${esc(ui("speakerUnavailable"))}"` : "", '>',
    ui("speakerOnly"), '</button></span>',
    '<span class="utterance-actions">',
    '<button type="button" data-review-step="-1" ', position <= 0 ? "disabled" : "",
    '>◀ ', ui("previousUtterance"), '</button>',
    '<button type="button" data-review-replay ', current == null ? "disabled" : "",
    '>↻ ', ui("replayUtterance"), '</button>',
    '<button type="button" data-review-step="1" ',
    position >= indexes.length - 1 ? "disabled" : "", '>',
    ui("nextUtterance"), ' ▶</button></span>',
    speaker ? '<button type="button" class="utterance-clear" data-review-clear>'
      + ui("clearSpeaker") + '</button>' : "",
  ];
  box.innerHTML = html.join("");
  $$("[data-playback-scope]", box).forEach(button =>
    button.addEventListener("click", () => setPlaybackScope(button.dataset.playbackScope)));
  $$("[data-review-step]", box).forEach(button =>
    button.addEventListener("click", () => stepReviewTurn(Number(button.dataset.reviewStep))));
  $("[data-review-replay]", box)?.addEventListener("click", () => {
    const index = ensureReviewTurn();
    if (index != null) selectReviewTurn(index, true);
  });
  $("[data-review-clear]", box)?.addEventListener("click", () =>
    selectPlaybackSpeaker(state.speakerPin, true));
  box.classList.remove("hidden");
}

function updateReviewHighlights() {
  const current = ensureReviewTurn();
  const unit = reviewUnitList()[current];
  $$("#person-lanes .pl-block").forEach(block => {
    const indexes = String(block.dataset.turnIndexes || "").split(",").map(Number);
    block.classList.toggle("review-current", Boolean(unit) && indexes.includes(unit.turnIndex));
  });
  $$("#transcript .turn.review-current").forEach(turn =>
    turn.classList.remove("review-current"));
  if (current != null)
    $(`#transcript .turn[data-review-unit="${current}"]`)?.classList.add("review-current");
}

function syncReviewFromPlayback(activeIndex) {
  const unit = reviewUnitList()[activeIndex];
  if (!unit) return;
  if (state.playbackScope === "speaker" && state.speakerPin
      && unit.speaker !== state.speakerPin) return;
  if (state.reviewTurnIndex === activeIndex) return;
  state.reviewTurnIndex = activeIndex;
  updateReviewHighlights();
  renderUtteranceControls();
}

function handleSpeakerOnlyPlayback(p, time) {
  if (state.playbackScope !== "speaker" || !state.speakerPin) return false;
  const indexes = reviewIndexes();
  const current = ensureReviewTurn();
  const position = indexes.indexOf(current);
  const units = reviewUnitList();
  const unit = units[current];
  if (current == null || position < 0 || !unit) return false;
  if (time >= unit.end - 0.12) {
    const next = indexes[position + 1];
    if (next == null) {
      p.pause();
      renderUtteranceControls();
      return true;
    }
    state.reviewTurnIndex = next;
    p.currentTime = units[next].start;
    p.play().catch(() => {});
    updateReviewHighlights();
    renderUtteranceControls();
    return true;
  }
  if (time < unit.start - 0.05 || time > unit.end + 0.05) {
    const next = indexes.find(index => units[index].start >= time)
      ?? indexes[indexes.length - 1];
    const targetTime = units[next].start;
    if (next !== current || Math.abs(time - targetTime) > 0.05) {
      state.reviewTurnIndex = next;
      p.currentTime = targetTime;
      p.play().catch(() => {});
      updateReviewHighlights();
      renderUtteranceControls();
      return true;
    }
  }
  return false;
}

function showSemanticTip(ev, item) {
  const tip = $("#tl-tip");
  const visuals = state.bundle?.structure?.visuals || [];
  const source = item.topic || item.chapter || {};
  const visual = (source.page_ids || []).map(id => visuals.find(visual => visual.id === id))
    .find(visual => visual?.image && visual.information_value !== "low");
  const image = visualImageUrl(visual);
  tip.innerHTML = `<div class="tip-title">${isEnglishUi() ? "Topic" : "议题"} ${String(item.index + 1).padStart(2, "0")} · ` +
    `${fmt(item.start)}–${fmt(item.end)}</div>` +
    `<b class="tip-heading">${esc(item.title)}</b>` +
    `<p class="tip-summary">${esc(item.summary || (isEnglishUi()
      ? "Click to play and locate this topic in the meeting map." : "点击播放并定位到会议语义脉络。"))}</p>` +
    (item.topic ? `<div class="tip-metrics">${isEnglishUi()
      ? `${item.topic.children?.length || 0} structured nodes · ${item.topic.ranges?.length || 0} occurrences`
      : `${item.topic.children?.length || 0} 个结构节点 · ${item.topic.ranges?.length || 0} 个出现区间`}</div>` : "") +
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
  updatePhotoCurrentButton(t);
  if (handleSpeakerOnlyPlayback(p, t)) return;
  updateActiveChapter(t);
  syncTimeFocus(t, false);
  // 高亮当前核听段落；长发言的显示分段与上一/下一/重播使用同一索引。
  const activeUnitIndex = nearestReviewTurn(null, t);
  const activeUnit = reviewUnitList()[activeUnitIndex];
  const cur = activeUnit?.turnIndex ?? -1;
  const reviewUnitChanged = state.reviewTurnIndex !== activeUnitIndex;
  $$(".turn.playing").forEach(el => el.classList.remove("playing"));
  if (cur >= 0) {
    syncReviewFromPlayback(activeUnitIndex);
    const el = $(`#transcript .turn[data-review-unit="${activeUnitIndex}"]`);
    if (el) {
      el.classList.add("playing");
      if ($("#follow").checked && reviewUnitChanged)
        scrollInside($("#transcript"), el, "center", true);
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
  label.title = current ? `${topic ? (isEnglishUi() ? "Current topic" : "当前议题")
    : (isEnglishUi() ? "Current chapter" : "当前章节")} · ${current.title}` : "";
}

/* ---------- 转写区 ---------- */

function transcriptPendingByTurn() {
  return pendingReviewByTurn(state.bundle?.transcript_review);
}

function openTranscriptEdit(index, candidate = null) {
  const turn = state.bundle?.transcript?.[index];
  if (!turn) return;
  state.transcriptEditIndex = index;
  const pending = candidate || transcriptPendingByTurn().get(index);
  $("#transcript-edit-meta").textContent = [
    `${fmt(turn.start)} · ${turn.speaker || (isEnglishUi() ? "Unknown" : "未知")}`,
    pending?.suggested_text ? (isEnglishUi()
      ? `ASR review candidate: ${pending.suggested_text}`
      : `音频复核候选：${pending.suggested_text}`) : null,
  ].filter(Boolean).join(" · ");
  $("#transcript-edit-text").value = String(turn.text || "");
  $("#transcript-edit-mask").classList.remove("hidden");
  $("#transcript-edit-text").focus();
  $("#transcript-edit-text").select();
}

function closeTranscriptEdit() {
  $("#transcript-edit-mask").classList.add("hidden");
  state.transcriptEditIndex = null;
}

async function saveTranscriptEdit() {
  const index = state.transcriptEditIndex;
  if (!Number.isInteger(index) || !state.slug) return;
  const button = $("#transcript-edit-save");
  button.disabled = true;
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/transcript/${index}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: $("#transcript-edit-text").value,
          transcript_revision: state.bundle.transcript_revision }),
      });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || response.status);
    closeTranscriptEdit();
    resetAssistant();
    toast(result.changed
      ? (isEnglishUi() ? "Transcript corrected; downstream views need updating"
        : "逐字稿已修正；纪要、脉络、翻译和检索已标记待同步")
      : (isEnglishUi() ? "No text change" : "文本没有变化"));
    await loadMeeting(state.slug);
    scrollTranscriptTurn(index, "center", false);
  } catch (error) {
    toast(`${isEnglishUi() ? "Correction failed" : "修正失败"}：${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function undoTranscriptEdit() {
  if (!state.slug) return;
  const response = await api(
    `/api/meetings/${encodeURIComponent(state.slug)}/transcript/undo`, { method: "POST" });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    toast(`${isEnglishUi() ? "Undo failed" : "撤销失败"}：${result.detail || response.status}`);
    return;
  }
  resetAssistant();
  toast(isEnglishUi() ? "Latest transcript correction undone" : "已撤销上次逐字稿文本修正");
  await loadMeeting(state.slug);
  if (Number.isInteger(result.index)) scrollTranscriptTurn(result.index, "center", false);
}

function renderTranscript(preserveScroll = true) {
  const translations = new Map((state.translation?.turns || []).map(item => [item.index, item]));
  const sourceLanguages = new Map((state.translation?.source_languages || [])
    .map(item => [item.index, item.source_language]));
  const pendingByTurn = transcriptPendingByTurn();
  state.reviewUnits = renderTranscriptView({
    box: $("#transcript"),
    transcript: state.bundle?.transcript || [],
    pendingByTurn,
    translations,
    sourceLanguages,
    transcriptMode: state.transcriptMode,
    translationTarget: state.translationTarget,
    evidenceBilingual: state.evidenceBilingual,
    expandedOriginals: state.expandedOriginals,
    correctionSelected: state.speakerCorrection.selectedTurnIndexes,
    correctionVoice: state.speakerCorrection.sourceVoice,
    correctionMode: state.speakerCorrection.mode,
    correctionProtected: new Set(state.speakerCorrectionReview?.protected || []),
    bundleDuration: Number(state.bundle?.duration || 0),
    preserveScroll,
    isEnglish: isEnglishUi(),
    translationActive: Boolean(state.translationJob),
    sourceNeedsTranslation,
    formatTime: fmt,
    escapeHtml: esc,
    speakerColor,
    ui,
    turnEnd: reviewTurnEnd,
    onSelectUnit: index => selectReviewTurn(index, true),
    onOpenBind: (voice, speaker, detail) => openSpeakerIdentity(voice, speaker, detail),
    onToggleCorrection: (index, voice) => toggleSpeakerCorrectionExample(index, voice),
    onQuote: index => addReferenceRange(index, index),
    onEdit: (index, candidate) => openTranscriptEdit(index, candidate),
    onToggleOriginal: index => {
      if (state.expandedOriginals.has(index)) state.expandedOriginals.delete(index);
      else state.expandedOriginals.add(index);
      renderTranscript();
      scrollTranscriptTurn(index, "center", false);
    },
  });
  state.reviewTurnIndex = nearestReviewTurn(reviewSpeaker(), playbackPosition());
  updateFocusedTurns(false);
  updateReviewHighlights();
  // 重渲染后搜索高亮会随 DOM 重建丢失, 有查询词时重新标记(保持当前命中位置, 不滚动)。
  if (state.transcriptSearch?.query) applyTranscriptSearch(true);
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

const VISUAL_PROTOCOL_HEADING =
  "(?:标题|页面角色|信息价值|页面内容|这页想说明什么|title|page role|information value|page content|what this page shows)";

function normalizeVisualText(value) {
  return String(value || "").replace(/\\r\\n/g, "\n").replace(/\\n/g, "\n").trim();
}

function visualTitleCandidate(value) {
  const text = normalizeVisualText(value);
  const labeled = text.match(new RegExp(
    `(?:^|\\n)#{1,5}\\s*(?:标题|title)\\s*[:：]?\\s*([\\s\\S]*?)` +
    `(?=\\s+#{1,5}\\s*${VISUAL_PROTOCOL_HEADING}\\b|$)`, "i"));
  if (labeled?.[1]?.trim()) return labeled[1].trim().replace(/^["']|["',]$/g, "").slice(0, 100);
  const plain = text.replace(/^#{1,5}\s*/, "").replace(/^(?:标题|title)\s*[:：]?\s*/i, "").trim();
  if (!plain || new RegExp(`^${VISUAL_PROTOCOL_HEADING}$`, "i").test(plain)) return "";
  return plain.split(new RegExp(`\\s+#{1,5}\\s*${VISUAL_PROTOCOL_HEADING}\\b`, "i"))[0]
    .trim().slice(0, 100);
}

function visualDescriptionHtml(visual) {
  let html = String(visual?.description_html || "").replace(/\\r\\n/g, "\n").replace(/\\n/g, "\n");
  // 旧后端可能已把整段协议元数据渲染成第一个 <p>；标题/角色/价值在界面其他位置
  // 已有结构化展示，移除这个重复段，保留后续页面内容、表格和列表。
  html = html.replace(/^\s*<p>\s*#{1,5}\s*(?:标题|title)\b[\s\S]*?<\/p>\s*/i, "");
  if (html.trim()) return html;
  const text = normalizeVisualText(visual?.description);
  const body = text.split(new RegExp(`#{1,5}\\s*(?:页面内容|page content)\\s*[:：]?`, "i"))[1];
  return `<p>${esc((body || text || "当前画面没有可用的 VL 详细解读。").trim())}</p>`;
}

function visualReadingCopy(visual) {
  const page = Number(visual?.page);
  const translated = state.visualsTranslation?.target_language === state.uiLanguage
    && state.visualsTranslation?.state === "ready"
    ? (state.visualsTranslation.pages || []).find(item => Number(item.number) === page) : null;
  const title = visualTitleCandidate(translated?.title)
    || visualTitleCandidate(visual?.title)
    || visualTitleCandidate(visual?.description)
    || (isEnglishUi() ? "Screen content" : "屏幕内容");
  const rawSummary = normalizeVisualText(translated?.summary);
  return {
    title,
    summary: new RegExp(`#{1,5}\\s*${VISUAL_PROTOCOL_HEADING}\\b`, "i").test(rawSummary)
      ? "" : rawSummary,
  };
}

async function loadVisualsTranslation(autoStart = false) {
  if (!state.slug || !(state.bundle?.structure?.visuals || []).some(item => item.kind === "slide")) {
    state.visualsTranslation = null;
    return;
  }
  const target = state.uiLanguage;
  try {
    const payload = await jget(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/visuals?target=${encodeURIComponent(target)}`);
    if (target !== state.uiLanguage) return;
    state.visualsTranslation = payload;
    renderVisuals();
    updateFocusPresentation(false);
    if (autoStart && ["missing", "stale", "failed", "cancelled", "partial"].includes(payload.state))
      await startVisualsTranslation();
  } catch (_) {
    state.visualsTranslation = null;
    renderVisuals();
  }
}

async function startVisualsTranslation() {
  if (!state.slug || state.visualsTranslationJob) return;
  const target = state.uiLanguage;
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/translations/visuals?target=${encodeURIComponent(target)}`,
      { method: "POST" });
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || response.status);
    if (!job.id) {
      await loadVisualsTranslation(false);
      return;
    }
    state.visualsTranslationJob = job.id;
    if (state.visualsTranslationPoller) clearInterval(state.visualsTranslationPoller);
    const check = async () => {
      try {
        const current = await jget(`/api/jobs/${job.id}`);
        if (!["done", "failed", "cancelled"].includes(current.status)) return;
        clearInterval(state.visualsTranslationPoller);
        state.visualsTranslationPoller = null;
        state.visualsTranslationJob = null;
        await loadVisualsTranslation(false);
      } catch (_) { /* 下一轮继续 */ }
    };
    state.visualsTranslationPoller = setInterval(check, 1800);
    check();
  } catch (_) {
    state.visualsTranslationJob = null;
    state.visualsTranslation = { ...(state.visualsTranslation || {}), state: "failed" };
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
  state.visualsTranslation = null;
  if (state.visualsTranslationPoller) clearInterval(state.visualsTranslationPoller);
  state.visualsTranslationPoller = null;
  state.visualsTranslationJob = null;
  saveWorkspaceState();
  applyUiLanguage();
  if (state.slug && !state.workspace.translationTargets[state.slug] && !state.translationJob) {
    const target = defaultTranslationTarget();
    if (target !== state.translationTarget) {
      state.translationTarget = target;
      state.translation = null;
      state.translationProgress = { done: 0, total: 0 };
      updateTranslationTargetControl();
      updateTranslationState();
      await loadTranscriptTranslation();
    }
  }
  renderMeetingList();
  renderJobs(state.jobs);
  renderMeetingHeaderMeta();
  renderMeetingStatuses();
  renderTranscript();
  renderTranscriptReviewBar();
  renderUtteranceControls();
  renderMinutes();
  if (state.viewMode === "chapters") renderChapters();
  if (state.viewMode === "visuals") renderVisuals();
  if (state.viewMode === "quality") renderQualityReview();
  if (state.quality) updateQualityIndicators();
  updateFocusPresentation(false);
  await loadTopicMapTranslation(true);
  await loadMinutesTranslation(true);
  await loadVisualsTranslation(true);
}

function renderMinutes() {
  const box = $("#minutes");
  const availableViews = state.bundle?.minutes_views || [];
  const selection = resolveMinutesView(
    availableViews, state.workspace.minutesViews[state.slug] || "standard");
  const selectedViewId = selection.id;
  const selectedView = selection.view;
  if (selection.reset) {
    state.workspace.minutesViews[state.slug] = "standard";
    saveWorkspaceState();
  }
  const presentation = minutesState(
    state.bundle, selectedView, state.minutesTranslation, state.uiLanguage, state.assistantBusy);
  renderMinutesView({
    box,
    viewSelect: $("#minutes-view"),
    restoreButton: $("#restore-minutes"),
    restructureButton: $("#restructure-minutes"),
    availableViews,
    selectedViewId,
    selectedView,
    viewMode: state.viewMode,
    historyAvailable: Boolean(state.bundle?.minutes_history_available),
    presentation,
    draftFailure: voiceDraftFailureCopy(state.bundle?.generation?.voice_draft_rc),
    minutesHtml: state.bundle?.minutes_html || "",
    evidence: state.bundle?.evidence,
    evidenceState: state.bundle?.evidence?.state,
    translationState: state.minutesTranslation?.state,
    translationActive: Boolean(state.minutesTranslationJob),
    isEnglish: isEnglishUi(),
    ui,
    escapeHtml: esc,
    formatTime: fmt,
    onCanonicalClaim: claimId => showMinutesEvidence(claimId, true),
    onAssistantClaim: claim => showAssistantSource(claim),
  });
  updateFocusedClaims();
}

function structureClaimCard(id) {
  const claim = (state.bundle?.evidence?.claims || []).find(item => item.id === id);
  if (!claim) return "";
  const statusPair = qualityStatusNames[claim.status];
  const kindPair = qualityKindNames[claim.kind];
  const status = statusPair ? statusPair[isEnglishUi() ? 1 : 0]
    : claim.status || (isEnglishUi() ? "Record" : "记录");
  const kind = kindPair ? kindPair[isEnglishUi() ? 1 : 0]
    : claim.kind || (isEnglishUi() ? "Content" : "内容");
  const action = claimAction(state.bundle?.evidence, claim);
  return `<button type="button" class="structure-claim" data-structure-claim="${esc(id)}">` +
    `<span class="structure-claim-meta"><i>${esc(kind)}</i><i>${esc(status)}</i>` +
    `${claim.start != null ? `<i>${fmt(claim.start)}</i>` : ""}</span>` +
    `<b>${esc(action?.text || claim.text)}</b>` +
    (action ? `<small>${isEnglishUi() ? "Owner" : "负责人"}：${esc(action.owner || (isEnglishUi() ? "Unconfirmed" : "待确认"))} · ` +
      `${isEnglishUi() ? "Due" : "期限"}：${esc(action.deadline || (isEnglishUi() ? "Unconfirmed" : "待确认"))}` +
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
  const action = claimAction(state.bundle?.evidence, claim);
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
    `<small style="color:${topicColor(index)}">${isEnglishUi() ? "Topic" : "议题"} ${String(index + 1).padStart(2, "0")} · ` +
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
      `<b>${esc(visualReadingCopy(page).title)}</b></button>`;
    }).join("")}</div></section>`;
}

function topicMapDetail(topic, node, pageMap, index = 0) {
  const ranges = node.ranges || topic.ranges || [];
  const claims = (node.claim_ids || []).map(flowClaim).filter(Boolean).join("");
  return `<section class="topic-map-detail" style="border-left:3px solid ${topicColor(index)}"><header><div><span>${esc(
    node.id === topic.id ? (isEnglishUi() ? "Primary topic" : "一级议题") :
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
        `<p>系统正在补充屏幕表格、数字和视觉上下文。为避免基于不完整资料提前固化观点，` +
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
          ? `当前有 ${topics.length} 个一级议题，需要重新归纳` : "还没有整场会议语义脉络")}</h3>` +
      `<p>${isEnglishUi()
        ? "The system synthesizes the transcript, speakers, conclusion evidence, and screen content into a small set of meeting-wide topics. Screens, time windows, and attendee changes do not become topics by themselves."
        : "系统会读取逐字稿、说话人、结论依据和屏幕资料，归并为少量整场议题。截图、时间窗和参会人变化不会直接成为议题。"}</p>` +
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
    `<span>${isEnglishUi() ? `AI meeting-wide synthesis · ${topics.length} primary topics` : `AI 全场语义归纳 · ${topics.length} 个一级议题`}</span>` +
    `<h2>${esc(state.bundle?.title || (isEnglishUi() ? "Meeting map" : "会议脉络"))}</h2>` +
    `<p>${esc(topicMap.meeting_summary || (isEnglishUi()
      ? "Organized by arguments, disagreements, decisions, and actions; screens remain evidence."
      : "按整场会议的议题、分歧、结论和行动组织；页面只作为证据。"))}</p>` +
    `<div class="topic-overview-stats"><button type="button" data-overview-target="minutes">` +
    `<b>${confirmed}</b><span>${isEnglishUi() ? "Confirmed conclusions" : "已确认结论"}</span></button><button type="button" data-overview-target="minutes">` +
    `<b>${actions}</b><span>${isEnglishUi() ? "Verifiable actions" : "可核验待办"}</span></button><button type="button" data-overview-target="minutes">` +
    `<b>${unresolved}</b><span>${isEnglishUi() ? "Open questions" : "未决问题"}</span></button></div>` +
    `</div><button type="button" id="topic-map-refresh">${isEnglishUi() ? "Regenerate" : "重新归纳"}</button></header>` +
    `<div class="topic-map-canvas"><div class="topic-map-root-wrap"><button type="button" class="topic-map-root" id="topic-map-overview">` +
    `<small>${isEnglishUi() ? "Whole meeting" : "整场会议"}</small><b>${esc(state.bundle?.title || (isEnglishUi() ? "Meeting" : "会议"))}</b>` +
    `<span>${isEnglishUi() ? `${topics.length} topics · ${topicMap.stats?.children || 0} nodes · ${Math.round((topicMap.stats?.coverage || 0) * 100)}% mapped` :
      `${topics.length} 个议题 · ${topicMap.stats?.children || 0} 个节点 · ${Math.round((topicMap.stats?.coverage || 0) * 100)}% 已归入议题`}</span></button></div>` +
    `<div class="topic-map-branches">${topics.map((topic, index) =>
      topicMapBranch(topic, index, selectedNode?.id) +
      (selectedTopic && selectedNode && topic.id === selectedTopic.id
        ? topicMapDetail(selectedTopic, selectedNode, pageMap, index) : "")).join("")}</div></div>` +
    (selectedTopic && selectedNode ? "" :
      `<div class="topic-overview-hint"><b>${isEnglishUi() ? "Scan the whole structure, then select a topic" : "先看整场结构，再选择一个议题"}</b>` +
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

const MEDIA_VISUAL_ROLE_LABELS = {
  "zh-CN": { all: "全部", evidence: "证据帧", demo: "演示帧", context: "铺垫口播",
    transition: "过渡", blank: "空白", unknown: "待判断" },
  en: { all: "All", evidence: "Evidence", demo: "Demo", context: "Context / talk",
    transition: "Transition", blank: "Blank", unknown: "Pending" },
};

function mediaVisualRole(visual) {
  if (visual?.talking_head) return "context";
  const role = String(visual?.content_role || "unknown");
  return ["evidence", "demo", "context", "transition", "blank"].includes(role)
    ? role : "unknown";
}

function mediaRoleLabel(role) {
  return MEDIA_VISUAL_ROLE_LABELS[state.uiLanguage]?.[role]
    || MEDIA_VISUAL_ROLE_LABELS["zh-CN"][role] || role;
}

function visualNavCard(visual, selected) {
  const visualImage = visualImageUrl(visual);
  const copy = visualReadingCopy(visual);
  const photo = visual.kind === "photo";
  const visualStatus = photo
    ? (visual.alignment?.seconds == null ? (isEnglishUi() ? "Unlocated" : "未定位")
      : visual.alignment?.state === "suggested" ? (isEnglishUi() ? "Suggested time" : "建议时间")
        : (isEnglishUi() ? "Time confirmed" : "时间已确认"))
    : visual.display_status === "discussed" ? (isEnglishUi() ? "Discussed" : "有讨论") :
    visual.display_status === "display_only" ? (isEnglishUi() ? "Display only" : "仅展示") :
      (isEnglishUi() ? "Motion" : "动态画面");
  const role = contentTypeOf(state.bundle) === "media" ? mediaVisualRole(visual) : null;
  return `<button type="button" class="visual-nav-card ${visual.id === selected.id ? "active" : ""} ` +
    `${visual.information_value === "low" ? "low-information" : ""}" ` +
    `data-visual-select="${esc(visual.id)}"><span class="visual-nav-thumb">` +
    (visualImage ? `<img src="${visualImage}" alt="">` : `<i>${isEnglishUi() ? "No frame" : "无截图"}</i>`) +
    `</span><span class="visual-nav-copy"><small>${visual.first == null ? (isEnglishUi() ? "Unlocated" : "未定位") : fmt(visual.first)} · ` +
    `${visual.kind === "slide" ? (isEnglishUi() ? `Frame ${visual.page}` : `第${visual.page}帧`) : photo ? (isEnglishUi() ? "Meeting material" : "现场资料") : (isEnglishUi() ? "Camera" : "摄像头")}</small>` +
    `<b>${esc(copy.title)}</b><span>` +
    (role ? `<i class="visual-role ${esc(role)}">${esc(mediaRoleLabel(role))}</i>` : photo ? "" :
      `<i class="visual-value ${esc(visual.information_value || "unknown")}">${esc(visualValueLabel(visual))}</i>`) +
    `<em>${esc(visualStatus)}</em></span></span></button>`;
}

function photoAnalysisCopy(stateName) {
  const english = isEnglishUi();
  return {
    queued: english ? "Visual analysis queued" : "视觉分析已排队",
    analyzing: english ? "Analyzing meeting material" : "正在分析现场资料",
    ready: english ? "Visual interpretation ready" : "现场资料解读已就绪",
    failed: english ? "Visual analysis did not finish" : "视觉分析未完成",
    not_requested: english ? "Not analyzed yet" : "尚未进行视觉分析",
  }[stateName] || (english ? "Analysis status unknown" : "分析状态未知");
}

async function queuePhotoAnalysis(photoIds) {
  if (!state.slug || !photoIds?.length) return false;
  const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/photos/analyze`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ photo_ids: [...new Set(photoIds)] }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || String(response.status));
  await refreshPhotoMaterials();
  await pollJobs();
  return true;
}

function visualRangeDuration(visual) {
  return (visual.ranges || []).reduce((total, range) =>
    total + Math.max(0, Number(range[1]) - Number(range[0])), 0);
}

function mediaVisualGroups(visuals) {
  const topics = topicMapReady() ? (readingTopicMap().topics || []) : [];
  const pageToTopic = new Map();
  topics.forEach(topic => (topic.page_ids || []).forEach(id => {
    if (!pageToTopic.has(id)) pageToTopic.set(id, topic.id);
  }));
  const groups = topics.map((topic, index) => ({
    id: topic.id, title: topic.title, index,
    visuals: visuals.filter(visual => pageToTopic.get(visual.id) === topic.id),
  })).filter(group => group.visuals.length);
  const unmatched = visuals.filter(visual => !pageToTopic.has(visual.id));
  if (unmatched.length) groups.push({
    id: "unmapped", index: groups.length,
    title: isEnglishUi() ? "Other visual material" : "其他画面资料", visuals: unmatched,
  });
  return groups.length ? groups : [{
    id: "all", index: 0, title: isEnglishUi() ? "Whole content" : "整条内容", visuals,
  }];
}

function mediaVisualList(visuals, selected) {
  return mediaVisualGroups(visuals).map((group, groupIndex) => {
    const talking = group.visuals.filter(visual => visual.talking_head);
    const frames = group.visuals.filter(visual => !visual.talking_head);
    const appearances = talking.reduce((total, visual) => total + (visual.ranges || []).length, 0);
    const duration = talking.reduce((total, visual) => total + visualRangeDuration(visual), 0);
    const talkMarkup = talking.length ? `<details class="media-talking-group" ${groupIndex === 0 ? "open" : ""}>` +
      `<summary><b>${isEnglishUi() ? "Talking head" : "口播"}</b><span>${isEnglishUi()
        ? `${appearances} appearances · ${fmt(duration)}` : `${appearances} 次 · 共 ${fmt(duration)}`}</span></summary>` +
      `<div>${talking.flatMap(visual => (visual.ranges || []).map(([start, end]) =>
        `<button type="button" data-talking-visual="${esc(visual.id)}" data-talking-time="${Number(start)}">` +
        `${fmt(start)}–${fmt(end)}</button>`)).join("")}</div></details>` : "";
    return `<details class="media-visual-section" open><summary><span>${String(groupIndex + 1).padStart(2, "0")}</span>` +
      `<b>${esc(group.title)}</b><em>${group.visuals.length}</em></summary><div class="media-visual-section-body">` +
      frames.map(visual => visualNavCard(visual, selected)).join("") + talkMarkup + `</div></details>`;
  }).join("");
}

function renderVisuals(preserveListScroll = false) {
  const box = $("#visuals");
  if (!state.bundle) {
    box.innerHTML = `<p class="placeholder">${isEnglishUi()
      ? "Select a meeting to view visuals and materials" : "选择会议后可查看画面与资料"}</p>`;
    return;
  }
  // 点选卡片会整棵重建 DOM，先记住左侧列表滚动位置，渲染后恢复，
  // 否则点第 N 页时列表会跳回顶部。
  const prevListScroll = preserveListScroll
    ? (box.querySelector(".visual-list")?.scrollTop || 0) : 0;
  const allVisuals = state.bundle?.structure?.visuals || [];
  const media = contentTypeOf(state.bundle) === "media";
  const upgradeNotice = visualUpgradeNotice();
  if (!allVisuals.length) {
    box.innerHTML = media
      ? `${upgradeNotice}<div class="structure-empty-state"><h3>${isEnglishUi() ? "No visual analysis" : "没有画面解析"}</h3>`
        + `<p>${isEnglishUi() ? "This media can still be reviewed through its analysis and transcript." : "仍可通过分析纪要和逐字稿回顾这条媒体。"}</p></div>`
      : `${upgradeNotice}<div class="materials-empty"><div><h3>${isEnglishUi() ? "No visuals or meeting materials yet" : "还没有画面或现场资料"}</h3>`
        + `<p>${isEnglishUi() ? "Add photos of whiteboards, paper notes, room displays, or physical objects that the recording did not capture clearly." : "可以补充视频中没有清楚记录的白板、纸面笔记、会议室展示或实物照片。"}</p>`
        + `<button type="button" class="primary" data-add-materials><svg class="fluent-icon" aria-hidden="true"><use href="/static/fluent-icons.svg#fluent-add"></use></svg>`
        + `<span>${isEnglishUi() ? "Add meeting materials" : "添加现场资料"}</span></button></div>`
        + `<p class="materials-trust-boundary">${isEnglishUi() ? "Meeting materials supplement context; without discussion or human confirmation, they are not meeting decisions." : "现场资料用于补充上下文；未经发言或人工确认，不单独作为会议决定依据。"}</p></div>`;
    $("[data-add-materials]", box)?.addEventListener("click", event =>
      choosePhotoFiles("materials", event.currentTarget));
    wireVisualUpgrade(box);
    return;
  }
  const useful = allVisuals.filter(item => item.information_value !== "low");
  if (!media && !useful.length) state.visualFilter = "all";
  const visuals = media
    ? (state.visualFilter === "all" ? allVisuals : allVisuals.filter(
      visual => mediaVisualRole(visual) === state.visualFilter))
    : (state.visualFilter === "useful" && useful.length ? useful : allVisuals);
  if (!visuals.length) state.visualFilter = "all";
  const visibleVisuals = visuals.length ? visuals : allVisuals;
  const selected = visibleVisuals.find(item => item.id === state.selectedVisualId) || visibleVisuals[0];
  state.selectedVisualId = selected.id;
  const selectedCopy = visualReadingCopy(selected);
  const selectedPhoto = selected.kind === "photo";
  const status = selectedPhoto
    ? (selected.alignment?.seconds == null ? (isEnglishUi() ? "Unlocated" : "未定位")
      : selected.alignment?.state === "suggested" ? (isEnglishUi() ? "Suggested time" : "建议时间")
        : (isEnglishUi() ? "Time confirmed" : "时间已确认"))
    : selected.display_status === "discussed" ? (isEnglishUi() ? "Discussed" : "有对应讨论")
    : selected.display_status === "display_only" ? (isEnglishUi() ? "Display only" : "仅展示")
      : (isEnglishUi() ? "Motion" : "动态画面");
  const image = visualImageUrl(selected);
  const filters = media ? ["all", "evidence", "demo", "context", "transition"].map(role => {
    const count = role === "all" ? allVisuals.length : allVisuals.filter(
      visual => mediaVisualRole(visual) === role).length;
    return `<button type="button" data-visual-filter="${role}" class="${state.visualFilter === role ? "active" : ""}">` +
      `${esc(mediaRoleLabel(role))} ${count}</button>`;
  }).join("") : `<button type="button" data-visual-filter="useful" ` +
    `class="${state.visualFilter === "useful" ? "active" : ""}">${isEnglishUi() ? "Key" : "重点"} ${useful.length}</button>` +
    `<button type="button" data-visual-filter="all" class="${state.visualFilter === "all" ? "active" : ""}">` +
    `${isEnglishUi() ? "All" : "全部"} ${allVisuals.length}</button>`;
  const materialsHeader = media ? "" : `<div class="materials-toolbar"><p>${isEnglishUi()
    ? "Meeting materials supplement context; without discussion or human confirmation, they are not meeting decisions."
    : "现场资料用于补充上下文；未经发言或人工确认，不单独作为会议决定依据。"}</p>`
    + `<button type="button" class="subtle" data-add-materials><svg class="fluent-icon" aria-hidden="true"><use href="/static/fluent-icons.svg#fluent-add"></use></svg>`
    + `<span>${isEnglishUi() ? "Add meeting materials" : "添加现场资料"}</span></button></div>`;
  const analysisNotice = selectedPhoto
    ? (["queued", "analyzing"].includes(selected.analysis_state)
      ? `<div class="visual-reprocess pending">${esc(photoAnalysisCopy(selected.analysis_state))}</div>`
      : (["failed", "not_requested"].includes(selected.analysis_state)
        ? `<div class="visual-reprocess"><span>${esc(photoAnalysisCopy(selected.analysis_state))}</span>`
          + `<button type="button" data-photo-analyze="${esc(selected.id)}">${isEnglishUi() ? "Analyze again" : "重新分析"}</button></div>`
        : ""))
    : (selected.analysis_state === "pending"
      ? `<div class="visual-reprocess pending">${isEnglishUi()
        ? "Visual analysis is still running. Its information value will be assessed after completion."
        : "屏幕解析仍在进行，完成前不会判断这页的内容价值。"}</div>`
      : (selected.needs_reprocess
        ? `<div class="visual-reprocess">页面解析没有得到可读正文，已标记为需要重新解析；当前不会将它判为低信息。</div>`
        : ""));
  box.innerHTML = `${upgradeNotice}${materialsHeader}<div class="structure-layout visual-layout"><nav class="structure-list visual-list" aria-label="${esc(contentLabel(contentTypeOf(state.bundle), "screens"))}">` +
    `<div class="structure-list-head visual-list-head"><div><b>${esc(contentLabel(contentTypeOf(state.bundle), "screens"))}</b>` +
    `<span>${allVisuals.length} ${isEnglishUi() ? "items" : "项"}</span></div><div class="visual-filter ${media ? "media-role-filter" : ""}">` +
    filters + `</div></div>` +
    (media ? mediaVisualList(visibleVisuals, selected) : visibleVisuals.map(
      visual => visualNavCard(visual, selected)).join("")) +
    `</nav><article class="structure-detail visual-detail">` +
    `<header class="structure-detail-head"><div><span>${selectedPhoto ? (isEnglishUi() ? "Meeting material" : "现场资料") : (isEnglishUi() ? "Screen" : "屏幕")} · ${esc(status)}`
    + (selectedPhoto ? "" : ` · ${esc(visualValueLabel(selected))}`) + `</span>` +
    `<h2>${esc(selectedCopy.title)}</h2>` +
    (selectedCopy.summary ? `<p>${esc(selectedCopy.summary)}</p>` : "") + `</div></header>` +
    (selectedPhoto ? "" : `<div class="visual-value-note ${esc(selected.information_value || "unknown")}"><b>${esc(visualValueLabel(selected))}</b>` +
      `<span>${esc(selected.value_reason || (isEnglishUi() ? "The information value has not been assessed." : "尚未判断这张画面的信息价值。"))}</span></div>`) +
    analysisNotice +
    (selectedPhoto ? `<div class="visual-photo-actions"><span>${selected.alignment?.seconds == null
      ? (isEnglishUi() ? "This photo is saved but not linked to playback." : "照片已保存，但尚未关联播放进度。")
      : `${isEnglishUi() ? "Located at" : "定位于"} ${fmt(selected.alignment.seconds)} · ${selected.alignment?.state === "suggested" ? (isEnglishUi() ? "Suggested from capture time" : "依据拍摄时间建议") : (isEnglishUi() ? "Confirmed" : "已确认")}`}</span>` +
      `<button type="button" data-photo-align-current="${esc(selected.id)}">${isEnglishUi() ? "Place at current playback" : "放到当前播放位置"}</button>` +
      (selected.alignment?.seconds != null ? `<button type="button" data-photo-unlocate="${esc(selected.id)}">${isEnglishUi() ? "Remove time link" : "取消时间定位"}</button>` : "") +
      `<button type="button" data-photo-rename="${esc(selected.id)}">${isEnglishUi() ? "Rename" : "修改标题"}</button>` +
      `<button type="button" class="danger-text" data-photo-delete="${esc(selected.id)}">${isEnglishUi() ? "Delete" : "删除"}</button>` +
      `</div>` : "") +
    (selectedPhoto && state.photoRenameId === selected.id ? `<form class="photo-rename-form" data-photo-rename-form="${esc(selected.id)}">`
      + `<label><span>${isEnglishUi() ? "Display title" : "显示标题"}</span><input name="title" maxlength="120" value="${esc(selectedCopy.title)}"></label>`
      + `<div><button type="submit" class="primary">${isEnglishUi() ? "Save" : "保存"}</button>`
      + `<button type="button" data-photo-rename-cancel>${isEnglishUi() ? "Cancel" : "取消"}</button></div></form>` : "") +
    `<div class="visual-ranges">${(selected.ranges || []).map(([start, end]) =>
      `<button type="button" data-visual-seek="${start}">${fmt(start)}–${fmt(end)}</button>`).join("")}</div>` +
    (image ? `<img class="visual-hero" data-preview-visual="${esc(selected.id)}" src="${image}" ` +
      `alt="${esc(selectedCopy.title)}" title="${isEnglishUi() ? "Click to enlarge" : "点击放大查看"}">` :
      `<div class="visual-no-image">${isEnglishUi() ? "No static image is available" : "没有可用的静态图片"}</div>`) +
    (selectedPhoto ? `<section class="visual-description photo-material-description"><h3>${isEnglishUi() ? "Material interpretation" : "现场资料解读"}</h3>`
      + (selected.description ? `<div>${visualDescriptionHtml(selected)}</div>`
        : `<p>${esc(photoAnalysisCopy(selected.analysis_state))}</p>`)
      + `</section>` : `<section class="visual-description"><h3>${isEnglishUi() ? "Screen interpretation" : "屏幕内容解读"}</h3>`
      + `<p class="visual-boundary">${isEnglishUi() ? "This describes what was shown; it does not prove a meeting decision." : "仅说明画面展示内容，不代表会议作出了决定。"}</p>`
      + `<div>${visualDescriptionHtml(selected)}</div></section>`) +
    structureClaimGroup(isEnglishUi() ? "Related meeting content" : "相关会议内容", selected.claim_ids) +
    `</article></div>`;
  $$('[data-add-materials]', box).forEach(button => button.onclick = event =>
    choosePhotoFiles("materials", event.currentTarget));
  wireVisualUpgrade(box);
  $$('[data-visual-select]', box).forEach(button => button.onclick = () => {
    state.selectedVisualId = button.dataset.visualSelect;
    renderVisuals(true);
  });
  $$('[data-visual-filter]', box).forEach(button => button.onclick = () => {
    state.visualFilter = button.dataset.visualFilter;
    renderVisuals();
  });
  $$('[data-talking-visual]', box).forEach(button => button.onclick = () => {
    state.selectedVisualId = button.dataset.talkingVisual;
    renderVisuals(true);
    seek(Number(button.dataset.talkingTime));
  });
  $$('[data-visual-seek]', box).forEach(button =>
    button.onclick = () => seek(Number(button.dataset.visualSeek)));
  $$('[data-photo-align-current]', box).forEach(button =>
    button.onclick = () => updatePhotoAlignment(button.dataset.photoAlignCurrent,
      Number(player()?.currentTime || state.focus.time || 0)));
  $$('[data-photo-unlocate]', box).forEach(button =>
    button.onclick = () => updatePhotoAlignment(button.dataset.photoUnlocate, null));
  $$('[data-photo-rename]', box).forEach(button => button.onclick = () => {
    state.photoRenameId = button.dataset.photoRename;
    renderVisuals(true);
    $(".photo-rename-form input", box)?.select();
  });
  $("[data-photo-rename-cancel]", box)?.addEventListener("click", () => {
    state.photoRenameId = null;
    renderVisuals(true);
  });
  $("[data-photo-rename-form]", box)?.addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    try { await savePhotoTitle(form.dataset.photoRenameForm, new FormData(form).get("title")); }
    catch (error) { toast(`${isEnglishUi() ? "Rename failed" : "修改标题失败"}：${error.message}`); }
  });
  $$('[data-photo-delete]', box).forEach(button => button.onclick = () =>
    openPhotoDeleteDialog(button.dataset.photoDelete, selectedCopy.title, button));
  $$('[data-photo-analyze]', box).forEach(button => button.onclick = async () => {
    button.disabled = true;
    try {
      await queuePhotoAnalysis([button.dataset.photoAnalyze]);
      toast(isEnglishUi() ? "Visual analysis queued" : "视觉分析已排队");
    } catch (error) {
      button.disabled = false;
      toast(isEnglishUi() ? "Could not queue visual analysis" : "无法排入视觉分析");
    }
  });
  $$('[data-preview-visual]', box).forEach(image =>
    image.onclick = () => openScreenPreview(image.dataset.previewVisual));
  wireStructureClaims(box);
  if (prevListScroll) {
    const list = box.querySelector(".visual-list");
    if (list) list.scrollTop = prevListScroll;
  }
}

function setReviewMode(mode) {
  state.viewMode = normalizeReviewMode(mode, state.bundle);
  for (const id of ["minutes", "chapters", "visuals", "quality"])
    $(`#${id}`).classList.toggle("hidden", state.viewMode !== id);
  for (const id of ["minutes", "chapters", "visuals", "quality"]) {
    const active = state.viewMode === id;
    $(`#${id}-tab`).classList.toggle("active", active);
    $(`#${id}-tab`).setAttribute("aria-selected", String(active));
  }
  $("#restructure-minutes")?.classList.toggle("hidden", state.viewMode !== "minutes");
  $("#minutes-view")?.classList.toggle("hidden", state.viewMode !== "minutes"
    || !(state.bundle?.minutes_views || []).length);
  $("#restore-minutes")?.classList.toggle("hidden", state.viewMode !== "minutes"
    || (state.workspace.minutesViews[state.slug] || "standard") !== "standard"
    || !state.bundle?.minutes_history_available);
  if (state.viewMode === "chapters") renderChapters();
  if (state.viewMode === "visuals") renderVisuals();
  if (state.viewMode === "quality") renderQualityReview();
  if (state.quality) updateQualityIndicators();
}

function showMinutesEvidence(claimId, jumpToFirst = false) {
  const claim = (state.bundle?.evidence?.claims || []).find(c => c.id === claimId);
  if (!claim) return;
  expandEvidenceBilingual(claim.turn_indexes || []);
  const sources = evidenceSources(state.bundle, claim);
  const turns = sources.turns.map(item => ({ i: item.index, t: item.turn }));
  const pages = sources.pages;
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
  if (jumpToFirst) {
    if (sources.firstTime != null) seek(sources.firstTime);
  }
}

/* ---------- 关键结论核对 ---------- */

const qualityStatusNames = {
  confirmed: ["已确认决定", "Confirmed decision"],
  working_alignment: ["方向共识", "Working alignment"],
  proposal: ["提议", "Proposal"],
  open: ["待解决", "Open"],
  informational: ["信息记录", "Information"],
};

const qualityKindNames = {
  decision: ["决定", "Decision"],
  alignment: ["共识", "Alignment"],
  proposal: ["提议", "Proposal"],
  action: ["行动项", "Action"],
  discussion: ["讨论", "Discussion"],
  purpose: ["主旨", "Purpose"],
  open_question: ["待决问题", "Open question"],
};

const qualityLabelEnglish = {
  correct: "Conclusion matches the evidence",
  proposal_not_decision: "Proposal presented as a decision",
  should_be_decision: "Decision omitted or weakened",
  wrong_evidence: "Evidence does not support this conclusion",
  wrong_owner_deadline: "Owner or due date is incorrect",
  unsupported: "No transcript support",
  cannot_judge: "Cannot verify yet",
};

function qualityCopy(chinese, english) { return isEnglishUi() ? english : chinese; }

function qualityLabelName(id) {
  if (isEnglishUi() && qualityLabelEnglish[id]) return qualityLabelEnglish[id];
  return state.quality?.labels?.find(item => item.id === id)?.label || id || "";
}

function updateQualityIndicators() {
  const summary = state.quality?.priority_summary || state.quality?.summary || {};
  const pending = summary.pending || 0;
  const total = summary.total || 0;
  const evidenceReady = state.quality?.evidence_state === "ready";
  $("#quality-badge").textContent = pending;
  $("#quality-badge").classList.toggle("hidden", pending === 0);
  const issues = Number(summary.issues || 0);
  const stale = Number(summary.stale || 0);
  const needsAttention = !evidenceReady || pending > 0 || issues > 0 || stale > 0;
  const entry = $("#quality-entry-btn");
  entry.classList.toggle("hidden", !needsAttention && state.viewMode !== "quality");
  entry.classList.toggle("evidence-missing", !evidenceReady || stale > 0);
  entry.setAttribute("aria-pressed", String(state.viewMode === "quality"));
  entry.textContent = !evidenceReady
    ? (isEnglishUi() ? "Conclusion evidence needs updating" : "结论依据需要更新")
    : pending
      ? `${isEnglishUi() ? "Review key conclusions" : "核对关键结论"} · ${pending}`
      : issues
        ? `${isEnglishUi() ? "Review identified issues" : "查看已发现问题"} · ${issues}`
        : stale
          ? `${isEnglishUi() ? "Review outdated decisions" : "重新核对过期判断"} · ${stale}`
          : (isEnglishUi() ? "Key conclusions reviewed" : "关键结论已核对");
}

async function loadQualityReview() {
  if (!state.slug) return;
  try {
    state.quality = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/quality`);
    updateQualityIndicators();
    renderQualityReview();
  } catch (e) {
    state.quality = null;
    $("#quality").innerHTML = `<p class="placeholder">${qualityCopy(
      "无法读取本地核对记录", "Could not load the local review record")}</p>`;
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
    return claim.status === "informational"
      ? qualityCopy("过程记录", "Process note")
      : qualityCopy("行动线索（未入待办）", "Action clue (not a formal action)");
  const pair = qualityKindNames[claim.kind];
  return pair ? pair[isEnglishUi() ? 1 : 0] : claim.kind;
}

function renderQualityReview() {
  const box = $("#quality");
  const quality = state.quality;
  if (!box || !quality) return;
  if (quality.evidence_state !== "ready") {
    const reason = quality.evidence_state === "stale"
      ? qualityCopy("纪要或逐字稿已经变化，现有依据已过期。",
        "The minutes or transcript changed, so the current evidence is out of date.")
      : qualityCopy("这场会议还没有结构化的结论依据。",
        "This meeting does not have structured conclusion evidence yet.");
    box.innerHTML = `<div class="quality-empty"><h3>${qualityCopy(
      "暂时无法核对关键结论", "Key conclusions cannot be reviewed yet")}</h3><p>${esc(reason)}</p>` +
      `<p class="dim">${qualityCopy(
        "请先重新生成纪要；核对不会调用模型，也不会修改正式纪要。",
        "Regenerate the minutes first. Reviewing does not call a model or modify the official minutes.")}</p></div>`;
    return;
  }
  const allSummary = quality.summary || {};
  const prioritySummary = quality.priority_summary || allSummary;
  if (!allSummary.total) {
    box.innerHTML = `<div class="quality-empty"><h3>${qualityCopy(
      "还没有可核对的结构化结论", "There are no structured conclusions to review")}</h3>` +
      `<p>${qualityCopy("这份旧纪要没有结论级依据标记，需要重新生成一次带依据的纪要。",
        "These older minutes do not contain conclusion-level evidence markers. Regenerate them once to add evidence.")}</p>` +
      `<p class="dim">${qualityCopy("打开核对不会运行模型，也不会改变现有纪要。",
        "Opening this review does not run a model or change the official minutes.")}</p></div>`;
    return;
  }
  const s = state.qualityScope === "priority" ? prioritySummary : allSummary;
  const pct = s.total ? Math.round((s.reviewed / s.total) * 100) : 0;
  const filters = [
    ["pending", `${qualityCopy("待核对", "Pending")} ${s.pending || 0}`],
    ["issues", `${qualityCopy("有问题", "Issues")} ${s.issues || 0}`],
    ["passed", `${qualityCopy("正确", "Correct")} ${s.passed || 0}`],
    ["all", `${qualityCopy("全部", "All")} ${s.total || 0}`],
  ];
  let html = `<section class="quality-summary">` +
    `<div class="quality-summary-head"><div><b>${qualityCopy("核对关键结论", "Review key conclusions")}</b>` +
    `<p>${qualityCopy("默认只核对决定、共识、正式行动、风险与未决问题；背景记录仍保留在“全部证据”。",
      "The default view focuses on decisions, alignment, formal actions, risks, and open questions. Background records remain under All evidence.")}</p></div>` +
    `<strong>${s.reviewed || 0}/${s.total || 0}</strong></div>` +
    `<div class="quality-progress"><i style="width:${pct}%"></i></div>` +
    `<div class="quality-metrics"><span>${qualityCopy("完成", "Complete")} ${pct}%</span>` +
    `<span class="issue">${qualityCopy("问题", "Issues")} ${s.issues || 0}</span>` +
    `<span>${qualityCopy("待定", "Uncertain")} ${s.uncertain || 0}</span>` +
    `<span>${qualityCopy("过期", "Outdated")} ${s.stale || 0}</span>` +
    `<span>${qualityCopy("逐字稿依据", "Transcript evidence")} ${s.with_transcript_evidence || 0}/${s.total || 0}</span></div>` +
    `<div class="quality-scope"><button type="button" data-quality-scope="priority" ` +
    `class="${state.qualityScope === "priority" ? "active" : ""}">${qualityCopy(
      "重点结论", "Key conclusions")} ${prioritySummary.total || 0}</button>` +
    `<button type="button" data-quality-scope="all" class="${state.qualityScope === "all" ? "active" : ""}">` +
    `${qualityCopy("全部证据", "All evidence")} ${allSummary.total || 0}</button></div>` +
    `<div class="quality-filters">${filters.map(([id, label]) =>
      `<button type="button" data-quality-filter="${id}" class="${state.qualityFilter === id ? "active" : ""}">${label}</button>`
    ).join("")}</div></section>`;

  const claims = quality.claims.filter(qualityClaimVisible);
  if (!claims.length) {
    const emptyTitle = state.qualityScope === "priority" && !(prioritySummary.total || 0)
      ? qualityCopy("没有需要优先核对的重点结论", "No key conclusions need priority review")
      : state.qualityFilter === "pending"
        ? qualityCopy("这一轮结论已经核对完成", "This review is complete")
        : qualityCopy("此筛选下没有条目", "No items match this filter");
    html += `<div class="quality-empty"><h3>${emptyTitle}</h3>` +
      `<p class="dim">${qualityCopy("可以切换范围或筛选，查看保留的背景事实与既有判断。",
        "Change the scope or filter to inspect retained background facts and earlier reviews.")}</p></div>`;
  }
  for (const claim of claims) {
    const review = claim.review;
    const stale = claim.previous_review;
    const statusPair = qualityStatusNames[claim.status];
    const status = statusPair ? statusPair[isEnglishUi() ? 1 : 0] : claim.status;
    const kind = qualityClaimKind(claim);
    html += `<article class="quality-card ${review ? `reviewed label-${esc(review.label)}` : ""}" data-quality-claim="${esc(claim.id)}">` +
      `<div class="quality-card-head"><div class="quality-tags"><span>${esc(status)}</span><span>${esc(kind)}</span>` +
      `<span class="${claim.has_transcript_evidence ? "has-evidence" : "missing-evidence"}">` +
      `${claim.turn_ids?.length || 0} ${qualityCopy("段原文", "excerpts")}</span>` +
      `<span>${claim.page_ids?.length || 0} ${qualityCopy("页画面", "visuals")}</span></div>` +
      `<button type="button" class="quality-evidence">${qualityCopy("打开相关原话", "Open source evidence")}</button></div>` +
      `<div class="quality-claim-text">${esc(claim.text)}</div>` +
      (claim.speakers?.length ? `<div class="quality-speakers">${qualityCopy("发言", "Speakers")}：${esc(claim.speakers.join("、"))}</div>` : "") +
      (stale ? `<div class="quality-stale">${esc(qualityCopy(
        `相关内容有变化，原判断“${qualityLabelName(stale.label)}”已失效，请重新核对。`,
        `The source changed. The previous review “${qualityLabelName(stale.label)}” is outdated; review it again.`))}</div>` : "") +
      `<div class="quality-labels">${quality.labels.map(item =>
        `<button type="button" data-quality-label="${esc(item.id)}" title="${qualityCopy("快捷键", "Shortcut")} ${esc(item.shortcut)}" ` +
        `class="${review?.label === item.id ? "selected" : ""}"><kbd>${esc(item.shortcut)}</kbd>${esc(qualityLabelName(item.id))}</button>`
      ).join("")}</div>` +
      `<details class="quality-note" ${review?.note ? "open" : ""}><summary>${qualityCopy(
        "补充说明（可选）", "Add a note (optional)")}</summary>` +
      `<textarea maxlength="1000" rows="2" placeholder="${qualityCopy(
        "例如：原文是建议语气，尚未确认…", "For example: the source is phrased as a proposal, not a confirmed decision…")}">${esc(review?.note || "")}</textarea>` +
      (review ? `<button type="button" class="quality-save-note">${qualityCopy("保存说明", "Save note")}</button>` : `<span class="dim">${qualityCopy("选择判断时会一并保存", "The note is saved with your review")}</span>`) +
      `</details>` +
      (review ? `<div class="quality-result">${qualityCopy("已记录", "Recorded")}：${esc(qualityLabelName(review.label))}</div>` : "") +
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
    toast(`${qualityCopy("已记录", "Recorded")}：${qualityLabelName(label)}`);
  } catch (e) {
    button.disabled = false;
    toast(`${qualityCopy("核对记录失败", "Could not save the review")}：${e.message}`);
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

function updatePhotoCurrentButton(seconds = 0) {
  const button = $("#photo-import-current-btn");
  if (!button) return;
  const meeting = state.bundle && contentTypeOf(state.bundle) === "meeting";
  button.classList.toggle("hidden", !meeting);
  button.disabled = !meeting;
  const label = $("span", button);
  if (label) label.textContent = isEnglishUi()
    ? `Add photo at ${fmt(seconds)}` : `在 ${fmt(seconds)} 添加照片`;
  button.setAttribute("aria-label", label?.textContent || "");
}

function choosePhotoFiles(entry = "materials", trigger = null) {
  if (!state.slug || contentTypeOf(state.bundle) !== "meeting") return;
  state.pendingPhotoEntry = entry === "player" ? "player" : "materials";
  state.pendingPhotoReturnFocus = trigger || document.activeElement;
  $(".more-menu")?.removeAttribute("open");
  $("#photo-file-input")?.click();
}

function renderPhotoImportDialog() {
  renderPhotoImport({
    root: $("#photo-import-content"),
    state: state.photoImport,
    language: state.uiLanguage,
    escapeHtml: esc,
    formatTime: fmt,
    formatBytes: formatPhotoBytes,
    onRemove: id => {
      state.photoImport = removePhotoImportItem(state.photoImport, id);
      if (!state.photoImport.items.length) return closePhotoImportDialog();
      renderPhotoImportDialog();
    },
    onToggleSettings: id => {
      state.photoImport = togglePhotoTimeSettings(state.photoImport, id);
      renderPhotoImportDialog();
    },
    onMode: (id, mode) => {
      state.photoImport = setPhotoPositionMode(
        state.photoImport, id, mode, Number(player()?.currentTime || 0));
      renderPhotoImportDialog();
    },
    onMeetingStart: value => {
      state.photoImport = setPhotoMeetingStart(state.photoImport, value);
      renderPhotoImportDialog();
    },
  });
  const button = $("#photo-import-confirm");
  if (button) {
    button.disabled = state.photoImport.busy || !state.photoImport.items.length
      || state.photoImport.items.every(item => item.result);
    button.textContent = state.photoImport.busy
      ? (isEnglishUi() ? "Importing…" : "正在导入…")
      : (isEnglishUi() ? `Import ${state.photoImport.items.length} materials`
        : `导入 ${state.photoImport.items.length} 张现场资料`);
  }
}

async function openPhotoImportDialog(files) {
  if (!state.slug || contentTypeOf(state.bundle) !== "meeting") return;
  state.photoImport = beginPhotoImport(state.photoImport, files, {
    entry: state.pendingPhotoEntry,
    currentTime: Number(player()?.currentTime || 0),
    returnFocus: state.pendingPhotoReturnFocus,
  });
  if (!state.photoImport.open) return;
  $("#photo-import-mask").classList.remove("hidden");
  renderPhotoImportDialog();
  $("#photo-import-close")?.focus();
  const opened = state.photoImport;
  const hydrated = await hydratePhotoCaptureTimes(opened);
  if (state.photoImport !== opened) return;
  state.photoImport = hydrated;
  renderPhotoImportDialog();
}

function closePhotoImportDialog() {
  if (state.photoImport.busy) return;
  const returnFocus = state.photoImport.returnFocus;
  releasePhotoImport(state.photoImport);
  state.photoImport = createPhotoImportState();
  $("#photo-import-mask")?.classList.add("hidden");
  const input = $("#photo-file-input");
  if (input) input.value = "";
  if (returnFocus?.isConnected) returnFocus.focus();
}

async function importMeetingPhotos() {
  if (!state.slug || !state.photoImport.items.length || state.photoImport.busy) return;
  const specs = state.photoImport.items.map(item => ({ item,
    spec: photoUploadSpec(item, state.photoImport.meetingStart) }));
  const invalid = specs.find(entry => !entry.spec.valid);
  if (invalid) {
    state.photoImport = withPhotoImportError(state.photoImport, invalid.spec.error, invalid.item.id);
    renderPhotoImportDialog();
    scrollInside($("#photo-import-content"),
      $("[data-photo-item].has-error", $("#photo-import-content")), "nearest", false);
    return;
  }
  state.photoImport = withPhotoImportBusy(state.photoImport, true);
  renderPhotoImportDialog();
  let created = 0;
  let duplicates = 0;
  let failed = 0;
  for (const { item, spec } of specs) {
    if (item.result) continue;
    const form = new FormData();
    form.append("files", spec.file, spec.file.name);
    form.append("mode", spec.mode);
    form.append("defer_analysis", "1");
    if (spec.meetingStart) form.append("meeting_start", spec.meetingStart);
    if (spec.anchorSeconds != null) form.append("anchor_seconds", String(spec.anchorSeconds));
    try {
      const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/photos`, {
        method: "POST", body: form,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || String(response.status));
      const result = payload.results?.[0] || {
        photo: payload.imported?.[0], duplicate: Boolean(payload.duplicate_ids?.length),
      };
      if (result.duplicate) duplicates += 1; else created += 1;
      state.photoImport = markPhotoImportResult(state.photoImport, item.id, result);
    } catch (_) {
      failed += 1;
      state.photoImport = withPhotoImportError(state.photoImport, "import_failed", item.id);
    }
    renderPhotoImportDialog();
  }
  state.photoImport = withPhotoImportBusy(state.photoImport, false);
  const analysisIds = state.photoImport.items
    .filter(item => item.result && (!item.result.duplicate
      || item.result.photo?.analysis_state !== "ready"))
    .map(item => item.result?.photo?.id)
    .filter(Boolean);
  let analysisQueued = false;
  if (analysisIds.length) {
    try {
      const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/photos/analyze`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ photo_ids: [...new Set(analysisIds)] }),
      });
      analysisQueued = response.ok;
    } catch (_) { /* 图片已安全导入；分析可在资料详情中重试。 */ }
  }
  if (created || duplicates) await refreshPhotoMaterials();
  if (!failed) {
    closePhotoImportDialog();
    const message = isEnglishUi()
      ? `${created} materials imported${duplicates ? `; ${duplicates} duplicates skipped` : ""}`
        + `${analysisQueued ? ". Visual analysis is queued." : "."}`
      : `已导入 ${created} 张现场资料${duplicates ? `；${duplicates} 张重复内容未重复保存` : ""}`
        + `${analysisQueued ? "；视觉分析已排队。" : "。"}`;
    toast(message);
  } else {
    state.photoImport = withPhotoImportError(state.photoImport,
      isEnglishUi() ? "Some materials were not imported. Fix or remove the marked items, then try again."
        : "部分现场资料没有导入。请处理或移除标记项后重试。");
    renderPhotoImportDialog();
  }
}

async function openExportDialog() {
  if (!state.slug) return;
  $(".more-menu")?.removeAttribute("open");
  $("#export-mask").classList.remove("hidden");
  $("#export-confirm").disabled = true;
  state.exportRelated = [];
  $("#export-related").innerHTML = "";
  updateExportConfirmLabel();
  $("#export-preflight").innerHTML = '<p class="placeholder">正在检查证据、页面与媒体…</p>';
  jget(`/api/meetings/${encodeURIComponent(state.slug)}/keywords/related?limit=5`)
    .then(data => { state.exportRelated = data.related || []; })
    .catch(() => { state.exportRelated = []; })
    .finally(() => renderExportRelated());
  try {
    state.exportPreflight = await jget(
      `/api/meetings/${encodeURIComponent(state.slug)}/export/preflight`);
    renderExportPreflight();
  } catch (error) {
    $("#export-preflight").innerHTML = `<div class="export-warning">无法检查导出内容（${esc(error.message)}）</div>`;
  }
}

function selectedRelatedSlugs() {
  const box = $("#export-related");
  return box ? $$("input[data-related-slug]:checked", box).map(input => input.dataset.relatedSlug) : [];
}

function updateExportConfirmLabel() {
  const count = selectedRelatedSlugs().length;
  const profile = selectedExportProfile();
  if (profile === "ai") {
    $("#export-confirm").textContent = count
      ? (isEnglishUi() ? `Generate AI / knowledge pack (${count + 1})` : `生成 AI / 知识库 Pack（${count + 1} 项）`)
      : (isEnglishUi() ? "Generate AI / knowledge pack" : "生成 AI / 知识库 Pack");
  } else {
    $("#export-confirm").textContent = count
      ? (isEnglishUi() ? `Export Viewer pack (${count + 1})` : `导出 Viewer 合集（${count + 1} 项）`)
      : (isEnglishUi() ? "Generate offline Viewer" : "生成离线 Viewer");
  }
}

function renderExportRelated() {
  const box = $("#export-related");
  if (!box) return;
  const items = (state.exportRelated || []).slice(0, 5);
  if (!items.length) {
    box.innerHTML = "";
    return;
  }
  const sep = isEnglishUi() ? ", " : "、";
  box.innerHTML = `<div class="export-related-head">${esc(isEnglishUi()
    ? "Related content (optional, export together as a pack)" : "相关内容（可选，勾选后一起打包导出）")}</div>` +
    items.map(item => {
      const reason = (item.shared || []).slice(0, 4).map(k => k.text).filter(Boolean).join(sep);
      return `<label class="export-related-item">` +
        `<input type="checkbox" data-related-slug="${esc(item.slug)}">` +
        `<span><b>${esc(item.title || item.slug)}</b>` +
        `<small>${esc(isEnglishUi() ? "Shared: " : "共享：")}${esc(reason)}</small></span></label>`;
    }).join("");
  $$("input[data-related-slug]", box).forEach(input => {
    input.onchange = updateExportConfirmLabel;
  });
}

function exportPack(slugs, media = "none", profile = "full") {
  if (!slugs.length) return;
  closeExportDialog();
  const a = document.createElement("a");
  a.href = packExportHref(slugs, media, profile);
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast(profile !== "full"
    ? (profile === "ai"
      ? (isEnglishUi()
        ? `Generating AI context pack (${slugs.length} sources)…`
        : `正在生成 AI 上下文包（${slugs.length} 个来源）…`)
      : (isEnglishUi()
        ? `Generating ${profile === "kb-html" ? "visual " : ""}knowledge-base pack (${slugs.length} items)…`
        : `正在生成${profile === "kb-html" ? "图文" : "轻量"}知识库内容包（${slugs.length} 个内容）…`))
    : isEnglishUi()
    ? `Generating content pack (${slugs.length} items)…`
    : `正在生成内容包（${slugs.length} 个内容）…`);
}

function closeExportDialog() {
  $("#export-mask").classList.add("hidden");
}

async function openKnowledgePublishDialog() {
  if (!state.slug) return;
  $(".more-menu")?.removeAttribute("open");
  $("#knowledge-publish-title").textContent = isEnglishUi()
    ? "Publish to knowledge base" : "发布到知识库";
  $("#knowledge-publish-subtitle").textContent = isEnglishUi()
    ? "Publish the current trusted revision to WeKnora; publishing again updates the same knowledge item."
    : "把当前可信版本发布到 WeKnora；再次发布会更新同一条知识。";
  $("#knowledge-publish-cancel").textContent = isEnglishUi() ? "Cancel" : "取消";
  $("#knowledge-publish-confirm").textContent = isEnglishUi()
    ? "Publish current revision" : "发布当前版本";
  $("#knowledge-publish-mask").classList.remove("hidden");
  $("#knowledge-publish-confirm").disabled = true;
  $("#knowledge-publish-content").innerHTML = `<p class="placeholder">${isEnglishUi()
    ? "Checking knowledge structure and publication status…"
    : "正在检查知识结构与发布状态…"}</p>`;
  try {
    state.knowledgePreflight = await jget(
      `/api/meetings/${encodeURIComponent(state.slug)}/knowledge/preflight`);
    renderKnowledgePublishDialog();
  } catch (error) {
    $("#knowledge-publish-content").innerHTML = `<div class="export-warning">${esc(
      isEnglishUi() ? `Preflight failed: ${error.message}` : `发布检查失败：${error.message}`)}</div>`;
  }
}

function closeKnowledgePublishDialog() {
  $("#knowledge-publish-mask").classList.add("hidden");
}

function renderKnowledgePublishDialog() {
  const data = state.knowledgePreflight;
  if (!data) return;
  const english = isEnglishUi();
  const kind = data.content_type === "media"
    ? (english ? "Media source" : "媒体内容") : (english ? "Meeting" : "会议");
  if (!data.configured || !data.targets?.length) {
    $("#knowledge-publish-content").innerHTML = `<div class="knowledge-setup"><b>${esc(english
      ? "One-time server setup required" : "需要一次服务端配置")}</b><p>${esc(english
      ? "Set the WeKnora API URL, scoped API key, and an allowed target knowledge-base ID. Credentials stay on the server and never enter this browser or Git."
      : "配置 WeKnora API 地址、具备写权限的 API key 和允许发布的知识库 ID。凭据只留在服务端，不进入浏览器或 Git。")}</p>` +
      `<code>MEETING_KB_API_URL · MEETING_KB_API_KEY · MEETING_KB_DEFAULT_ID</code></div>`;
    return;
  }
  const targets = data.targets.filter(item => item.available);
  const selectedTarget = targets[0];
  const profiles = [
    ["auto", english ? "Auto for this source" : "按内容自动选择",
      data.recommended_profile === "kb-html"
        ? (english ? "Visual HTML" : "图文 HTML") : (english ? "Text knowledge" : "轻量文字")],
    ["kb", english ? "Text knowledge" : "轻量文字",
      english ? "Small, fast, conclusions + transcript + deep links" : "体积小、入库快，保留结论/原文/时间依据"],
    ["kb-html", english ? "Visual knowledge" : "图文知识",
      english ? "Embeds selected frames and meeting photos" : "内嵌筛选画面与现场照片"],
  ];
  const publication = selectedTarget?.publication;
  $("#knowledge-publish-content").innerHTML =
    `<div class="knowledge-summary"><span><b>${esc(kind)}</b>${esc(english ? "Source type" : "内容类型")}</span>` +
    `<span><b>${Number(data.content?.transcript_turns || 0)}</b>${esc(english ? "Transcript turns" : "段逐字稿")}</span>` +
    `<span><b>${Number(data.content?.pages || 0)} + ${Number(data.content?.photos || 0)}</b>${esc(english ? "Key frames + photos" : "关键画面 + 现场照片")}</span></div>` +
    `<label class="knowledge-target-field"><span>${esc(english ? "Target knowledge base" : "目标知识库")}</span>` +
    `<select id="knowledge-target-select">${targets.map(item =>
      `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")}</select></label>` +
    `<div class="knowledge-recommendation"><b>${esc(english ? "Recommended" : "推荐")}: ${esc(
      data.recommended_profile === "kb-html" ? (english ? "Visual knowledge" : "图文知识")
        : (english ? "Text knowledge" : "轻量文字"))}</b><br>${esc(data.recommendation_reason || "")}</div>` +
    `<div class="export-profile">${profiles.map(([id, title, detail], index) =>
      `<label class="export-profile-option"><input type="radio" name="knowledge-profile" value="${id}" ${index === 0 ? "checked" : ""}>` +
      `<span><b>${esc(title)}</b><small>${esc(detail)}</small></span></label>`).join("")}</div>` +
    (publication ? `<div class="export-note"><b>${esc(english ? "Existing publication" : "已有发布")}</b><br>` +
      `${esc(publication.published_at || "")} · ${esc(publication.profile || "")}` +
      `<br>${esc(english ? "Publishing again updates this knowledge item." : "再次发布会更新这条知识，不创建无标识副本。")}</div>` : "") +
    (!data.document_ready ? `<div class="export-warning">${esc(english
      ? "Final minutes are not ready. Export a review pack instead of publishing incomplete knowledge."
      : "纪要尚未就绪；请先导出核听包，不把不完整结果发布到正式知识库。")}</div>` : "");
  $("#knowledge-publish-confirm").disabled = !data.document_ready || !targets.length;
}

async function publishToKnowledgeBase() {
  if (!state.slug) return;
  const target = $("#knowledge-target-select")?.value;
  const profile = $('input[name="knowledge-profile"]:checked')?.value || "auto";
  if (!target) return;
  const button = $("#knowledge-publish-confirm");
  button.disabled = true;
  button.textContent = isEnglishUi() ? "Publishing…" : "正在发布…";
  try {
    const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/knowledge/publish`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_id: target, profile }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || response.status);
    closeKnowledgePublishDialog();
    const outcome = result.publication?.outcome;
    toast(isEnglishUi()
      ? (outcome === "already_current" ? "Knowledge is already current" : "Published to knowledge base; indexing has started")
      : (outcome === "already_current" ? "知识库已经是当前版本" : "已发布到知识库，后台正在索引"));
  } catch (error) {
    toast(`${isEnglishUi() ? "Publish failed" : "发布失败"}：${error.message}`);
    button.disabled = false;
  } finally {
    button.textContent = isEnglishUi() ? "Publish current revision" : "发布当前版本";
  }
}

function selectedExportProfile() {
  return normalizeExportProfile(
    $('input[name="export-profile"]:checked', $("#export-preflight"))?.value);
}

function updateExportSizeHint() {
  const data = state.exportPreflight;
  const hint = $("#export-size-hint");
  if (!data || !hint) return;
  const profile = selectedExportProfile();
  const media = $('input[name="export-media"]:checked', $("#export-preflight"))?.value || "none";
  const selection = exportSizeState(data, profile, media);
  $(".export-options", $("#export-preflight"))?.classList.toggle(
    "inactive", selection.profile !== "full");
  hint.classList.toggle("hidden", !selection.oversized);
  if (selection.oversized) {
    hint.textContent = isEnglishUi()
      ? "Estimated size exceeds the common 30MB email attachment limit; consider the knowledge-base profile (text + media links) instead."
      : "预计大小超过常见邮件附件 30MB 限制，可改用知识库版（纯文本+媒体链接）。";
  }
  updateExportConfirmLabel();
}

function renderExportPreflight() {
  const data = state.exportPreflight;
  if (!data) return;
  const evidenceNames = isEnglishUi()
    ? { ready: "Traceable", stale: "Evidence stale", partial: "Partial evidence" }
    : { ready: "可核证", stale: "依据已过期", partial: "部分证据" };
  const optionCopy = {
    none: [isEnglishUi() ? "Without media" : "不附媒体",
      isEnglishUi() ? "Smallest Viewer; minutes, map, transcript and evidence stay available" : "体积最小；仍保留纪要、脉络、逐字稿与证据"],
    audio: [isEnglishUi() ? "Include review audio" : "附带回听音频",
      `${data.media.audio.format || "AAC"} · ${isEnglishUi() ? "seekable from evidence" : "可按证据跳转"}`],
    video: [isEnglishUi() ? "Include review video" : "附带回看视频",
      `${data.media.video.format || "720p"} · ${isEnglishUi() ? "screen remains readable" : "保留屏幕可读性"}`],
  };
  const options = availableViewerMedia(data.media).map(id => [id, ...optionCopy[id], true]);
  const profiles = [
    ["full", isEnglishUi() ? "Offline Viewer" : "离线 Viewer",
     isEnglishUi() ? "Open, listen and verify without a server" : "无需服务即可阅读、回听与核证"],
    ["ai", isEnglishUi() ? "AI / knowledge pack" : "AI / 知识库 Pack",
     isEnglishUi()
       ? "Portable Markdown for GPT, Gemini, NotebookLM or a knowledge base"
       : "可交给 GPT、豆包、Gemini、NotebookLM 或知识库的 Markdown"],
  ];
  const html = `<div class="export-facts">` +
    `<span><b>${esc(evidenceNames[data.evidence.state] || (isEnglishUi() ? "Partial evidence" : "部分证据"))}</b>${data.evidence.linked_claims}/${data.evidence.claims} ${isEnglishUi() ? "linked conclusions" : "条结论有链接"}</span>` +
    `<span><b>${data.content.transcript_turns}</b>${isEnglishUi() ? "transcript segments" : "段逐字稿"}</span>` +
    `<span><b>${data.content.pages}</b>${isEnglishUi() ? "shared-screen pages" : "页共享画面"}</span></div>` +
    `<div class="export-profile">${profiles.map(([id, title, detail], index) =>
      `<label class="export-profile-option">` +
      `<input type="radio" name="export-profile" value="${id}" ${index === 0 ? "checked" : ""}>` +
      `<span><b>${title}</b><small>${detail}</small></span></label>`).join("")}</div>` +
    `<div class="export-options">${options.map(([id, title, detail, available], index) =>
      `<label class="export-option ${available ? "" : "disabled"}">` +
      `<input type="radio" name="export-media" value="${id}" ${index === 0 ? "checked" : ""} ${available ? "" : "disabled"}>` +
      `<span><b>${title}</b><small>${detail}</small></span>` +
      `<strong>${isEnglishUi() ? "About" : "约"} ${formatBytes(data.estimated_bytes[id])}</strong></label>`).join("")}</div>` +
    `<div id="export-size-hint" class="export-warning hidden"></div>` +
    (data.export_mode === "review_snapshot"
      ? '<div class="export-warning"><b>处理中核听快照</b><br>说话人、逐字稿、跳播和所选媒体可用；纪要、脉络、证据与屏幕资料仅代表现在，终稿完成后请重新导出正式分享版。</div>'
      : "") +
    (data.evidence.state === "ready" ? "" :
      '<div class="export-warning">当前包仍可阅读，但部分结论不能回到原文核对。建议重新生成纪要后再正式分享。</div>') +
    `<p class="export-note">由 Meeting Minutes v${esc(data.product_version || "-")} 生成；文件名格式 <code>${esc(data.filename_pattern || "")}</code>。<br>` +
    '包顶层只有 <code>viewer.html</code>、<code>README.txt</code> 和 <code>assets/</code>。音视频是分享压缩版，项目中的原始母版不会被修改。' +
    `${isEnglishUi() ? "The AI / knowledge pack is portable Markdown without local links or media. Confirm policy before uploading internal content to an external service. Advanced KB projections remain available through the publish workflow and API." : "AI / 知识库 Pack 是不含本机链接和媒体的可携带 Markdown；将内部内容上传外部服务前请确认公司政策。图文知识投影仍可通过“发布到知识库”和 API 使用。"}</p>`;
  $("#export-preflight").innerHTML = html;
  $$('input[name="export-profile"]', $("#export-preflight")).forEach(radio => {
    radio.onchange = updateExportSizeHint;
  });
  $$('input[name="export-media"]', $("#export-preflight")).forEach(radio => {
    radio.onchange = updateExportSizeHint;
  });
  updateExportSizeHint();
  $("#export-confirm").disabled = false;
}

function exportMeeting(media = "none", profile = "full") {
  if (!state.slug) return;
  closeExportDialog();
  const a = document.createElement("a");
  a.href = meetingExportHref(state.slug, media, profile);
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast(profile !== "full"
    ? (profile === "ai"
      ? (isEnglishUi() ? "Generating portable AI context…" : "正在生成可携带 AI 上下文…")
      : (isEnglishUi()
        ? `Generating ${profile === "kb-html" ? "visual " : ""}knowledge-base export…`
        : `正在生成${profile === "kb-html" ? "图文" : "轻量"}知识库导出…`))
    : media === "none" ? "正在生成离线查看包（默认不含音视频）…" : `正在生成含${media === "video" ? "视频" : "音频"}的查看包…`);
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

function startMinutesRestructure() {
  if (!state.bundle || state.assistantBusy || state.bundle.document_state === "draft"
      || state.bundle.evidence?.state !== "ready") return;
  setReviewMode("minutes");
  state.assistantNextIntent = "restructure";
  openUtility("assistant");
  const input = $("#assistant-input");
  input.value = "";
  input.placeholder = ui("restructurePlaceholder");
  $("#assistant-state").textContent = isEnglishUi()
    ? "This changes the minutes view only; the chronological meeting map stays unchanged."
    : "只重组正式纪要；时间线性的会议脉络保持不变。";
  input.focus();
}

function resetAssistant() {
  state.assistantRefs = [];
  state.assistantHistory = [];
  state.assistantMessages = [];
  state.assistantBusy = false;
  state.assistantNextIntent = null;
  // 归属置空：切会议时的清空不得覆盖目标会议已保存的对话（persistAssistant 会跳过）。
  state.assistantSlug = null;
  if ($("#assistant-refs")) renderAssistantRefs();
  if ($("#assistant-messages")) renderAssistantMessages();
  if ($("#assistant-input")) {
    $("#assistant-input").value = "";
    $("#assistant-input").placeholder = ui("ask");
  }
  renderAssistantSuggestions();
}

/* ---------- 对话持久化（本浏览器 localStorage，逐字稿 revision 绑定） ---------- */

const ASSISTANT_KEY_PREFIX = "meeting-minutes:assistant:v1:";

function persistAssistant() {
  // 只写当前对话归属的会议；归属为空（刚切换/刚重置）时不写，避免覆盖目标会议的存档。
  if (!state.slug || state.assistantSlug !== state.slug) return;
  try {
    localStorage.setItem(ASSISTANT_KEY_PREFIX + state.slug, JSON.stringify({
      revision: state.bundle?.transcript_revision || null,
      messages: state.assistantMessages.slice(-50),
      history: state.assistantHistory.slice(-8),
    }));
  } catch (_) { /* 存储满时静默放弃持久化 */ }
}

function restoreAssistant() {
  if (!state.slug || !state.bundle) return;
  const key = ASSISTANT_KEY_PREFIX + state.slug;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch (_) { /* 损坏即弃 */ }
  if (saved && saved.revision === (state.bundle.transcript_revision || null)) {
    state.assistantMessages = Array.isArray(saved.messages) ? saved.messages : [];
    // 服务端提案只在内存中保留；刷新后不再展示可能已经失效的巨大“待确认”正文。
    for (const message of state.assistantMessages) {
      if (message.proposal && !message.proposal.status) message.proposal.status = "expired";
    }
    state.assistantHistory = Array.isArray(saved.history) ? saved.history : [];
    state.assistantSlug = state.slug;
  } else if (saved) {
    localStorage.removeItem(key);  // 逐字稿已变，旧对话与引用作废
  }
  renderAssistantMessages();
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
  if (!state.assistantSlug) state.assistantSlug = state.slug;
  state.assistantMessages.push(message);
  renderAssistantMessages();
}

function citedText(text, sources) {
  const ids = new Set((sources || []).map(s => s.id));
  return esc(text)
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/【([RT]\d+)】/g, (all, id) =>
      ids.has(id) ? `<button type="button" class="source-link" data-source="${id}">${all}</button>` : all);
}

function assistantMessageBody(message) {
  if (message.role !== "assistant") return citedText(message.content, message.sources);
  if (message.html) return message.html;
  // p64 以前持久化的回答没有服务端安全 HTML；长表格默认折叠，避免再次铺满窄栏。
  if (/^\s*\|.+\|\s*$/m.test(String(message.content || ""))) {
    return `<details class="legacy-assistant-answer"><summary>${isEnglishUi()
      ? "Older unformatted answer · ask again for the formatted view"
      : "旧版未格式化回答 · 重新提问可获得新版排版"}</summary>` +
      `<pre>${esc(message.content)}</pre></details>`;
  }
  return citedText(message.content, message.sources);
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

function proposalReadingHtml(proposal, side = "after") {
  const rendered = proposal?.[`${side}_html`];
  if (rendered) return rendered;
  // 兼容刷新前保存在 localStorage 的旧提案：宁可退化成干净文本，也不展示内部协议。
  const clean = String(proposal?.[side] || "")
    .replace(/`?\s*<!--\s*mm:evidence\s+[^<>]*?-->\s*`?/g, "")
    .trim();
  return `<pre>${esc(clean)}</pre>`;
}

function renderAssistantMessages() {
  const box = $("#assistant-messages");
  if (!box) return;
  const pendingProposal = state.assistantMessages.some(message =>
    message.proposal && !message.proposal.status);
  $("#content-shell")?.classList.toggle("proposal-open", pendingProposal);
  if (!state.assistantMessages.length) {
    box.innerHTML = '<p class="placeholder">你可以直接追问整场会议；引用逐字稿后，回答和修改会优先使用这些内容。</p>';
    persistAssistant();
    return;
  }
  box.innerHTML = "";
  for (const msg of state.assistantMessages) {
    const el = document.createElement("div");
    el.className = `assistant-msg ${msg.role}`;
    const bodyClass = msg.role === "assistant" && msg.html ? "msg-body assistant-markdown" : "msg-body";
    el.innerHTML = `<div class="msg-role">${msg.role === "user" ? "你" : "助手"}</div>` +
      `<div class="${bodyClass}">${assistantMessageBody(msg)}</div>`;
    if (msg.proposal) {
      const p = msg.proposal;
      if (p.status === "applied") {
        const isView = p.scope === "document" && p.view_id;
        el.innerHTML += `<div class="edit-card edit-result">` +
          `<div class="edit-result-head"><div><span class="applied">${isView
            ? (isEnglishUi() ? "AI view saved" : "已保存 AI 纪要视图")
            : (isEnglishUi() ? "Minutes updated" : "已更新会议纪要")}</span>` +
          `<small>${esc(p.summary || (isEnglishUi() ? "The requested change is now visible in the minutes." : "修改已同步到会议纪要。"))}</small></div>` +
          (isView
            ? `<button type="button" class="show-standard-minutes">${isEnglishUi() ? "Standard minutes" : "切回标准纪要"}</button>`
            : `<button type="button" class="undo-edit" data-id="${esc(p.proposal_id)}">${isEnglishUi() ? "Undo" : "撤销"}</button>`) + `</div>` +
          `<details class="edit-version"><summary>${isEnglishUi() ? "View this saved version" : "查看本次写入版本"}</summary>` +
          `<div class="proposal-reading minutes">${proposalReadingHtml(p)}</div></details></div>`;
      } else if (p.status === "undone") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">这次修改已撤销，纪要已恢复。</span></div>';
      } else if (p.status === "cancelled") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">这次修改已取消。</span></div>';
      } else if (p.status === "superseded") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">正在继续调整，旧方案不会写入。</span></div>';
      } else if (p.status === "expired") {
        el.innerHTML += `<div class="edit-card edit-result"><span class="dim">${isEnglishUi()
          ? "This old preview expired after refresh. Send the instruction again to create and save a reversible version."
          : "这份旧预览已在刷新后失效。重新发送要求即可生成并写入可撤销的新版本。"}</span></div>`;
      } else {
        el.innerHTML +=
          `<div class="edit-card">` +
          `<div class="edit-card-kicker">${p.scope === "document" ? (isEnglishUi() ? "Ready to restructure" : "准备重组") : (isEnglishUi() ? "Ready to update" : "准备更新")} · ${esc(p.target_heading)}</div>` +
          `<div class="edit-summary">${esc(p.summary || "已根据要求整理修改")}</div>` +
          `<div class="edit-actions">` +
          `<button type="button" class="apply-edit primary" data-id="${esc(p.proposal_id)}">保存到纪要</button>` +
          `<button type="button" class="dismiss-edit">取消</button>` +
          `</div>` +
          `<div class="proposal-reading minutes">${proposalReadingHtml(p)}</div>` +
          `<details class="edit-before"><summary>${isEnglishUi() ? "Compare with the previous version" : "对照修改前版本"}</summary>` +
          `<div class="proposal-reading minutes">${proposalReadingHtml(p, "before")}</div></details></div>`;
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
    $$('a[href^="#assistant-source-"]', el).forEach(link => {
      link.onclick = event => {
        event.preventDefault();
        const id = link.getAttribute("href").slice("#assistant-source-".length);
        const source = (msg.sources || []).find(item => item.id === id);
        if (source) showAssistantSource(source);
      };
    });
    $$('a[href^="#mm-"]', el).forEach(link => {
      link.onclick = event => {
        event.preventDefault();
        const claimId = link.getAttribute("href").slice(4);
        const source = (msg.proposal?.sources || []).find(item => item.claim_id === claimId);
        if (source) showAssistantSource(source);
      };
    });
    const apply = $(".apply-edit", el);
    if (apply) apply.onclick = () => applyAssistantEdit(apply.dataset.id, apply);
    const undo = $(".undo-edit", el);
    if (undo) undo.onclick = () => undoAssistantEdit(undo.dataset.id, undo);
    const standard = $(".show-standard-minutes", el);
    if (standard) standard.onclick = () => {
      state.workspace.minutesViews[state.slug] = "standard";
      saveWorkspaceState();
      renderMinutes();
    };
    const dismiss = $(".dismiss-edit", el);
    if (dismiss) dismiss.onclick = () => {
      msg.proposal.status = "cancelled";
      renderAssistantMessages();
    };
    box.appendChild(el);
  }
  box.scrollTop = box.scrollHeight;
  persistAssistant();
}

function inferAssistantIntent(message) {
  if (state.assistantNextIntent) return state.assistantNextIntent;
  const restructurePatterns = [
    /(重组|重新组织|重新编排|调整结构|自定义结构).{0,12}(纪要|总结)/,
    /(纪要|总结).{0,12}(重组|重新组织|重新编排|调整结构|栏目|版式)/,
    /按.{1,30}(结构|栏目|顺序|项目|人员|分享人).{0,12}(整理|生成|重写|组织)/,
    /按(?:照)?.{0,40}(顺序|人员|分享人|项目|栏目|结构).{0,30}(给出|总结|整理|组织|生成|重写|列出)/,
    /(个人|每个人|分享人).{0,16}(发言|分享).{0,12}(总结|要点).{0,50}(总体结构|待办|关键结论)/,
    /(总体结构|待办事项|关键结论).{0,60}(个人|每个人|分享人).{0,20}(总结|顺序)/,
  ];
  if (restructurePatterns.some(pattern => pattern.test(message))) return "restructure";
  const editPatterns = [
    /(写入|加入|添加|补充|更新|同步).{0,10}(纪要|总结|行动项|决定|结论)/,
    /(纪要|总结|行动项|决定|结论).{0,10}(改成|改为|修改|改写|润色|精简|删除|移除|补充|更新)/,
    /^(请)?(帮我|把|将)?\s*(修改|改写|润色|精简|删除|移除|补充|更新)/,
    /(请|帮我).{0,8}(修改|改写|补充|更新|写入|加入|删除|润色)/,
    /(把|将).{0,30}(改成|改为|修改|改写|润色|精简|删除|移除|写入|加入|补充到|更新)/,
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
  if (["edit", "restructure"].includes(intent) && state.bundle?.document_state === "draft") {
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
  const path = intent === "restructure"
    ? `/api/meetings/${encodeURIComponent(state.slug)}/assistant/restructure/preview`
    : intent === "edit"
      ? `/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/preview`
      : `/api/meetings/${encodeURIComponent(state.slug)}/assistant/chat/stream`;
  const body = intent === "restructure"
    ? { message, transcript_revision: state.bundle.transcript_revision,
        minutes_revision: state.bundle.minutes_revision }
    : intent === "edit"
      ? { ...common, minutes_revision: state.bundle.minutes_revision }
      : { ...common, history: state.assistantHistory.slice(-8) };
  addAssistantMessage({ role: "user", content: message, sources: [] });
  setAssistantThread(true);
  input.value = "";
  input.placeholder = ui("ask");
  state.assistantBusy = true;
  $("#assistant-send").disabled = true;
  $("#assistant-state").textContent = intent === "restructure"
    ? (isEnglishUi() ? "Building a fact-grounded structure preview…" : "正在按事实层生成结构预览…")
    : intent === "edit" ? "正在生成修改预览…" : "正在查找证据并回答…";
  let streamMsg = null;
  try {
    const r = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (["edit", "restructure"].includes(intent)) {
      const j = await r.json();
      if (!r.ok) throw new Error(assistantError(j.detail));
      // 局部修改写入标准纪要并可撤销；整篇重组只保存为可切换 AI 视图。
      const applyPath = intent === "restructure" ? "assistant/restructure/apply" : "assistant/edit/apply";
      const applyResponse = await api(`/api/meetings/${encodeURIComponent(state.slug)}/${applyPath}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposal_id: j.proposal_id }),
      });
      const applied = await applyResponse.json();
      if (!applyResponse.ok) {
        addAssistantMessage({
          role: "assistant",
          content: isEnglishUi() ? "The change is ready but was not saved automatically. Review and save it below."
            : "修改已经生成，但自动写入没有完成；请在下方检查后保存。",
          sources: j.sources || [], proposal: j,
        });
        throw new Error(assistantError(applied.detail));
      }
      state.bundle = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
      if (intent === "restructure" && applied.view_id) {
        state.workspace.minutesViews[state.slug] = applied.view_id;
        saveWorkspaceState();
      }
      setReviewMode("minutes");
      addAssistantMessage({
        role: "assistant",
        content: intent === "restructure"
          ? (isEnglishUi() ? "I saved this as an AI minutes view. The standard minutes remain unchanged." : "已保存为 AI 纪要视图，标准纪要保持不变。")
          : (isEnglishUi() ? "I updated the minutes. You can undo it below." : "我已更新会议纪要，可在下方一步撤销。"),
        sources: j.sources || [],
        // 已写入卡只保留阅读与撤销所需字段，避免把 before/diff/raw marker 塞满 localStorage。
        proposal: {
          proposal_id: j.proposal_id, target_heading: j.target_heading, scope: j.scope,
          summary: j.summary, sources: j.sources || [], after_html: j.after_html,
          status: "applied", view_id: applied.view_id || null,
        },
      });
    } else {
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(assistantError(j.detail));
      }
      // SSE 流式渲染：meta 带证据 → delta 逐段追加到气泡 → done 后落历史并持久化
      const msg = { role: "assistant", content: "", sources: [] };
      streamMsg = msg;
      addAssistantMessage(msg);
      const bubble = () => $("#assistant-messages").lastElementChild?.querySelector(".msg-body");
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, sep);
          buf = buf.slice(sep + 2);
          const line = frame.split("\n").find(l => l.startsWith("data:"));
          if (!line) continue;
          let ev;
          try { ev = JSON.parse(line.slice(5).trim()); } catch (_) { continue; }
          if (ev.type === "meta") {
            msg.sources = ev.sources || [];
            $("#assistant-state").textContent = "正在作答…";
          } else if (ev.type === "delta") {
            msg.content += ev.text;
            const el = bubble();
            if (el) el.textContent = msg.content;
            const box = $("#assistant-messages");
            if (box) box.scrollTop = box.scrollHeight;
          } else if (ev.type === "done") {
            msg.html = ev.answer_html || null;
          } else if (ev.type === "error") {
            throw new Error(ev.message || "生成失败");
          }
        }
      }
      if (!msg.content.trim()) throw new Error("空响应");
      renderAssistantMessages();  // 全量重渲染一次:引用链接可点 + 持久化
      state.assistantHistory.push({ role: "user", content: message });
      state.assistantHistory.push({ role: "assistant", content: msg.content });
      state.assistantHistory = state.assistantHistory.slice(-8);
      persistAssistant();
    }
  } catch (e) {
    if (streamMsg && !streamMsg.content.trim()) {
      state.assistantMessages = state.assistantMessages.filter(m => m !== streamMsg);
    }  // 流式失败时撤掉空气泡
    addAssistantMessage({ role: "assistant", content: `无法完成：${e.message}`, sources: [] });
  } finally {
    state.assistantBusy = false;
    $("#assistant-send").disabled = false;
    $("#assistant-state").textContent = "";
    renderMinutes();
  }
}

async function applyAssistantEdit(proposalId, button) {
  button.disabled = true;
  const msg = state.assistantMessages.find(item => item.proposal?.proposal_id === proposalId);
  const isView = msg?.proposal?.scope === "document";
  const applyPath = isView ? "assistant/restructure/apply" : "assistant/edit/apply";
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/${applyPath}`, {
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
  if (isView && j.view_id) {
    state.workspace.minutesViews[state.slug] = j.view_id;
    saveWorkspaceState();
  }
  renderMinutes();
  if (msg) {
    msg.proposal.status = "applied";
    msg.proposal.view_id = j.view_id || null;
  }
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

async function restorePreviousMinutes() {
  if (!state.slug || !state.bundle?.minutes_history_available) return;
  if (!confirm(isEnglishUi()
    ? "Restore the previous saved minutes? The current version will be backed up first."
    : "恢复上一份已保存的纪要？当前版本会先自动备份，之后仍可恢复。")) return;
  const button = $("#restore-minutes");
  button.disabled = true;
  try {
    const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/restore-previous`, {
      method: "POST",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(assistantError(result.detail));
    state.workspace.minutesViews[state.slug] = "standard";
    state.bundle = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
    saveWorkspaceState();
    renderMinutes();
    addAssistantMessage({ role: "assistant", content: isEnglishUi()
      ? "The previous minutes were restored. The replaced version was backed up locally."
      : "已恢复上一版纪要；刚才被替换的版本也已在本机备份。", sources: [] });
  } catch (error) {
    addAssistantMessage({ role: "assistant", content: `恢复失败：${error.message}`, sources: [] });
  } finally {
    button.disabled = false;
  }
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

function visualUpgradeNotice() {
  if (!state.bundle?.visual_analysis?.upgrade_available) return "";
  return `<section class="visual-upgrade-notice"><div><b>${isEnglishUi()
    ? "This result was created without visual understanding"
    : "当前结果未进行画面理解"}</b><span>${isEnglishUi()
    ? "Add it later without rerunning speech recognition or speaker processing. The current result remains readable while it runs."
    : "可以稍后补充，不会重跑语音识别或说话人处理；运行期间当前结果仍可阅读。"}</span></div>`
    + `<button type="button" class="fluent-button fluent-button--primary" data-visual-upgrade>${isEnglishUi()
      ? "Add visual analysis" : "补充画面分析"}</button></section>`;
}

function wireVisualUpgrade(container = document) {
  $$('[data-visual-upgrade]', container).forEach(button => {
    button.onclick = () => startVisualUpgrade(button);
  });
}

async function startVisualUpgrade(button) {
  if (!state.slug) return;
  button.disabled = true;
  const response = await api(
    `/api/meetings/${encodeURIComponent(state.slug)}/visual-upgrade`, { method: "POST" });
  const job = await response.json().catch(() => ({}));
  if (!response.ok) {
    button.disabled = false;
    toast(`${isEnglishUi() ? "Could not add visual analysis" : "无法补充画面分析"}：${job.detail || response.status}`);
    return;
  }
  rememberReadingPosition();
  toast(isEnglishUi()
    ? "Visual analysis queued. Speech recognition and speaker processing will be reused."
    : "画面分析已排队，将复用逐字稿和说话人结果");
  pollJobs();
  pollJob(job.id, async current => {
    if (current.status === "done") {
      toast(isEnglishUi()
        ? "Visual analysis added; minutes and the meeting map are updated."
        : "画面分析已补充，纪要和会议脉络已经更新");
      await loadMeeting(state.slug);
    } else if (["failed", "cancelled"].includes(current.status)) {
      toast(isEnglishUi()
        ? "Visual analysis did not finish. The fast minutes remain available."
        : "画面分析未完成，原快速纪要仍然可用");
      await loadMeeting(state.slug);
    }
  });
}

async function syncMinutes() {
  if (!state.slug) return;
  const button = $("[data-review-action='sync']", $("#transcript-review-bar"));
  if (button) button.disabled = true;
  const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/sync_minutes`,
    { method: "POST" });
  const job = await response.json();
  if (!response.ok) {
    toast(`${isEnglishUi() ? "Quick sync unavailable" : "暂时无法快速同步"}：${job.detail || response.status}`);
    if (button) button.disabled = false;
    return;
  }
  toast(isEnglishUi()
    ? "Updating minutes with the saved visual analysis…"
    : "正在复用已有画面资料更新纪要…");
  pollJob(job.id, current => {
    if (current.status === "done") {
      toast(isEnglishUi()
        ? "Minutes updated. The meeting map and translations will continue in the background."
        : "纪要已更新；会议脉络和翻译将在后台继续同步");
      loadMeeting(state.slug);
    } else if (["failed", "cancelled"].includes(current.status)) {
      toast(isEnglishUi()
        ? "Minutes sync did not finish. Your transcript edits were kept."
        : "纪要同步未完成；逐字稿修正已经保留");
      if (button) button.disabled = false;
    }
  });
}

async function retranscribeLocal() {
  if (!state.slug || !state.bundle) return;
  const warning = "使用最新上下文重新转写？\n\n"
    + "原始音视频、外部 VTT/DOCX 和当前文本会保留为可恢复快照。\n"
    + "系统将使用当前显式配置的 ASR provider 重建逐字稿、说话人、纪要、证据和会议脉络；已有屏幕资料会复用。\n"
    + "如果配置的是远程端点，音频只会发送到该显式端点，不会静默切换其他服务。";
  if (!confirm(warning)) return;
  $(".more-menu")?.removeAttribute("open");
  const response = await api(
    `/api/meetings/${encodeURIComponent(state.slug)}/retranscribe-local`, { method: "POST" });
  const job = await response.json();
  if (!response.ok) {
    toast(`本地重转写失败：${job.detail || response.status}`);
    return;
  }
  $("#retranscribe-btn").disabled = true;
  toast(`本地重转写作业 ${job.id} 已排队…`);
  pollJob(job.id, async current => {
    if (current.status === "done") {
      toast("已使用最新上下文重新转写，旧逐字稿仍已保留");
      await loadMeetings();
      await loadMeeting(state.slug);
    } else if (["failed", "cancelled"].includes(current.status)) {
      toast(`重新转写${current.status === "failed" ? "失败，已恢复原资产" : "已取消"}`);
      $("#retranscribe-btn").disabled = false;
    } else {
      toast(`重新转写：${current.stage || current.status}`);
    }
  });
}

/* ---------- 渐进式人物核对 ---------- */

async function ensureSpeakers() {
  if (!state.speakers) state.speakers = await jget("/api/speakers");
  return state.speakers;
}

function correctionPlaybackTime() { return Number(player()?.currentTime || playbackPosition() || 0); }

function correctionScrollAnchor(index = null) {
  const box = $("#transcript");
  const bounds = box?.getBoundingClientRect();
  const row = Number.isInteger(index) ? $(`#turn-${index}`)
    : [...(box?.querySelectorAll(".turn[id]") || [])]
      .find(item => item.getBoundingClientRect().bottom > (bounds?.top || 0) + 2);
  return row && bounds ? { id: row.id, offset: row.getBoundingClientRect().top - bounds.top } : null;
}

function positionIdentityPopover() {
  const root = $("#speaker-identity-popover");
  const rect = state.speakerCorrection.anchorRect;
  if (!root || !rect || innerWidth <= 820) return;
  const width = Math.min(390, innerWidth - 24);
  root.style.left = `${Math.max(12, Math.min(innerWidth - width - 12, rect.left))}px`;
  root.style.top = `${Math.max(56, Math.min(innerHeight - root.offsetHeight - 12, rect.bottom + 8))}px`;
}

function restoreCorrectionContext(correction, changed = []) {
  const p = player();
  if (p) p.currentTime = Math.max(0, Number(correction.returnPlaybackTime) || 0);
  const anchor = correction.returnScrollAnchor;
  if (anchor) {
    const box = $("#transcript");
    const row = document.getElementById(anchor.id);
    if (box && row) {
      const bounds = box.getBoundingClientRect();
      box.scrollTop += row.getBoundingClientRect().top - bounds.top - Number(anchor.offset || 0);
    }
  }
  changed.forEach(index => $(`#turn-${index}`)?.classList.add("speaker-change-flash"));
}

function showSpeakerChangeNotice(message) {
  const box = $("#speaker-change-notice");
  const undoLabel = isEnglishUi() ? "Undo" : "撤销";
  box.innerHTML = `<span>${esc(message)}</span><button type="button" aria-label="${isEnglishUi() ? "Undo this speaker change" : "撤销本次人物修改"}">${undoLabel}</button>`;
  box.querySelector("button").onclick = async () => {
    box.classList.add("hidden");
    await undoSpeakerOperation();
  };
  box.classList.remove("hidden");
  clearTimeout(state.speakerNoticeTimer);
  state.speakerNoticeTimer = setTimeout(() => box.classList.add("hidden"), 9000);
}

function closeSpeakerCorrection(force = false) {
  const correction = state.speakerCorrection;
  if (!force && correction.mode !== "identify" && correction.selectedTurnIndexes.size
      && !correction.exitConfirmation) {
    state.speakerCorrection = withCorrectionError({ ...correction, exitConfirmation: true },
      isEnglishUi()
        ? `Leaving will discard ${correction.selectedTurnIndexes.size} selected segments.`
        : `退出会放弃已选择的 ${correction.selectedTurnIndexes.size} 段发言。`);
    renderSpeakerCorrectionUI();
    return;
  }
  state.speakerCorrection = resetSpeakerCorrection(correction);
  state.speakerCorrectionReview = null;
  state.speakerCorrectionChoice = "";
  renderSpeakerCorrectionUI();
  renderTranscript();
}

function playCorrectionTurn(index) {
  const turn = state.bundle?.transcript?.[index];
  if (turn) seek(Number(turn.start) || 0, true);
}

function renderSpeakerCorrectionUI() {
  const correction = state.speakerCorrection;
  const transcript = state.bundle?.transcript || [];
  const persons = state.speakers?.persons || [];
  renderIdentityPopover({
    root: $("#speaker-identity-popover"), correction, transcript, persons,
    language: state.uiLanguage,
    representatives: state.speakerCorrectionReview?.summary?.representative_turns
      || representativeTurns(transcript, correction.sourceVoice, 3),
    formatTime: fmt, escapeHtml: esc, onClose: () => closeSpeakerCorrection(true),
    onSelectPerson: name => { state.speakerCorrectionChoice = name; },
    onConfirm: confirmSpeakerIdentity, onRepair: beginSpeakerRepair,
    onPlay: playCorrectionTurn,
  });
  const summary = correctionSummary(correction, transcript,
    isEnglishUi() ? "Speaker to review" : "待确认说话人");
  renderCorrectionSheet({
    root: $("#speaker-correction-sheet"), correction, transcript, persons,
    language: state.uiLanguage,
    locked: new Set(state.speakerCorrectionReview?.protected || []),
    formatTime: fmt, formatDuration: fmt, escapeHtml: esc, summary,
    onExit: () => closeSpeakerCorrection(false),
    onDiscard: () => closeSpeakerCorrection(true),
    onContinueExit: () => {
      state.speakerCorrection = withCorrectionError(
        { ...state.speakerCorrection, exitConfirmation: false }, "");
      renderSpeakerCorrectionUI();
    },
    onToggleExample: toggleSpeakerCorrectionExample,
    onNext: previewSpeakerCorrection,
    onBack: () => {
      state.speakerCorrection = { ...correction, mode: "select_examples",
        exitConfirmation: false, error: "" };
      renderSpeakerCorrectionUI(); renderTranscript();
    },
    onIncludeSuggested: include => {
      state.speakerCorrection = setIncludeSuggested(state.speakerCorrection, include);
      renderSpeakerCorrectionUI();
    },
    onAssignment: (key, assignment) => {
      state.speakerCorrection = setGroupAssignment(state.speakerCorrection, key, assignment);
      renderSpeakerCorrectionUI();
    },
    onApply: applySpeakerCorrection,
    onPlay: playCorrectionTurn,
  });
  requestAnimationFrame(positionIdentityPopover);
}

async function openSpeakerIdentity(voice, name, detail = {}) {
  if (!state.slug || !voice) return;
  const rect = detail.anchor?.getBoundingClientRect?.();
  state.speakerCorrection = beginIdentity(state.speakerCorrection, {
    voice, displayName: name, playbackTime: correctionPlaybackTime(),
    scrollAnchor: correctionScrollAnchor(detail.index),
    anchorRect: rect ? { left: rect.left, bottom: rect.bottom } : null,
  });
  state.speakerCorrectionReview = null;
  state.speakerCorrectionChoice = "";
  renderSpeakerCorrectionUI();
  try {
    const [speakers, review] = await Promise.all([
      ensureSpeakers(),
      jget(`/api/meetings/${encodeURIComponent(state.slug)}/speakers/${encodeURIComponent(voice)}/review`),
    ]);
    state.speakers = speakers;
    state.speakerCorrectionReview = review;
    renderSpeakerCorrectionUI();
  } catch (error) {
    state.speakerCorrection = withCorrectionError(state.speakerCorrection,
      `${isEnglishUi() ? "Representative segments are temporarily unavailable" : "暂时无法读取代表片段"}：${error.message}`);
    renderSpeakerCorrectionUI();
  }
}

async function confirmSpeakerIdentity(name, create = false) {
  name = String(name || state.speakerCorrectionChoice || "").trim();
  if (!name) {
    state.speakerCorrection = withCorrectionError(state.speakerCorrection,
      isEnglishUi() ? "Choose or enter a person name first." : "请先选择或输入一个人员姓名。");
    renderSpeakerCorrectionUI(); return;
  }
  const correction = state.speakerCorrection;
  state.speakerCorrection = { ...correction, mode: "applying", error: "" };
  renderSpeakerCorrectionUI();
  const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/bind`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice: correction.sourceVoice, name, create: Boolean(create) }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const candidates = result.detail?.candidates?.map(item => item.name).filter(Boolean) || [];
    state.speakerCorrection = withCorrectionError({ ...correction, mode: "identify" },
      response.status === 409
        ? (isEnglishUi()
          ? `No exact match for “${name}”. ${candidates.length ? `Candidates: ${candidates.join(", ")}. ` : ""}Choose a candidate or use “Create person and confirm”.`
          : `没有精确找到「${name}」。${candidates.length ? `候选：${candidates.join("、")}。` : ""}可选择候选，或点击“新建人员并确认”。`)
        : `${isEnglishUi() ? "Confirmation failed" : "确认失败"}：${result.detail?.detail || result.detail || response.status}`);
    state.speakerCorrectionChoice = name;
    renderSpeakerCorrectionUI(); return;
  }
  const changed = state.speakerCorrectionReview?.indexes || [];
  state.speakers = null; resetAssistant();
  state.speakerCorrection = resetSpeakerCorrection();
  state.speakerCorrectionReview = null;
  renderSpeakerCorrectionUI();
  await loadMeeting(state.slug);
  restoreCorrectionContext(correction, changed);
  showSpeakerChangeNotice(isEnglishUi()
    ? `${result.turns || changed.length} segments confirmed as “${result.name || name}”.`
    : `已将 ${result.turns || changed.length} 段发言确认给「${result.name || name}」。`);
}

function beginSpeakerRepair() {
  state.speakerCorrection = beginExampleSelection(state.speakerCorrection);
  renderSpeakerCorrectionUI();
  renderTranscript();
}

function toggleSpeakerCorrectionExample(index, voice = state.speakerCorrection.sourceVoice) {
  if (state.speakerCorrection.mode !== "select_examples"
      || voice !== state.speakerCorrection.sourceVoice
      || new Set(state.speakerCorrectionReview?.protected || []).has(index)) return;
  state.speakerCorrection = toggleExample(state.speakerCorrection, index);
  renderSpeakerCorrectionUI();
  renderTranscript();
}

async function previewSpeakerCorrection() {
  const correction = state.speakerCorrection;
  if (!correction.selectedTurnIndexes.size) return;
  state.speakerCorrection = { ...correction, error: "" };
  renderSpeakerCorrectionUI();
  try {
    const response = await api(
      `/api/meetings/${encodeURIComponent(state.slug)}/split/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice: correction.sourceVoice,
          turns: [...correction.selectedTurnIndexes] }),
      });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail?.message || result.detail || response.status);
    state.speakerCorrection = setPreview(state.speakerCorrection, result,
      state.bundle?.transcript || []);
    renderSpeakerCorrectionUI();
    renderTranscript();
  } catch (error) {
    state.speakerCorrection = withCorrectionError(state.speakerCorrection,
      isEnglishUi()
        ? `Could not build the preview: ${error.message}. Your selected segments are preserved; try again.`
        : `无法生成结果预览：${error.message}。已选片段仍然保留，可重试。`);
    renderSpeakerCorrectionUI();
  }
}

async function applySpeakerCorrection() {
  const correction = state.speakerCorrection;
  const payload = buildCorrectionApplyPayload(correction);
  state.speakerCorrection = { ...correction, mode: "applying", error: "" };
  renderSpeakerCorrectionUI();
  try {
    const current = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
    const stable = payload.turns.every(index => {
      const before = state.bundle?.transcript?.[index];
      const after = current.transcript?.[index];
      return before && after && Math.abs(Number(before.start || 0) - Number(after.start || 0)) < .05;
    });
    if (!stable) throw new Error(isEnglishUi()
      ? "The transcript changed. Go back and select examples again."
      : "逐字稿已变化，请返回后重新选择样例");
    const response = await api(`/api/meetings/${encodeURIComponent(state.slug)}/split`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail?.message || result.detail || response.status);
    const changed = result.turn_indexes || result.voices?.flatMap(group => group.turn_indexes || []) || [];
    const assignments = Object.values(correction.groupAssignments || {})
      .map(item => item.name).filter(Boolean);
    state.speakers = null; resetAssistant();
    state.speakerCorrection = resetSpeakerCorrection();
    state.speakerCorrectionReview = null;
    renderSpeakerCorrectionUI();
    await loadMeeting(state.slug);
    restoreCorrectionContext(correction, changed);
    const target = [...new Set(assignments)];
    showSpeakerChangeNotice(target.length === 1
      ? (isEnglishUi()
        ? `${result.moved || changed.length} segments changed from “${correction.sourceDisplayName}” to “${target[0]}”.`
        : `已将 ${result.moved || changed.length} 段发言从「${correction.sourceDisplayName}」调整为「${target[0]}」。`)
      : (isEnglishUi()
        ? `${result.moved || changed.length} segments reviewed into ${result.clusters || target.length} result groups.`
        : `已重新核对 ${result.moved || changed.length} 段发言，并形成 ${result.clusters || target.length} 个结果组。`));
  } catch (error) {
    state.speakerCorrection = withCorrectionError({ ...correction, mode: "preview" },
      isEnglishUi()
        ? `Apply failed: ${error.message}. Your selection and person assignments are preserved.`
        : `应用失败：${error.message}。你的选择和人员指定仍然保留。`);
    renderSpeakerCorrectionUI();
  }
}

/* ---------- 上传与作业 ---------- */

async function uploadFiles(files) {
  if (!files.length) return;
  const contentType = state.workspace.contentType;
  const localMediaIsVideo = isSingleLocalVideo(files);
  if (contentType === "media" && !localMediaIsVideo) {
    toast(isEnglishUi() ? "Media mode accepts one local video at a time" : "媒体模式一次只支持一个本地视频");
    return;
  }
  const fd = buildUploadFormData(files, {
    contentType,
    noVl: !!$("#skip-vl")?.checked,
    ignoreTranscript: !!$("#ignore-transcript")?.checked,
  });
  const r = await api("/api/upload", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) { toast(`上传被拒: ${j.detail || r.status}`); return; }
  toast(contentType === "media" ? "媒体处理已排队" : `作业 ${j.id} (${j.route}) 已创建，目标会议 ${j.meeting}`);
  let draftOpened = false;
  pollJob(j.id, async jj => {
    const logs = (jj.log || []).map(String);
    if (!draftOpened && logs.some(line => line.includes("语音草稿已可阅读"))) {
      draftOpened = true;
      state.progressiveRefreshes.add(`${j.id}:draft`);
      toast("语音草稿已可阅读，正在补充屏幕资料…");
      await loadMeetings();
      if (state.bundle) rememberReadingPosition();
      const target = jj.meeting || j.meeting;
      if (target) await loadMeeting(target);
      return;
    }
    if (jj.status === "done") {
      const key = `${j.id}:final`;
      if (state.progressiveRefreshes.has(key)) return;
      state.progressiveRefreshes.add(key);
      toast(`作业 ${j.id} 完成，已升级为多模态终稿`);
      if (state.bundle) rememberReadingPosition();
      await loadMeetings();
      const target = jj.meeting || j.meeting;
      if (target && (state.slug === target || draftOpened)) await loadMeeting(target);
    } else if (jj.status === "failed") {
      toast(`作业 ${j.id} 失败 (rc=${jj.rc})`);
    } else {
      toast(`作业 ${j.id} (${j.route}): ${jj.status}`);
    }
  });
}

async function importMediaUrl() {
  const input = $("#media-url-input");
  const button = $("#media-url-submit");
  const url = String(input?.value || "").trim();
  if (!url) {
    input?.focus();
    return;
  }
  button.disabled = true;
  try {
    const { response, body: job } = await enqueueMediaUrl(
      api, url, !!$("#skip-vl")?.checked);
    if (!response.ok) {
      toast(`${isEnglishUi() ? "URL import rejected" : "链接导入失败"}：${job.detail || response.status}`);
      return;
    }
    input.value = "";
    toast(isEnglishUi() ? "Public video queued for local processing" : "公开视频已排队，将在本机下载并分析");
    pollJobs();
  } finally {
    button.disabled = false;
  }
}

function pollJob(id, onUpdate) {
  if (state.poller) clearInterval(state.poller);
  state.poller = setInterval(async () => {
    try {
      const j = await jget(`/api/jobs/${id}`);
      onUpdate(j);
      if (["done", "failed", "cancelled", "paused"].includes(j.status)) {
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
    state.jobs = d.jobs;
    state.jobPriorityAvailable = d.capabilities?.job_priority === true;
    state.jobPreemptionAvailable = d.capabilities?.checkpointed_preemption === true;
    state.jobRecoveryAvailable = d.capabilities?.job_recovery === true;
    state.jobHideAvailable = d.capabilities?.job_hide === true;
    renderJobs(d.jobs);
    const completed = d.jobs.filter(job => job.meeting === state.slug
      && ((["upload", "topic_map", "regen", "retranscribe", "photo_analysis"].includes(job.kind)
        && job.status === "done")
        || (job.kind === "photo_analysis" && job.status === "failed"))
      && Number(job.finished || 0) >= Number(state.bundleLoadedAt || 0)
      && !state.refreshedArtifactJobs.has(job.id));
    completed.forEach(job => state.refreshedArtifactJobs.add(job.id));
    if (completed.length && state.slug && !state.bundleRefreshInFlight) {
      state.bundleRefreshInFlight = true;
      if (state.bundle) rememberReadingPosition();
      try { await loadMeeting(state.slug); }
      finally { state.bundleRefreshInFlight = false; }
    }
  } catch (e) { /* 忽略 */ }
}

function currentJobForMeeting() {
  if (!state.slug) return null;
  const matches = state.jobs.filter(job => job.meeting === state.slug);
  return matches.find(job => ["running", "recovering", "waiting_resource"].includes(job.progress?.state))
    || matches.find(job => job.status === "queued")
    || matches.find(job => ["failed", "paused"].includes(job.status))
    || matches.find(job => job.progress?.state === "degraded")
    || null;
}

function closeProcessingDetails() {
  closeJobSheet($("#job-detail-sheet"));
  const returnFocus = state.jobSheet.returnFocus;
  state.jobSheet = { jobId: null, mode: null, returnFocus: null, options: {} };
  if (returnFocus?.isConnected) returnFocus.focus();
}

function openProcessingDetails(job, mode = "details", trigger = null, options = {}) {
  const sheet = $("#job-detail-sheet");
  if (!sheet || !job) return;
  const model = jobPresentation(job, jobDisplayName(
    job, state.meetings, contentTypeOf, state.uiLanguage), state.uiLanguage);
  const returnFocus = trigger || state.jobSheet.returnFocus || document.activeElement;
  state.jobSheet = { jobId: job.id, mode, returnFocus, options };
  renderJobSheet(sheet, model, { mode, ...options }, {
    language: state.uiLanguage,
    onClose: closeProcessingDetails,
    onRecovery: () => openProcessingDetails(job, "recovery", trigger),
    onStartRecovery: async (_model, button) => {
      button.disabled = true;
      const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/retry?quality=standard`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        button.disabled = false;
        toast(`${isEnglishUi() ? "Recovery failed" : "恢复失败"}：${body.detail || response.status}`);
        return;
      }
      closeProcessingDetails();
      toast(isEnglishUi() ? "Recovery queued" : "恢复任务已排队");
      pollJobs();
    },
    onStartDegraded: async (_model, button) => {
      button.disabled = true;
      const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/retry?quality=standard&strategy=degraded`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        button.disabled = false;
        toast(`${isEnglishUi() ? "Could not create the voice-only result" : "无法生成语音版结果"}：${body.detail || response.status}`);
        return;
      }
      closeProcessingDetails();
      toast(isEnglishUi() ? "Voice-only completion queued; visual material can be added later"
        : "语音版结果已排队；后续仍可单独补充画面");
      pollJobs();
    },
    onStartPreempt: async (_model, button) => {
      button.disabled = true;
      const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/force-prioritize`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        button.disabled = false;
        toast(`${isEnglishUi() ? "Could not process now" : "立即处理失败"}：${body.detail || response.status}`);
        return;
      }
      closeProcessingDetails();
      toast(isEnglishUi() ? "Urgent item queued; the current task will resume afterward"
        : "急件将优先处理，原任务随后自动续跑");
      pollJobs();
    },
    onCopyDiagnostics: async modelValue => {
      const text = JSON.stringify({
        product_version: $("#product-version")?.textContent || null,
        web_build: SCRIPT_BUILD || null,
        diagnostic_id: modelValue.progress.failure?.diagnostic_id || null,
        error_code: modelValue.progress.failure?.code || null,
        exception_type: modelValue.progress.failure?.technical?.exception_type || null,
        phase: modelValue.progress.phase || null,
        attempt: modelValue.progress.attempt || 1,
        route: modelValue.progress.route || null,
        content_type: modelValue.job.content_type || null,
        done: modelValue.progress.done ?? null,
        total: modelValue.progress.total ?? null,
      }, null, 2);
      await navigator.clipboard.writeText(text);
      toast(isEnglishUi() ? "Diagnostics copied" : "诊断信息已复制");
    },
  });
}

async function handleJobAction(action, model, trigger) {
  const job = model.job;
  if (action === "details") return openProcessingDetails(job, "details", trigger);
  if (action === "recovery") return openProcessingDetails(job, "recovery", trigger);
  if (action === "preempt") {
    const running = state.activeJobs.find(item => item.status === "running");
    return openProcessingDetails(job, "preempt", trigger, {
      runningName: running ? jobDisplayName(
        running, state.meetings, contentTypeOf, state.uiLanguage) : "",
    });
  }
  if (action === "open_draft") {
    if (job.meeting && state.slug !== job.meeting) await loadMeeting(job.meeting);
    setReviewMode("minutes");
    $("#minutes")?.focus?.();
    return;
  }
  if (action === "open_result") {
    if (job.meeting) await loadMeeting(job.meeting);
    return;
  }
  if (action === "reimport") {
    closeMeetingLibrary();
    $("#pick-btn")?.focus();
    $("#file-input")?.click();
    return;
  }
  if (action === "reimport_url") {
    state.workspace.contentType = "media";
    saveWorkspaceState();
    applyUiLanguage();
    $("#media-url-input")?.focus();
    return;
  }
  if (action === "storage") {
    if (job.meeting && state.slug !== job.meeting) await loadMeeting(job.meeting);
    if (state.slug) await openStorageDialog();
    return;
  }
  if (action === "settings") {
    location.href = "/admin";
    return;
  }
  if (action === "check") return pollJobs();
  if (action === "priority") {
    const response = await api(`/api/jobs/${encodeURIComponent(job.id)}/prioritize`, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) toast(`${isEnglishUi() ? "Could not reprioritize" : "调整失败"}：${body.detail || response.status}`);
    return pollJobs();
  }
  if (action === "cancel") {
    await api(`/api/jobs/${encodeURIComponent(job.id)}/cancel`, { method: "POST" });
    return pollJobs();
  }
  if (action === "hide") {
    await api(`/api/jobs/${encodeURIComponent(job.id)}/hide`, { method: "POST" });
    return pollJobs();
  }
}

function renderJobsStructured(jobs) {
  const ul = $("#jobs-list");
  if (!ul) return;
  const { allActiveJobs, activeJobs, runningJob, visibleJobs } = selectJobPanel(
    jobs, state.workspace.contentType, contentTypeOf);
  state.activeJobs = allActiveJobs;
  $("#jobs-panel").classList.toggle("hidden", visibleJobs.length === 0);
  $(".jobs-head").textContent = activeJobs.length
    ? (isEnglishUi() ? "Processing" : "正在处理") : (isEnglishUi() ? "Needs attention" : "需要处理");
  ul.replaceChildren();
  visibleJobs.slice(0, 8).forEach(job => {
    const model = jobPresentation(job, jobDisplayName(
      job, state.meetings, contentTypeOf, state.uiLanguage), state.uiLanguage,
      jobTaskLabel(job, state.uiLanguage));
    const node = renderCompactJob(model, {
      language: state.uiLanguage,
      allowHide: state.jobHideAvailable && ["failed", "paused", "cancelled"].includes(job.status),
      extraActions: () => {
        const actions = [];
        if (state.jobPriorityAvailable && job.status === "queued"
            && (!job.priority_boost || Number(job.queue_position) > 1)) {
          actions.push({ id: "priority", label: isEnglishUi() ? "Next" : "优先",
            title: isEnglishUi() ? "Move after the current task" : "排到当前任务之后" });
        }
        if (state.jobPreemptionAvailable && job.status === "queued"
            && runningJob?.preemptible && runningJob.id !== job.id) {
          actions.push({ id: "preempt", label: isEnglishUi() ? "Now" : "立即",
            title: isEnglishUi() ? "Pause safely and process this item" : "安全暂停当前任务并先处理此项" });
        }
        return actions;
      },
      onAction: handleJobAction,
    });
    ul.appendChild(node);
  });
  const current = currentJobForMeeting();
  renderProcessingBanner($("#processing-banner"), current
    ? jobPresentation(current, jobDisplayName(
      current, state.meetings, contentTypeOf, state.uiLanguage), state.uiLanguage,
      jobTaskLabel(current, state.uiLanguage))
    : null, { language: state.uiLanguage, onAction: handleJobAction });
  if (state.jobSheet.jobId && !$("#job-detail-sheet")?.classList.contains("hidden")) {
    const openJob = jobs.find(job => job.id === state.jobSheet.jobId);
    if (openJob) openProcessingDetails(openJob, state.jobSheet.mode,
      state.jobSheet.returnFocus, { ...state.jobSheet.options, focus: false });
    else closeProcessingDetails();
  }
  renderMeetingStatuses();
}

function renderJobs(jobs) {
  return renderJobsStructured(jobs);
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

function wireTablistKeyboard(tablist) {
  if (!tablist || tablist.dataset.keyboardReady === "true") return;
  tablist.dataset.keyboardReady = "true";
  tablist.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = [...tablist.querySelectorAll('[role="tab"]')]
      .filter(tab => !tab.disabled && !tab.hidden && !tab.classList.contains("hidden"));
    const current = tabs.indexOf(document.activeElement);
    if (current < 0 || !tabs.length) return;
    let next = current;
    if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else next = (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length)
      % tabs.length;
    event.preventDefault();
    tabs[next].focus();
    tabs[next].click();
  });
}

function init() {
  liveContextView = mountLiveContext(document);
  applyUiLanguage();
  wireTablistKeyboard(document.querySelector(".minutes-mode-tabs"));
  wireTablistKeyboard(document.querySelector(".utility-tabs"));
  loadProductVersion();
  $$('[data-ui-language]').forEach(button =>
    button.onclick = () => setUiLanguage(button.dataset.uiLanguage));
  $("#search").addEventListener("input", renderMeetingList);
  $$("#content-type-tabs [data-content-type]").forEach(button =>
    button.onclick = () => {
      if (state.workspace.contentType === button.dataset.contentType) return;
      state.workspace.contentType = button.dataset.contentType;
      saveWorkspaceState();
      applyUiLanguage();
      renderMeetingList();
      renderJobs(state.jobs);
    });
  $("#meeting-sort").value = state.workspace.meetingSort;
  $("#meeting-sort").addEventListener("change", event => {
    state.workspace.meetingSort = event.target.value;
    saveWorkspaceState();
    renderMeetingList();
  });
  $("#minutes-view").addEventListener("change", event => {
    if (!state.slug) return;
    state.workspace.minutesViews[state.slug] = event.target.value || "standard";
    saveWorkspaceState();
    renderMinutes();
  });
  $("#restore-minutes").onclick = restorePreviousMinutes;
  $("#regen-btn").onclick = () => regenMinutes("");
  $("#retranscribe-btn").onclick = retranscribeLocal;
  $("#undo-speaker-btn").onclick = undoSpeakerOperation;
  $("#rename-btn").onclick = startRename;
  $("#content-type-btn").onclick = toggleContentType;
  $("#photo-import-btn").onclick = event => choosePhotoFiles("materials", event.currentTarget);
  $("#photo-import-current-btn").onclick = event => choosePhotoFiles("player", event.currentTarget);
  $("#photo-file-input").addEventListener("change", event => openPhotoImportDialog(event.target.files));
  $("#photo-import-close").onclick = closePhotoImportDialog;
  $("#photo-import-cancel").onclick = closePhotoImportDialog;
  $("#photo-import-confirm").onclick = importMeetingPhotos;
  $("#photo-import-mask").addEventListener("click", event => {
    if (event.target.id === "photo-import-mask") closePhotoImportDialog();
  });
  $("#photo-delete-cancel").onclick = closePhotoDeleteDialog;
  $("#photo-delete-confirm").onclick = deletePhotoMaterial;
  $("#photo-delete-mask").addEventListener("click", event => {
    if (event.target.id === "photo-delete-mask") closePhotoDeleteDialog();
  });
  $("#transcript-search").addEventListener("input", applyTranscriptSearch);
  $("#transcript-search").addEventListener("keydown", e => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    stepTranscriptMatch(e.shiftKey ? -1 : 1);
  });
  $("#transcript-edit-cancel").onclick = closeTranscriptEdit;
  $("#transcript-edit-save").onclick = saveTranscriptEdit;
  $("#transcript-edit-play").onclick = () => {
    const index = state.transcriptEditIndex;
    const turn = Number.isInteger(index) ? state.bundle?.transcript?.[index] : null;
    if (!turn) return;
    seek(Number(turn.start) || 0);
    player()?.play().catch(() => {});
  };
  $("#transcript-edit-mask").addEventListener("click", event => {
    if (event.target.id === "transcript-edit-mask") closeTranscriptEdit();
  });
  $("#transcript-edit-text").addEventListener("keydown", event => {
    if (event.key === "Escape") closeTranscriptEdit();
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") saveTranscriptEdit();
  });
  $("#refine-btn").onclick = () => {
    if (confirm("用 122B 大模型整体重写纪要？首次调用需加载模型(数分钟)，且会挤占常驻模型。"))
      regenMinutes("qwen3.5-122b-a10b-planner");
  };
  $("#export-btn").onclick = openExportDialog;
  $("#knowledge-publish-btn").onclick = openKnowledgePublishDialog;
  $("#storage-btn").onclick = openStorageDialog;
  $("#minutes-tab").onclick = () => setReviewMode("minutes");
  $("#chapters-tab").onclick = () => setReviewMode("chapters");
  $("#visuals-tab").onclick = () => setReviewMode("visuals");
  $("#quality-tab").onclick = () => setReviewMode("quality");
  $("#quality-entry-btn").onclick = () => setReviewMode("quality");
  $("#restructure-minutes").onclick = startMinutesRestructure;
  $("#translation-control").onclick = () => {
    if (state.translationJob) stopTranscriptTranslation();
    else startTranscriptTranslation([...state.evidenceBilingual]);
  };
  $$('[data-transcript-mode]').forEach(button => {
    button.onclick = () => setTranscriptMode(button.dataset.transcriptMode);
  });
  $("#translation-target").onchange = event => setTranslationTarget(event.target.value);
  document.addEventListener("keydown", qualityShortcut);
  // 节奏条按像素分桶，窗口尺寸变化后防抖重算。
  let speakerLaneResizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(speakerLaneResizeTimer);
    speakerLaneResizeTimer = setTimeout(() => {
      const tl = $("#timeline");
      if (!tl || !state.bundle) return;
      renderSpeakerLane(tl, Number(tl.dataset.dur || state.bundle.duration || 1));
      applySpeakerFocus();
    }, 180);
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || state.speakerCorrection.mode === "idle") return;
    event.preventDefault();
    closeSpeakerCorrection(state.speakerCorrection.mode === "identify");
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || $("#job-detail-sheet")?.classList.contains("hidden")) return;
    event.preventDefault();
    closeProcessingDetails();
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (!$("#photo-delete-mask")?.classList.contains("hidden")) {
      event.preventDefault(); closePhotoDeleteDialog(); return;
    }
    if (!$("#photo-import-mask")?.classList.contains("hidden") && !state.photoImport.busy) {
      event.preventDefault(); closePhotoImportDialog();
    }
  });

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
    const profile = selectedExportProfile();
    const related = selectedRelatedSlugs();
    if (related.length) exportPack([state.slug, ...related], media, profile);
    else exportMeeting(media, profile);
  };
  $("#export-mask").addEventListener("click", event => {
    if (event.target.id === "export-mask") closeExportDialog();
  });
  $("#knowledge-publish-close").onclick = closeKnowledgePublishDialog;
  $("#knowledge-publish-cancel").onclick = closeKnowledgePublishDialog;
  $("#knowledge-publish-confirm").onclick = publishToKnowledgeBase;
  $("#knowledge-publish-mask").addEventListener("click", event => {
    if (event.target.id === "knowledge-publish-mask") closeKnowledgePublishDialog();
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
  $("#media-url-submit").onclick = importMediaUrl;
  $("#media-url-input").addEventListener("keydown", event => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    importMediaUrl();
  });

  pollJobs();
  setInterval(pollJobs, 4000);
  loadMeetings();
}

/* 构建号自检：产品版本从 /api/health 读取，缓存构建号从脚本 v= 参数读取。 */
const SCRIPT_BUILD = new URL(import.meta.url).searchParams.get("v");
document.addEventListener("DOMContentLoaded", () => {
  if (SCRIPT_BUILD) document.querySelector(".brand")?.setAttribute("title", `构建 ${SCRIPT_BUILD}`);
});


/* 布局诊断：?diag=1 时在页面右下角叠加关键容器的滚动链路数据，供远程排障 */
function showLayoutDiag() {
  const q = s => {
    const n = document.querySelector(s);
    if (!n) return `${s}: 不存在`;
    const cs = getComputedStyle(n);
    const r = n.getBoundingClientRect();
    return `${s}\n  sh=${n.scrollHeight} h=${Math.round(r.height)} ov=${cs.overflowY} pos=${cs.position}`;
  };
  const pre = document.createElement("pre");
  pre.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:9999;max-width:46vw;" +
    "max-height:70vh;overflow:auto;background:#101318;color:#9fe8a9;border:1px solid #3a4;" +
    "padding:10px;font:11px/1.5 ui-monospace,monospace;white-space:pre-wrap";
  pre.textContent = [
    `build=${SCRIPT_BUILD || "?"} inner=${innerWidth}x${innerHeight} dpr=${devicePixelRatio}`,
    q(".layout"), q(".workspace"), q("#content-shell"), q(".review-grid"),
    q(".minutes-pane"), q("#minutes"), q(".structure-view:not(.hidden)"),
    q(".topic-map-view"), q("#utility-panel"), q(".assistant-pane"),
    q(".assistant-thread"), q(".assistant-messages"),
  ].join("\n");
  document.body.appendChild(pre);
}
if (new URLSearchParams(location.search).get("diag")) {
  setTimeout(showLayoutDiag, 2500);
}

document.addEventListener("DOMContentLoaded", init);
