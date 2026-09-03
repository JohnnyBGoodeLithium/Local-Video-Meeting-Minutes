/* DOM projection for processing, failure, and recovery. No API or global state. */

import { diagnosticText, failureReason, formatDuration, outputLabel, phaseLabel, recoveryPreview }
  from "./job-progress.js";

const button = (label, action, primary = false) => {
  const node = document.createElement("button");
  node.type = "button";
  node.textContent = label;
  node.dataset.jobAction = action;
  node.className = primary ? "fluent-button fluent-button--primary" : "fluent-button fluent-button--subtle";
  return node;
};

export function renderCompactJob(model, handlers = {}) {
  const item = document.createElement("li");
  item.className = `job-card job-card--${model.tone}`;
  const name = document.createElement("strong");
  name.className = "j-name";
  name.textContent = model.name;
  const task = document.createElement("span");
  task.className = "j-task";
  task.textContent = model.taskLabel || (handlers.language === "en" ? "Process meeting content" : "处理会议资料");
  const status = document.createElement("span");
  status.className = "j-st";
  status.textContent = model.headline;
  item.append(name, task, status);
  if (model.detail) {
    const detail = document.createElement("small");
    detail.className = "j-detail";
    detail.textContent = model.detail;
    item.appendChild(detail);
  }
  if (model.ratio !== null) {
    const track = document.createElement("div");
    track.className = "job-progress-track";
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(Math.round(model.ratio * 100)));
    const fill = document.createElement("i");
    fill.style.width = `${model.ratio * 100}%`;
    track.appendChild(fill);
    item.appendChild(track);
  }
  const actions = document.createElement("div");
  actions.className = "j-actions";
  (handlers.extraActions?.(model) || []).forEach(extra => {
    const extraButton = button(extra.label, extra.id);
    extraButton.title = extra.title || "";
    extraButton.addEventListener("click", event => handlers.onAction?.(
      extra.id, model, event.currentTarget));
    actions.appendChild(extraButton);
  });
  const primary = button(model.primary.label, model.primary.id, model.primary.id !== "details");
  primary.addEventListener("click", event => handlers.onAction?.(model.primary.id, model, event.currentTarget));
  actions.appendChild(primary);
  if (["queued", "running", "waiting_resource", "recovering"].includes(model.state)) {
    const cancel = button(handlers.language === "en" ? "Cancel" : "取消", "cancel");
    cancel.addEventListener("click", event => handlers.onAction?.("cancel", model, event.currentTarget));
    actions.appendChild(cancel);
  } else if (handlers.allowHide) {
    const hide = button(handlers.language === "en" ? "Hide" : "隐藏", "hide");
    hide.addEventListener("click", event => handlers.onAction?.("hide", model, event.currentTarget));
    actions.appendChild(hide);
  }
  item.appendChild(actions);
  if (model.legacy) {
    item.title = handlers.language === "en"
      ? "Historical task: stage is an estimate" : "历史任务：阶段来自兼容估算";
  }
  return item;
}

export function renderProcessingBanner(container, model, handlers = {}) {
  const previousSignature = container.dataset.liveSignature || "";
  const nextSignature = model ? `${model.state}:${model.progress.phase}` : "";
  container.setAttribute("aria-live", nextSignature !== previousSignature
    ? (model?.state === "failed" ? "assertive" : "polite") : "off");
  container.dataset.liveSignature = nextSignature;
  container.replaceChildren();
  if (!model || model.state === "done") {
    container.classList.add("hidden");
    return;
  }
  container.className = `processing-banner processing-banner--${model.tone}`;
  const text = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = model.headline;
  const detail = document.createElement("p");
  detail.textContent = model.detail || (model.outputs.length
    ? `${handlers.language === "en" ? "Available" : "已经可用"}：${model.outputs.join("、")}` : "");
  text.append(title, detail);
  const actions = document.createElement("div");
  actions.className = "processing-banner__actions";
  const primary = button(model.primary.label, model.primary.id, true);
  primary.addEventListener("click", event => handlers.onAction?.(model.primary.id, model, event.currentTarget));
  actions.appendChild(primary);
  if (model.primary.id !== "details") {
    const details = button(handlers.language === "en" ? "Processing details" : "查看处理详情", "details");
    details.addEventListener("click", event => handlers.onAction?.("details", model, event.currentTarget));
    actions.appendChild(details);
  }
  container.append(text, actions);
  container.classList.remove("hidden");
}

