// DOM projection for speaker identity and mixed-speaker correction. No API/global state/media access.

function h(value, escapeHtml) { return escapeHtml(String(value ?? "")); }

const SPEAKER_COPY = {
  "zh-CN": {
    identityTitle: "这个声音是谁？", identitySummary: (count, duration) => `系统将 ${count} 段、共 ${duration} 的发言归为同一位说话人。`,
    closeIdentity: "关闭身份卡", playRepresentative: "播放代表片段", personLabel: "选择人员",
    personPlaceholder: "搜索已有人员或输入新姓名", personAria: "搜索或输入人员姓名",
    confirming: "正在确认…", confirmAll: "确认全部为此人", createAndConfirm: "新建人员并确认",
    repair: "这组里混入了其他人", later: "稍后处理", playAt: time => `播放 ${time}`,
    protected: "已人工确认，不会自动修改", groupTitle: index => `新分组 ${index}`,
    segmentDuration: (count, duration) => `${count} 段 · ${duration}`, limited: "音频证据较少",
    groupWho: "这个分组是谁？", keepPending: "保持待确认说话人", createMissing: "姓名不存在时新建人员",
    keepUnnamed: "保持未命名", scope: "处理范围", selected: "手选片段", suggested: "相似片段",
    protectedCount: "已保护", ambiguous: "保持存疑", suggestedGroups: "个建议分组",
    directOnly: "这些片段太短，系统不会自动寻找相似发言。只会修改你明确选择的片段，其他内容保持不变。",
    includeSuggested: "同时处理系统发现的高相似片段",
    includeSuggestedHint: "开启后会同时调整与已选样例高度相似的发言；已有人工确认的身份不会改变。",
    beforeAfter: "修改前后", before: "修改前", after: "修改后", newGroup: "新分组",
    unchanged: (protectedCount, ambiguous) => `保持不变：${protectedCount} 段已有人工确认；${ambiguous} 段证据不足。应用后仍可撤销。`,
    repairTitle: "修复混入的说话人", repairSubtitle: name => `选出几段明显不是「${name}」的发言即可，无需全部找出。`,
    exitReview: "退出人物核对", selectionCount: (count, name) => `已选择 ${count} 段明显不是「${name}」的发言。`,
    continueReview: "继续核对", discardExit: "放弃选择并退出", exitReviewButton: "退出核对",
    back: "返回重新选择", next: "下一步", applying: "正在应用…", apply: "应用修改",
  },
  en: {
    identityTitle: "Who is this speaker?", identitySummary: (count, duration) => `The system grouped ${count} segments (${duration}) as one speaker.`,
    closeIdentity: "Close speaker card", playRepresentative: "Play representative segment", personLabel: "Choose a person",
    personPlaceholder: "Search people or enter a new name", personAria: "Search or enter a person name",
    confirming: "Confirming…", confirmAll: "Confirm all as this person", createAndConfirm: "Create person and confirm",
    repair: "Other people are mixed into this group", later: "Review later", playAt: time => `Play at ${time}`,
    protected: "Manually confirmed; it will not change automatically", groupTitle: index => `New group ${index}`,
    segmentDuration: (count, duration) => `${count} segments · ${duration}`, limited: "Limited audio evidence",
    groupWho: "Who is this group?", keepPending: "Keep as speaker to review", createMissing: "Create the person if the name is new",
    keepUnnamed: "Keep unnamed", scope: "Change scope", selected: "Selected", suggested: "Similar suggestions",
    protectedCount: "Protected", ambiguous: "Uncertain", suggestedGroups: "suggested groups",
    directOnly: "These segments are too short to find similar speech reliably. Only your selected segments will change; everything else stays unchanged.",
    includeSuggested: "Also change highly similar segments found by the system",
    includeSuggestedHint: "When enabled, highly similar speech will also be adjusted. Manually confirmed identities will not change.",
    beforeAfter: "Before and after", before: "Before", after: "After", newGroup: "New group",
    unchanged: (protectedCount, ambiguous) => `Unchanged: ${protectedCount} manually confirmed; ${ambiguous} lack enough evidence. You can still undo after applying.`,
    repairTitle: "Fix mixed speakers", repairSubtitle: name => `Select a few segments that clearly are not “${name}”. You do not need to find every one.`,
    exitReview: "Exit speaker review", selectionCount: (count, name) => `${count} segments selected as clearly not “${name}”.`,
    continueReview: "Continue reviewing", discardExit: "Discard selection and exit", exitReviewButton: "Exit review",
    back: "Back to selection", next: "Next", applying: "Applying…", apply: "Apply changes",
  },
};

