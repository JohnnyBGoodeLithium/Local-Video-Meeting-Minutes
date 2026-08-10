/* 会议列表 + 回顾工作台 */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const state = {
  meetings: [],
  slug: null,
  bundle: null,
  speakers: null,   // /api/speakers 缓存
  poller: null,
  assistantRefs: [],
  assistantHistory: [],
  assistantMessages: [],
  assistantBusy: false,
  assistantNextIntent: null,
};

/* ---------- 工具 ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r;
}

async function jget(path) {
  const r = await api(path);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function toast(msg) {
  $("#job-status").textContent = msg;
}

/* ---------- 会议列表 ---------- */

async function loadMeetings() {
  const d = await jget("/api/meetings");
  state.meetings = d.meetings;
  renderMeetingList();
}

function renderMeetingList() {
  const q = $("#search").value.trim().toLowerCase();
  const ul = $("#meeting-list");
  ul.innerHTML = "";
  for (const m of state.meetings) {
    if (q && !`${m.title || ""} ${m.date || ""} ${m.slug}`.toLowerCase().includes(q)) continue;
    const li = document.createElement("li");
    li.className = "meeting-item" + (m.slug === state.slug ? " active" : "");
    const meta = [
      m.date,
      m.duration ? fmt(m.duration) : null,
      m.speaker_count ? `${m.speaker_count} 人` : null,
      m.has_minutes ? "可回顾" : "待生成纪要",
    ].filter(Boolean).join(" · ");
    li.innerHTML =
      `<div class="m-title">${esc(m.title || m.slug)}</div>` +
      `<div class="m-meta">${esc(meta)}</div>`;
    const del = document.createElement("button");
    del.type = "button";
    del.className = "m-del";
    del.textContent = "✕";
    del.title = "删除会议";
    del.onclick = ev => deleteMeeting(ev, m.slug);
    li.appendChild(del);
    li.onclick = () => loadMeeting(m.slug);
    ul.appendChild(li);
  }
}

/* ---------- 删除会议 ---------- */

async function deleteMeeting(ev, slug) {
  ev.stopPropagation();
  const meeting = state.meetings.find(m => m.slug === slug);
  if (!confirm(`删除会议「${meeting?.title || slug}」？\n逐字稿、纪要、截图和音视频都会删除，且无法恢复。`)) return;
  const r = await api(`/api/meetings/${encodeURIComponent(slug)}/delete`, { method: "POST" });
  if (!r.ok) { toast(`删除失败: ${r.status}`); return; }
  toast(`已删除 ${slug}`);
  if (state.slug === slug) {
    state.slug = null;
    state.bundle = null;
    $("#meeting-title").textContent = "选择一场会议";
    $("#meeting-meta").textContent = "阅读纪要、追问内容并修正记录";
    $("#transcript").innerHTML = '<p class="placeholder">← 选择一场会议</p>';
    $("#minutes").innerHTML = '<p class="placeholder">纪要内容</p>';
    $("#player-holder").innerHTML = '<p class="placeholder">播放器</p>';
    $("#timeline").innerHTML = "";
    $(".player-box").classList.add("media-collapsed");
    $("#media-toggle").textContent = "展开播放";
    $("#media-toggle").disabled = true;
    $("#regen-btn").disabled = true;
    $("#refine-btn").disabled = true;
    resetAssistant();
  }
  loadMeetings();
}

/* ---------- 会议详情 ---------- */

function player() { return $("#player-holder video") || $("#player-holder audio"); }

