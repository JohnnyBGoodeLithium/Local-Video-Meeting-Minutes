import { EN_COPY, EN_META } from "./product-copy.js?v=20260904p117";
import { enhanceProductDemo } from "./product-demo.js?v=20260904p117";

"use strict";

const WORKSPACE_KEY = "meeting-minutes:workspace:v1";
const supportedLanguages = new Set(["zh-CN", "en"]);
const textNodes = [...document.querySelectorAll("[data-i18n]")];
const htmlNodes = [...document.querySelectorAll("[data-i18n-html]")];
const ariaNodes = [...document.querySelectorAll("[data-i18n-aria]")];
const languageButtons = [...document.querySelectorAll("[data-ui-language]")];
const originalText = new Map(textNodes.map(node => [node, node.textContent]));
const originalHtml = new Map(htmlNodes.map(node => [node, node.innerHTML]));
const originalAria = new Map(ariaNodes.map(node => [node, node.getAttribute("aria-label") || ""]));
const originalMeta = Object.freeze({
  title: document.title,
  description: document.querySelector('meta[name="description"]')?.content || "",
});

let currentLanguage = "zh-CN";
let correctionUndone = false;

function readWorkspaceLanguage() {
  try {
    const saved = JSON.parse(localStorage.getItem(WORKSPACE_KEY) || "{}") || {};
    return supportedLanguages.has(saved.uiLanguage) ? saved.uiLanguage : "zh-CN";
  } catch (_) {
    return "zh-CN";
  }
}

function writeWorkspaceLanguage(language) {
  try {
    const saved = JSON.parse(localStorage.getItem(WORKSPACE_KEY) || "{}") || {};
    saved.uiLanguage = language;
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify(saved));
  } catch (_) {
    // Language switching still works when storage is blocked.
  }
}

function translated(key, fallback) {
  return EN_COPY[key] ?? fallback;
}

function setMeta(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.content = value;
}

const demo = enhanceProductDemo(document.querySelector("[data-product-demo]"));

function renderCorrectionState() {
  const root = document.querySelector("[data-correction-demo]");
  const button = document.querySelector("[data-correction-toggle]");
  const status = document.querySelector("[data-correction-status]");
  if (!root || !button || !status) return;
  root.classList.toggle("undone", correctionUndone);
  if (correctionUndone) {
    button.textContent = currentLanguage === "en" ? EN_COPY.restoreChange : "恢复更改";
    status.textContent = currentLanguage === "en"
      ? EN_COPY.changeUndone
      : "更改已撤销，原始来源已恢复。";
  } else {
    button.textContent = currentLanguage === "en" ? EN_COPY.undo : originalText.get(button);
    status.textContent = currentLanguage === "en"
      ? EN_COPY.changePreviewed
      : originalText.get(status);
  }
}

function applyLanguage(language, {persist = false} = {}) {
  const next = supportedLanguages.has(language) ? language : "zh-CN";
  const english = next === "en";
  currentLanguage = next;
  document.documentElement.lang = next;
  document.documentElement.dataset.uiLanguage = next;

  for (const node of textNodes) {
    node.textContent = english
      ? translated(node.dataset.i18n, originalText.get(node))
      : originalText.get(node);
  }
  for (const node of htmlNodes) {
    node.innerHTML = english
      ? translated(node.dataset.i18nHtml, originalHtml.get(node))
      : originalHtml.get(node);
  }
  for (const node of ariaNodes) {
    node.setAttribute("aria-label", english
      ? translated(node.dataset.i18nAria, originalAria.get(node))
      : originalAria.get(node));
  }

  const title = english ? EN_META.title : originalMeta.title;
  const description = english ? EN_META.description : originalMeta.description;
  document.title = title;
  setMeta('meta[name="description"]', description);
  setMeta('meta[property="og:title"]', title);
  setMeta('meta[property="og:description"]', description);
  setMeta('meta[name="twitter:title"]', title);
  setMeta('meta[name="twitter:description"]', description);

  for (const button of languageButtons) {
    const active = button.dataset.uiLanguage === next;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  demo.setLanguage(next);
  renderCorrectionState();
  if (persist) writeWorkspaceLanguage(next);
}

languageButtons.forEach(button => button.addEventListener("click", () => {
  applyLanguage(button.dataset.uiLanguage, {persist: true});
}));

document.querySelector("[data-verify-toggle]")?.addEventListener("click", event => {
  const button = event.currentTarget;
  const expanded = button.getAttribute("aria-expanded") !== "true";
  button.setAttribute("aria-expanded", String(expanded));
  document.querySelector("[data-verify-source]")?.classList.toggle("focused", expanded);
});

document.querySelector("[data-correction-toggle]")?.addEventListener("click", () => {
  correctionUndone = !correctionUndone;
  renderCorrectionState();
});

applyLanguage(readWorkspaceLanguage());
document.documentElement.dataset.productReady = "true";

const staticProductVersion = document.documentElement.dataset.staticProductVersion;
const versionNode = document.querySelector("#product-version");
if (staticProductVersion && versionNode) {
  versionNode.textContent = `v${staticProductVersion}`;
  versionNode.hidden = false;
} else {
  fetch("/api/health", {cache: "no-store"})
    .then(response => response.ok ? response.json() : Promise.reject(new Error("health unavailable")))
    .then(health => {
      const value = health.product?.version;
      if (!versionNode || !value) return;
      versionNode.textContent = `v${value}`;
      versionNode.hidden = false;
    })
    .catch(() => {});
}

if (location.hash) {
  const target = document.querySelector(location.hash);
  if (target) requestAnimationFrame(() => target.scrollIntoView());
}
