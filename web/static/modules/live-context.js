"use strict";

import { adjacentReviewUnit, defaultReviewUnits, reviewIndexesFor }
  from "./player-navigation.js";

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

export function livePersonFocusNavigation(turns, duration, speaker, currentIndex, delta) {
  const units = defaultReviewUnits(turns, duration);
  const indexes = reviewIndexesFor(units, speaker || null);
  return {
    units,
    indexes,
    target: delta === 0 ? currentIndex : adjacentReviewUnit(indexes, currentIndex, delta),
  };
}

export function normalizeLiveWorkspace(value) {
  const session = value?.session && typeof value.session === "object" ? value.session : {};
  const rawTurns = Array.isArray(value?.transcript?.turns) ? value.transcript.turns : [];
  const turns = rawTurns.map((item, index) => ({
    id: String(item?.id || `live-turn-${index}`),
    start: Math.max(0, Number(item?.start) || 0),
    end: Math.max(Number(item?.start) || 0, Number(item?.end) || 0),
    speaker: String(item?.speaker || ""),
    text: String(item?.text || "").trim(),
  })).filter(item => item.text);
  const items = Array.isArray(value?.takeaways?.items)
    ? value.takeaways.items.map(item => ({
      text: String(item?.text || item || "").trim(),
      start: Math.max(0, Number(item?.start) || 0),
    })).filter(item => item.text)
    : [];
  return {
    schema: value?.schema === "meeting-live-workspace/v1"
      ? value.schema : "meeting-live-workspace/v1",
    session,
    source: {
      displayUrl: String(value?.source?.display_url || ""),
      kind: String(value?.source?.source_kind || ""),
    },
    transcript: {
      turns,
      totalTurns: Math.max(turns.length, Number(value?.transcript?.total_turns) || 0),
      truncated: Boolean(value?.transcript?.truncated),
      provisional: value?.transcript?.provisional !== false,
    },
    takeaways: {
      state: String(value?.takeaways?.state || "collecting"),
      items,
      provisional: value?.takeaways?.provisional !== false,
    },
  };
}