async function loadMeeting(slug) {
  const changed = state.slug !== slug;
  state.slug = slug;
  if (changed) {
    resetAssistant();
    $(".player-box").classList.add("media-collapsed");
    $("#media-toggle").textContent = "展开播放";
  }
  renderMeetingList();
  const b = await jget(`/api/meetings/${encodeURIComponent(slug)}/bundle`);
  state.bundle = b;
  $("#meeting-title").textContent = b.title || slug;
  $("#meeting-meta").textContent = [
    b.date,
    b.duration ? `${fmt(b.duration)} 时长` : null,
    b.speaker_count ? `${b.speaker_count} 位发言人` : null,
    b.transcript?.length ? `${b.transcript.length} 段逐字稿` : null,
  ].filter(Boolean).join(" · ") || "会议记录";
  renderPlayer();
  renderTranscript();
  renderMinutes();
  $("#regen-btn").disabled = false;
  $("#refine-btn").disabled = false;
  const hasMedia = b.has_video || b.has_audio;
  $("#media-toggle").disabled = !hasMedia;
}

function renderPlayer() {
  const b = state.bundle;
  const holder = $("#player-holder");
  holder.innerHTML = "";
  let el;
  if (b.has_video) {
    el = document.createElement("video");
    el.src = `/api/meetings/${encodeURIComponent(state.slug)}/media/video`;
    el.controls = true;
  } else if (b.has_audio) {
    el = document.createElement("audio");
    el.src = `/api/meetings/${encodeURIComponent(state.slug)}/media/audio`;
    el.controls = true;
  } else {
    holder.innerHTML = '<p class="placeholder">无媒体文件</p>';
    buildTimeline(0);
    return;
  }
  el.addEventListener("loadedmetadata", () => buildTimeline(el.duration));
  el.addEventListener("timeupdate", onTimeUpdate);
  holder.appendChild(el);
  buildTimeline(b.duration || 0);
}

/* ---------- 时间轴（页区间分段 + 刻度 + 议题标记） ---------- */

const PAGE_COLORS = ["#4f7cff", "#22a06b", "#e2a13c", "#c25050", "#8a5cd6", "#2ba3b8", "#b8609a"];

function buildTimeline(duration) {
  const b = state.bundle || { slides: [], topics: [] };
  const tl = $("#timeline");
  tl.innerHTML = "";
  if (!duration) duration = b.duration || 1;
  tl.dataset.dur = duration;

  // 页/相机区间分段
  for (const p of b.slides) {
    const color = p.kind === "camera" ? "#666" : PAGE_COLORS[(p.page - 1) % PAGE_COLORS.length];
    for (const [s, e] of (p.ranges || [])) {
      const seg = document.createElement("div");
      seg.className = "tl-seg";
      seg.style.left = (s / duration * 100) + "%";
      seg.style.width = Math.max(0.5, (e - s) / duration * 100) + "%";
      seg.style.background = color;
      seg.dataset.start = s;
      const label = p.kind === "camera" ? "画面" : `第${p.page}页`;
      seg.addEventListener("mouseenter", ev => showTip(ev, p, label));
      seg.addEventListener("mousemove", ev => moveTip(ev));
      seg.addEventListener("mouseleave", hideTip);
      seg.addEventListener("click", () => seek(s));
      tl.appendChild(seg);
    }
  }
  // 分钟刻度
  const step = duration > 5400 ? 600 : duration > 1500 ? 300 : 60;
  for (let t = 0; t <= duration; t += step) {
    const tick = document.createElement("div");
    tick.className = "tl-tick";
    tick.style.left = (t / duration * 100) + "%";
    tick.title = fmt(t);
    const lab = document.createElement("span");
    lab.textContent = fmt(t);
    tick.appendChild(lab);
    tl.appendChild(tick);
  }
  // 议题/页标记点
  for (const tp of b.topics || []) {
    const mk = document.createElement("div");
    mk.className = "tl-marker";
    mk.style.left = (tp.start / duration * 100) + "%";
    mk.title = `${fmt(tp.start)} ${tp.title}`;
    mk.addEventListener("click", () => seek(tp.start));
    tl.appendChild(mk);
  }
  // 播放头
  const head = document.createElement("div");
  head.className = "tl-head";
  tl.appendChild(head);
  // 空白处点击 seek
  tl.addEventListener("click", ev => {
    if (ev.target !== tl) return;
    const r = tl.getBoundingClientRect();
    seek((ev.clientX - r.left) / r.width * duration);
  });
}

