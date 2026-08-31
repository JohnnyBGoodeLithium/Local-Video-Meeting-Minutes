// Pure state and presentation rules for progressive speaker identity correction.

export const CORRECTION_MODES = new Set([
  "idle", "identify", "select_examples", "preview", "applying",
]);

export function createSpeakerCorrectionState() {
  return {
    mode: "idle",
    sourceVoice: null,
    sourceDisplayName: "",
    selectedTurnIndexes: new Set(),
    preview: null,
    includeSuggested: false,
    groupAssignments: {},
    returnScrollAnchor: null,
    returnPlaybackTime: null,
    anchorRect: null,
    exitConfirmation: false,
    error: "",
  };
}

export function resetSpeakerCorrection(current = null) {
  return createSpeakerCorrectionState();
}

export function beginIdentity(current, { voice, displayName, scrollAnchor, playbackTime,
  anchorRect = null } = {}) {
  return {
    ...createSpeakerCorrectionState(),
    mode: "identify",
    sourceVoice: voice || null,
    sourceDisplayName: displayName || "",
    returnScrollAnchor: scrollAnchor || null,
    returnPlaybackTime: Number(playbackTime) || 0,
    anchorRect,
  };
}

export function beginExampleSelection(current) {
  return { ...current, mode: "select_examples", preview: null,
    includeSuggested: false, groupAssignments: {}, exitConfirmation: false, error: "" };
}

export function toggleExample(current, index) {
  const selected = new Set(current.selectedTurnIndexes || []);
  if (selected.has(index)) selected.delete(index);
  else selected.add(index);
  return { ...current, selectedTurnIndexes: selected, preview: null,
    includeSuggested: false, groupAssignments: {}, exitConfirmation: false, error: "" };
}

export function withCorrectionError(current, error) {
  return { ...current, error: String(error || "") };
}

function indexes(values) {
  const source = values instanceof Set ? [...values] : (Array.isArray(values) ? values : []);
  return [...new Set(source.map(Number).filter(Number.isInteger))].sort((a, b) => a - b);
}

function groupKey(group, index) {
  return String(group?.group_key || `group-${index + 1}`);
}

export function normalizeCorrectionPreview(raw = {}, transcript = []) {
  const selected = indexes(raw.selected);
  const suggested = indexes(raw.suggested);
  const protectedTurns = indexes(raw.protected);
  const ambiguous = indexes(raw.ambiguous);
  const groups = (raw.groups || [{ selected, suggested }]).map((group, index) => {
    const selectedTurns = indexes(group.selected || (index === 0 ? selected : []));
    const suggestedTurns = indexes(group.suggested);
    const active = [...selectedTurns, ...(raw.include_suggested ? suggestedTurns : [])];
    return {
      groupKey: groupKey(group, index),
      selectedTurns,
      suggestedTurns,
      allTurns: indexes(group.turns || [...selectedTurns, ...suggestedTurns]),
      duration: Number(group.duration || durationOf(transcript, active || selectedTurns)),
      representativeTurns: indexes(group.representative_turns).slice(0, 3),
      suggestedPerson: String(group.suggested_person || ""),
      evidenceLimited: Boolean(group.evidence_limited),
    };
  });
  return {
    ...raw,
    selected,
    suggested,
    protected: protectedTurns,
    ambiguous,
    groups,
    directOnly: Boolean(raw.direct_only),
  };
}

export function setPreview(current, raw, transcript = []) {
  const preview = normalizeCorrectionPreview(raw, transcript);
  const assignments = {};
  preview.groups.forEach(group => {
    assignments[group.groupKey] = group.suggestedPerson
      ? { name: group.suggestedPerson, create: false }
      : { name: "", create: false };
  });
  return { ...current, mode: "preview", preview, includeSuggested: false,
    groupAssignments: assignments, exitConfirmation: false, error: "" };
}

export function setIncludeSuggested(current, include) {
  return { ...current, includeSuggested: Boolean(include), exitConfirmation: false, error: "" };
}

export function setGroupAssignment(current, key, assignment = {}) {
  return { ...current, groupAssignments: { ...current.groupAssignments,
    [key]: { name: String(assignment.name || "").trim(), create: Boolean(assignment.create) } },
    exitConfirmation: false, error: "" };
}

export function durationOf(transcript = [], turnIndexes = []) {
  return indexes(turnIndexes).reduce((total, index) => {
    const turn = transcript[index] || {};
    return total + Math.max(0, Number(turn.end || 0) - Number(turn.start || 0));
  }, 0);
}

export function representativeTurns(transcript = [], voice, limit = 3) {
  const candidates = transcript.map((turn, index) => ({ turn, index,
    duration: Math.max(0, Number(turn.end || 0) - Number(turn.start || 0)) }))
    .filter(item => item.turn.voice === voice);
  if (candidates.length <= limit) return candidates.map(item => item.index);
  const thirds = [
    candidates.slice(0, Math.ceil(candidates.length / 3)),
    candidates.slice(Math.floor(candidates.length / 3), Math.ceil(candidates.length * 2 / 3)),
    candidates.slice(Math.floor(candidates.length * 2 / 3)),
  ];
  return thirds.map(part => [...part].sort((a, b) => b.duration - a.duration)[0]?.index)
    .filter(Number.isInteger).slice(0, limit);
}

export function correctionSummary(current, transcript = [], pendingLabel = "待确认说话人") {
  const preview = current.preview;
  if (!preview) return null;
  const sourceTurns = transcript.map((turn, index) => ({ turn, index }))
    .filter(item => item.turn.voice === current.sourceVoice).map(item => item.index);
  const groups = preview.groups.map(group => {
    const turns = indexes([...group.selectedTurns,
      ...(current.includeSuggested ? group.suggestedTurns : [])]);
    const assignment = current.groupAssignments[group.groupKey] || {};
    return { ...group, turns, duration: durationOf(transcript, turns),
      displayName: assignment.name || pendingLabel };
  });
  const moved = new Set(groups.flatMap(group => group.turns));
  return {
    before: { name: current.sourceDisplayName, turns: sourceTurns.length,
      duration: durationOf(transcript, sourceTurns) },
    sourceAfter: { name: current.sourceDisplayName,
      turns: sourceTurns.filter(index => !moved.has(index)).length,
      duration: durationOf(transcript, sourceTurns.filter(index => !moved.has(index))) },
    groups,
    protected: preview.protected.length,
    ambiguous: preview.ambiguous.length,
    moved: moved.size,
  };
}

export function buildCorrectionApplyPayload(current) {
  const assignments = {};
  for (const group of current.preview?.groups || []) {
    const value = current.groupAssignments[group.groupKey] || {};
    assignments[group.groupKey] = { name: String(value.name || "").trim(),
      create: Boolean(value.create) };
  }
  return {
    voice: current.sourceVoice,
    turns: indexes(current.selectedTurnIndexes),
    expand_similar: Boolean(current.includeSuggested),
    group_assignments: assignments,
  };
}
