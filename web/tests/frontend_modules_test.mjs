import assert from "node:assert/strict";
import { contentTypeOf, safeSourceUrl, sourcePublishedDate, sourceSearchText }
  from "../static/modules/media-source.js";
import { buildUploadFormData, enqueueMediaUrl, isSingleLocalVideo }
  from "../static/modules/imports.js";
import { jobDisplayName, selectJobPanel } from "../static/modules/jobs.js";

const media = {
  slug: "synthetic-media",
  title: "Synthetic Keynote",
  content_type: "media",
  source_info: {
    platform: "Example Video",
    publisher: "Example Publisher",
    published_at: "2026-08-20",
    canonical_url: "https://example.invalid/watch?v=synthetic",
  },
};
assert.equal(contentTypeOf(media), "media");
assert.equal(contentTypeOf({}), "meeting");
assert.equal(sourcePublishedDate(media), "2026-08-20");
assert.match(sourceSearchText(media), /Example Publisher/);
assert.equal(safeSourceUrl(media), "https://example.invalid/watch?v=synthetic");
assert.equal(safeSourceUrl({ source_info: { canonical_url: "file:///tmp/private" } }), "");

assert.equal(isSingleLocalVideo([{ name: "demo.mp4", type: "" }]), true);
assert.equal(isSingleLocalVideo([{ name: "audio.wav", type: "audio/wav" }]), false);
assert.equal(isSingleLocalVideo([{ name: "a.mp4" }, { name: "b.mp4" }]), false);
const form = buildUploadFormData([new Blob(["video"])], {
  contentType: "media", noVl: true, ignoreTranscript: false,
});
assert.equal(form.get("content_type"), "media");
assert.equal(form.get("no_vl"), "1");
assert.equal(form.has("ignore_transcript"), false);
let request = null;
const queued = await enqueueMediaUrl(async (path, options) => {
  request = { path, options };
  return { ok: true, json: async () => ({ id: "synthetic-job" }) };
}, "https://example.invalid/watch?v=synthetic", true);
assert.equal(request.path, "/api/import-url");
assert.equal(JSON.parse(request.options.body).no_vl, true);
assert.equal(queued.body.id, "synthetic-job");

const contentType = item => item.content_type === "media" ? "media" : "meeting";
const selected = selectJobPanel([
  { id: "running-meeting", status: "running", content_type: "meeting", meeting: "m1" },
  { id: "queued-media", status: "queued", queue_position: 2, content_type: "media" },
  { id: "failed-media", status: "failed", finished: 90, content_type: "media",
    recovery: { state: "available" } },
  { id: "failed-meeting", status: "failed", finished: 90, content_type: "meeting",
    recovery: { state: "available" } },
], "media", contentType, 100);
assert.deepEqual(selected.visibleJobs.map(item => item.id), ["queued-media", "failed-media"]);
assert.equal(selected.runningJob.id, "running-meeting");
assert.equal(jobDisplayName({ content_type: "media" }, [], contentType), "媒体处理");

console.log("frontend modules: source/import/job policies passed");
