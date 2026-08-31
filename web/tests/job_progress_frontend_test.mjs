import assert from "node:assert/strict";
import {
  availableOutputLabels, diagnosticText, formatDuration, formatEtaRange,
  jobPresentation, normalizeProgress, phaseLabel, recoveryPreview, sortedRetryOptions,
} from "../static/modules/job-progress.js";

const progress = {
  schema: "job-progress/v2", source: "structured", route: "teams", state: "running",
  phase: "visual_understanding", done: 12, total: 36, unit: "pages", attempt: 1,
  estimated_first_usable: null,
  estimated_remaining: { low_seconds: 1080, high_seconds: 1560, confidence: "medium" },
  available_outputs: {
    transcript: "ready", speaker_navigation: "ready", voice_draft: "ready",
    visuals: "partial", final_minutes: "pending", topic_map: "pending", retrieval: "pending",
  },
  phases: [
    { id: "prepare", state: "done", elapsed_seconds: 18 },
    { id: "teams_alignment", state: "done", elapsed_seconds: 130 },
    { id: "voice_draft", state: "done", elapsed_seconds: 156 },
    { id: "visual_understanding", state: "running", done: 12, total: 36 },
  ],
  failure: null,
};
const job = { id: "fixture", kind: "upload", route: "teams", status: "running", progress };

assert.equal(phaseLabel("visual_understanding", "zh-CN"), "理解共享画面");
assert.equal(phaseLabel("visual_understanding", "en"), "Understanding shared visuals");
assert.equal(formatEtaRange(progress.estimated_remaining, "zh-CN"), "预计还需 18–26 分钟");
assert.equal(formatDuration(130, "en"), "2 min");
assert.deepEqual(availableOutputLabels(progress, "en"), [
  "transcript", "speaker navigation", "voice draft", "completed visuals (partial)",
]);

const zh = jobPresentation(job, "Synthetic Review", "zh-CN");
assert.match(zh.headline, /语音草稿已就绪/);
assert.match(zh.detail, /完整结果 预计还需 18–26 分钟/);
assert.equal(zh.ratio, 1 / 3);
const en = jobPresentation(job, "Synthetic Review", "en");
assert.match(en.headline, /Voice draft ready/);

const failedProgress = structuredClone(progress);
failedProgress.state = "failed";
failedProgress.failure = {
  code: "VISUAL_MODEL_START_FAILED", category: "service_unavailable",
  completed_units: 12, total_units: 36, diagnostic_id: "ERR-A1B2C3",
  technical: { exception_type: "ModelServiceUnavailable" },
  retry_options: [
    { action: "resume_high" }, { action: "resume" }, { action: "degraded_continue" },
  ],
};
const failedJob = { ...job, status: "failed", recovery: { state: "available", mode: "minutes" },
  progress: failedProgress, content_type: "meeting" };
const failed = jobPresentation(failedJob, "Synthetic Review", "zh-CN");
assert.equal(failed.primary.label, "从第 13 个画面继续");
assert.deepEqual(sortedRetryOptions(failedProgress).map(option => option.action),
  ["resume", "degraded_continue", "resume_high"]);
const preview = recoveryPreview(failedJob, "en");
assert.match(preview.title, /visual 13/);
assert.ok(preview.kept.includes("transcript"));
const diagnostic = diagnosticText(failedJob);
assert.match(diagnostic, /ERR-A1B2C3/);
assert.doesNotMatch(diagnostic, /Synthetic Review/);

const legacy = normalizeProgress({ status: "running", progress: { done: 3, total: 9 } });
assert.equal(legacy.source, "legacy_estimate");
assert.equal(legacy.done, 3);

const draftFailed = structuredClone(progress);
draftFailed.available_outputs.voice_draft = "failed";
draftFailed.available_outputs.final_minutes = "pending";
const draftFailedPresentation = jobPresentation({ ...job, progress: draftFailed },
  "Synthetic Review", "zh-CN");
assert.doesNotMatch(draftFailedPresentation.headline, /语音草稿已就绪/);

console.log("Job progress frontend: bilingual projection, ETA, recovery, and diagnostics passed");
