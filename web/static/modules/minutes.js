/* Minutes/evidence selection rules. HTML rendering and mutations stay in app.js. */

export function resolveMinutesView(views, requestedId = "standard") {
  const available = Array.isArray(views) ? views : [];
  const id = requestedId || "standard";
  const view = id === "standard" ? null : available.find(item => item.id === id) || null;
  return view ? { id, view, reset: false } : {
    id: "standard", view: null, reset: id !== "standard",
  };
}

export function minutesState(bundle, selectedView, translation, uiLanguage, assistantBusy = false) {
  const document = bundle || {};
  const draft = document.document_state === "draft";
  const draftFailed = !document.has_minutes
    && Number(document.generation?.voice_draft_rc || 0) !== 0;
  const translatedHtml = translation?.target_language === uiLanguage
    && translation?.state === "ready" ? translation.html || "" : "";
  const evidenceReady = document.evidence?.state === "ready";
  return {
    draft,
    phase: document.generation?.phase || null,
    draftFailed,
    translatedHtml,
    evidenceReady,
    canRestructure: Boolean(document.has_minutes && !draft && evidenceReady && !assistantBusy),
    actionCandidates: selectedView ? [] : document.evidence?.action_candidates || [],
    canRestoreStandard: Boolean(document.minutes_history_available),
  };
}

export function turnIndexesForSourceIds(transcriptSources, ids = []) {
  const wanted = new Set(ids || []);
  return (transcriptSources || []).filter(item => wanted.has(item.id))
    .map(item => Number(item.index)).filter(Number.isInteger);
}

export function turnIndexAtTime(transcript, time) {
  let index = -1;
  for (let at = 0; at < (transcript || []).length; at += 1) {
    if (Number(transcript[at].start) <= time) index = at;
    else break;
  }
  return index;
}

export function claimIdsForTurn(claims, index) {
  if (index < 0) return [];
  return (claims || []).filter(claim => (claim.turn_indexes || []).includes(index))
    .map(claim => claim.id);
}

export function resolveMinutesClaim(evidence, selectedView, claimId) {
  const canonical = (evidence?.claims || []).find(item => item.id === claimId) || null;
  const claim = canonical
    || (selectedView?.sources || []).find(item => item.claim_id === claimId) || null;
  return { claim, canonical: Boolean(canonical) };
}

export function claimAction(evidence, claim) {
  if (!claim || claim.kind !== "action") return null;
  return claim.action || (evidence?.actions || []).find(item => item.claim_id === claim.id) || null;
}

export function evidenceSources(bundle, claim) {
  const transcript = bundle?.transcript || [];
  const slides = bundle?.slides || [];
  const turns = (claim?.turn_indexes || []).map(index => ({ index, turn: transcript[index] }))
    .filter(item => item.turn);
  const pageNumbers = (claim?.page_ids || []).map(id => Number(String(id).slice(1)))
    .filter(Number.isFinite);
  const pages = pageNumbers.map(page => slides.find(item => item.page === page)).filter(Boolean);
  return {
    turns,
    pages,
    firstTime: turns.length ? Number(turns[0].turn.start || 0)
      : pages.length ? Number(pages[0].first || 0) : null,
  };
}

export function normalizeReviewMode(mode, bundle) {
  const allowed = new Set(["minutes", "chapters", "visuals", "quality"]);
  let value = allowed.has(mode) ? mode : "minutes";
  if (value === "chapters" && !bundle?.transcript?.length) value = "minutes";
  if (value === "visuals" && !bundle?.structure?.visuals?.length) value = "minutes";
  return value;
}
