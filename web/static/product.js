import { EN_COPY, EN_META } from "./product-copy.js?v=20260828p104";

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

function applyLanguage(language, { persist = false } = {}) {
  const next = supportedLanguages.has(language) ? language : "zh-CN";
  const english = next === "en";
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

  document.title = english ? EN_META.title : originalMeta.title;
  const description = document.querySelector('meta[name="description"]');
  if (description) description.content = english ? EN_META.description : originalMeta.description;

  for (const button of languageButtons) {
    const active = button.dataset.uiLanguage === next;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.setAttribute("aria-selected", String(active));
  }
  if (persist) writeWorkspaceLanguage(next);
}

languageButtons.forEach(button => button.addEventListener("click", () => {
  applyLanguage(button.dataset.uiLanguage, { persist: true });
}));
applyLanguage(readWorkspaceLanguage());

fetch("/api/health", { cache: "no-store" })
  .then(response => response.ok ? response.json() : Promise.reject(new Error("health unavailable")))
  .then(health => {
    const version = document.querySelector("#product-version");
    const value = health.product?.version;
    if (!version || !value) return;
    version.textContent = `v${value}`;
    version.hidden = false;
  })
  .catch(() => {});

const revealItems = [...document.querySelectorAll(".reveal")];
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (reduceMotion || !("IntersectionObserver" in window)) {
  revealItems.forEach(item => item.classList.add("visible"));
} else {
  const revealObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add("visible");
      revealObserver.unobserve(entry.target);
    }
  }, { rootMargin: "0px 0px -8%", threshold: 0.08 });
  revealItems.forEach(item => revealObserver.observe(item));
}

const navLinks = [...document.querySelectorAll("#product-nav a")];
const sections = navLinks.map(link => document.querySelector(link.getAttribute("href"))).filter(Boolean);

if ("IntersectionObserver" in window) {
  const navObserver = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    navLinks.forEach(link => link.classList.toggle(
      "active", link.getAttribute("href") === `#${visible.target.id}`));
  }, { rootMargin: "-25% 0px -60%", threshold: [0, 0.1, 0.4] });
  sections.forEach(section => navObserver.observe(section));
}

if (location.hash) {
  const target = document.querySelector(location.hash);
  if (target) {
    target.querySelectorAll(".reveal").forEach(item => item.classList.add("visible"));
    requestAnimationFrame(() => target.scrollIntoView());
  }
}