function copyFor(language) { return SPEAKER_COPY[language] || SPEAKER_COPY["zh-CN"]; }

function sampleRows(indexes, transcript, formatTime, escapeHtml, label = "") {
  return indexes.map(index => {
    const turn = transcript[index] || {};
    return `<button type="button" class="speaker-sample" data-play-turn="${index}" `
      + `aria-label="${label} ${h(formatTime(turn.start || 0), escapeHtml)}">`
      + `<span>▶ ${h(formatTime(turn.start || 0), escapeHtml)}</span>`
      + `<small>${h(String(turn.text || "").slice(0, 72), escapeHtml)}</small></button>`;
  }).join("");
}

export function renderIdentityPopover({ root, correction, transcript = [], persons = [], language = "zh-CN",
  representatives = [], formatTime, escapeHtml, onClose, onSelectPerson, onCreatePerson,
  onConfirm, onRepair, onPlay } = {}) {
  if (!root) return;
  const applyingIdentity = correction.mode === "applying" && !correction.preview;
  if (correction.mode !== "identify" && !applyingIdentity) {
    root.classList.add("hidden"); return;
  }
  const copy = copyFor(language);
  const source = transcript.filter(turn => turn.voice === correction.sourceVoice);
  const duration = source.reduce((n, turn) => n + Math.max(0,
    Number(turn.end || 0) - Number(turn.start || 0)), 0);
  root.innerHTML = `<div class="speaker-card-head"><div><h3>${copy.identityTitle}</h3>`
    + `<p>${h(copy.identitySummary(source.length, formatTime(duration)), escapeHtml)}</p></div>`
    + `<button type="button" data-close aria-label="${copy.closeIdentity}">×</button></div>`
    + `<div class="speaker-samples">${sampleRows(representatives, transcript, formatTime, escapeHtml, copy.playRepresentative)}</div>`
    + `<label class="speaker-person-search"><span>${copy.personLabel}</span>`
    + `<input type="search" data-person-input list="speaker-correction-person-list" autocomplete="off" `
    + `placeholder="${copy.personPlaceholder}" aria-label="${copy.personAria}"></label>`
    + `<datalist id="speaker-correction-person-list">${persons.map(person =>
      `<option value="${h(person.display_name || person.name, escapeHtml)}"></option>`).join("")}</datalist>`
    + `<div class="speaker-person-candidates">${persons.slice(0, 5).map(person =>
      `<button type="button" data-person="${h(person.display_name || person.name, escapeHtml)}">${h(person.display_name || person.name, escapeHtml)}</button>`).join("")}</div>`
    + `<div class="speaker-inline-error" aria-live="polite">${h(correction.error, escapeHtml)}</div>`
    + `<div class="speaker-card-actions"><button type="button" data-confirm class="primary" ${applyingIdentity ? "disabled" : ""}>${applyingIdentity ? copy.confirming : copy.confirmAll}</button>`
    + `<button type="button" data-create ${applyingIdentity ? "disabled" : ""}>${copy.createAndConfirm}</button>`
    + `<button type="button" data-repair ${applyingIdentity ? "disabled" : ""}>${copy.repair}</button>`
    + `<button type="button" data-later>${copy.later}</button></div>`;
  const input = root.querySelector("[data-person-input]");
  root.querySelectorAll("[data-person]").forEach(button => button.onclick = () => {
    input.value = button.dataset.person;
    onSelectPerson?.(button.dataset.person);
  });
  root.querySelectorAll("[data-play-turn]").forEach(button =>
    button.onclick = () => onPlay?.(Number(button.dataset.playTurn)));
  root.querySelector("[data-close]").onclick = onClose;
  root.querySelector("[data-later]").onclick = onClose;
  root.querySelector("[data-repair]").onclick = onRepair;
  root.querySelector("[data-confirm]").onclick = () => onConfirm?.(input.value.trim(), false);
  root.querySelector("[data-create]").onclick = () => onConfirm?.(input.value.trim(), true);
  input.oninput = () => onSelectPerson?.(input.value.trim());
  input.onkeydown = event => {
    if (event.key === "Enter") { event.preventDefault(); onConfirm?.(input.value.trim(), false); }
  };
  root.classList.remove("hidden");
  input.focus();
}

