/* No network, frameworks or package data: also embedded in offline Viewer. */
(() => {
  "use strict";
  const root = document.documentElement;
  const key = "minutes.appearance.v1";
  const system = matchMedia("(prefers-color-scheme: dark)");
  const modes = ["system", "light", "dark"], colors = ["blue", "teal", "violet", "amber"];
  let state = {mode: "system", accent: "blue"}, control;
  function read(value) {
    try {
      const saved = JSON.parse(value);
      state = {mode: modes.includes(saved?.mode) ? saved.mode : "system",
        accent: colors.includes(saved?.accent) ? saved.accent : "blue"};
    } catch (_) { state = {mode: "system", accent: "blue"}; }
  }
  try { read(localStorage.getItem(key)); } catch (_) { /* Private/file mode stays usable. */ }
  function apply() {
    root.dataset.fluentTheme = state.mode === "system" ? (system.matches ? "dark" : "light") : state.mode;
    root.dataset.accent = state.accent;
    root.dataset.appearanceMode = state.mode;
    if (control) {
      control.querySelector('[name="appearance-mode"]').value = state.mode;
      control.querySelector('[name="appearance-accent"]').value = state.accent;
    }
  }
  apply();
  system.addEventListener("change", apply);
  addEventListener("storage", event => { if (event.key === key || event.key === null) { read(event.newValue); apply(); } });
  function mount() {
    const host = document.querySelector(".header-actions") || document.querySelector("body > header");
    if (!host) return;
    control = document.createElement("details"); control.className = "appearance-control";
    control.innerHTML = '<summary><span aria-hidden="true">◐</span><span class="appearance-label"></span></summary>'
      + '<div class="appearance-panel"><label><span data-appearance-copy="mode"></span><select name="appearance-mode"></select></label>'
      + '<label><span data-appearance-copy="accent"></span><select name="appearance-accent"></select></label>'
      + '<p data-appearance-copy="hint"></p></div>';
    host.append(control);
    function translate() {
      const en = root.lang.startsWith("en");
      const title = en ? "Appearance" : "外观";
      control.querySelector("summary").setAttribute("aria-label", title);
      control.querySelector(".appearance-label").textContent = title;
      const words = en ? {mode:"Theme", accent:"Highlight color", hint:"Saved in this browser. Other devices can choose their own appearance."}
        : {mode:"明暗模式", accent:"高亮颜色", hint:"保存在当前浏览器；其他设备可独立选择外观。"};
      for (const node of control.querySelectorAll("[data-appearance-copy]")) node.textContent = words[node.dataset.appearanceCopy];
      for (const [name, values, labels] of [["mode", modes, en ? ["Follow system", "Light", "Dark"] : ["跟随系统", "浅色", "深色"]],
        ["accent", colors, en ? ["Blue", "Teal", "Violet", "Amber"] : ["蓝色", "青绿", "紫色", "琥珀"]]]) {
        const select = control.querySelector(`[name="appearance-${name}"]`);
        select.replaceChildren(...values.map((value, index) => new Option(labels[index], value)));
      }
      apply();
    }
    control.addEventListener("change", event => {
      if (event.target.name === "appearance-mode") state.mode = event.target.value;
      if (event.target.name === "appearance-accent") state.accent = event.target.value;
      apply(); try { localStorage.setItem(key, JSON.stringify(state)); } catch (_) { /* Session-only preference. */ }
    });
    document.addEventListener("pointerdown", event => { if (!control.contains(event.target)) control.open = false; });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && control.open) { event.preventDefault(); event.stopPropagation(); control.open = false; control.querySelector("summary").focus(); }
    }, true);
    new MutationObserver(translate).observe(root, {attributes: true, attributeFilter: ["lang"]});
    translate();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once:true}); else mount();
})();
