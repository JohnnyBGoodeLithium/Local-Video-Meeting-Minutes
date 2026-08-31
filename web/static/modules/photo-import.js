// Pure state and file-metadata rules for the meeting-material import journey.

const MAX_FILE_BYTES = 32 * 1024 * 1024;
const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

let nextItemId = 1;

export function createPhotoImportState() {
  return {
    open: false,
    entry: "materials",
    items: [],
    meetingStart: "",
    busy: false,
    error: "",
    returnFocus: null,
  };
}

function safeUrlCreate(urlApi, file) {
  try { return urlApi?.createObjectURL?.(file) || ""; }
  catch (_) { return ""; }
}

function validateFile(file) {
  if (!file || !Number(file.size)) return "empty";
  if (Number(file.size) > MAX_FILE_BYTES) return "too_large";
  const suffix = String(file.name || "").toLowerCase().split(".").pop();
  if (!ACCEPTED_TYPES.has(String(file.type || ""))
      && !["jpg", "jpeg", "png", "webp"].includes(suffix)) return "unsupported";
  return "";
}

export function beginPhotoImport(current, files, { entry = "materials", currentTime = 0,
  returnFocus = null, urlApi = globalThis.URL } = {}) {
  releasePhotoImport(current, urlApi);
  const mode = entry === "player" ? "current_time" : "unlocated";
  const items = [...(files || [])].map(file => ({
    id: `pending-photo-${nextItemId++}`,
    file,
    name: String(file?.name || "image"),
    size: Number(file?.size || 0),
    previewUrl: safeUrlCreate(urlApi, file),
    mode,
    seconds: mode === "current_time" ? Math.max(0, Number(currentTime) || 0) : null,
    capturedAt: null,
    settingsOpen: false,
    error: validateFile(file),
    result: null,
  }));
  return { ...createPhotoImportState(), open: Boolean(items.length), entry, items, returnFocus };
}

export function releasePhotoImport(current, urlApi = globalThis.URL) {
  for (const item of current?.items || []) {
    if (!item.previewUrl) continue;
    try { urlApi?.revokeObjectURL?.(item.previewUrl); } catch (_) { /* noop */ }
  }
}

export function removePhotoImportItem(current, id, urlApi = globalThis.URL) {
  const removed = (current.items || []).find(item => item.id === id);
  if (removed?.previewUrl) {
    try { urlApi?.revokeObjectURL?.(removed.previewUrl); } catch (_) { /* noop */ }
  }
  return { ...current, items: current.items.filter(item => item.id !== id), error: "" };
}

export function togglePhotoTimeSettings(current, id) {
  return { ...current, items: current.items.map(item => item.id === id
    ? { ...item, settingsOpen: !item.settingsOpen } : item) };
}

export function setPhotoPositionMode(current, id, mode, currentTime = 0) {
  const valid = ["unlocated", "current_time", "capture_time"].includes(mode) ? mode : "unlocated";
  return { ...current, items: current.items.map(item => item.id === id ? {
    ...item,
    mode: valid,
    seconds: valid === "current_time" ? Math.max(0, Number(currentTime) || 0)
      : valid === "capture_time" ? captureSeconds(item.capturedAt, current.meetingStart) : null,
    settingsOpen: false,
    error: item.error === "meeting_start_required" ? "" : item.error,
  } : item) };
}

export function setPhotoMeetingStart(current, value) {
  const meetingStart = String(value || "");
  return { ...current, meetingStart, items: current.items.map(item => item.mode === "capture_time"
    ? { ...item, seconds: captureSeconds(item.capturedAt, meetingStart),
      error: item.error === "meeting_start_required" ? "" : item.error }
    : item) };
}

export function withPhotoImportBusy(current, busy) {
  return { ...current, busy: Boolean(busy), error: "" };
}

export function withPhotoImportError(current, error, itemId = null) {
  if (itemId) return { ...current, busy: false, items: current.items.map(item => item.id === itemId
    ? { ...item, error: String(error || "import_failed") } : item) };
  return { ...current, busy: false, error: String(error || "import_failed") };
}

export function markPhotoImportResult(current, itemId, result) {
  return { ...current, items: current.items.map(item => item.id === itemId
    ? { ...item, result, error: "" } : item) };
}

export function captureSeconds(capturedAt, meetingStart) {
  const capture = Date.parse(capturedAt || "");
  const start = Date.parse(meetingStart || "");
  if (!Number.isFinite(capture) || !Number.isFinite(start)) return null;
  const seconds = (capture - start) / 1000;
  return seconds >= 0 ? Math.round(seconds * 1000) / 1000 : null;
}