function exampleList(correction, transcript, formatTime, escapeHtml, copy, locked = new Set()) {
  return transcript.map((turn, index) => ({ turn, index }))
    .filter(item => item.turn.voice === correction.sourceVoice)
    .map(({ turn, index }) => {
      const isLocked = locked.has(index);
      const checked = correction.selectedTurnIndexes.has(index);
      return `<article class="speaker-example ${isLocked ? "protected" : ""}" data-turn-row="${index}">`
        + `<label><input type="checkbox" data-example="${index}" ${checked ? "checked" : ""} ${isLocked ? "disabled" : ""}>`
        + `<span><b>${h(formatTime(turn.start || 0), escapeHtml)}</b><small>${h(String(turn.text || "").slice(0, 120), escapeHtml)}</small></span></label>`
        + `<button type="button" data-play-turn="${index}" aria-label="${h(copy.playAt(formatTime(turn.start || 0)), escapeHtml)}">▶</button>`
        + `${isLocked ? `<em>${copy.protected}</em>` : ""}</article>`;
    }).join("");
}

function previewHtml(correction, transcript, persons, formatTime, formatDuration, escapeHtml, summary, copy) {
  const preview = correction.preview;
  const groupCards = preview.groups.map((group, index) => {
    const assignment = correction.groupAssignments[group.groupKey] || {};
    const summaryGroup = summary.groups.find(item => item.groupKey === group.groupKey);
    const count = summaryGroup?.turns.length || 0;
    const duration = summaryGroup?.duration || 0;
    return `<article class="speaker-result-group" data-group="${h(group.groupKey, escapeHtml)}">`
      + `<header><div><b>${copy.groupTitle(index + 1)}</b><small>${h(copy.segmentDuration(count, formatDuration(duration)), escapeHtml)}</small></div>`
      + `${group.evidenceLimited ? `<em>${copy.limited}</em>` : ""}</header>`
      + `<div class="speaker-samples">${sampleRows(group.representativeTurns, transcript, formatTime, escapeHtml, copy.playRepresentative)}</div>`
      + `<label><span>${copy.groupWho}</span><input type="search" data-group-person="${h(group.groupKey, escapeHtml)}" `
      + `list="speaker-correction-person-list" value="${h(assignment.name || "", escapeHtml)}" placeholder="${copy.keepPending}"></label>`
      + `<label class="keep-unnamed"><input type="checkbox" data-group-create="${h(group.groupKey, escapeHtml)}" ${assignment.create ? "checked" : ""}> ${copy.createMissing}</label>`
      + `<label class="keep-unnamed"><input type="checkbox" data-keep-unnamed="${h(group.groupKey, escapeHtml)}" ${assignment.name ? "" : "checked"}> ${copy.keepUnnamed}</label></article>`;
  }).join("");
  return `<section class="speaker-preview-scope"><h4>${copy.scope}</h4>`
    + `<div><span><b>${preview.selected.length}</b>${copy.selected}</span><span><b>${preview.suggested.length}</b>${copy.suggested}</span>`
    + `<span><b>${preview.protected.length}</b>${copy.protectedCount}</span><span><b>${preview.ambiguous.length}</b>${copy.ambiguous}</span>`
    + `<span><b>${preview.groups.length}</b>${copy.suggestedGroups}</span></div></section>`
    + (preview.directOnly ? `<p class="speaker-direct-note">${copy.directOnly}</p>` : "")
    + `<label class="speaker-suggestion-toggle"><input type="checkbox" data-include-suggested ${correction.includeSuggested ? "checked" : ""} ${preview.directOnly ? "disabled" : ""}>`
    + `<span><b>${copy.includeSuggested}</b><small>${copy.includeSuggestedHint}</small></span></label>`
    + `<div class="speaker-result-groups">${groupCards}</div>`
    + `<section class="speaker-change-summary"><h4>${copy.beforeAfter}</h4>`
    + `<div><span><small>${copy.before}</small><b>${h(summary.before.name, escapeHtml)}</b><em>${h(copy.segmentDuration(summary.before.turns, formatDuration(summary.before.duration)), escapeHtml)}</em></span>`
    + `<span><small>${copy.after}</small><b>${h(summary.sourceAfter.name, escapeHtml)}</b><em>${h(copy.segmentDuration(summary.sourceAfter.turns, formatDuration(summary.sourceAfter.duration)), escapeHtml)}</em></span>`
    + summary.groups.map(group => `<span><small>${copy.newGroup}</small><b>${h(group.displayName, escapeHtml)}</b><em>${h(copy.segmentDuration(group.turns.length, formatDuration(group.duration)), escapeHtml)}</em></span>`).join("")
    + `</div><p>${h(copy.unchanged(summary.protected, summary.ambiguous), escapeHtml)}</p></section>`;
}