function showTip(ev, page, label) {
  const tip = $("#tl-tip");
  let html = `<div class="tip-title">${esc(label)} · ${fmt(page.first)}</div>`;
  if (page.image) {
    html += `<img src="/api/meetings/${encodeURIComponent(state.slug)}/file?path=${encodeURIComponent("slides/" + page.image)}">`;
  }
  tip.innerHTML = html;
  tip.classList.remove("hidden");
  moveTip(ev);
}

function moveTip(ev) {
  const tip = $("#tl-tip");
  tip.style.left = Math.min(window.innerWidth - 240, ev.clientX + 12) + "px";
  tip.style.top = (ev.clientY - tip.offsetHeight - 14) + "px";
}

function hideTip() { $("#tl-tip").classList.add("hidden"); }

function seek(t) {
  const p = player();
  if (p) {
    $(".player-box").classList.remove("media-collapsed");
    $("#media-toggle").textContent = "收起播放";
    p.currentTime = t;
    p.play().catch(() => {});
  }
}

function onTimeUpdate() {
  const p = player();
  if (!p || !state.bundle) return;
  const t = p.currentTime;
  const tl = $("#timeline");
  const dur = parseFloat(tl.dataset.dur || 0);
  const head = $(".tl-head", tl);
  if (head && dur) head.style.left = (t / dur * 100) + "%";
  // 高亮当前轮
  const turns = state.bundle.transcript;
  let cur = -1;
  for (let i = 0; i < turns.length; i++) {
    if (turns[i].start <= t) cur = i; else break;
  }
  $$(".turn.playing").forEach(el => el.classList.remove("playing"));
  if (cur >= 0) {
    const el = $(`#turn-${cur}`);
    if (el) {
      el.classList.add("playing");
      if ($("#follow").checked) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }
}

/* ---------- 转写区 ---------- */

function renderTranscript() {
  const box = $("#transcript");
  box.innerHTML = "";
  state.bundle.transcript.forEach((t, i) => {
    const div = document.createElement("div");
    div.className = "turn";
    div.id = `turn-${i}`;
    div.dataset.index = i;
    const chipCls = t.voice ? "chip" : "chip disabled";
    div.innerHTML =
      `<span class="tc" title="点击跳转">[${fmt(t.start)}]</span>` +
      `<span class="${chipCls}" title="${t.voice ? "点击绑定说话人" : "无对应声纹"}">${esc(t.speaker)}</span>` +
      `<span class="txt">${esc(t.text)}</span>` +
      `<button type="button" class="quote-turn" title="引用这一轮到会议助手">引用</button>`;
    $(".tc", div).onclick = () => seek(t.start);
    if (t.voice) $(".chip", div).onclick = () => openBind(t.voice, t.speaker);
    $(".quote-turn", div).onclick = ev => {
      ev.stopPropagation();
      addReferenceRange(i, i);
    };
    box.appendChild(div);
  });
  if (!state.bundle.transcript.length)
    box.innerHTML = '<p class="placeholder">无逐字稿</p>';
}

/* ---------- 纪要区 ---------- */

function renderMinutes() {
  const box = $("#minutes");
  box.innerHTML = state.bundle.minutes_html || '<p class="placeholder">暂无纪要</p>';
}

/* ---------- 本地会议助手：结构化逐字稿引用 ---------- */

function setAssistantThread(open) {
  $("#assistant-thread")?.classList.toggle("hidden", !open);
}

function resetAssistant() {
  state.assistantRefs = [];
  state.assistantHistory = [];
  state.assistantMessages = [];
  state.assistantBusy = false;
  state.assistantNextIntent = null;
  if ($("#assistant-refs")) renderAssistantRefs();
  if ($("#assistant-messages")) renderAssistantMessages();
  setAssistantThread(false);
  if ($("#assistant-input")) {
    $("#assistant-input").value = "";
    $("#assistant-input").placeholder = "问这场会议，或告诉我如何修改纪要…";
  }
}

function referenceGroups() {
  const indexes = [...new Set(state.assistantRefs)].sort((a, b) => a - b);
  const groups = [];
  for (const idx of indexes) {
    if (!groups.length || idx !== groups[groups.length - 1].at(-1) + 1) groups.push([idx]);
    else groups[groups.length - 1].push(idx);
  }
  return groups;
}

function addReferenceRange(start, end, intent = null) {
  if (!state.bundle) return;
  const lo = Math.max(0, Math.min(start, end));
  const hi = Math.min(state.bundle.transcript.length - 1, Math.max(start, end));
  for (let i = lo; i <= hi; i++) state.assistantRefs.push(i);
  state.assistantRefs = [...new Set(state.assistantRefs)].sort((a, b) => a - b).slice(0, 30);
  state.assistantNextIntent = intent;
  renderAssistantRefs();
  if (intent === "edit") {
    $("#assistant-input").placeholder = "说明要怎样把这段内容更新到纪要…";
  } else if (intent === "ask") {
    $("#assistant-input").placeholder = "针对这段逐字稿提问…";
  }
  $("#assistant-input").focus();
}

function renderAssistantRefs() {
  const box = $("#assistant-refs");
  if (!box) return;
  box.innerHTML = "";
  if (!state.bundle || !state.assistantRefs.length) return;
  for (const group of referenceGroups()) {
    const turns = group.map(i => state.bundle.transcript[i]).filter(Boolean);
    if (!turns.length) continue;
    const card = document.createElement("div");
    card.className = "assistant-ref";
    const speakers = [...new Set(turns.map(t => t.speaker))];
    const excerpt = turns.map(t => t.text).join(" ").slice(0, 120);
    card.innerHTML =
      `<button type="button" class="ref-remove" title="移除引用">×</button>` +
      `<b>逐字稿 ${fmt(turns[0].start)}–${fmt(turns.at(-1).end)}</b>` +
      `<span class="dim">${esc(speakers.join("、"))} · ${turns.length}轮</span>` +
      `<span class="ref-excerpt">${esc(excerpt)}${excerpt.length >= 120 ? "…" : ""}</span>`;
    $(".ref-remove", card).onclick = () => {
      const removing = new Set(group);
      state.assistantRefs = state.assistantRefs.filter(i => !removing.has(i));
      renderAssistantRefs();
    };
    card.onclick = ev => {
      if (ev.target.closest(".ref-remove")) return;
      highlightTurns(group);
      seek(turns[0].start);
    };
    box.appendChild(card);
  }
}

function highlightTurns(indexes) {
  $$(".turn.referenced").forEach(el => el.classList.remove("referenced"));
  for (const i of indexes) $(`#turn-${i}`)?.classList.add("referenced");
  $(`#turn-${indexes[0]}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

function addAssistantMessage(message) {
  state.assistantMessages.push(message);
  renderAssistantMessages();
}

function citedText(text, sources) {
  const ids = new Set((sources || []).map(s => s.id));
  return esc(text).replace(/【(T\d+)】/g, (all, id) =>
    ids.has(id) ? `<button type="button" class="source-link" data-source="${id}">${all}</button>` : all);
}

function renderAssistantMessages() {
  const box = $("#assistant-messages");
  if (!box) return;
  if (!state.assistantMessages.length) {
    box.innerHTML = '<p class="placeholder">你可以直接追问整场会议；引用逐字稿后，回答和修改会优先使用这些内容。</p>';
    return;
  }
  box.innerHTML = "";
  for (const msg of state.assistantMessages) {
    const el = document.createElement("div");
    el.className = `assistant-msg ${msg.role}`;
    el.innerHTML = `<div class="msg-role">${msg.role === "user" ? "你" : "助手"}</div>` +
      `<div class="msg-body">${citedText(msg.content, msg.sources)}</div>`;
    if (msg.proposal) {
      const p = msg.proposal;
      if (p.status === "applied") {
        el.innerHTML += `<div class="edit-card edit-result"><span class="applied">已更新会议纪要</span>` +
          `<button type="button" class="undo-edit" data-id="${esc(p.proposal_id)}">撤销</button></div>`;
      } else if (p.status === "undone") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">这次修改已撤销，纪要已恢复。</span></div>';
      } else if (p.status === "cancelled") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">这次修改已取消。</span></div>';
      } else if (p.status === "superseded") {
        el.innerHTML += '<div class="edit-card edit-result"><span class="dim">正在继续调整，旧方案不会写入。</span></div>';
      } else {
        el.innerHTML +=
          `<div class="edit-card">` +
          `<div class="edit-card-kicker">准备更新 · ${esc(p.target_heading)}</div>` +
          `<div class="edit-summary">${esc(p.summary || "已根据要求整理修改")}</div>` +
          `<div class="edit-actions">` +
          `<button type="button" class="apply-edit primary" data-id="${esc(p.proposal_id)}">保存到纪要</button>` +
          `<button type="button" class="adjust-edit">继续调整</button>` +
          `<button type="button" class="dismiss-edit">取消</button>` +
          `</div>` +
          `<div class="edit-after"><span>修改后</span><pre>${esc(p.after || "")}</pre></div>` +
          `<details><summary>查看完整修改与原内容</summary>` +
          `<div class="compare-label">完整修改后</div><pre>${esc(p.after || "")}</pre>` +
          `<div class="compare-label">修改前</div><pre>${esc(p.before || "")}</pre></details></div>`;
      }
    }
    $$(".source-link", el).forEach(btn => {
      btn.onclick = () => {
        const src = (msg.sources || []).find(s => s.id === btn.dataset.source);
        if (!src) return;
        highlightTurns(src.turn_indexes || []);
        seek(src.start || 0);
      };
    });
    const apply = $(".apply-edit", el);
    if (apply) apply.onclick = () => applyAssistantEdit(apply.dataset.id, apply);
    const undo = $(".undo-edit", el);
    if (undo) undo.onclick = () => undoAssistantEdit(undo.dataset.id, undo);
    const adjust = $(".adjust-edit", el);
    if (adjust) adjust.onclick = () => {
      const p = msg.proposal;
      const msgIndex = state.assistantMessages.indexOf(msg);
      const original = state.assistantMessages.slice(0, msgIndex).reverse()
        .find(item => item.role === "user")?.content || p.summary || "修改纪要";
      p.status = "superseded";
      state.assistantNextIntent = "edit";
      renderAssistantMessages();
      $("#assistant-input").value = `${original}\n请继续调整：`;
      $("#assistant-input").focus();
    };
    const dismiss = $(".dismiss-edit", el);
    if (dismiss) dismiss.onclick = () => {
      msg.proposal.status = "cancelled";
      renderAssistantMessages();
    };
    box.appendChild(el);
  }
  box.scrollTop = box.scrollHeight;
}

function inferAssistantIntent(message) {
  if (state.assistantNextIntent) return state.assistantNextIntent;
  const editPatterns = [
    /(写入|加入|添加|补充|更新|同步).{0,10}(纪要|总结|行动项|决定|结论)/,
    /(纪要|总结|行动项|决定|结论).{0,10}(改成|改为|修改|改写|润色|精简|删除|移除|补充|更新)/,
    /^(请)?(帮我|把|将)?\s*(修改|改写|润色|精简|删除|移除|补充|更新)/,
    /(请|帮我).{0,8}(修改|改写|补充|更新|写入|加入|删除|润色)/,
    /(把|将).{0,20}(改成|改为|写入|加入|补充到|删除)/,
  ];
  return editPatterns.some(pattern => pattern.test(message)) ? "edit" : "ask";
}

function assistantError(detail) {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.detail === "string") return detail.detail;
  return "请求失败";
}

async function sendAssistant() {
  if (!state.slug || state.assistantBusy) return;
  const input = $("#assistant-input");
  const message = input.value.trim();
  if (!message) return;
  const intent = inferAssistantIntent(message);
  state.assistantNextIntent = null;
  const common = {
    message,
    turn_indexes: state.assistantRefs,
    transcript_revision: state.bundle.transcript_revision,
  };
  const path = intent === "edit"
    ? `/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/preview`
    : `/api/meetings/${encodeURIComponent(state.slug)}/assistant/chat`;
  const body = intent === "edit"
    ? { ...common, minutes_revision: state.bundle.minutes_revision }
    : { ...common, history: state.assistantHistory.slice(-8) };
  addAssistantMessage({ role: "user", content: message, sources: [] });
  setAssistantThread(true);
  input.value = "";
  input.placeholder = "问这场会议，或告诉我如何修改纪要…";
  state.assistantBusy = true;
  $("#assistant-send").disabled = true;
  $("#assistant-state").textContent = intent === "edit" ? "正在生成修改预览…" : "正在查找证据并回答…";
  try {
    const r = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(assistantError(j.detail));
    if (intent === "edit") {
      addAssistantMessage({
        role: "assistant",
        content: "我整理了一项纪要更新，请确认后再保存。",
        sources: j.sources || [],
        proposal: j,
      });
    } else {
      addAssistantMessage({ role: "assistant", content: j.answer, sources: j.sources || [] });
      state.assistantHistory.push({ role: "user", content: message });
      state.assistantHistory.push({ role: "assistant", content: j.answer });
      state.assistantHistory = state.assistantHistory.slice(-8);
    }
  } catch (e) {
    addAssistantMessage({ role: "assistant", content: `无法完成：${e.message}`, sources: [] });
  } finally {
    state.assistantBusy = false;
    $("#assistant-send").disabled = false;
    $("#assistant-state").textContent = "";
  }
}

async function applyAssistantEdit(proposalId, button) {
  button.disabled = true;
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id: proposalId }),
  });
  const j = await r.json();
  if (!r.ok) {
    button.disabled = false;
    addAssistantMessage({ role: "assistant", content: `应用失败：${assistantError(j.detail)}`, sources: [] });
    return;
  }
  state.bundle = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
  renderMinutes();
  const msg = state.assistantMessages.find(item => item.proposal?.proposal_id === proposalId);
  if (msg) msg.proposal.status = "applied";
  renderAssistantMessages();
}

async function undoAssistantEdit(proposalId, button) {
  button.disabled = true;
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/assistant/edit/undo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proposal_id: proposalId }),
  });
  const j = await r.json();
  if (!r.ok) {
    button.disabled = false;
    addAssistantMessage({ role: "assistant", content: `撤销失败：${assistantError(j.detail)}`, sources: [] });
    return;
  }
  state.bundle = await jget(`/api/meetings/${encodeURIComponent(state.slug)}/bundle`);
  renderMinutes();
  const msg = state.assistantMessages.find(item => item.proposal?.proposal_id === proposalId);
  if (msg) msg.proposal.status = "undone";
  renderAssistantMessages();
}

function setupTranscriptSelection() {
  $("#transcript").addEventListener("mouseup", () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    const startEl = (range.startContainer.nodeType === 1
      ? range.startContainer : range.startContainer.parentElement)?.closest?.(".turn");
    const endEl = (range.endContainer.nodeType === 1
      ? range.endContainer : range.endContainer.parentElement)?.closest?.(".turn");
    if (!startEl || !endEl) return;
    const rect = range.getBoundingClientRect();
    const pop = $("#quote-pop");
    pop.dataset.start = startEl.dataset.index;
    pop.dataset.end = endEl.dataset.index;
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 290, rect.right + 8))}px`;
    pop.style.top = `${Math.max(8, rect.top - 36)}px`;
    pop.classList.remove("hidden");
  });
  $$("#quote-pop [data-intent]").forEach(btn => {
    btn.onclick = () => {
      const pop = $("#quote-pop");
      addReferenceRange(Number(pop.dataset.start), Number(pop.dataset.end), btn.dataset.intent);
      pop.classList.add("hidden");
      window.getSelection()?.removeAllRanges();
    };
  });
  document.addEventListener("mousedown", ev => {
    if (!ev.target.closest("#quote-pop") && !ev.target.closest("#transcript"))
      $("#quote-pop").classList.add("hidden");
  });
}

