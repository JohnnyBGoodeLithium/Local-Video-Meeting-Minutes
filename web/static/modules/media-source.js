/* Media/Meeting shared source projection. Keep DOM and global state out of this module. */

export function contentTypeOf(item) {
  return item?.content_type === "media" ? "media" : "meeting";
}

export function sourcePublishedDate(item) {
  return item?.source_info?.published_at || item?.date || item?.slug || "";
}

export function sourceSearchText(item) {
  const source = item?.source_info || {};
  return [
    item?.title,
    item?.date,
    item?.slug,
    ...(item?.keywords || []),
    source.platform,
    source.publisher,
    source.published_at,
  ].filter(Boolean).join(" ");
}

export function safeSourceUrl(item) {
  const value = String(item?.source_info?.canonical_url || "").trim();
  if (!/^https?:\/\//i.test(value)) return "";
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch (_) {
    return "";
  }
}
