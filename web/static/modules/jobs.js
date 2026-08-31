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

export function jobDisplayName(job, meetings, contentTypeOf) {
  const meeting = (meetings || []).find(item => item.slug === job?.meeting);
  return meeting?.title || job?.display_name || job?.meeting
    || (contentTypeOf(job) === "media" ? "媒体处理" : "会议处理");
}