export function photoUploadSpec(item, meetingStart = "") {
  if (item.error) return { valid: false, error: item.error };
  if (item.mode === "capture_time" && !meetingStart) {
    return { valid: false, error: "meeting_start_required" };
  }
  return {
    valid: true,
    file: item.file,
    mode: item.mode,
    anchorSeconds: item.mode === "current_time" ? Number(item.seconds) || 0 : null,
    meetingStart: item.mode === "capture_time" ? meetingStart : "",
  };
}

export function formatPhotoBytes(value, language = "zh-CN") {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`;
  const mb = Math.round(bytes / 1024 / 102.4) / 10;
  return `${mb} MB${language === "en" ? "" : ""}`;
}

// Minimal JPEG EXIF reader: DateTimeOriginal -> DateTimeDigitized -> DateTime.
// PNG/WebP remain without a capture-time suggestion; file mtime is never substituted.
export async function readPhotoCaptureTime(file) {
  if (!file || !/jpe?g/i.test(String(file.type || file.name || ""))) return null;
  let buffer;
  try { buffer = await file.arrayBuffer(); } catch (_) { return null; }
  const view = new DataView(buffer);
  if (view.byteLength < 12 || view.getUint16(0) !== 0xffd8) return null;
  let offset = 2;
  while (offset + 4 <= view.byteLength) {
    const marker = view.getUint16(offset); offset += 2;
    if ((marker & 0xff00) !== 0xff00 || offset + 2 > view.byteLength) break;
    const length = view.getUint16(offset); offset += 2;
    if (marker === 0xffe1 && length >= 8 && offset + length - 2 <= view.byteLength
        && view.getUint32(offset) === 0x45786966 && view.getUint16(offset + 4) === 0) {
      return readExifDate(view, offset + 6, length - 8);
    }
    offset += Math.max(0, length - 2);
  }
  return null;
}

function readExifDate(view, base, length) {
  if (length < 8 || base + length > view.byteLength) return null;
  const byteOrder = view.getUint16(base);
  const little = byteOrder === 0x4949;
  if (!little && byteOrder !== 0x4d4d) return null;
  const u16 = at => view.getUint16(base + at, little);
  const u32 = at => view.getUint32(base + at, little);
  const readAscii = (pointer, count) => {
    if (pointer < 0 || pointer + count > length) return "";
    let value = "";
    for (let i = 0; i < count; i += 1) {
      const char = view.getUint8(base + pointer + i);
      if (!char) break;
      value += String.fromCharCode(char);
    }
    return value;
  };
  const scanIfd = pointer => {
    if (pointer < 0 || pointer + 2 > length) return { dates: [], exif: null };
    const count = u16(pointer);
    const dates = [];
    let exif = null;
    for (let i = 0; i < count; i += 1) {
      const entry = pointer + 2 + i * 12;
      if (entry + 12 > length) break;
      const tag = u16(entry), type = u16(entry + 2), size = u32(entry + 4);
      const value = u32(entry + 8);
      if (tag === 0x8769) exif = value;
      if ([0x9003, 0x9004, 0x0132].includes(tag) && type === 2) {
        const text = size <= 4 ? readAscii(entry + 8, size) : readAscii(value, size);
        if (text) dates.push({ tag, text });
      }
    }
    return { dates, exif };
  };
  if (u16(2) !== 42) return null;
  const root = scanIfd(u32(4));
  const nested = root.exif != null ? scanIfd(root.exif) : { dates: [] };
  const candidate = [...nested.dates, ...root.dates].sort((a, b) =>
    [0x9003, 0x9004, 0x0132].indexOf(a.tag) - [0x9003, 0x9004, 0x0132].indexOf(b.tag))[0];
  if (!candidate) return null;
  const match = candidate.text.match(/^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})/);
  if (!match) return null;
  const [, y, month, day, hour, minute, second] = match;
  const local = new Date(Number(y), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second));
  return Number.isNaN(local.getTime()) ? null : local.toISOString();
}

export async function hydratePhotoCaptureTimes(current) {
  const times = await Promise.all(current.items.map(item => readPhotoCaptureTime(item.file)));
  return { ...current, items: current.items.map((item, index) => {
    const capturedAt = times[index];
    return { ...item, capturedAt,
      seconds: item.mode === "capture_time" ? captureSeconds(capturedAt, current.meetingStart) : item.seconds };
  }) };
}
