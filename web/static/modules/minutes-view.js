/* Minutes reading projection. State selection and all write side effects stay in app.js. */

import { resolveMinutesClaim } from "./minutes.js?v=20260901p111";

export function renderMinutesView(options) {
  const {
    box, viewSelect, restoreButton, restructureButton, availableViews = [],
    selectedViewId = "standard", selectedView = null, viewMode = "minutes",
    historyAvailable = false, presentation = {}, draftFailure = {},
    minutesHtml = "", evidence = null, evidenceState = "missing",
    translationState = null, translationActive = false, isEnglish = false,
    ui, escapeHtml, formatTime, onCanonicalClaim, onAssistantClaim,
  } = options;

  if (viewSelect) {
    viewSelect.innerHTML = `<option value="standard">${isEnglish ? "Standard minutes" : "标准纪要"}</option>`
      + availableViews.map(view =>
        `<option value="${escapeHtml(view.id)}">AI · ${escapeHtml(view.title)}</option>`).join("");
    viewSelect.value = selectedViewId;
    viewSelect.classList.toggle("hidden", !availableViews.length || viewMode !== "minutes");
  }
  restoreButton?.classList.toggle("hidden", viewMode !== "minutes"
    || selectedViewId !== "standard" || !historyAvailable);

  const { draft, phase, draftFailed } = presentation;
  const banner = draft ? (isEnglish
    ? `<section class="minutes-draft-banner"><div><span>Voice draft · Ready to read</span>`
      + `<b>${phase === "visual_enrichment" ? "Adding screen context" : "Preparing screen analysis"}</b>`
      + "<p>This draft uses the transcript and speaker identities. Tables, figures, and visual context will be added to the multimodal final version. Playback, search, and Q&A are available; editing and export remain disabled.</p></div><i></i></section>"
    : `<section class="minutes-draft-banner"><div><span>语音草稿 · 已可阅读</span>`
      + `<b>${phase === "visual_enrichment" ? "正在补充屏幕资料" : "正在准备屏幕分析"}</b>`
      + "<p>当前结论来自逐字稿和说话人；页面数字、表格和画面上下文会在多模态终稿中补充。"
      + "草稿期间可以播放、搜索和追问，暂不支持修改或导出。</p></div><i></i></section>") : "";
  const pending = draftFailed
    ? '<section class="minutes-draft-banner"><div><span>语音草稿生成失败</span><b>正在继续生成多模态终稿</b>'
      + `<p>${escapeHtml(draftFailure.detail)}</p></div><i></i></section>`
    : '<p class="placeholder">暂无纪要</p>';
  const languageBanner = translationActive
    ? `<div class="minutes-language-banner"><b>${escapeHtml(ui("translatingMinutes"))}</b><span>…</span></div>`
    : translationState === "failed"
      ? `<div class="minutes-language-banner"><b>${escapeHtml(ui("minutesFailed"))}</b></div>` : "";
  box.innerHTML = selectedView
    ? `<section class="minutes-view-banner"><b>${isEnglish ? "AI minutes view" : "AI 纪要视图"}</b>`
      + `<span>${escapeHtml(selectedView.title)}</span><small>${isEnglish
        ? "The standard minutes are preserved; switch back above at any time."
        : "标准纪要未被覆盖，可从上方随时切回。"}</small></section>`
      + (selectedView.html || pending)
    : languageBanner + banner + (presentation.translatedHtml || minutesHtml || pending);

  if (restructureButton) {
    restructureButton.disabled = !presentation.canRestructure;
    restructureButton.title = draft
      ? (isEnglish ? "Wait for the multimodal final minutes" : "等待多模态终稿后再重组")
      : evidenceState !== "ready"
        ? (isEnglish ? "Regenerate evidence before restructuring" : "事实依据尚未就绪，请先重新生成纪要")
        : ui("restructurePlaceholder");
  }

  const candidates = presentation.actionCandidates || [];
  if (candidates.length) {
    const candidateHtml = '<details class="action-candidate-panel"><summary>'
      + `<span>${isEnglish ? "Unverified candidates" : "待核实候选"}</span>`
      + `<b>${isEnglish ? `${candidates.length} generated clues` : `另有 ${candidates.length} 条生成线索`}</b>`
      + `<small>${isEnglish
        ? "Not linked to transcript evidence and not confirmed. Expand to inspect the original clues."
        : "尚未绑定逐字稿依据，不代表已确认；展开后可完整保留查看。"}</small></summary>`
      + `<div class="action-candidate-list">${candidates.map((item, index) =>
        `<article><i>${String(index + 1).padStart(2, "0")}</i><div><b>${escapeHtml(item.text)}</b>`
        + `<small>${isEnglish ? "Owner" : "负责人"}：${escapeHtml(item.owner || (isEnglish ? "Unconfirmed" : "待确认"))} · `
        + `${isEnglish ? "Due" : "期限"}：${escapeHtml(item.deadline || (isEnglish ? "Unconfirmed" : "待确认"))} · `
        + `${isEnglish ? "Source status" : "原状态"}：${escapeHtml(item.original_status || (isEnglish ? "Unconfirmed" : "待确认"))}</small>`
        + `</div><span>${isEnglish ? "Evidence needed" : "待绑定依据"}</span></article>`
      ).join("")}</div></details>`;
    const riskHeading = [...box.querySelectorAll("h3")]
      .find(item => item.textContent.trim() === "风险/待确认");
    if (riskHeading) riskHeading.insertAdjacentHTML("beforebegin", candidateHtml);
    else box.insertAdjacentHTML("beforeend", candidateHtml);
  }

  [...box.querySelectorAll("h1, h2, h3")].forEach((heading, index) => {
    heading.id = `minutes-heading-${index}`;
    heading.dataset.readingHeading = "1";
  });
  [...box.querySelectorAll('a[href^="#mm-"]')].forEach(link => {
    const claimId = link.getAttribute("href").slice(4);
    const resolved = resolveMinutesClaim(evidence, selectedView, claimId);
    const claim = resolved.claim;
    if (claim?.start != null) {
      link.textContent = `${isEnglish ? "Evidence" : "依据"} · ${formatTime(claim.start)}`;
      link.title = isEnglish ? "Jump to the first supporting excerpt" : "跳到第一条原文依据";
    }
    link.onclick = event => {
      event.preventDefault();
      if (resolved.canonical) onCanonicalClaim(claimId);
      else if (claim) onAssistantClaim(claim);
    };
  });
}
