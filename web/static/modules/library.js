/* Content-library ordering and selection. Rendering stays in the application shell. */

import { contentTypeOf, sourcePublishedDate, sourceSearchText }
  from "./media-source.js?v=20260826p97";

export function sortLibrary(items, order = "imported") {
  return [...(items || [])].sort((left, right) => {
    if (order === "meeting") {
      const dateCompare = sourcePublishedDate(right).localeCompare(sourcePublishedDate(left));
      return dateCompare || String(right.slug).localeCompare(String(left.slug));
    }
    const key = order === "updated" ? "updated_at" : "imported_at";
    return Number(right[key] || 0) - Number(left[key] || 0)
      || String(right.slug).localeCompare(String(left.slug));
  });
}

export function filterLibrary(items, { contentType = "meeting", query = "" } = {}) {
  const needle = String(query || "").trim().toLowerCase();
  return (items || []).filter(item => contentTypeOf(item) === contentType
    && (!needle || sourceSearchText(item).toLowerCase().includes(needle)));
}

export function chooseInitialItem(items, { linked = "", remembered = "", contentType = "meeting",
  order = "imported" } = {}) {
  const all = items || [];
  const preferred = all.find(item => item.slug === (linked || remembered));
  const sorted = sortLibrary(all, order);
  return preferred || sorted.find(item => contentTypeOf(item) === contentType) || sorted[0] || null;
}

export function deepLinkSeconds(raw, duration) {
  const value = Number.parseFloat(String(raw ?? ""));
  const maximum = Number(duration);
  if (!Number.isFinite(value) || value < 0) return null;
  if (Number.isFinite(maximum) && value > maximum) return null;
  return value;
}
