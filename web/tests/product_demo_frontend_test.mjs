import assert from "node:assert/strict";

import { normalizeDemoLanguage, resolveDemoState, segmentIsFocused }
  from "../static/product-demo.js";


assert.equal(normalizeDemoLanguage("en"), "en");
assert.equal(normalizeDemoLanguage("zh-CN"), "zh-CN");
assert.equal(normalizeDemoLanguage("fr"), "zh-CN");

const meeting = resolveDemoState("meeting", "maya", "en");
assert.equal(meeting.mode, "meeting");
assert.equal(meeting.selection, "maya");
assert.equal(meeting.values.selection, "Maya Chen");
assert.equal(meeting.values.time, "42:18");
assert.match(meeting.values.conclusion, /supplier validation/i);

const video = resolveDemoState("video", "materials", "zh-CN");
assert.equal(video.mode, "video");
assert.equal(video.selection, "materials");
assert.equal(video.values.selection, "材料与结构");
assert.equal(video.values.range, "05:48–07:02");

const fallback = resolveDemoState("unknown", "unknown", "unknown");
assert.equal(fallback.mode, "meeting");
assert.equal(fallback.selection, "maya");
assert.equal(fallback.language, "zh-CN");
assert.equal(segmentIsFocused("maya", "maya"), true);
assert.equal(segmentIsFocused("alex", "maya"), false);
assert.equal(Object.isFrozen(meeting), true);

console.log("product demo: bilingual fictional meeting/video state policy passed");
