/* Pure projection for job-progress/v2. No DOM, API, or application state. */

const PHASE_COPY = {
  prepare: ["准备资料", "Preparing materials"],
  download: ["获取并保存媒体", "Saving media"],
  speech_processing: ["处理语音与发言人", "Processing speech and speakers"],
  teams_alignment: ["区分发言人并对齐 Teams 文稿", "Aligning speakers with the Teams transcript"],
  voice_draft: ["生成语音草稿", "Generating the voice draft"],
  visual_extraction: ["提取共享画面", "Extracting shared visuals"],
  visual_understanding: ["理解共享画面", "Understanding shared visuals"],
  final_minutes: ["生成正式纪要", "Generating final minutes"],
  topic_map: ["构建会议脉络", "Building the meeting map"],
  retranscribe_prepare: ["检查已有母版", "Checking the saved source"],
  retrieval: ["建立检索资料", "Building retrieval material"],
};

const OUTPUT_COPY = {
  transcript: ["逐字稿", "transcript"],
  speaker_navigation: ["说话人导航", "speaker navigation"],
  voice_draft: ["语音草稿", "voice draft"],
  visuals: ["已完成的画面", "completed visuals"],
  final_minutes: ["正式纪要", "final minutes"],
  topic_map: ["会议脉络", "meeting map"],
  retrieval: ["检索资料", "retrieval material"],
};

const FAILURE_COPY = {
  input_invalid: ["输入资料无法读取", "The input could not be read"],
  resource_insufficient: ["本机资源不足", "Local resources were insufficient"],
  service_unavailable: ["所需的本地服务暂时不可用", "A required local service is unavailable"],
  capability_missing: ["当前服务缺少这一步所需能力", "The current service lacks a required capability"],
  stage_processing_failed: ["这一处理步骤没有完成", "This processing step did not finish"],
  revision_conflict: ["会议内容已变化，旧任务不能直接覆盖", "The meeting changed and the old task cannot overwrite it"],
  download_or_network_failed: ["媒体下载或网络访问中断", "Media download or network access failed"],
  cancelled_or_paused: ["任务已暂停，已完成结果仍被保留", "The task paused and completed results were kept"],
  unknown_internal: ["系统未能安全判断具体原因", "The exact cause could not be classified safely"],
};

const RETRY_ORDER = {
  resume: 1, retry_stage: 2, low_resource: 3, degraded_continue: 4,
  resume_high: 5, restart: 6, reimport: 7,
};

const pick = (pair, language) => pair?.[language === "en" ? 1 : 0] || "";

export function isStructuredProgress(progress) {
  return progress?.schema === "job-progress/v2";
}

export function phaseLabel(phase, language = "zh-CN") {
  return pick(PHASE_COPY[phase] || ["处理资料", "Processing"], language);
}

