/* Transcript DOM projection. All application state and side effects arrive as callbacks. */

import { splitTurnChunks, turnReviewUnits } from "./transcript.js?v=20260903p115";

export function transcriptScrollAnchor(box) {
  const bounds = box.getBoundingClientRect();
  const turn = [...box.querySelectorAll(".turn[id]")]
    .find(item => item.getBoundingClientRect().bottom > bounds.top + 2);
  return turn ? { id: turn.id, offset: turn.getBoundingClientRect().top - bounds.top } : null;
}

function clickWithoutSelection(callback) {
  const selection = window.getSelection();
  if (selection && !selection.isCollapsed && String(selection)) return;
  callback();
}

export function renderTranscriptView(options) {
  const {
    box, transcript = [], pendingByTurn = new Map(), translations = new Map(),
    sourceLanguages = new Map(), transcriptMode = "original", translationTarget,
    evidenceBilingual = new Set(), expandedOriginals = new Set(),
    correctionSelected = new Set(), correctionVoice = null, correctionMode = "idle",
    correctionProtected = new Set(), bundleDuration = 0, preserveScroll = true, isEnglish = false,
    translationActive = false,
    sourceNeedsTranslation, formatTime, escapeHtml, speakerColor, ui, turnEnd,
    onSelectUnit, onOpenBind, onToggleCorrection, onQuote, onEdit, onToggleOriginal,
  } = options;
  const anchor = preserveScroll ? transcriptScrollAnchor(box) : null;
  const reviewUnits = [];
  box.innerHTML = "";

  transcript.forEach((turn, turnIndex) => {
    const div = document.createElement("div");
    div.className = "turn";
    div.id = `turn-${turnIndex}`;
    div.dataset.index = turnIndex;
    if (pendingByTurn.has(turnIndex)) div.classList.add("review-pending");
    const chipClass = turn.voice ? "chip" : "chip disabled";
    const translated = translations.get(turnIndex);
    const sourceLanguage = sourceLanguages.get(turnIndex);
    const forcedComparison = evidenceBilingual.has(turnIndex);
    const mode = forcedComparison ? "comparison" : transcriptMode;
    const canTranslate = translated
      && sourceNeedsTranslation(translated.source_language, translationTarget);
    const showOriginal = mode === "original" || !canTranslate || mode === "comparison"
      || expandedOriginals.has(turnIndex);
    const showTranslation = canTranslate && mode !== "original";
    const duration = Math.max(0,
      (Number(turn.end ?? transcript[turnIndex + 1]?.start ?? bundleDuration) || 0)
      - (Number(turn.start) || 0));
    const chunks = showOriginal && !showTranslation ? splitTurnChunks(turn.text, duration) : null;
    const pieces = chunks || [{ text: turn.text, charStart: 0 }];
    const firstUnitIndex = reviewUnits.length;
    reviewUnits.push(...turnReviewUnits(
      turn, turnIndex, turnEnd(turnIndex), pieces, firstUnitIndex));
    div.dataset.reviewUnit = firstUnitIndex;

    let textHtml = '<span class="turn-text">';
    if (showOriginal)
      textHtml += `<span class="txt source-text">${escapeHtml(chunks ? chunks[0].text : turn.text)}</span>`;
    if (showTranslation) {
      textHtml += `<span class="txt translated-text ${mode === "translated" ? "primary" : ""}">${escapeHtml(translated.translated_text)}</span>`;
      if (translated.warnings?.includes("number_mismatch"))
        textHtml += '<span class="translation-warning">数字可能需要核对</span>';
      if (mode === "translated") {
        textHtml += `<button type="button" class="toggle-turn-original" data-index="${turnIndex}">`
          + `${expandedOriginals.has(turnIndex) ? "收起原文" : `${escapeHtml(String(translated.source_language).toUpperCase())} 原文`}</button>`;
      }
    } else if (mode !== "original" && sourceLanguage
        && sourceNeedsTranslation(sourceLanguage, translationTarget)) {
      const priority = evidenceBilingual.has(turnIndex) ? " priority" : "";
      textHtml += `<span class="turn-translation-pending${priority}">`
        + `${priority ? "优先翻译中" : (translationActive ? "等待翻译" : "等待继续翻译")}</span>`;
    }
    textHtml += "</span>";
    div.innerHTML =
      `<span class="tc" title="点击跳转">[${formatTime(turn.start)}]</span>`
      + `<span class="${chipClass}" style="border-left: 3px solid ${speakerColor(turn.speaker)}" `
      + `title="${escapeHtml(turn.speaker)} · ${turn.voice ? "点击核对人物身份" : "暂无可核对身份"}" `
      + `aria-label="说话人：${escapeHtml(turn.speaker)}">${escapeHtml(turn.speaker)}</span>`
      + textHtml
      + `<button type="button" class="edit-turn" title="${isEnglish ? "Listen and correct original transcript" : "核听并修正原语言逐字稿"}">${isEnglish ? "Correct" : "修正"}</button>`
      + '<button type="button" class="quote-turn" title="引用这一轮到会议助手">引用</button>';
    const correctionActive = correctionMode === "select_examples";
    if (correctionSelected.has(turnIndex)) div.classList.add("speaker-correction-selected");
    if (correctionActive && turn.voice === correctionVoice) {
      div.classList.add("speaker-correction-candidate");
      if (correctionProtected.has(turnIndex)) div.classList.add("speaker-correction-confirmed");
    }
    else if (correctionActive) div.classList.add("speaker-correction-muted");
    div.querySelector(".tc").onclick = event => {
      event.stopPropagation();
      onSelectUnit(firstUnitIndex);
    };
    div.querySelector(".chip").onclick = event => {
      event.stopPropagation();
      if (correctionActive) onToggleCorrection(turnIndex, turn.voice);
      else if (turn.voice) onOpenBind(turn.voice, turn.speaker, {
        index: turnIndex, anchor: event.currentTarget,
      });
    };
    div.addEventListener("click", () => clickWithoutSelection(() => {
      if (correctionActive) onToggleCorrection(turnIndex, turn.voice);
      else onSelectUnit(firstUnitIndex);
    }));
    div.querySelector(".quote-turn").onclick = event => {
      event.stopPropagation();
      onQuote(turnIndex);
    };
    div.querySelector(".edit-turn").onclick = event => {
      event.stopPropagation();
      onEdit(turnIndex, pendingByTurn.get(turnIndex));
    };
    const toggleOriginal = div.querySelector(".toggle-turn-original");
    if (toggleOriginal) toggleOriginal.onclick = event => {
      event.stopPropagation();
      onToggleOriginal(turnIndex);
    };
    box.appendChild(div);

    if (chunks) {
      for (const [offset, chunk] of chunks.slice(1).entries()) {
        const chunkIndex = offset + 1;
        const unitIndex = firstUnitIndex + chunkIndex;
        const at = reviewUnits[unitIndex].start;
        const continuation = document.createElement("div");
        continuation.className = "turn turn-cont";
        continuation.dataset.index = turnIndex;
        continuation.dataset.reviewUnit = unitIndex;
        continuation.innerHTML =
          `<span class="tc" title="点击跳转(按字符位置估算)">[${formatTime(at)}]</span>`
          + `<span class="chip cont-speaker" style="border-left: 3px solid ${speakerColor(turn.speaker)}" `
          + `title="${escapeHtml(turn.speaker)}" aria-label="说话人：${escapeHtml(turn.speaker)}">${escapeHtml(turn.speaker)}</span>`
          + `<span class="turn-text"><span class="cont-mark">${ui("continued")} · ${chunkIndex + 1}/${chunks.length}</span>`
          + `<span class="txt source-text">${escapeHtml(chunk.text)}</span></span>`;
        continuation.querySelector(".tc").onclick = event => {
          event.stopPropagation();
          onSelectUnit(unitIndex);
        };
        continuation.addEventListener("click", () => clickWithoutSelection(() => {
          if (correctionActive) onToggleCorrection(turnIndex, turn.voice);
          else onSelectUnit(unitIndex);
        }));
        box.appendChild(continuation);
      }
    }
  });

  if (!transcript.length) box.innerHTML = '<p class="placeholder">无逐字稿</p>';
  if (anchor) {
    const restored = document.getElementById(anchor.id);
    if (restored) {
      const bounds = box.getBoundingClientRect();
      box.scrollTop += restored.getBoundingClientRect().top - bounds.top - anchor.offset;
    }
  } else if (!preserveScroll) box.scrollTop = 0;
  return reviewUnits;
}
