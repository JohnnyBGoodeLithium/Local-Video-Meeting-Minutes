/* Export selection, size, and URL rules. Dialog rendering and downloads stay in app.js. */

const PROFILES = new Set(["full", "ai", "kb", "kb-html"]);
const MEDIA = new Set(["none", "audio", "video"]);

export function normalizeExportProfile(value) {
  return PROFILES.has(value) ? value : "full";
}

export function normalizeExportMedia(value) {
  return MEDIA.has(value) ? value : "none";
}

export function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  if (value < 1024 * 1024 * 1024)
    return `${(value / 1024 / 1024).toFixed(value > 100 * 1024 * 1024 ? 0 : 1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function exportSizeState(preflight, profile, media, limit = 30 * 1024 * 1024) {
  const selectedProfile = normalizeExportProfile(profile);
  const selectedMedia = normalizeExportMedia(media);
  const estimatedBytes = Number(preflight?.estimated_bytes?.[selectedMedia] || 0);
  return {
    profile: selectedProfile,
    media: selectedProfile === "full" ? selectedMedia : "none",
    estimatedBytes,
    oversized: selectedProfile === "full" && estimatedBytes > limit,
  };
}

export function meetingExportHref(slug, media, profile) {
  return `/api/meetings/${encodeURIComponent(slug)}/export?media=${encodeURIComponent(
    normalizeExportMedia(media))}&profile=${encodeURIComponent(normalizeExportProfile(profile))}`;
}

export function packExportHref(slugs, media, profile) {
  return `/api/export/pack?slugs=${encodeURIComponent((slugs || []).join(","))}`
    + `&media=${encodeURIComponent(normalizeExportMedia(media))}`
    + `&profile=${encodeURIComponent(normalizeExportProfile(profile))}`;
}
