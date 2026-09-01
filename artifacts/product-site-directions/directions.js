const params = new URLSearchParams(location.search);
const directions = new Set(["splice", "dossier", "cue"]);
const direction = directions.has(params.get("direction")) ? params.get("direction") : "splice";
const language = params.get("lang") === "en" ? "en" : "zh-CN";

const directionNames = {
  splice: {"zh-CN": "证据剪接", en: "Evidence Splice"},
  dossier: {"zh-CN": "核证折页", en: "Source Fold"},
  cue: {"zh-CN": "声画同帧", en: "Sound / Frame Cue"},
};

const copy = {
  studyLabel: {"zh-CN": "视觉方向探索", en: "Art direction study"},
  kicker: {"zh-CN": "会议与视频回顾", en: "Meeting & video review"},
  heroTitle: {"zh-CN": "两小时会议，不该再花两小时复盘。", en: "A two-hour meeting shouldn't take two hours to review."},
  heroBody: {"zh-CN": "会议从人物开始，视频从议题开始。找到真正相关的片段，再让重要结论回到原声、时间和当时画面。", en: "Start meetings with people and video with topics. Find the moments that matter, then return every important conclusion to the original words, time, and screen."},
  fictional: {"zh-CN": "虚构演示", en: "Fictional demo"},
  meetingEntry: {"zh-CN": "会议 · 按人物进入", en: "Meeting · start with a person"},
  videoEntry: {"zh-CN": "视频 · 按议题进入", en: "Video · start with a topic"},
  selected: {"zh-CN": "已选择", en: "Selected"},
  topic: {"zh-CN": "电池与散热设计", en: "Battery & thermal design"},
  keyConclusion: {"zh-CN": "重要结论", en: "Key conclusion"},
  claim: {"zh-CN": "试点发布仍以十月为目标，等待供应商验证。", en: "The pilot launch remains targeted for October, pending supplier validation."},
  viewEvidence: {"zh-CN": "回到依据", en: "Return to evidence"},
  screenAtTime: {"zh-CN": "42:18 · 当时画面", en: "42:18 · Screen at that moment"},
  screenTitle: {"zh-CN": "供应商验证", en: "Supplier validation"},
  pending: {"zh-CN": "状态：待确认", en: "Status: pending"},
  verifyKicker: {"zh-CN": "核对事实", en: "Verify the facts"},
  verifyTitle: {"zh-CN": "重要结论，不该停在一句没有来源的摘要。", en: "An important conclusion shouldn't end as a source-less summary."},
  verifyBody: {"zh-CN": "人物、原话、时间和当时画面保持在同一条证据路径上。提议不会静默变成决定，画面出现也不等于会议已经确认。", en: "Keep the person, original words, time, and screen on one evidence path. A proposal does not silently become a decision, and something appearing on screen does not prove approval."},
  meetingConclusion: {"zh-CN": "会议结论", en: "Meeting conclusion"},
  transcript: {"zh-CN": "“试点发布仍以十月为目标，前提是供应商验证通过。”", en: "“The pilot launch remains targeted for October, pending supplier validation.”"},
  sharedScreen: {"zh-CN": "共享画面", en: "Shared screen"},
  linked: {"zh-CN": "原声、时间与画面已关联", en: "Words, time, and screen are linked"},
};

document.documentElement.dataset.direction = direction;
document.documentElement.lang = language;
document.querySelector("[data-direction-name]").textContent = directionNames[direction][language];
document.querySelectorAll("[data-copy]").forEach(node => {
  node.textContent = copy[node.dataset.copy][language];
});
document.querySelectorAll("[data-language]").forEach(link => {
  const active = link.dataset.language === language;
  link.classList.toggle("active", active);
  link.setAttribute("aria-current", active ? "true" : "false");
  const next = new URLSearchParams(params);
  next.set("direction", direction);
  next.set("lang", link.dataset.language);
  link.href = `?${next}`;
});
document.querySelectorAll("[data-evidence-toggle]").forEach(button => {
  button.addEventListener("click", () => {
    const expanded = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(expanded));
    document.querySelector(".evidence-composition").dataset.evidenceState = expanded ? "expanded" : "collapsed";
  });
});
document.documentElement.dataset.ready = "true";
