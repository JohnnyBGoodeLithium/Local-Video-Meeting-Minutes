import assert from "node:assert/strict";
import { contentTypeOf, safeSourceUrl, sourcePublishedDate, sourceSearchText }
  from "../static/modules/media-source.js";
import { buildUploadFormData, enqueueMediaUrl, isSingleLocalVideo }
  from "../static/modules/imports.js";
import { jobDisplayName, selectJobPanel } from "../static/modules/jobs.js";
import { chooseInitialItem, deepLinkSeconds, filterLibrary, sortLibrary }
  from "../static/modules/library.js";
import { adjacentReviewUnit, defaultReviewUnits, nearestReviewUnit,
  reviewIndexesFor, reviewUnitForTurn, turnEnd }
  from "../static/modules/player-navigation.js";
import { nextSearchCursor, pendingReviewByTurn, splitTurnChunks, transcriptSearchHits,
  turnReviewUnits }
  from "../static/modules/transcript.js";
import { renderTranscriptView, transcriptScrollAnchor }
  from "../static/modules/transcript-view.js";
import { exportSizeState, formatBytes, meetingExportHref, normalizeExportProfile,
  packExportHref }
  from "../static/modules/export.js";
import { claimAction, claimIdsForTurn, evidenceSources, minutesState, normalizeReviewMode,
  resolveMinutesClaim, resolveMinutesView, turnIndexAtTime, turnIndexesForSourceIds }
  from "../static/modules/minutes.js";
import { renderMinutesView } from "../static/modules/minutes-view.js";

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

const library = [
  { slug: "older", title: "Older meeting", imported_at: 10, date: "2026-08-01" },
  { ...media, imported_at: 30 },
  { slug: "newer", title: "Newer meeting", imported_at: 20, date: "2026-08-22" },
];
assert.deepEqual(sortLibrary(library).map(item => item.slug),
  ["synthetic-media", "newer", "older"]);
assert.deepEqual(filterLibrary(library, { contentType: "media", query: "publisher" })
  .map(item => item.slug), ["synthetic-media"]);
assert.equal(chooseInitialItem(library, { remembered: "older", contentType: "media" }).slug,
  "older");
assert.equal(chooseInitialItem(library, { linked: "missing", contentType: "media" }).slug,
  "synthetic-media");
assert.equal(deepLinkSeconds("12.5", 30), 12.5);
assert.equal(deepLinkSeconds("31", 30), null);

const transcript = [
  { start: 0, end: 8, speaker: "Alice" },
  { start: 8, end: 15, speaker: "Bob" },
  { start: 15, speaker: "Alice" },
];
const units = defaultReviewUnits(transcript, 20);
assert.equal(turnEnd(transcript, 20, 2), 20);
assert.deepEqual(reviewIndexesFor(units, "Alice"), [0, 2]);
assert.equal(reviewUnitForTurn(units, 1, 10), 1);
assert.equal(nearestReviewUnit(units, [0, 2], 10), 2);
assert.equal(adjacentReviewUnit([0, 2], 0, 1), 2);
assert.equal(adjacentReviewUnit([0, 2], 2, 1), null);

assert.deepEqual(transcriptSearchHits([
  { text: "Quarterly margin review" }, { text: "Supply update" }, { text: "MARGIN action" },
], " margin "), [0, 2]);
assert.equal(nextSearchCursor(-1, 3, 1), 0);
assert.equal(nextSearchCursor(0, 3, -1), 2);
const chunks = splitTurnChunks("第一句。第二句。第三句。", 120, 4, 20);
assert.equal(chunks.length, 3);
const chunkUnits = turnReviewUnits(
  { start: 10, text: "第一句。第二句。第三句。", speaker: "Alice" }, 4, 130, chunks, 7);
assert.deepEqual(chunkUnits.map(unit => unit.index), [7, 8, 9]);
assert.equal(chunkUnits[0].start, 10);
assert.equal(chunkUnits.at(-1).end, 130);
assert.equal(pendingReviewByTurn({ pending: [
  { turn_index: 2, suggested_text: "synthetic" }, { turn_index: "3" },
] }).size, 1);
assert.equal(typeof renderTranscriptView, "function");
assert.equal(typeof transcriptScrollAnchor, "function");

assert.equal(normalizeExportProfile("unknown"), "full");
assert.equal(formatBytes(2 * 1024 * 1024), "2.0 MB");
assert.deepEqual(exportSizeState({ estimated_bytes: { video: 40 * 1024 * 1024 } },
  "full", "video"), {
  profile: "full", media: "video", estimatedBytes: 40 * 1024 * 1024, oversized: true,
});
assert.equal(exportSizeState({}, "kb", "video").media, "none");
assert.equal(meetingExportHref("synthetic meeting", "audio", "full"),
  "/api/meetings/synthetic%20meeting/export?media=audio&profile=full");
assert.match(packExportHref(["one", "two"], "video", "kb-html"),
  /slugs=one%2Ctwo&media=video&profile=kb-html$/);

const minutesView = { id: "ai-brief", title: "Brief", sources: [
  { claim_id: "A1", start: 12 },
] };
assert.deepEqual(resolveMinutesView([minutesView], "ai-brief"), {
  id: "ai-brief", view: minutesView, reset: false,
});
assert.deepEqual(resolveMinutesView([minutesView], "missing"), {
  id: "standard", view: null, reset: true,
});
const evidence = {
  state: "ready",
  claims: [{ id: "C1", kind: "action", turn_indexes: [1], page_ids: ["P2"] }],
  actions: [{ claim_id: "C1", text: "Synthetic action" }],
  action_candidates: [{ text: "Candidate" }],
  sources: { transcript: [{ id: "T1", index: 1 }] },
};
const stateReady = minutesState({ has_minutes: true, evidence }, null,
  { target_language: "en", state: "ready", html: "<p>English</p>" }, "en", false);
assert.equal(stateReady.canRestructure, true);
assert.equal(stateReady.translatedHtml, "<p>English</p>");
assert.equal(stateReady.actionCandidates.length, 1);
assert.equal(minutesState({ document_state: "draft", has_minutes: true, evidence },
  null, null, "en").canRestructure, false);
assert.deepEqual(turnIndexesForSourceIds(evidence.sources.transcript, ["T1"]), [1]);
assert.equal(turnIndexAtTime([{ start: 0 }, { start: 10 }, { start: 20 }], 15), 1);
assert.deepEqual(claimIdsForTurn(evidence.claims, 1), ["C1"]);
assert.equal(resolveMinutesClaim(evidence, minutesView, "C1").canonical, true);
assert.equal(resolveMinutesClaim(evidence, minutesView, "A1").claim.start, 12);
assert.equal(claimAction(evidence, evidence.claims[0]).text, "Synthetic action");
const evidenceBundle = {
  transcript: [{ start: 0 }, { start: 10, speaker: "Alice" }],
  slides: [{ page: 2, first: 14 }],
};
assert.equal(evidenceSources(evidenceBundle, evidence.claims[0]).firstTime, 10);
assert.equal(normalizeReviewMode("chapters", { transcript: [] }), "minutes");
assert.equal(normalizeReviewMode("quality", {}), "quality");
assert.equal(typeof renderMinutesView, "function");

console.log("frontend modules: source/import/job/library/player/transcript-view/export/minutes-view policies passed");
