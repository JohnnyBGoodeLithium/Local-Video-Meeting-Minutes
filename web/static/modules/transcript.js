/* Pure transcript search, review metadata, and long-turn display segmentation. */

export const TURN_CHUNK_CHARS = 200;
export const TURN_CHUNK_SECS = 45;

export function transcriptSearchHits(transcript, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return [];
  const hits = [];
  (transcript || []).forEach((turn, index) => {
    if (String(turn?.text || "").toLowerCase().includes(needle)) hits.push(index);
  });
  return hits;
}

export function nextSearchCursor(current, count, direction) {
  if (!(count > 0)) return -1;
  return (Number(current) + Number(direction) + count) % count;
}

export function splitTurnChunks(text, duration, maxChars = TURN_CHUNK_CHARS,
  maxSeconds = TURN_CHUNK_SECS) {
  const value = String(text || "");
  if (!(duration > 90 || value.length > 500)) return null;
  const sentences = value.match(/[^。!?\n]+[。!?\n]?/g) || [value];
  const chunks = [];
  let buffer = "", bufferStart = 0, position = 0;
  for (const sentence of sentences) {
    const chunkSeconds = duration > 0
      ? (position - bufferStart) / Math.max(1, value.length) * duration : 0;
    if (buffer && (buffer.length >= maxChars || chunkSeconds >= maxSeconds)) {
      chunks.push({ text: buffer, charStart: bufferStart });
      buffer = "";
    }
    if (!buffer) bufferStart = position;
    buffer += sentence;
    position += sentence.length;
  }
  if (buffer) chunks.push({ text: buffer, charStart: bufferStart });
  if (chunks.length === 1 && value.length > 500) {
    chunks.length = 0;
    for (let at = 0; at < value.length; at += maxChars)
      chunks.push({ text: value.slice(at, at + maxChars), charStart: at });
  }
  return chunks.length > 1 ? chunks : null;
}

export function turnReviewUnits(turn, turnIndex, turnEnd, pieces, firstIndex = 0) {
  const start = Number(turn?.start) || 0;
  const end = Math.max(start, Number(turnEnd) || start);
  const duration = end - start;
  const totalChars = Math.max(1, String(turn?.text || "").length);
  return (pieces || [{ text: turn?.text, charStart: 0 }]).map((piece, chunkIndex, all) => {
    const unitStart = start + Number(piece.charStart || 0) / totalChars * duration;
    const next = all[chunkIndex + 1];
    const unitEnd = next
      ? start + Number(next.charStart || 0) / totalChars * duration : end;
    return {
      index: firstIndex + chunkIndex,
      turnIndex,
      chunkIndex,
      chunkCount: all.length,
      start: unitStart,
      end: Math.max(unitStart, unitEnd),
      speaker: turn?.speaker,
    };
  });
}

export function pendingReviewByTurn(review) {
  return new Map((review?.pending || [])
    .filter(item => Number.isInteger(item.turn_index))
    .map(item => [item.turn_index, item]));
}
