#!/usr/bin/env node
// AI 输入框不依赖专用按钮：真实反馈中的自然语言必须识别为整篇重组。

import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const block = source.match(/function inferAssistantIntent\(message\) \{[\s\S]*?\n\}\n\nfunction assistantError/);
assert.ok(block, "inferAssistantIntent block not found");
const state = { assistantNextIntent: null };
eval(`${block[0].replace(/\n\nfunction assistantError$/, "")}\n` +
     "globalThis.__inferAssistantIntent = inferAssistantIntent;");

assert.equal(globalThis.__inferAssistantIntent(
  "总结有哪些重复，耗时间的工作，AI能帮助替代的。按照依次分享的顺序给出个人的发言总结，以及总体的结构、待办事项和关键结论。"
), "restructure");
assert.equal(globalThis.__inferAssistantIntent("这次确认了什么？"), "ask");
assert.equal(globalThis.__inferAssistantIntent("把总体摘要精简一些"), "edit");

console.log("Assistant intent: free-form ask/edit/restructure routing passed");
