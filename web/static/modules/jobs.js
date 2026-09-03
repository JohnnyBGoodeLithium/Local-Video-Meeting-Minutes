/* Job-panel selection policy. Rendering/actions stay in the application shell. */

export function selectJobPanel(jobs, contentType, contentTypeOf, now = Date.now() / 1000) {
  const all = Array.isArray(jobs) ? jobs : [];
  const allActiveJobs = all.filter(job => ["queued", "running"].includes(job.status))
    .sort((left, right) => left.status === right.status
      ? Number(left.queue_position || 9999) - Number(right.queue_position || 9999)
      : left.status === "running" ? -1 : 1);
  const jobsOfType = all.filter(job => contentTypeOf(job) === contentType);
  const activeJobs = allActiveJobs.filter(job => contentTypeOf(job) === contentType);
  const runningJob = allActiveJobs.find(job => job.status === "running") || null;
  const activeMeetings = new Set(activeJobs.map(job => job.meeting).filter(Boolean));
  const recoverableStops = jobsOfType.filter(job => ["failed", "paused"].includes(job.status)
    && job.recovery?.state !== "recovered"
    && !activeMeetings.has(job.meeting)
    && (job.recovery?.state === "available"
      || now - Number(job.finished || job.created || 0) < 60 * 60)).slice(0, 2);
  const degradedStops = jobsOfType.filter(job => job.progress?.state === "degraded"
    && now - Number(job.finished || job.created || 0) < 60 * 60).slice(0, 1);
  const visibleJobs = [...activeJobs, ...recoverableStops, ...degradedStops]
    .filter((job, index, visible) => visible.findIndex(item => item.id === job.id) === index);
  return { allActiveJobs, activeJobs, runningJob, visibleJobs };
}

export function jobDisplayName(job, meetings, contentTypeOf, language = "zh-CN") {
  const meeting = (meetings || []).find(item => item.slug === job?.meeting);
  return meeting?.title || job?.display_name || job?.meeting
    || (contentTypeOf(job) === "media"
      ? (language === "en" ? "Media processing" : "媒体处理")
      : (language === "en" ? "Meeting processing" : "会议处理"));
}

function languageName(target, language) {
  const english = language === "en";
  if (target === "en") return english ? "English" : "英文";
  if (target === "zh-CN") return english ? "Chinese" : "中文";
  return english ? "the selected language" : "所选语言";
}

/** 用户可理解的作业动作；不能让队列只剩一串相同的会议标题。 */
export function jobTaskLabel(job = {}, language = "zh-CN") {
  const english = language === "en";
  const target = languageName(job.target_language, language);
  if (job.kind === "translation") {
    const artifact = job.translation_artifact || "transcript";
    const labels = {
      transcript: english ? `Translate transcript to ${target}` : `将逐字稿翻译为${target}`,
      minutes: english ? `Translate minutes to ${target}` : `将会议纪要翻译为${target}`,
      topic_map: english ? `Translate meeting map to ${target}` : `将会议脉络翻译为${target}`,
      visuals: english ? `Translate visual notes to ${target}` : `将画面解读翻译为${target}`,
    };
    const label = labels[artifact] || (english ? `Translate content to ${target}` : `生成${target}译文`);
    return job.auto ? (english ? `Automatic · ${label}` : `自动补充 · ${label}`) : label;
  }
  if (job.kind === "topic_map") return english ? "Build meeting map" : "构建会议脉络";
  if (job.kind === "keywords") return english ? "Extract meeting keywords" : "提取会议关键字";
  if (job.kind === "retranscribe") return english ? "Run speech recognition again" : "重新进行语音识别";
  if (job.kind === "photo_analysis") return english ? "Analyze meeting materials" : "分析现场资料";
  if (job.kind === "photo_minutes_sync") return english ? "Update minutes with meeting materials" : "将现场资料同步到纪要";
  if (job.kind === "orgchart_extract") return english ? "Read participant information" : "读取参会者信息";
  if (job.kind === "regen") {
    if (job.sync_mode === "fast") return english ? "Quick-sync minutes" : "快速同步会议纪要";
    if (job.upgrade_mode === "visual") return english ? "Add visual analysis" : "补充画面分析";
    return english ? "Generate minutes again" : "重新生成会议纪要";
  }
  if (job.kind === "upload") {
    if (job.route === "media_url") return english ? "Save and analyze public media" : "获取并分析公开视频";
    if (job.route === "audio") return english ? "Process audio meeting" : "处理录音会议";
    if (job.content_type === "media") return english ? "Analyze local media" : "分析本地视频";
    const mode = job.processing_mode === "fast"
      ? (english ? "quick minutes" : "快速纪要")
      : (english ? "full analysis" : "完整分析");
    if (job.route === "teams") return english ? `Process Teams meeting · ${mode}` : `处理 Teams 会议 · ${mode}`;
    return english ? `Process video meeting · ${mode}` : `处理会议录像 · ${mode}`;
  }
  return english ? "Process meeting content" : "处理会议资料";
}