async function regenMinutes(refineModel) {
  if (!state.slug) return;
  const qs = refineModel ? `?refine=${encodeURIComponent(refineModel)}` : "";
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/regen_minutes${qs}`,
    { method: "POST" });
  const job = await r.json();
  if (!r.ok) { toast(`重生成失败: ${job.detail || r.status}`); return; }
  toast(`纪要${refineModel ? "精修" : "重生成"}作业 ${job.id} 已排队…`);
  pollJob(job.id, j => {
    if (j.status === "done") {
      toast(`纪要${refineModel ? "精修" : "重生成"}完成 (${job.id})`);
      loadMeeting(state.slug);
    } else if (j.status === "failed" || j.status === "cancelled") {
      toast(`作业 ${job.id} ${j.status}，详情见 /api/jobs/${job.id}`);
    } else {
      toast(`作业 ${job.id} ${j.status}…`);
    }
  });
}

/* ---------- 说话人绑定弹框 ---------- */

async function ensureSpeakers() {
  if (!state.speakers) state.speakers = await jget("/api/speakers");
  return state.speakers;
}

async function openBind(voice, name) {
  $("#bind-voice").textContent = voice;
  $("#bind-name").textContent = name;
  $("#bind-input").value = "";
  $("#bind-cands").innerHTML = "";
  const sp = await ensureSpeakers();
  $("#person-list").innerHTML =
    sp.persons.map(p => `<option value="${esc(p.name)}">`).join("");
  const sample = $("#bind-sample");
  sample.src = `/api/meetings/${encodeURIComponent(state.slug)}/samples/${encodeURIComponent(name)}.wav`;
  sample.onerror = () => { sample.style.display = "none"; };
  sample.style.display = "";
  $("#bind-mask").classList.remove("hidden");
  $("#bind-input").focus();
  $("#bind-ok").onclick = () => doBind(voice);
}

function closeBind() { $("#bind-mask").classList.add("hidden"); }

async function doBind(voice, create) {
  const name = $("#bind-input").value.trim();
  if (!name) return;
  const r = await api(`/api/meetings/${encodeURIComponent(state.slug)}/bind`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice, name, create: !!create }),
  });
  const j = await r.json();
  if (r.status === 409) {
    // 未精确命中 → 展示候选(点击回填) + “新建此人”按钮
    const d = j.detail || {};
    const cands = d.candidates || [];
    let html = cands.length
      ? "候选：" + cands.map(c =>
        `<button type="button" class="cand" data-name="${esc(c.name)}">${esc(c.name)}</button>`).join("")
      : "库里没有这个名字。";
    html += `<button type="button" id="bind-create" class="cand create">新建「${esc(name)}」</button>`;
    $("#bind-cands").innerHTML = html;
    $$("#bind-cands .cand[data-name]").forEach(btn =>
      btn.onclick = () => { $("#bind-input").value = btn.dataset.name; });
    const cb = $("#bind-create");
    if (cb) cb.onclick = () => doBind(voice, true);
    return;
  }
  if (!r.ok) { toast(`绑定失败: ${j.detail || r.status}`); return; }
  closeBind();
  state.speakers = null;  // 库已变，刷新缓存
  resetAssistant();       // 逐字稿 revision 已变化，旧引用作废
  toast(`已绑定为 ${j.name}（${j.turns} 轮）`);
  await loadMeeting(state.slug);  // 逐字稿立即更新
}

/* ---------- 上传与作业 ---------- */

async function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  if ($("#skip-vl") && $("#skip-vl").checked) fd.append("no_vl", "1");
  const r = await api("/api/upload", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) { toast(`上传被拒: ${j.detail || r.status}`); return; }
  toast(`作业 ${j.id} (${j.route}) 已创建，目标会议 ${j.meeting}`);
  pollJob(j.id, jj => {
    if (jj.status === "done") {
      toast(`作业 ${j.id} 完成`);
      loadMeetings();
    } else if (jj.status === "failed") {
      toast(`作业 ${j.id} 失败 (rc=${jj.rc})`);
    } else {
      toast(`作业 ${j.id} (${j.route}): ${jj.status}`);
    }
  });
}

function pollJob(id, onUpdate) {
  if (state.poller) clearInterval(state.poller);
  state.poller = setInterval(async () => {
    try {
      const j = await jget(`/api/jobs/${id}`);
      onUpdate(j);
      if (["done", "failed", "cancelled"].includes(j.status)) {
        clearInterval(state.poller);
        state.poller = null;
      }
    } catch (e) { /* 网络抖动忽略 */ }
  }, 2000);
}

/* ---------- 作业队列面板 ---------- */

async function pollJobs() {
  try {
    const d = await jget("/api/jobs");
    renderJobs(d.jobs.slice(0, 8));
  } catch (e) { /* 忽略 */ }
}

function renderJobs(jobs) {
  const ul = $("#jobs-list");
  if (!ul) return;
  const activeJobs = jobs.filter(j => j.status === "queued" || j.status === "running");
  $("#jobs-panel").classList.toggle("hidden", activeJobs.length === 0);
  ul.innerHTML = "";
  for (const j of activeJobs) {
    const li = document.createElement("li");
    const active = j.status === "queued" || j.status === "running";
    li.innerHTML =
      `<span class="j-name" title="${esc(j.id)}">${esc(j.meeting || j.kind)}</span>` +
      `<span class="j-st st-${esc(j.status)}">${esc(j.status)}</span>`;
    if (active) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "j-cancel";
      btn.textContent = "取消";
      btn.onclick = async () => {
        await api(`/api/jobs/${j.id}/cancel`, { method: "POST" });
        pollJobs();
      };
      li.appendChild(btn);
    }
    li.title = (j.log || []).slice(-1)[0] || j.id;
    ul.appendChild(li);
  }
}

/* ---------- 事件 ---------- */

function init() {
  $("#search").addEventListener("input", renderMeetingList);
  $("#regen-btn").onclick = () => regenMinutes("");
  $("#refine-btn").onclick = () => {
    if (confirm("用 122B 大模型整体重写纪要？首次调用需加载模型(数分钟)，且会挤占常驻模型。"))
      regenMinutes("qwen3.5-122b-a10b-planner");
  };
  $("#bind-cancel").onclick = closeBind;
  $("#bind-mask").addEventListener("click", e => { if (e.target.id === "bind-mask") closeBind(); });

  $("#media-toggle").onclick = () => {
    const box = $(".player-box");
    box.classList.toggle("media-collapsed");
    $("#media-toggle").textContent = box.classList.contains("media-collapsed")
      ? "展开播放" : "收起播放";
  };
  $("#assistant-thread-close").onclick = () => setAssistantThread(false);
  $("#assistant-send").onclick = sendAssistant;
  $("#assistant-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendAssistant();
    }
  });
  setupTranscriptSelection();

  const dz = $("#dropzone");
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", e => {
    e.preventDefault();
    dz.classList.remove("over");
    uploadFiles(e.dataTransfer.files);
  });
  $("#pick-btn").onclick = () => $("#file-input").click();
  $("#file-input").addEventListener("change", e => uploadFiles(e.target.files));

  pollJobs();
  setInterval(pollJobs, 4000);
  loadMeetings();
}

document.addEventListener("DOMContentLoaded", init);
