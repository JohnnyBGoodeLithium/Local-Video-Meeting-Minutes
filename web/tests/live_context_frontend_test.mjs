import assert from "node:assert/strict";
import fs from "node:fs";
import { createLiveContextState, defaultLiveMode, selectLiveContentType, selectLiveMode }
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

const html = fs.readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
assert.match(html, /id="live-context-entry"[^>]*hidden/);
assert.match(html, /name="live-content-type"[^>]*value="live_event"[^>]*checked/);
assert.match(html, /id="live-mode-options"/);
assert.match(html, /aria-labelledby="live-context-title"/);

const view = fs.readFileSync(new URL("../static/modules/live-context-view.js", import.meta.url), "utf8");
assert.match(view, /No playback required/);
assert.match(view, /listens quietly in the background/);
assert.doesNotMatch(view, /\.play\s*\(/);

console.log("live context frontend: defaults, bilingual copy and no-playback contract passed");
