#!/usr/bin/env node
// 说话人泳道/图例排序：已绑定者在前，未绑定/会议机沉底，两组内部都按发言时长降序。
// 全新会议（所有人都未绑定）时图例和泳道也必须按时长降序，而不是首次发言顺序。

import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const block = source.match(/function speakerOrderByShare\(\) \{[\s\S]*?\n\}\n/);
assert.ok(block, "speakerOrderByShare block not found");

const stats = new Map([["说话人2", 120], ["说话人1", 600], ["说话人3", 30]]);
globalThis.speakerStats = () => ({ stats, total: 750 });
const unboundNames = new Set(["说话人1", "说话人3"]);
globalThis.isUnboundSpeaker = name => unboundNames.has(name);

eval(`${block[0]}\nglobalThis.__speakerOrderByShare = speakerOrderByShare;`);

const { bound, unbound } = globalThis.__speakerOrderByShare();
assert.deepEqual(bound, ["说话人2"], "已绑定组按发言时长降序");
assert.deepEqual(unbound, ["说话人1", "说话人3"], "未绑定组内也必须按发言时长降序");

console.log("Speaker order: duration-desc within bound/unbound groups passed");
