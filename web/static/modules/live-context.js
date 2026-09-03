"use strict";

export const LIVE_CONTENT_TYPES = new Set(["meeting", "live_event"]);
export const LIVE_MODES = new Set([
  "analyze_background", "watch_analyze", "meeting_companion", "manual",
]);

export function defaultLiveMode(contentType) {
  if (contentType === "live_event") return "analyze_background";
  if (contentType === "meeting") return "meeting_companion";
  throw new Error("unsupported live content type");
}

export function createLiveContextState(contentType = "live_event") {
  if (!LIVE_CONTENT_TYPES.has(contentType)) throw new Error("unsupported live content type");
  return {
    open: false,
    contentType,
    mode: defaultLiveMode(contentType),
    source: "",
    advanced: false,
  };
}

export function selectLiveContentType(state, contentType) {
  if (!LIVE_CONTENT_TYPES.has(contentType)) throw new Error("unsupported live content type");
  return { ...state, contentType, mode: defaultLiveMode(contentType) };
}

export function selectLiveMode(state, mode) {
  if (!LIVE_MODES.has(mode)) throw new Error("unsupported live mode");
  const allowed = state.contentType === "meeting"
    ? new Set(["meeting_companion", "manual"])
    : new Set(["analyze_background", "watch_analyze"]);
  if (!allowed.has(mode)) throw new Error("mode is not available for this content type");
  return { ...state, mode };
}
