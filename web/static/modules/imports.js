/* Import request construction. UI progress and navigation remain in the shell. */

const VIDEO_NAME = /\.(?:mp4|mkv|mov|webm|avi|m4v)$/i;

export function isSingleLocalVideo(files) {
  const items = [...(files || [])];
  if (items.length !== 1) return false;
  const file = items[0];
  return String(file?.type || "").startsWith("video/")
    || VIDEO_NAME.test(String(file?.name || ""));
}

export function buildUploadFormData(files, options = {}) {
  const body = new FormData();
  for (const file of files || []) body.append("files", file);
  body.append("content_type", options.contentType === "media" ? "media" : "meeting");
  if (options.noVl) body.append("no_vl", "1");
  if (options.ignoreTranscript) body.append("ignore_transcript", "1");
  return body;
}

export async function enqueueMediaUrl(api, url, noVl = false) {
  const response = await api("/api/import-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: String(url || "").trim(), no_vl: !!noVl }),
  });
  return { response, body: await response.json().catch(() => ({})) };
}
