// DOM projection for speaker identity and mixed-speaker correction. No API/global state/media access.

function h(value, escapeHtml) { return escapeHtml(String(value ?? "")); }

function sampleRows(indexes, transcript, formatTime, escapeHtml, label = "播放") {
  return indexes.map(index => {
    const turn = transcript[index] || {};
    return `<button type="button" class="speaker-sample" data-play-turn="${index}" `
      + `aria-label="${label} ${h(formatTime(turn.start || 0), escapeHtml)}">`
      + `<span>▶ ${h(formatTime(turn.start || 0), escapeHtml)}</span>`
      + `<small>${h(String(turn.text || "").slice(0, 72), escapeHtml)}</small></button>`;
  }).join("");
}

export function renderIdentityPopover({ root, correction, transcript = [], persons = [],
  representatives = [], formatTime, escapeHtml, onClose, onSelectPerson, onCreatePerson,
  onConfirm, onRepair, onPlay } = {}) {
  if (!root) return;
  const applyingIdentity = correction.mode === "applying" && !correction.preview;
  if (correction.mode !== "identify" && !applyingIdentity) {
    root.classList.add("hidden"); return;
  }
  const source = transcript.filter(turn => turn.voice === correction.sourceVoice);
  const duration = source.reduce((n, turn) => n + Math.max(0,
    Number(turn.end || 0) - Number(turn.start || 0)), 0);
  root.innerHTML = `<div class="speaker-card-head"><div><h3>这个声音是谁？</h3>`
    + `<p>系统将 ${source.length} 段、共 ${h(formatTime(duration), escapeHtml)} 的发言归为同一位说话人。</p></div>`
    + `<button type="button" data-close aria-label="关闭身份卡">×</button></div>`
    + `<div class="speaker-samples">${sampleRows(representatives, transcript, formatTime, escapeHtml, "播放代表片段")}</div>`
    + `<label class="speaker-person-search"><span>选择人员</span>`
    + `<input type="search" data-person-input list="speaker-correction-person-list" autocomplete="off" `
    + `placeholder="搜索已有人员或输入新姓名" aria-label="搜索或输入人员姓名"></label>`
    + `<datalist id="speaker-correction-person-list">${persons.map(person =>
      `<option value="${h(person.display_name || person.name, escapeHtml)}"></option>`).join("")}</datalist>`
    + `<div class="speaker-person-candidates">${persons.slice(0, 5).map(person =>
      `<button type="button" data-person="${h(person.display_name || person.name, escapeHtml)}">${h(person.display_name || person.name, escapeHtml)}</button>`).join("")}</div>`
    + `<div class="speaker-inline-error" aria-live="polite">${h(correction.error, escapeHtml)}</div>`
    + `<div class="speaker-card-actions"><button type="button" data-confirm class="primary" ${applyingIdentity ? "disabled" : ""}>${applyingIdentity ? "正在确认…" : "确认全部为此人"}</button>`
    + `<button type="button" data-create ${applyingIdentity ? "disabled" : ""}>新建人员并确认</button>`
    + `<button type="button" data-repair ${applyingIdentity ? "disabled" : ""}>这组里混入了其他人</button>`
    + `<button type="button" data-unconfirmed>暂不确认</button>`
    + `<button type="button" data-later>稍后处理</button></div>`;
  const input = root.querySelector("[data-person-input]");
  root.querySelectorAll("[data-person]").forEach(button => button.onclick = () => {
    input.value = button.dataset.person;
    onSelectPerson?.(button.dataset.person);
  });
  root.querySelectorAll("[data-play-turn]").forEach(button =>
    button.onclick = () => onPlay?.(Number(button.dataset.playTurn)));
  root.querySelector("[data-close]").onclick = onClose;
  root.querySelector("[data-unconfirmed]").onclick = onClose;
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

function exampleList(correction, transcript, formatTime, escapeHtml, locked = new Set()) {
  return transcript.map((turn, index) => ({ turn, index }))
    .filter(item => item.turn.voice === correction.sourceVoice)
    .map(({ turn, index }) => {
      const isLocked = locked.has(index);
      const checked = correction.selectedTurnIndexes.has(index);
      return `<article class="speaker-example ${isLocked ? "protected" : ""}" data-turn-row="${index}">`
        + `<label><input type="checkbox" data-example="${index}" ${checked ? "checked" : ""} ${isLocked ? "disabled" : ""}>`
        + `<span><b>${h(formatTime(turn.start || 0), escapeHtml)}</b><small>${h(String(turn.text || "").slice(0, 120), escapeHtml)}</small></span></label>`
        + `<button type="button" data-play-turn="${index}" aria-label="播放 ${h(formatTime(turn.start || 0), escapeHtml)}">▶</button>`
        + `${isLocked ? '<em>已人工确认，不会自动修改</em>' : ""}</article>`;
    }).join("");
}

function previewHtml(correction, transcript, persons, formatTime, formatDuration, escapeHtml, summary) {
  const preview = correction.preview;
  const groupCards = preview.groups.map((group, index) => {
    const assignment = correction.groupAssignments[group.groupKey] || {};
    const summaryGroup = summary.groups.find(item => item.groupKey === group.groupKey);
    const count = summaryGroup?.turns.length || 0;
    const duration = summaryGroup?.duration || 0;
    return `<article class="speaker-result-group" data-group="${h(group.groupKey, escapeHtml)}">`
      + `<header><div><b>新分组 ${index + 1}</b><small>${count} 段 · ${h(formatDuration(duration), escapeHtml)}</small></div>`
      + `${group.evidenceLimited ? '<em>音频证据较少</em>' : ""}</header>`
      + `<div class="speaker-samples">${sampleRows(group.representativeTurns, transcript, formatTime, escapeHtml, "播放分组代表片段")}</div>`
      + `<label><span>这个分组是谁？</span><input type="search" data-group-person="${h(group.groupKey, escapeHtml)}" `
      + `list="speaker-correction-person-list" value="${h(assignment.name || "", escapeHtml)}" placeholder="保持待确认说话人"></label>`
      + `<label class="keep-unnamed"><input type="checkbox" data-group-create="${h(group.groupKey, escapeHtml)}" ${assignment.create ? "checked" : ""}> 姓名不存在时新建人员</label>`
      + `<label class="keep-unnamed"><input type="checkbox" data-keep-unnamed="${h(group.groupKey, escapeHtml)}" ${assignment.name ? "" : "checked"}> 保持未命名</label></article>`;
  }).join("");
  return `<section class="speaker-preview-scope"><h4>处理范围</h4>`
    + `<div><span><b>${preview.selected.length}</b>手选片段</span><span><b>${preview.suggested.length}</b>相似片段</span>`
    + `<span><b>${preview.protected.length}</b>已保护</span><span><b>${preview.ambiguous.length}</b>保持存疑</span>`
    + `<span><b>${preview.groups.length}</b>个建议分组</span></div></section>`
    + (preview.directOnly ? '<p class="speaker-direct-note">这些片段太短，系统不会自动寻找相似发言。只会修改你明确选择的片段，其他内容保持不变。</p>' : "")
    + `<label class="speaker-suggestion-toggle"><input type="checkbox" data-include-suggested ${correction.includeSuggested ? "checked" : ""} ${preview.directOnly ? "disabled" : ""}>`
    + `<span><b>同时处理系统发现的高相似片段</b><small>开启后会同时调整与已选样例高度相似的发言；已有人工确认的身份不会改变。</small></span></label>`
    + `<div class="speaker-result-groups">${groupCards}</div>`
    + `<section class="speaker-change-summary"><h4>修改前后</h4>`
    + `<div><span><small>修改前</small><b>${h(summary.before.name, escapeHtml)}</b><em>${summary.before.turns} 段 · ${h(formatDuration(summary.before.duration), escapeHtml)}</em></span>`
    + `<span><small>修改后</small><b>${h(summary.sourceAfter.name, escapeHtml)}</b><em>${summary.sourceAfter.turns} 段 · ${h(formatDuration(summary.sourceAfter.duration), escapeHtml)}</em></span>`
    + summary.groups.map(group => `<span><small>新分组</small><b>${h(group.displayName, escapeHtml)}</b><em>${group.turns.length} 段 · ${h(formatDuration(group.duration), escapeHtml)}</em></span>`).join("")
    + `</div><p>保持不变：${summary.protected} 段已有人工确认；${summary.ambiguous} 段证据不足。应用后仍可撤销。</p></section>`;
}

export function renderCorrectionSheet({ root, correction, transcript = [], persons = [], locked = new Set(),
  formatTime, formatDuration, escapeHtml, summary, onExit, onToggleExample, onNext, onBack,
  onIncludeSuggested, onAssignment, onApply, onPlay, onDiscard, onContinueExit } = {}) {
  if (!root) return;
  if (!["select_examples", "preview"].includes(correction.mode)
      && !(correction.mode === "applying" && correction.preview)) {
    root.classList.add("hidden"); return;
  }
  const selecting = correction.mode === "select_examples";
  root.innerHTML = `<div class="speaker-sheet-head"><div><h3>修复混入的说话人</h3>`
    + `<p>选出几段明显不是「${h(correction.sourceDisplayName, escapeHtml)}」的发言即可，无需全部找出。</p></div>`
    + `<button type="button" data-exit aria-label="退出人物核对">×</button></div>`
    + `<div class="speaker-sheet-body">${selecting
      ? `<p class="speaker-selection-count" aria-live="polite">已选择 ${correction.selectedTurnIndexes.size} 段明显不是「${h(correction.sourceDisplayName, escapeHtml)}」的发言。</p>`
        + `<div class="speaker-example-list">${exampleList(correction, transcript, formatTime, escapeHtml, locked)}</div>`
      : previewHtml(correction, transcript, persons, formatTime, formatDuration, escapeHtml, summary)}`
    + `<div class="speaker-inline-error" aria-live="polite">${h(correction.error, escapeHtml)}</div>`
    + `${String(correction.error || "").startsWith("退出会放弃")
      ? '<div class="speaker-discard-actions"><button type="button" data-continue>继续核对</button><button type="button" data-discard>放弃选择并退出</button></div>' : ""}</div>`
    + `<div class="speaker-sheet-actions"><button type="button" data-secondary>${selecting ? "退出核对" : "返回重新选择"}</button>`
    + `<button type="button" data-primary class="primary" ${selecting && !correction.selectedTurnIndexes.size ? "disabled" : ""} ${correction.mode === "applying" ? "disabled" : ""}>`
    + `${selecting ? "下一步" : (correction.mode === "applying" ? "正在应用…" : "应用修改")}</button></div>`;
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
