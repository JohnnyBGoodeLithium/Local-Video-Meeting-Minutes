// DOM projection for meeting-material import. No API or application state access.

const COPY = {
  "zh-CN": {
    selected: count => `已选择 ${count} 张现场资料`, remove: "移除", preview: "现场资料预览",
    position: "位置", current: seconds => `${seconds}（当前播放位置）`, unlocated: "暂不定位",
    capture: seconds => seconds ? `${seconds}（根据拍摄时间建议）` : "拍摄时间尚不能匹配",
    change: "更改", currentOption: "放到当前播放位置", captureOption: "根据拍摄时间匹配",
    unlocatedOption: "暂不定位", start: "会议开始时间", startHint: "仅在选择拍摄时间匹配时使用",
    noCapture: "图片没有可读取的 EXIF 拍摄时间，将保持未定位。",
    empty: "没有待导入的现场资料。", emptyFile: "文件为空或不可读取",
    tooLarge: "单张资料不能超过 32 MB", unsupported: "支持 JPG、PNG 和 WebP",
    importFailed: "这张资料导入失败", duplicate: "与已有现场资料内容相同，不会重复保存",
    trust: "现场资料用于补充上下文；未经发言或人工确认，不单独作为会议决定依据。",
  },
  en: {
    selected: count => `${count} meeting materials selected`, remove: "Remove", preview: "Meeting material preview",
    position: "Position", current: seconds => `${seconds} (current playback)`, unlocated: "Leave unlocated",
    capture: seconds => seconds ? `${seconds} (capture-time suggestion)` : "Capture time cannot be matched yet",
    change: "Change", currentOption: "Place at current playback", captureOption: "Match by capture time",
    unlocatedOption: "Leave unlocated", start: "Meeting start time", startHint: "Used only for capture-time matching",
    noCapture: "No readable EXIF capture time was found; this item will remain unlocated.",
    empty: "No meeting materials are waiting to import.", emptyFile: "The file is empty or unreadable",
    tooLarge: "Each item must be 32 MB or smaller", unsupported: "JPG, PNG, and WebP are supported",
    importFailed: "This item could not be imported", duplicate: "This matches an existing item and was not saved again",
    trust: "Meeting materials supplement context; without discussion or human confirmation, they are not meeting decisions.",
  },
};

function t(language) { return COPY[language] || COPY["zh-CN"]; }
function errorText(code, copy) {
  if (!code) return "";
  return ({ empty: copy.emptyFile, too_large: copy.tooLarge, unsupported: copy.unsupported,
    import_failed: copy.importFailed, meeting_start_required: copy.start }[code] || code);
}

export function renderPhotoImport({ root, state, language = "zh-CN", escapeHtml,
  formatTime, formatBytes, onRemove, onToggleSettings, onMode, onMeetingStart } = {}) {
  if (!root) return;
  const copy = t(language);
  const h = value => escapeHtml(String(value ?? ""));
  const position = item => item.mode === "current_time" ? copy.current(formatTime(item.seconds || 0))
    : item.mode === "capture_time" ? copy.capture(Number.isFinite(item.seconds) ? formatTime(item.seconds) : "")
      : copy.unlocated;
  const rows = (state.items || []).map(item => {
    const itemError = errorText(item.error, copy);
    const duplicate = item.result?.duplicate;
    return `<article class="photo-import-item ${itemError ? "has-error" : ""}" data-photo-item="${h(item.id)}">`
      + `<div class="photo-import-thumb">${item.previewUrl ? `<img src="${h(item.previewUrl)}" alt="${h(copy.preview)}">` : ""}</div>`
      + `<div class="photo-import-item-copy"><div class="photo-import-item-head"><div><b>${h(item.name)}</b>`
      + `<small>${h(formatBytes(item.size, language))}</small></div>`
      + `<button type="button" class="subtle" data-photo-remove="${h(item.id)}" aria-label="${h(`${copy.remove} ${item.name}`)}">${h(copy.remove)}</button></div>`
      + `<div class="photo-position-row"><span><small>${h(copy.position)}</small><b>${h(position(item))}</b></span>`
      + `<button type="button" class="text-button" data-photo-settings="${h(item.id)}" aria-expanded="${String(item.settingsOpen)}">${h(copy.change)}</button></div>`
      + (item.settingsOpen ? `<div class="photo-position-options" role="group" aria-label="${h(copy.position)}">`
        + `<button type="button" data-photo-mode="current_time" data-photo-id="${h(item.id)}">${h(copy.currentOption)}</button>`
        + `<button type="button" data-photo-mode="capture_time" data-photo-id="${h(item.id)}">${h(copy.captureOption)}</button>`
        + `<button type="button" data-photo-mode="unlocated" data-photo-id="${h(item.id)}">${h(copy.unlocatedOption)}</button></div>` : "")
      + (item.mode === "capture_time" && !item.capturedAt ? `<p class="photo-import-inline-note">${h(copy.noCapture)}</p>` : "")
      + (itemError ? `<p class="photo-import-inline-error" role="alert">${h(itemError)}</p>` : "")
      + (duplicate ? `<p class="photo-import-inline-note">${h(copy.duplicate)}</p>` : "")
      + `</div></article>`;
  }).join("");
  const needsStart = state.items.some(item => item.mode === "capture_time");
  root.innerHTML = `<div class="photo-import-selection-head"><b>${h(copy.selected(state.items.length))}</b></div>`
    + (needsStart ? `<label class="photo-meeting-start"><span><b>${h(copy.start)}</b><small>${h(copy.startHint)}</small></span>`
      + `<input type="datetime-local" step="1" value="${h(state.meetingStart)}" data-photo-meeting-start></label>` : "")
    + `<div class="photo-import-files">${rows || `<p class="placeholder">${h(copy.empty)}</p>`}</div>`
    + (state.error ? `<p class="photo-import-global-error" role="alert">${h(state.error)}</p>` : "")
    + `<p class="photo-trust-note">${h(copy.trust)}</p>`;
  root.querySelectorAll("[data-photo-remove]").forEach(button => button.onclick = () => onRemove?.(button.dataset.photoRemove));
  root.querySelectorAll("[data-photo-settings]").forEach(button => button.onclick = () => onToggleSettings?.(button.dataset.photoSettings));
  root.querySelectorAll("[data-photo-mode]").forEach(button => button.onclick = () => onMode?.(button.dataset.photoId, button.dataset.photoMode));
  root.querySelector("[data-photo-meeting-start]")?.addEventListener("input", event => onMeetingStart?.(event.target.value));
}
