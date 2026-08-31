import assert from "node:assert/strict";
import {
  beginPhotoImport, captureSeconds, createPhotoImportState, formatPhotoBytes,
  hydratePhotoCaptureTimes, photoUploadSpec, releasePhotoImport, removePhotoImportItem,
  setPhotoMeetingStart, setPhotoPositionMode, togglePhotoTimeSettings,
} from "../static/modules/photo-import.js";

const urls = [];
const revoked = [];
const urlApi = {
  createObjectURL(file) { const value = `blob:test-${file.name}`; urls.push(value); return value; },
  revokeObjectURL(value) { revoked.push(value); },
};
const image = { name: "whiteboard.jpg", type: "image/jpeg", size: 2048,
  arrayBuffer: async () => new ArrayBuffer(0) };
const notes = { name: "notes.png", type: "image/png", size: 4096,
  arrayBuffer: async () => new ArrayBuffer(0) };

let state = beginPhotoImport(createPhotoImportState(), [image, notes], {
  entry: "materials", currentTime: 75, urlApi,
});
assert.equal(state.items.length, 2);
assert.equal(state.items[0].mode, "unlocated", "materials entry must not inherit playback time");
assert.equal(urls.length, 2);
state = togglePhotoTimeSettings(state, state.items[0].id);
assert.equal(state.items[0].settingsOpen, true);
state = setPhotoPositionMode(state, state.items[0].id, "current_time", 75);
assert.equal(state.items[0].seconds, 75);
assert.deepEqual(photoUploadSpec(state.items[0], ""), {
  valid: true, file: image, mode: "current_time", anchorSeconds: 75, meetingStart: "",
});

const firstId = state.items[0].id;
state = removePhotoImportItem(state, firstId, urlApi);
assert.equal(state.items.length, 1);
assert.ok(revoked.includes("blob:test-whiteboard.jpg"));
releasePhotoImport(state, urlApi);
assert.ok(revoked.includes("blob:test-notes.png"));

state = beginPhotoImport(createPhotoImportState(), [image], {
  entry: "player", currentTime: 125, urlApi,
});
assert.equal(state.items[0].mode, "current_time");
assert.equal(state.items[0].seconds, 125);
state = setPhotoPositionMode(state, state.items[0].id, "capture_time", 125);
assert.equal(photoUploadSpec(state.items[0], "").error, "meeting_start_required");
state = setPhotoMeetingStart(state, "2026-08-31T10:00:00");
state = await hydratePhotoCaptureTimes(state);
assert.equal(state.items[0].capturedAt, null, "missing EXIF must not fall back to file mtime");
assert.equal(captureSeconds("2026-08-31T10:02:30", "2026-08-31T10:00:00"), 150);
assert.equal(formatPhotoBytes(2048), "2 KB");

console.log("Photo import frontend: previews, conservative positioning, cleanup, and payloads passed");
