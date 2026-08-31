import assert from "node:assert/strict";
import {
  beginIdentity, beginExampleSelection, buildCorrectionApplyPayload,
  correctionSummary, createSpeakerCorrectionState, normalizeCorrectionPreview,
  representativeTurns, setGroupAssignment, setIncludeSuggested, setPreview, toggleExample,
  withCorrectionError,
} from "../static/modules/speaker-correction.js";

const transcript = [
  { voice: "source", speaker: "张三", start: 0, end: 12, text: "opening" },
  { voice: "other", speaker: "Other", start: 12, end: 16, text: "other" },
  { voice: "source", speaker: "张三", start: 20, end: 44, text: "middle long" },
  { voice: "source", speaker: "张三", start: 60, end: 66, text: "wrong one" },
  { voice: "source", speaker: "张三", start: 90, end: 108, text: "wrong two" },
  { voice: "source", speaker: "张三", start: 120, end: 130, text: "ending" },
];

let state = beginIdentity(createSpeakerCorrectionState(), {
  voice: "source", displayName: "张三", playbackTime: 33,
  scrollAnchor: { id: "turn-2", offset: 12 },
});
assert.equal(state.mode, "identify");
state = beginExampleSelection(state);
state = toggleExample(state, 3);
state = toggleExample(state, 4);
assert.deepEqual([...state.selectedTurnIndexes], [3, 4]);

const raw = {
  selected: [3, 4], suggested: [5], protected: [0], ambiguous: [2],
  groups: [
    { group_key: "group-1", selected: [3], suggested: [5], duration: 16,
      representative_turns: [3, 5], suggested_person: "李四" },
    { group_key: "group-2", selected: [4], suggested: [], duration: 18,
      representative_turns: [4], evidence_limited: true },
  ],
};
const normalized = normalizeCorrectionPreview(raw, transcript);
assert.equal(normalized.groups.length, 2);
state = setPreview(state, raw, transcript);
assert.equal(state.includeSuggested, false, "默认只处理手选片段");
state = setGroupAssignment(state, "group-2", { name: "王五", create: false });
let summary = correctionSummary(state, transcript);
assert.equal(summary.moved, 2);
assert.equal(summary.protected, 1);
state = setIncludeSuggested(state, true);
summary = correctionSummary(state, transcript);
assert.equal(summary.moved, 3);
const payload = buildCorrectionApplyPayload(state);
assert.equal(payload.expand_similar, true);
assert.equal(payload.group_assignments["group-1"].name, "李四");
assert.equal(payload.group_assignments["group-2"].name, "王五");
state = setGroupAssignment(state, "group-2", { name: "", create: false });
assert.equal(buildCorrectionApplyPayload(state).group_assignments["group-2"].name, "",
  "每个结果组可以独立保持未命名");
assert.equal(representativeTurns(transcript, "source", 3).length, 3);

const failed = withCorrectionError(state, "preview unavailable");
assert.deepEqual([...failed.selectedTurnIndexes], [3, 4], "API 失败后保留手选样例");
const direct = normalizeCorrectionPreview({
  selected: [3], suggested: [], protected: [0], ambiguous: [], direct_only: true,
  groups: [{ group_key: "group-1", selected: [3], evidence_limited: true }],
}, transcript);
assert.equal(direct.directOnly, true);
assert.deepEqual(direct.groups[0].selectedTurns, [3]);

console.log("speaker correction frontend state: conservative multi-group flow passed");