export function formatDuration(seconds, language = "zh-CN") {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  if (value < 60) return language === "en" ? `${value}s` : `${value} 秒`;
  const minutes = Math.round(value / 60);
  if (minutes < 60) return language === "en" ? `${minutes} min` : `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return language === "en" ? `${hours} hr ${rest} min` : `${hours} 小时 ${rest} 分钟`;
}

export function formatEtaRange(eta, language = "zh-CN") {
  if (!eta?.low_seconds || !eta?.high_seconds) return "";
  const low = Math.max(1, Math.round(eta.low_seconds / 60));
  const high = Math.max(low + 1, Math.round(eta.high_seconds / 60));
  return language === "en" ? `about ${low}–${high} min remaining` : `预计还需 ${low}–${high} 分钟`;
}

export function normalizeProgress(job = {}) {
  const progress = job.progress || {};
  if (isStructuredProgress(progress)) return progress;
  return {
    schema: "job-progress/v2", source: "legacy_estimate", route: job.route || job.kind || "unknown",
    state: job.status || "queued", phase: "prepare", phase_index: 0, phase_count: 1,
    done: Number(progress.done) || null, total: Number(progress.total) || null,
    available_outputs: {}, estimated_first_usable: null, estimated_remaining: null,
    phases: [{ id: "prepare", label_key: "progress.prepare", state: job.status || "pending" }],
    failure: null, attempt: Math.max(1, Number(job.recovery_attempt || 0) + 1),
  };
}

export function availableOutputLabels(progress, language = "zh-CN") {
  return Object.entries(progress?.available_outputs || {})
    .filter(([, state]) => ["ready", "partial"].includes(state))
    .map(([id, state]) => `${pick(OUTPUT_COPY[id], language)}${state === "partial"
      ? (language === "en" ? " (partial)" : "（部分）") : ""}`);
}

export function outputLabel(output, language = "zh-CN") {
  return pick(OUTPUT_COPY[output] || [output, output], language);
}

export function sortedRetryOptions(progress) {
  return [...(progress?.failure?.retry_options || [])]
    .sort((left, right) => (RETRY_ORDER[left.action] || 99) - (RETRY_ORDER[right.action] || 99));
}

function progressUnits(progress, language) {
  if (!Number.isFinite(Number(progress?.total)) || Number(progress.total) <= 0) return "";
  const done = Math.max(0, Number(progress.done) || 0);
  const unit = progress.unit === "pages" ? (language === "en" ? "visuals" : "个画面")
    : progress.unit === "windows" ? (language === "en" ? "sections" : "个区段")
    : progress.unit === "batches" ? (language === "en" ? "batches" : "个批次") : "";
  return `${done} / ${progress.total}${unit ? ` ${unit}` : ""}`;
}

function recoveryLabel(job, progress, language) {
  const mode = job.recovery?.mode;
  const next = Number(progress?.failure?.completed_units);
  if (mode === "minutes" && progress.phase === "visual_understanding" && Number.isFinite(next)) {
    return language === "en" ? `Continue from visual ${next + 1}` : `从第 ${next + 1} 个画面继续`;
  }
  const labels = {
    minutes: ["从已保存资料继续", "Continue from saved materials"],
    speaker_resume: ["从已完成的语音识别继续", "Continue from completed speech recognition"],
    retranscribe: ["重新运行语音识别", "Run speech recognition again"],
    topic_map: ["重新构建会议脉络", "Rebuild the meeting map"],
    translation: ["重新生成译文", "Generate the translation again"],
  };
  return pick(labels[mode] || ["查看恢复方式", "Review recovery options"], language);
}

export function jobPresentation(job, displayName, language = "zh-CN") {
  const progress = normalizeProgress(job);
  const state = progress.state || job.status;
  const phase = phaseLabel(progress.phase, language);
  const units = progressUnits(progress, language);
  const eta = formatEtaRange(progress.estimated_remaining, language);
  const outputs = availableOutputLabels(progress, language);
  const voiceDraft = progress.available_outputs?.voice_draft === "ready";
  const transcript = progress.available_outputs?.transcript === "ready";
  const failure = progress.failure || null;
  let headline = phase;
  let detail = [units, eta].filter(Boolean).join(" · ");
  let tone = "working";
  let primary = { id: "details", label: language === "en" ? "Details" : "查看详情" };

  if (state === "queued") {
    headline = job.queue_position ? (language === "en" ? `Queue position ${job.queue_position}` : `队列第 ${job.queue_position}`)
      : (language === "en" ? "Waiting to start" : "等待处理");
    detail = "";
    tone = "neutral";
  } else if (state === "waiting_resource") {
    headline = language === "en" ? "Waiting for compute resources" : "正在等待计算资源";
    detail = outputs.length ? `${language === "en" ? "Kept" : "已保留"}：${outputs.join("、")}` : "";
    tone = "warning";
    primary = { id: "check", label: language === "en" ? "Check now" : "立即再检查" };
  } else if (state === "failed") {
    headline = language === "en" ? `${phase} did not finish` : `${phase}没有完成`;
    const reason = pick(FAILURE_COPY[failure?.category] || FAILURE_COPY.unknown_internal, language);
    detail = outputs.length
      ? `${reason}${language === "en" ? ". Kept: " : "。已保留："}${outputs.join(language === "en" ? ", " : "、")}`
      : reason;
    tone = "danger";
    const blockedActions = {
      input_invalid: ["reimport", "更换源文件", "Choose another file"],
      resource_insufficient: ["storage", "打开存储与清理", "Open storage and cleanup"],
      capability_missing: ["settings", "更换处理服务", "Change processing service"],
      revision_conflict: ["open_result", "查看最新内容", "Open the latest content"],
      download_or_network_failed: ["reimport_url", "修改链接", "Edit the source URL"],
    };
    const blocked = blockedActions[failure?.category];
    primary = job.recovery?.state === "available"
      ? { id: "recovery", label: recoveryLabel(job, progress, language) }
      : blocked ? { id: blocked[0], label: language === "en" ? blocked[2] : blocked[1] }
        : { id: "details", label: language === "en" ? "What to do next" : "查看解决方式" };
  } else if (state === "paused") {
    headline = language === "en" ? "Paused at a safe checkpoint" : "已在安全检查点暂停";
    detail = outputs.length ? `${language === "en" ? "Kept" : "已保留"}：${outputs.join("、")}` : "";
    tone = "warning";
    primary = { id: "recovery", label: recoveryLabel(job, progress, language) };
  } else if (state === "recovering") {
    headline = language === "en" ? `Recovering: ${phase}` : `正在恢复：${phase}`;
    tone = "working";
  } else if (state === "degraded") {
    headline = language === "en" ? "Main result ready with an optional enhancement missing" : "主要结果已完成，部分增强未生成";
    tone = "warning";
  } else if (state === "done") {
    headline = language === "en" ? "Processing complete" : "处理完成";
    detail = job.started && job.finished
      ? `${language === "en" ? "Total" : "总耗时"} ${formatDuration(job.finished - job.started, language)}` : "";
    tone = "success";
  } else if (voiceDraft) {
    headline = language === "en" ? "Voice draft ready — you can start reviewing" : "语音草稿已就绪，可以先行回顾";
    detail = [phase, units, eta ? `${language === "en" ? "full result" : "完整结果"} ${eta}` : ""]
      .filter(Boolean).join(" · ");
    primary = { id: "open_draft", label: language === "en" ? "Open voice draft" : "打开语音草稿" };
  } else if (transcript) {
    headline = language === "en" ? `Transcript ready · ${phase}` : `逐字稿已就绪 · ${phase}`;
  } else {
    headline = language === "en" ? `In progress: ${phase}` : `正在${phase}`;
    const first = formatEtaRange(progress.estimated_first_usable, language);
    detail = first ? `${language === "en" ? "First readable result" : "第一份可读结果"} ${first}`
      : (language === "en" ? "Estimating time to the first readable result" : "正在估算第一份可读结果所需时间");
  }

  return {
    job, progress, name: displayName, state, phase, headline, detail, tone, primary,
    units, eta, outputs, legacy: progress.source === "legacy_estimate",
    ratio: Number(progress.total) > 0 ? Math.min(1, Math.max(0, Number(progress.done || 0) / Number(progress.total))) : null,
  };
}

export function recoveryPreview(job, language = "zh-CN") {
  const progress = normalizeProgress(job);
  const failure = progress.failure || {};
  const kept = availableOutputLabels(progress, language);
  const phase = phaseLabel(progress.phase, language);
  const total = Number(failure.total_units);
  const done = Number(failure.completed_units);
  const remaining = Number.isFinite(total) && Number.isFinite(done) && total > done
    ? `${total - done} ${language === "en" ? "remaining units" : "个剩余单元"}` : phase;
  return {
    title: recoveryLabel(job, progress, language),
    kept,
    rerun: [remaining, language === "en" ? "Final minutes and downstream meeting map" : "正式纪要及后续会议脉络"],
    eta: formatEtaRange(progress.estimated_remaining, language),
    warning: job.recovery?.mode === "retranscribe"
      ? (language === "en" ? "This replaces the canonical transcript after creating a recoverable snapshot."
        : "这会在创建可恢复快照后替换正式逐字稿。") : "",
    canDegrade: sortedRetryOptions(progress).some(option => option.action === "degraded_continue"),
  };
}

export function diagnosticText(job) {
  const progress = normalizeProgress(job);
  const failure = progress.failure || {};
  return JSON.stringify({
    schema: progress.schema, diagnostic_id: failure.diagnostic_id || null,
    error_code: failure.code || null, exception_type: failure.technical?.exception_type || null,
    phase: progress.phase || null, attempt: progress.attempt || 1,
    route: progress.route || job.route || null, content_type: job.content_type || null,
    done: progress.done ?? null, total: progress.total ?? null,
  }, null, 2);
}
