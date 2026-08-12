"use strict";

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
