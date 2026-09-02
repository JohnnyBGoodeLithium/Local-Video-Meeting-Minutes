import { DEMO_STATES } from "./product-copy.js?v=20260902p112";

const DEFAULT_SELECTION = Object.freeze({meeting: "maya", video: "thermal"});
const SUPPORTED_LANGUAGES = new Set(["zh-CN", "en"]);

export function normalizeDemoLanguage(language) {
  return SUPPORTED_LANGUAGES.has(language) ? language : "zh-CN";
}

export function resolveDemoState(mode, selection, language) {
  const safeMode = mode === "video" ? "video" : "meeting";
  const choices = DEMO_STATES[safeMode];
  const safeSelection = choices[selection] ? selection : DEFAULT_SELECTION[safeMode];
  return Object.freeze({
    mode: safeMode,
    selection: safeSelection,
    language: normalizeDemoLanguage(language),
    values: choices[safeSelection][normalizeDemoLanguage(language)],
  });
}

export function segmentIsFocused(owner, selection) {
  return owner === selection;
}

function announce(control, language) {
  const messages = {
    previous: {"zh-CN": "已定位到上一段虚构发言。", en: "Moved to the previous fictional segment."},
    replay: {"zh-CN": "正在重播当前虚构片段。", en: "Replaying the current fictional segment."},
    next: {"zh-CN": "已定位到下一段虚构发言。", en: "Moved to the next fictional segment."},
  };
  return messages[control]?.[normalizeDemoLanguage(language)] || "";
}

export function enhanceProductDemo(root, initialLanguage = "zh-CN") {
  if (!root) return {setLanguage() {}};

  let language = normalizeDemoLanguage(initialLanguage);
  let mode = "meeting";
  const selection = {...DEFAULT_SELECTION};
  const live = root.querySelector("[data-demo-live]");

  function renderPanel(panelMode) {
    const panel = root.querySelector(`[data-demo-panel="${panelMode}"]`);
    if (!panel) return;
    const state = resolveDemoState(panelMode, selection[panelMode], language);
    panel.querySelectorAll("[data-demo-bind]").forEach(node => {
      const value = state.values[node.dataset.demoBind];
      if (value !== undefined) node.textContent = value;
    });
    panel.querySelectorAll("[data-demo-choice]").forEach(button => {
      const active = button.dataset.demoChoice === state.selection;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    panel.querySelectorAll("[data-demo-segment]").forEach(segment => {
      const focused = segmentIsFocused(segment.dataset.demoSegment, state.selection);
      segment.classList.toggle("focused", focused);
      segment.classList.toggle("muted", !focused);
    });
  }

  function showMode(nextMode) {
    mode = nextMode === "video" ? "video" : "meeting";
    root.dataset.demoModeActive = mode;
    root.querySelectorAll("[data-demo-mode]").forEach(tab => {
      const active = tab.dataset.demoMode === mode;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    root.querySelectorAll("[data-demo-panel]").forEach(panel => {
      panel.hidden = panel.dataset.demoPanel !== mode;
    });
    renderPanel(mode);
  }

  root.querySelectorAll("[data-demo-mode]").forEach(tab => {
    tab.addEventListener("click", () => showMode(tab.dataset.demoMode));
    tab.addEventListener("keydown", event => {
      if (!new Set(["ArrowLeft", "ArrowRight"]).has(event.key)) return;
      event.preventDefault();
      const next = tab.dataset.demoMode === "meeting" ? "video" : "meeting";
      showMode(next);
      root.querySelector(`[data-demo-mode="${next}"]`)?.focus();
    });
  });

  root.querySelectorAll("[data-demo-choice]").forEach(button => {
    button.addEventListener("click", () => {
      const panel = button.closest("[data-demo-panel]");
      if (!panel) return;
      selection[panel.dataset.demoPanel] = button.dataset.demoChoice;
      renderPanel(panel.dataset.demoPanel);
    });
  });

  root.querySelectorAll("[data-demo-evidence]").forEach(button => {
    button.addEventListener("click", () => {
      const detail = button.parentElement?.querySelector("[data-demo-evidence-detail]");
      if (!detail) return;
      const expanded = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(expanded));
      detail.hidden = !expanded;
    });
  });

  root.querySelectorAll("[data-demo-control]").forEach(button => {
    button.addEventListener("click", () => {
      if (live) live.textContent = announce(button.dataset.demoControl, language);
    });
  });

  showMode(mode);
  return {
    setLanguage(nextLanguage) {
      language = normalizeDemoLanguage(nextLanguage);
      renderPanel("meeting");
      renderPanel("video");
    },
  };
}
