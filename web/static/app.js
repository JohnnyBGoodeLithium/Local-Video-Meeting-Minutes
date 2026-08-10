/* 会议列表 + 妙计式详情页 */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const state = {
  meetings: [],
  slug: null,
  bundle: null,
  speakers: null,   // /api/speakers 缓存
  poller: null,
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
    if (q && !m.slug.toLowerCase().includes(q)) continue;
    const li = document.createElement("li");
    li.className = "meeting-item" + (m.slug === state.slug ? " active" : "");
    const badges = [
      m.has_minutes ? "纪要" : null,
      m.has_video ? "视频" : null,
    ].filter(Boolean).join(" · ");
    li.innerHTML =
      `<div class="m-title">${esc(m.slug)}</div>` +
      `<div class="m-meta">${m.turns}轮 · ${m.pages}页` +
      (m.duration ? ` · ${fmt(m.duration)}` : "") +
      (badges ? ` · ${badges}` : "") + `</div>`;
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
  if (!confirm(`删除会议「${slug}」？\n目录内全部文件(逐字稿/纪要/截图/音轨)将被删除，不可恢复。`)) return;
  const r = await api(`/api/meetings/${encodeURIComponent(slug)}/delete`, { method: "POST" });
  if (!r.ok) { toast(`删除失败: ${r.status}`); return; }
  toast(`已删除 ${slug}`);
  if (state.slug === slug) {
    state.slug = null;
    state.bundle = null;
    $("#tr-title").textContent = "转写";
    $("#transcript").innerHTML = '<p class="placeholder">← 选择一场会议</p>';
    $("#minutes").innerHTML = '<p class="placeholder">纪要内容</p>';
    $("#player-holder").innerHTML = '<p class="placeholder">播放器</p>';
    $("#timeline").innerHTML = "";
    $("#regen-btn").disabled = true;
    $("#refine-btn").disabled = true;
  }
  loadMeetings();
}

/* ---------- 会议详情 ---------- */

function player() { return $("#player-holder video") || $("#player-holder audio"); }

async function loadMeeting(slug) {
  state.slug = slug;
  renderMeetingList();
  const b = await jget(`/api/meetings/${encodeURIComponent(slug)}/bundle`);
  state.bundle = b;
  $("#tr-title").textContent = slug;
  renderPlayer();
  renderTranscript();
  renderMinutes();
  $("#regen-btn").disabled = false;
  $("#refine-btn").disabled = false;
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
  if (p) { p.currentTime = t; p.play(); }
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
    const chipCls = t.voice ? "chip" : "chip disabled";
    div.innerHTML =
      `<span class="tc" title="点击跳转">[${fmt(t.start)}]</span>` +
      `<span class="${chipCls}" title="${t.voice ? "点击绑定说话人" : "无对应声纹"}">${esc(t.speaker)}</span>` +
      `<span class="txt">${esc(t.text)}</span>`;
    $(".tc", div).onclick = () => seek(t.start);
    if (t.voice) $(".chip", div).onclick = () => openBind(t.voice, t.speaker);
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
  ul.innerHTML = "";
  for (const j of jobs) {
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
