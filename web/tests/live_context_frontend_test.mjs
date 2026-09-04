import assert from "node:assert/strict";
import fs from "node:fs";
import { createLiveContextState, defaultLiveMode, livePersonFocusNavigation,
  normalizeLiveWorkspace, selectLiveContentType, selectLiveMode }
  from "../static/modules/live-context.js";

assert.equal(defaultLiveMode("live_event"), "analyze_background");
assert.equal(defaultLiveMode("meeting"), "meeting_companion");

let state = createLiveContextState("live_event");
assert.equal(state.mode, "analyze_background");
state = selectLiveMode(state, "watch_analyze");
assert.equal(state.mode, "watch_analyze");
state = selectLiveContentType(state, "meeting");
assert.equal(state.mode, "meeting_companion");
state = selectLiveMode(state, "manual");
assert.equal(state.mode, "manual");
assert.throws(() => selectLiveMode(state, "watch_analyze"));

const focus = livePersonFocusNavigation([
  { start: 0, end: 4, speaker: "Speaker A" },
  { start: 4, end: 8, speaker: "Speaker B" },
  { start: 8, end: 12, speaker: "Speaker A" },
], 12, "Speaker A", 0, 1);
assert.deepEqual(focus.indexes, [0, 2]);
assert.equal(focus.target, 2);

const workspace = normalizeLiveWorkspace({
  schema: "meeting-live-workspace/v1",
  session: {id: "live-synthetic", state: "LIVE"},
  source: {source_kind: "hls", display_url: "https://example.invalid/live"},
  transcript: {total_turns: 3, truncated: true, turns: [
    {start: 2, end: 4, speaker: "Speaker A", text: "Synthetic statement."},
  ]},
  takeaways: {state: "ready", items: [{text: "Provisional point", start: 2}]},
});
assert.equal(workspace.source.displayUrl, "https://example.invalid/live");
assert.equal(workspace.transcript.totalTurns, 3);
assert.equal(workspace.transcript.turns[0].text, "Synthetic statement.");
assert.equal(workspace.takeaways.items[0].text, "Provisional point");

const html = fs.readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
assert.match(html, /id="live-context-entry"[^>]*hidden/);
assert.match(html, /name="live-content-type"[^>]*value="live_event"[^>]*checked/);
assert.match(html, /id="live-mode-options"/);
assert.match(html, /aria-labelledby="live-context-title"/);
assert.match(html, /id="live-open-source"/);
assert.match(html, /id="live-workspace"/);
assert.match(html, /id="live-transcript-list"/);
assert.match(html, /id="live-takeaways-title"/);
assert.match(html, /id="live-workspace-stop-confirm"/);

const view = fs.readFileSync(new URL("../static/modules/live-context-view.js", import.meta.url), "utf8");
assert.match(view, /No playback required/);
assert.match(view, /listens quietly in the background/);
assert.match(view, /analysis has not started/);
assert.doesNotMatch(view, /\.play\s*\(/);
assert.match(view, /\/api\/live\/probe/);
assert.match(view, /\/api\/live\/sessions/);
assert.match(view, /\/workspace/);
assert.match(view, /Live takeaways \(provisional\)/);
const closeBody = view.match(/function close\(\) \{([\s\S]*?)\n  \}/)?.[1] || "";
assert.doesNotMatch(closeBody, /stop|DELETE|POST/);

console.log("live context frontend: defaults, bilingual copy and no-playback contract passed");
