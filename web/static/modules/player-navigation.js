/* Pure transcript-review navigation. Media playback and DOM effects stay in app.js. */

export function turnEnd(transcript, duration, index) {
  const turns = transcript || [];
  const turn = turns[index];
  if (!turn) return 0;
  return Number(turn.end ?? turns[index + 1]?.start ?? duration)
    || Number(turn.start) || 0;
}

export function defaultReviewUnits(transcript, duration) {
  return (transcript || []).map((turn, turnIndex) => ({
    index: turnIndex,
    turnIndex,
    chunkIndex: 0,
    chunkCount: 1,
    start: Number(turn.start) || 0,
    end: turnEnd(transcript, duration, turnIndex),
    speaker: turn.speaker,
  }));
}

export function reviewIndexesFor(units, speaker = null) {
  return (units || []).filter(unit => !speaker || unit.speaker === speaker)
    .map(unit => unit.index);
}

export function reviewUnitForTurn(units, turnIndex, time = null) {
  const matches = (units || []).filter(unit => unit.turnIndex === turnIndex);
  if (!matches.length) return null;
  if (time != null) {
    const containing = matches.find(unit => unit.start <= time && time < unit.end);
    if (containing) return containing.index;
  }
  return matches[0].index;
}

export function nearestReviewUnit(units, indexes, time) {
  if (!indexes?.length) return null;
  const containing = indexes.find(index => units[index].start <= time && time < units[index].end);
  if (containing != null) return containing;
  return indexes.find(index => units[index].start >= time) ?? indexes[indexes.length - 1];
}

export function adjacentReviewUnit(indexes, current, delta) {
  const position = (indexes || []).indexOf(current);
  return position < 0 ? null : indexes[position + delta] ?? null;
}
