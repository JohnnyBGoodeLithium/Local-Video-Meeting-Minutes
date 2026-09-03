"use strict";

import { createLiveContextState, selectLiveContentType, selectLiveMode }
  from "./live-context.js";

const COPY = {
  "zh-CN": {
    entry: "Live Context", title: "开始 Live Context",
    summary: "会议或直播进行时持续整理文字、人物、议题与证据。此能力仍在实验中。",
    contentLegend: "内容类型", meeting: "会议", event: "直播活动", source: "来源",
    sourcePlaceholder: "粘贴公开直播 URL，或稍后选择会议音频来源", modeLegend: "分析方式",
    background: "后台分析", backgroundDetail: "无需播放。我们会在后台跟随活动。",
    watch: "观看并分析", watchDetail: "打开来源，同时继续分析。",
    companion: "会议伴随", companionDetail: "正常加入会议，Live Context 在后台安静监听。",
    manual: "手动 / 高级来源模式", manualDetail: "明确选择字幕、标签页或系统音频来源。",
    advanced: "高级选项",
    advancedDetail: "来源能力探测后才会显示可用捕获方式；不会静默切换或播放声音。",
    cancel: "取消", continue: "检查来源", close: "关闭 Live Context",
  },
  en: {
    entry: "Live Context", title: "Start Live Context",
    summary: "Compile text, people, topics, and evidence while a meeting or live event is still running. Experimental.",
    contentLegend: "Content type", meeting: "Meeting", event: "Live event", source: "Source",
    sourcePlaceholder: "Paste a public live URL, or choose a meeting audio source later",
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
  },
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

export function mountLiveContext(root = document) {
  const entry = root.querySelector("#live-context-entry");
  const mask = root.querySelector("#live-context-mask");
  const form = root.querySelector("#live-context-form");
  let state = createLiveContextState();
  let language = "zh-CN";
  let returnFocus = null;

  function copy() { return COPY[language] || COPY["zh-CN"]; }

  function render() {
    const c = copy();
    entry.textContent = c.entry;
    root.querySelector("#live-context-title").textContent = c.title;
    root.querySelector("#live-context-summary").textContent = c.summary;
    root.querySelector("#live-content-legend").textContent = c.contentLegend;
    root.querySelector("#live-source-label").textContent = c.source;
    root.querySelector("#live-source-input").placeholder = c.sourcePlaceholder;
    root.querySelector("#live-mode-legend").textContent = c.modeLegend;
    root.querySelector("#live-advanced-label").textContent = c.advanced;
    root.querySelector("#live-advanced-detail").textContent = c.advancedDetail;
    root.querySelector("#live-context-cancel").textContent = c.cancel;
    root.querySelector("#live-context-continue").textContent = c.continue;
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
      state.contentType === "live_event" && !state.source.trim();
  }

  function close() {
    state = { ...state, open: false };
    mask.classList.add("hidden");
    returnFocus?.focus();
  }

  entry.addEventListener("click", event => {
    returnFocus = event.currentTarget;
    state = { ...state, open: true };
    mask.classList.remove("hidden");
    render();
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
    state = { ...state, source: event.target.value };
    root.querySelector("#live-context-continue").disabled =
      state.contentType === "live_event" && !state.source.trim();
  });
  form.addEventListener("submit", event => event.preventDefault());
  render();
  return {
    setEnabled(enabled) { entry.classList.toggle("hidden", !enabled); },
    setLanguage(value) { language = value === "en" ? "en" : "zh-CN"; render(); },
    getState() { return { ...state }; },
  };
}