export function renderCorrectionSheet({ root, correction, transcript = [], persons = [], language = "zh-CN", locked = new Set(),
  formatTime, formatDuration, escapeHtml, summary, onExit, onToggleExample, onNext, onBack,
  onIncludeSuggested, onAssignment, onApply, onPlay, onDiscard, onContinueExit } = {}) {
  if (!root) return;
  if (!["select_examples", "preview"].includes(correction.mode)
      && !(correction.mode === "applying" && correction.preview)) {
    root.classList.add("hidden"); return;
  }
  const selecting = correction.mode === "select_examples";
  const copy = copyFor(language);
  root.innerHTML = `<div class="speaker-sheet-head"><div><h3>${copy.repairTitle}</h3>`
    + `<p>${h(copy.repairSubtitle(correction.sourceDisplayName), escapeHtml)}</p></div>`
    + `<button type="button" data-exit aria-label="${copy.exitReview}">×</button></div>`
    + `<div class="speaker-sheet-body">${selecting
      ? `<p class="speaker-selection-count" aria-live="polite">${h(copy.selectionCount(correction.selectedTurnIndexes.size, correction.sourceDisplayName), escapeHtml)}</p>`
        + `<div class="speaker-example-list">${exampleList(correction, transcript, formatTime, escapeHtml, copy, locked)}</div>`
      : previewHtml(correction, transcript, persons, formatTime, formatDuration, escapeHtml, summary, copy)}`
    + `<div class="speaker-inline-error" aria-live="polite">${h(correction.error, escapeHtml)}</div>`
    + `${correction.exitConfirmation
      ? `<div class="speaker-discard-actions"><button type="button" data-continue>${copy.continueReview}</button><button type="button" data-discard>${copy.discardExit}</button></div>` : ""}</div>`
    + `<div class="speaker-sheet-actions"><button type="button" data-secondary>${selecting ? copy.exitReviewButton : copy.back}</button>`
    + `<button type="button" data-primary class="primary" ${selecting && !correction.selectedTurnIndexes.size ? "disabled" : ""} ${correction.mode === "applying" ? "disabled" : ""}>`
    + `${selecting ? copy.next : (correction.mode === "applying" ? copy.applying : copy.apply)}</button></div>`;
  root.querySelector("[data-exit]").onclick = onExit;
  root.querySelector("[data-secondary]").onclick = selecting ? onExit : onBack;
  root.querySelector("[data-primary]").onclick = selecting ? onNext : onApply;
  root.querySelector("[data-continue]")?.addEventListener("click", onContinueExit);
  root.querySelector("[data-discard]")?.addEventListener("click", onDiscard);
  root.querySelectorAll("[data-example]").forEach(input => input.onchange = () =>
    onToggleExample?.(Number(input.dataset.example)));
  root.querySelectorAll("[data-play-turn]").forEach(button => button.onclick = () =>
    onPlay?.(Number(button.dataset.playTurn)));
  root.querySelector("[data-include-suggested]")?.addEventListener("change", event =>
    onIncludeSuggested?.(event.target.checked));
  root.querySelectorAll("[data-group-person]").forEach(input => input.onchange = () =>
    onAssignment?.(input.dataset.groupPerson, { name: input.value.trim(),
      create: root.querySelector(`[data-group-create="${CSS.escape(input.dataset.groupPerson)}"]`)?.checked }));
  root.querySelectorAll("[data-group-create]").forEach(input => input.onchange = () => {
    const key = input.dataset.groupCreate;
    const field = root.querySelector(`[data-group-person="${CSS.escape(key)}"]`);
    onAssignment?.(key, { name: field?.value || "", create: input.checked });
  });
  root.querySelectorAll("[data-keep-unnamed]").forEach(input => input.onchange = () => {
    const key = input.dataset.keepUnnamed;
    const field = root.querySelector(`[data-group-person="${CSS.escape(key)}"]`);
    if (input.checked && field) field.value = "";
    onAssignment?.(key, { name: input.checked ? "" : field?.value || "", create: false });
  });
  root.classList.remove("hidden");
}
