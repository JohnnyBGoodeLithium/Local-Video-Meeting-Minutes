"use strict";

import { createLiveContextState, normalizeLiveWorkspace, selectLiveContentType, selectLiveMode }
  from "./live-context.js";

const COPY = {
  "zh-CN": {
    entry: "Live Context", title: "开始 Live Context",
    summary: "会议或直播进行时持续整理文字、人物、议题与证据。此能力仍在实验中。",
    contentLegend: "内容类型", meeting: "会议", event: "直播活动", source: "来源",
    sourcePlaceholder: "粘贴已授权的公开来源 URL", modeLegend: "分析方式",
    background: "后台分析", backgroundDetail: "无需播放。我们会在后台跟随活动。",
    watch: "观看并分析", watchDetail: "打开来源，同时继续分析。",
    companion: "会议伴随", companionDetail: "正常加入会议，Live Context 在后台安静监听。",
    manual: "手动 / 高级来源模式", manualDetail: "明确选择字幕、标签页或系统音频来源。",
    advanced: "高级选项",
    advancedDetail: "来源能力探测后才会显示可用捕获方式；不会静默切换或播放声音。",
    cancel: "取消", continue: "检查来源", close: "关闭 Live Context",
    probing: "正在检查来源能力…", starting: "正在启动后台分析…",
    unavailable: "此来源目前不能静默后台分析。请保持来源窗口打开后再继续。",
    sourceOpened: "来源已打开，但分析尚未开始。请再选择经授权的标签页或系统音频捕获方式。",
    live: "LIVE", finalizing: "正在整理已捕获内容", complete: "整理完成", failed: "分析未完成",
    text: "文字", audio: "音频", speakers: "人物", visual: "画面",
    textWaiting: "正在等待来源", audioSilent: "静默采集中", speakersProvisional: "暂定",
    visualWaiting: "选择性分析；允许稍后补完", openSource: "打开来源并分析", stop: "停止",
    stopQuestion: "停止并整理目前已捕获的内容？", stopCancel: "取消", stopFinalize: "停止并整理",
    workspaceTitle: "Live Context", transcriptTitle: "实时文字",
    transcriptHelp: "内容仍在更新，停止后会统一校正。",
    follow: "跟随最新内容", waitingTitle: "正在等待第一段文字",
    waitingDetail: "采集会在后台继续，你可以返回资料库。",
    takeawaysTitle: "实时要点（暂定）",
    takeawaysBoundary: "这里只显示有当前文字依据的临时判断；停止后才生成完整整理。",
    takeawaysWaitingTitle: "先积累一些上下文",
    takeawaysWaitingDetail: "为避免与实时语音识别争抢本机资源，本版在停止后统一提炼要点。",
    sourceLink: "打开原直播", back: "返回资料库", stopAndFinalize: "停止并整理",
    workspaceStopQuestion: "停止采集并整理目前的内容？",
    workspaceStopDetail: "已经捕获的文字和媒体会保留，并进入现有整理流程。",
    continueCapture: "继续采集", provisionalSpeaker: "说话人待确认", liveText: "段实时文字",
    truncatedText: "仅显示最近内容", collecting: "正在采集和识别",
  },
  en: {
    entry: "Live Context", title: "Start Live Context",
    summary: "Compile text, people, topics, and evidence while a meeting or live event is still running. Experimental.",
    contentLegend: "Content type", meeting: "Meeting", event: "Live event", source: "Source",
    sourcePlaceholder: "Paste an authorized public source URL",
    modeLegend: "Analysis mode", background: "Analyze in background",
    backgroundDetail: "No playback required. We'll follow the event for you.",
    watch: "Watch & analyze", watchDetail: "Open the source while analysis continues.",
    companion: "Meeting companion",
    companionDetail: "Join normally. Live Context listens quietly in the background.",
    manual: "Manual / advanced source mode",
    manualDetail: "Explicitly choose a transcript, tab, or system-audio source.",
    advanced: "Advanced options",
    advancedDetail: "Capture choices appear after source probing. No silent mode switch or audible playback.",
    cancel: "Cancel", continue: "Check source", close: "Close Live Context",
    probing: "Checking source capabilities…", starting: "Starting background analysis…",
    unavailable: "Background analysis is not available for this source. Keep the source window open to continue analysis.",
    sourceOpened: "Source opened, but analysis has not started. Choose an approved tab or system-audio capture source to continue.",
    live: "LIVE", finalizing: "Finalizing captured context", complete: "Complete", failed: "Analysis incomplete",
    text: "Text", audio: "Audio", speakers: "Speakers", visual: "Visual",
    textWaiting: "Waiting for source", audioSilent: "Capturing silently", speakersProvisional: "Provisional",
    visualWaiting: "Selective analysis; may finish later", openSource: "Open source & analyze", stop: "Stop",
    stopQuestion: "Stop and finalize what has been captured so far?", stopCancel: "Cancel",
    stopFinalize: "Stop & finalize",
    workspaceTitle: "Live Context", transcriptTitle: "Live transcript",
    transcriptHelp: "Content is still changing and will be reconciled after capture stops.",
    follow: "Follow latest", waitingTitle: "Waiting for the first transcript segment",
    waitingDetail: "Capture continues in the background while you return to the library.",
    takeawaysTitle: "Live takeaways (provisional)",
    takeawaysBoundary: "Only provisional points with current transcript support appear here; full synthesis happens after capture stops.",
    takeawaysWaitingTitle: "Building enough context",
    takeawaysWaitingDetail: "This release synthesizes takeaways after capture stops to avoid competing with live ASR for local resources.",
    sourceLink: "Open live source", back: "Back to library", stopAndFinalize: "Stop & finalize",
    workspaceStopQuestion: "Stop capture and finalize what is available?",
    workspaceStopDetail: "Captured text and media will be preserved and passed to the existing finalization workflow.",
    continueCapture: "Keep capturing", provisionalSpeaker: "Speaker pending", liveText: "live transcript segments",
    truncatedText: "showing recent content", collecting: "Capturing and transcribing",
  },
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

export function mountLiveContext(root = document, { request = fetch, pollEvery = 4000 } = {}) {
  const entry = root.querySelector("#live-context-entry");
  const mask = root.querySelector("#live-context-mask");
  const form = root.querySelector("#live-context-form");
  const workspace = root.querySelector("#live-workspace");
  const transcriptFeed = root.querySelector("#live-transcript-feed");
  let state = { ...createLiveContextState(), busy: false, notice: "", session: null,
    fallbackOpen: false, workspace: null, workspaceOpen: false };
  let language = "zh-CN";
  let returnFocus = null;
  let poller = null;
  let renderedTurnCount = 0;

  function copy() { return COPY[language] || COPY["zh-CN"]; }

  function formatDuration(seconds) {
    const value = Math.max(0, Number(seconds) || 0);
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor(value % 3600 / 60);
    const secs = Math.floor(value % 60);
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
      : `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  async function jsonRequest(path, options = {}) {
    const response = await request(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof body.detail === "object" ? body.detail?.message : body.detail;
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return body;
  }

  function currentSession() {
    return state.session || state.workspace?.session || null;
  }

  function sessionPath(suffix = "") {
    return `/api/live/sessions/${encodeURIComponent(currentSession().id)}${suffix}`;
  }

  async function refreshWorkspace() {
    if (!currentSession()?.id) return;
    const body = await jsonRequest(sessionPath("/workspace"));
    state = { ...state, workspace: normalizeLiveWorkspace(body),
      session: body.session || state.session };
  }

  function schedulePoll() {
    clearTimeout(poller);
    const session = currentSession();
    if (!session?.id || ["COMPLETE", "FAILED", "CANCELLED"].includes(session.state)) return;
    poller = setTimeout(async () => {
      try {
        if (state.workspaceOpen) await refreshWorkspace();
        else state = { ...state, session: await jsonRequest(sessionPath()) };
        render();
      } catch (_) {
        // A transient UI poll failure must not stop the backend session.
      }
      schedulePoll();
    }, pollEvery);
  }

  async function loadActiveSession() {
    try {
      const body = await jsonRequest("/api/live/sessions");
      const sessions = body.sessions || [];
      const active = sessions.find(item => !["COMPLETE", "FAILED", "CANCELLED"].includes(item.state));
      if (active) {
        state = { ...state, session: active, source: state.source || "" };
        render();
        schedulePoll();
      }
    } catch (_) {
      // Feature discovery may race service startup; the entry remains usable.
    }
  }

  function renderWorkspace() {
    const c = copy();
    const active = Boolean(state.workspaceOpen && state.session);
    workspace.classList.toggle("hidden", !active);
    if (!active) return;
    const projected = state.workspace;
    const session = projected?.session || state.session;
    const statusLabel = ({
      LIVE: c.collecting, CONNECTING: c.starting, STALLED: c.unavailable,
      RECOVERING: c.starting, ENDING: c.finalizing, FINALIZING: c.finalizing,
      COMPLETE: c.complete, FAILED: c.failed, CANCELLED: c.failed,
    })[session.state] || String(session.state || c.starting);
    root.querySelector("#live-workspace-title").textContent = c.workspaceTitle;
    root.querySelector("#live-workspace-status").textContent =
      `${statusLabel} · ${formatDuration(session.duration)}`;
    root.querySelector("#live-transcript-title").textContent = c.transcriptTitle;
    root.querySelector("#live-transcript-meta").textContent = projected
      ? `${projected.transcript.turns.length} ${c.liveText}${projected.transcript.truncated ? ` · ${c.truncatedText}` : ""}`
      : c.transcriptHelp;
    root.querySelector("#live-follow-label").textContent = c.follow;
    root.querySelector("#live-transcript-empty strong").textContent = c.waitingTitle;
    root.querySelector("#live-transcript-empty span").textContent = c.waitingDetail;
    root.querySelector("#live-takeaways-title").textContent = c.takeawaysTitle;
    root.querySelector("#live-takeaways-boundary").textContent = c.takeawaysBoundary;
    root.querySelector("#live-takeaways-empty strong").textContent = c.takeawaysWaitingTitle;
    root.querySelector("#live-takeaways-empty span").textContent = c.takeawaysWaitingDetail;
    root.querySelector("#live-workspace-back").textContent = c.back;
    root.querySelector("#live-workspace-stop").textContent = c.stopAndFinalize;
    root.querySelector("#live-workspace-stop-question").textContent = c.workspaceStopQuestion;
    root.querySelector("#live-workspace-stop-detail").textContent = c.workspaceStopDetail;
    root.querySelector("#live-workspace-stop-cancel").textContent = c.continueCapture;
    root.querySelector("#live-workspace-stop-finalize").textContent = c.stopAndFinalize;

    const turns = projected?.transcript.turns || [];
    root.querySelector("#live-transcript-empty").classList.toggle("hidden", turns.length > 0);
    root.querySelector("#live-transcript-list").innerHTML = turns.map(item => `
      <li class="live-transcript-turn">
        <time datetime="PT${Math.round(item.start)}S">${escapeHtml(formatDuration(item.start))}</time>
        <div class="live-transcript-copy">
          <b>${escapeHtml(item.speaker || c.provisionalSpeaker)}</b>
          <p>${escapeHtml(item.text)}</p>
        </div>
      </li>`).join("");
    if (turns.length !== renderedTurnCount && root.querySelector("#live-follow").checked) {
      transcriptFeed.scrollTop = transcriptFeed.scrollHeight;
    }
    renderedTurnCount = turns.length;

    const takeaways = projected?.takeaways.items || [];
    root.querySelector("#live-takeaways-empty").classList.toggle("hidden", takeaways.length > 0);
    root.querySelector("#live-takeaways-list").innerHTML = takeaways.map(item => `
      <article class="live-takeaway"><p>${escapeHtml(item.text)}</p>
        <time datetime="PT${Math.round(item.start)}S">${escapeHtml(formatDuration(item.start))}</time>
      </article>`).join("");

    const sourceLink = root.querySelector("#live-workspace-source");
    const displayUrl = projected?.source.displayUrl || state.source;
    const validSource = /^https?:\/\//i.test(displayUrl);
    sourceLink.classList.toggle("hidden", !validSource);
    sourceLink.href = validSource ? displayUrl : "#";
    sourceLink.textContent = c.sourceLink;
    root.querySelector("#live-workspace-stop").disabled =
      ["ENDING", "FINALIZING", "COMPLETE", "FAILED", "CANCELLED"].includes(session.state);
  }

  function render() {
    const c = copy();
    const sessionActive = state.session
      && !["COMPLETE", "FAILED", "CANCELLED"].includes(state.session.state);
    entry.textContent = sessionActive
      ? `● ${c.live} · ${formatDuration(state.session.duration)}` : c.entry;
    entry.classList.toggle("live-context-entry--active", Boolean(sessionActive));
    root.querySelector("#live-context-title").textContent = c.title;
    root.querySelector("#live-context-summary").textContent = c.summary;
    root.querySelector("#live-content-legend").textContent = c.contentLegend;
    root.querySelector("#live-source-label").textContent = c.source;
    root.querySelector("#live-source-input").placeholder = c.sourcePlaceholder;
    root.querySelector("#live-mode-legend").textContent = c.modeLegend;
    root.querySelector("#live-advanced-label").textContent = c.advanced;
    root.querySelector("#live-advanced-detail").textContent = c.advancedDetail;
    root.querySelector("#live-context-cancel").textContent = c.cancel;
    root.querySelector("#live-context-continue").textContent = state.busy
      ? (state.notice === c.starting ? c.starting : c.probing) : c.continue;
    root.querySelector("#live-context-close").setAttribute("aria-label", c.close);
    root.querySelectorAll('[name="live-content-type"]').forEach(input => {
      input.checked = input.value === state.contentType;
      input.parentElement.querySelector("b").textContent = input.value === "meeting" ? c.meeting : c.event;
    });
    const modes = state.contentType === "meeting" ? [
      ["meeting_companion", c.companion, c.companionDetail],
      ["manual", c.manual, c.manualDetail],
    ] : [
      ["analyze_background", c.background, c.backgroundDetail],
      ["watch_analyze", c.watch, c.watchDetail],
    ];
    root.querySelector("#live-mode-options").innerHTML = modes.map(([value, label, detail]) => `
      <label>
        <input type="radio" name="live-mode" value="${escapeHtml(value)}"
          ${state.mode === value ? "checked" : ""}>
        <span><b>${escapeHtml(label)}</b><small>${escapeHtml(detail)}</small></span>
      </label>`).join("");
    root.querySelector("#live-context-continue").disabled =
      state.busy || !!state.session || !state.source.trim();
    root.querySelector("#live-content-legend").closest("fieldset").disabled = !!state.session;
    root.querySelector("#live-source-input").disabled = !!state.session;
    root.querySelector("#live-mode-legend").closest("fieldset").disabled = !!state.session;
    const notice = root.querySelector("#live-probe-status");
    notice.textContent = state.notice || "";
    notice.classList.toggle("hidden", !state.notice);
    const sourceLink = root.querySelector("#live-open-source");
    const showSourceLink = state.fallbackOpen || (!!state.session && !!state.source);
    sourceLink.href = showSourceLink ? state.source : "#";
    sourceLink.textContent = state.fallbackOpen
      ? c.openSource : (language === "en" ? "Open source" : "打开来源");
    sourceLink.classList.toggle("hidden", !showSourceLink);

    const active = root.querySelector("#live-active-status");
    active.classList.toggle("hidden", !state.session);
    if (state.session) {
      const statusLabel = ({
        LIVE: c.live, CONNECTING: c.starting, STALLED: c.unavailable,
        RECOVERING: c.starting, ENDING: c.finalizing, FINALIZING: c.finalizing,
        COMPLETE: c.complete, FAILED: c.failed, CANCELLED: c.failed,
      })[state.session.state] || state.session.state;
      root.querySelector("#live-active-state").textContent =
        `${statusLabel} · ${formatDuration(state.session.duration)}`;
      root.querySelector("#live-text-label").textContent = c.text;
      root.querySelector("#live-audio-label").textContent = c.audio;
      root.querySelector("#live-speaker-label").textContent = c.speakers;
      root.querySelector("#live-visual-label").textContent = c.visual;
      root.querySelector("#live-text-status").textContent = state.session.text_signals
        ? `${state.session.text_signals} ${language === "en" ? "provisional signals" : "条暂定片段"}`
        : c.textWaiting;
      root.querySelector("#live-audio-status").textContent = c.audioSilent;
      root.querySelector("#live-speaker-status").textContent = c.speakersProvisional;
      root.querySelector("#live-visual-status").textContent = c.visualWaiting;
      root.querySelector("#live-stop").textContent = c.stop;
      root.querySelector("#live-stop-question").textContent = c.stopQuestion;
      root.querySelector("#live-stop-cancel").textContent = c.stopCancel;
      root.querySelector("#live-stop-finalize").textContent = c.stopFinalize;
      root.querySelector("#live-stop").disabled = ["ENDING", "FINALIZING", "COMPLETE", "FAILED"]
        .includes(state.session.state);
    }
    renderWorkspace();
  }

  function close() {
    state = { ...state, open: false };
    mask.classList.add("hidden");
    returnFocus?.focus();
  }

  async function openWorkspace(trigger = null) {
    returnFocus = trigger || returnFocus;
    state = { ...state, open: false, workspaceOpen: true };
    mask.classList.add("hidden");
    render();
    try {
      await refreshWorkspace();
    } catch (_) {
      // Metadata still communicates that capture is alive while content catches up.
    }
    render();
    transcriptFeed.focus();
    schedulePoll();
  }

  function closeWorkspace() {
    const terminal = ["COMPLETE", "FAILED", "CANCELLED"].includes(state.session?.state);
    state = { ...state, workspaceOpen: false,
      session: terminal ? null : state.session,
      workspace: terminal ? null : state.workspace };
    workspace.classList.add("hidden");
    root.querySelector("#live-workspace-stop-confirm").classList.add("hidden");
    entry.focus();
  }

  entry.addEventListener("click", event => {
    if (state.session) {
      openWorkspace(event.currentTarget);
      return;
    }
    returnFocus = event.currentTarget;
    state = { ...state, open: true };
    mask.classList.remove("hidden");
    render();
    loadActiveSession();
    root.querySelector('[name="live-content-type"]:checked')?.focus();
  });
  root.querySelector("#live-context-close").addEventListener("click", close);
  root.querySelector("#live-context-cancel").addEventListener("click", close);
  mask.addEventListener("click", event => { if (event.target === mask) close(); });
  mask.addEventListener("keydown", event => { if (event.key === "Escape") close(); });
  form.addEventListener("change", event => {
    if (event.target.name === "live-content-type") {
      state = selectLiveContentType(state, event.target.value);
    } else if (event.target.name === "live-mode") {
      state = selectLiveMode(state, event.target.value);
    }
    render();
  });
  root.querySelector("#live-source-input").addEventListener("input", event => {
    state = { ...state, source: event.target.value, fallbackOpen: false };
    root.querySelector("#live-context-continue").disabled =
      !state.source.trim();
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (state.busy || state.session) return;
    const c = copy();
    state = { ...state, busy: true, notice: c.probing, fallbackOpen: false };
    render();
    const payload = { source_url: state.source.trim(), content_type: state.contentType,
      mode: state.mode };
    try {
      const probe = await jsonRequest("/api/live/probe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!probe.capture_plan?.background_available || state.mode !== "analyze_background") {
        state = { ...state, busy: false, notice: c.unavailable, fallbackOpen: true };
        render();
        return;
      }
      state = { ...state, notice: c.starting };
      render();
      const session = await jsonRequest("/api/live/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      state = { ...state, busy: false, notice: "", session, fallbackOpen: false };
      render();
      await openWorkspace(entry);
    } catch (error) {
      state = { ...state, busy: false, notice: error.message || c.unavailable };
      render();
    }
  });
  root.querySelector("#live-open-source").addEventListener("click", () => {
    if (!state.fallbackOpen) return;
    state = { ...state, notice: copy().sourceOpened };
    render();
  });
  root.querySelector("#live-stop").addEventListener("click", () => {
    root.querySelector("#live-stop-confirm").classList.remove("hidden");
    root.querySelector("#live-stop-finalize").focus();
  });
  root.querySelector("#live-stop-cancel").addEventListener("click", () => {
    root.querySelector("#live-stop-confirm").classList.add("hidden");
    root.querySelector("#live-stop").focus();
  });
  root.querySelector("#live-stop-finalize").addEventListener("click", async () => {
    if (!currentSession()?.id) return;
    root.querySelector("#live-stop-confirm").classList.add("hidden");
    try {
      state = { ...state, session: await jsonRequest(
        `/api/live/sessions/${encodeURIComponent(state.session.id)}/stop`, { method: "POST" }) };
      render();
      schedulePoll();
    } catch (error) {
      state = { ...state, notice: error.message || copy().failed };
      render();
    }
  });
  root.querySelector("#live-workspace-back").addEventListener("click", closeWorkspace);
  root.querySelector("#live-workspace-stop").addEventListener("click", () => {
    root.querySelector("#live-workspace-stop-confirm").classList.remove("hidden");
    root.querySelector("#live-workspace-stop-finalize").focus();
  });
  root.querySelector("#live-workspace-stop-cancel").addEventListener("click", () => {
    root.querySelector("#live-workspace-stop-confirm").classList.add("hidden");
    root.querySelector("#live-workspace-stop").focus();
  });
  root.querySelector("#live-workspace-stop-finalize").addEventListener("click", async () => {
    if (!currentSession()?.id) return;
    root.querySelector("#live-workspace-stop-confirm").classList.add("hidden");
    try {
      state = { ...state, session: await jsonRequest(
        sessionPath("/stop"), { method: "POST" }) };
      render();
      schedulePoll();
    } catch (error) {
      state = { ...state, notice: error.message || copy().failed };
      render();
    }
  });
  workspace.addEventListener("keydown", event => {
    if (event.key === "Escape"
        && root.querySelector("#live-workspace-stop-confirm").classList.contains("hidden")) {
      closeWorkspace();
    }
  });
  render();
  return {
    setEnabled(enabled) {
      entry.classList.toggle("hidden", !enabled);
      if (enabled) loadActiveSession();
    },
    setLanguage(value) { language = value === "en" ? "en" : "zh-CN"; render(); },
    getState() { return { ...state }; },
  };
}