function section(titleText, items) {
  const block = document.createElement("section");
  const title = document.createElement("h4");
  title.textContent = titleText;
  block.appendChild(title);
  const list = document.createElement("ul");
  (items.length ? items : ["—"]).forEach(value => {
    const li = document.createElement("li");
    li.textContent = value;
    list.appendChild(li);
  });
  block.appendChild(list);
  return block;
}

export function renderJobSheet(sheet, model, options = {}, handlers = {}) {
  const language = handlers.language || "zh-CN";
  const english = language === "en";
  sheet.replaceChildren();
  sheet.className = "workspace-side-sheet job-detail-sheet";
  sheet.setAttribute("aria-hidden", "false");
  const head = document.createElement("header");
  const heading = document.createElement("div");
  const h2 = document.createElement("h2");
  h2.id = "job-detail-title";
  h2.textContent = options.mode === "recovery"
    ? (english ? "Recovery preview" : "恢复预览")
    : options.mode === "preempt" ? (english ? "Process this item now?" : "立即处理这项任务？")
    : (english ? "Processing details" : "处理详情");
  const sub = document.createElement("p");
  sub.textContent = model.taskLabel ? `${model.taskLabel} · ${model.name}` : model.name;
  heading.append(h2, sub);
  const close = button("×", "close");
  close.classList.add("workspace-side-sheet__close");
  close.setAttribute("aria-label", english ? "Close processing details" : "关闭处理详情");
  close.addEventListener("click", () => handlers.onClose?.());
  head.append(heading, close);
  const body = document.createElement("div");
  body.className = "workspace-side-sheet__body";

  if (options.mode === "recovery") {
    const preview = recoveryPreview(model.job, language);
    const intro = document.createElement("div");
    intro.className = "recovery-intro";
    const title = document.createElement("h3");
    title.textContent = preview.title;
    intro.appendChild(title);
    if (preview.eta) {
      const eta = document.createElement("p");
      eta.textContent = preview.eta;
      intro.appendChild(eta);
    }
    body.append(intro,
      section(english ? "Will reuse" : "将复用", preview.kept),
      section(english ? "Will run again" : "将重新执行", preview.rerun));
    if (preview.warning) {
      const warning = document.createElement("p");
      warning.className = "recovery-warning";
      warning.textContent = preview.warning;
      body.appendChild(warning);
    }
  } else if (options.mode === "preempt") {
    body.append(
      section(english ? "Current task" : "当前任务", [options.runningName || "—"]),
      section(english ? "What happens" : "将执行", [
        english ? "Pause at the existing safe checkpoint" : "在现有安全检查点暂停",
        english ? "Process this urgent item first" : "先处理这项急件",
        english ? "Resume the original task automatically afterward" : "急件完成后自动续跑原任务",
      ]));
    const note = document.createElement("p");
    note.className = "recovery-warning";
    note.textContent = english
      ? "Completed transcript, speaker, and visual checkpoints will be kept."
      : "已完成的逐字稿、说话人和画面检查点会被保留。";
    body.appendChild(note);
  } else {
    const list = document.createElement("ol");
    list.className = "job-phase-list";
    (model.progress.phases || []).forEach(phase => {
      const item = document.createElement("li");
      item.className = `phase-${phase.state || "pending"}`;
      if (["running", "recovering", "waiting_resource"].includes(phase.state)) item.setAttribute("aria-current", "step");
      const mark = document.createElement("span");
      mark.className = "job-phase-mark";
      mark.textContent = phase.state === "done" ? "✓" : phase.state === "failed" ? "×"
        : ["running", "recovering"].includes(phase.state) ? "●"
        : ["waiting_resource", "paused"].includes(phase.state) ? "Ⅱ"
        : phase.state === "degraded" ? "!" : phase.state === "cancelled" ? "–" : "○";
      const label = document.createElement("span");
      label.textContent = phaseLabel(phase.id, language);
      const value = document.createElement("span");
      value.textContent = phase.done != null && phase.total != null ? `${phase.done} / ${phase.total}`
        : phase.elapsed_seconds != null ? formatDuration(phase.elapsed_seconds, language)
        : phase.state === "pending" ? (english ? "Waiting" : "等待中") : "";
      item.append(mark, label, value);
      list.appendChild(item);
    });
    body.appendChild(list);
    if (model.progress.failure) {
      const explanation = document.createElement("p");
      explanation.className = "job-failure-explanation";
      explanation.textContent = failureReason(model.progress.failure, language);
      body.appendChild(explanation);
      const next = document.createElement("p");
      next.className = "job-recommended-action";
      next.textContent = `${english ? "Recommended next step" : "推荐下一步"}：${model.primary.label}`;
      body.appendChild(next);
      body.appendChild(section(english ? "Still available" : "仍可使用", model.outputs));
      body.appendChild(section(english ? "Not completed" : "尚未完成",
        (model.progress.failure.blocked_outputs || []).map(item => outputLabel(item, language))));
      const technical = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = english ? "Technical details" : "技术详情";
      const pre = document.createElement("pre");
      pre.textContent = diagnosticText(model.job);
      const copy = button(english ? "Copy diagnostics" : "复制诊断信息", "copy_diagnostics");
      copy.addEventListener("click", () => handlers.onCopyDiagnostics?.(model));
      technical.append(summary, pre, copy);
      body.appendChild(technical);
    }
    if ((model.job.attempt_history || []).length > 1) {
      const history = document.createElement("section");
      const title = document.createElement("h4");
      title.textContent = english ? "Attempts" : "处理尝试";
      history.appendChild(title);
      model.job.attempt_history.forEach(attempt => {
        const row = document.createElement("p");
        const status = {
          done: english ? "Completed" : "已完成",
          failed: english ? "Stopped" : "已停止",
          running: english ? "Running" : "处理中",
          recovering: english ? "Recovering" : "恢复中",
          paused: english ? "Paused" : "已暂停",
          cancelled: english ? "Cancelled" : "已取消",
        }[attempt.status] || (english ? "Waiting" : "等待中");
        const units = attempt.done != null && attempt.total != null
          ? ` · ${attempt.done} / ${attempt.total}` : "";
        row.textContent = `${english ? "Attempt" : "尝试"} ${attempt.attempt} · ${phaseLabel(attempt.phase, language)} · ${status}${units}`;
        history.appendChild(row);
      });
      body.appendChild(history);
    }
  }

  const foot = document.createElement("footer");
  if (options.mode === "recovery") {
    const preview = recoveryPreview(model.job, language);
    const back = button(english ? "Cancel" : "取消", "close");
    back.addEventListener("click", () => handlers.onClose?.());
    if (preview.canDegrade) {
      const degraded = button(english ? "Finish without remaining visuals" : "跳过剩余画面，生成语音版结果", "start_degraded");
      degraded.addEventListener("click", event => handlers.onStartDegraded?.(model, event.currentTarget));
      foot.appendChild(degraded);
    }
    const start = button(english ? "Start recovery" : "开始继续处理", "start_recovery", true);
    start.addEventListener("click", event => handlers.onStartRecovery?.(model, event.currentTarget));
    foot.append(back, start);
  } else if (options.mode === "preempt") {
    const back = button(english ? "Cancel" : "取消", "close");
    back.addEventListener("click", () => handlers.onClose?.());
    const start = button(english ? "Process now" : "立即处理", "start_preempt", true);
    start.addEventListener("click", event => handlers.onStartPreempt?.(model, event.currentTarget));
    foot.append(back, start);
  } else if ((model.state === "failed" || model.state === "paused")
      && model.job.recovery?.state === "available") {
    const recover = button(model.primary.label, "recovery", true);
    recover.addEventListener("click", () => handlers.onRecovery?.(model));
    foot.appendChild(recover);
  }
  sheet.append(head, body);
  if (foot.childElementCount) sheet.appendChild(foot);
  sheet.classList.remove("hidden");
  if (options.focus !== false) close.focus();
}

export function closeJobSheet(sheet) {
  sheet.classList.add("hidden");
  sheet.setAttribute("aria-hidden", "true");
  sheet.replaceChildren();
}
