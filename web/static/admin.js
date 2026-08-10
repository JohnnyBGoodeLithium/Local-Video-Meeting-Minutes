/* 人员身份、声音审核与 Org Chart 图形编辑 */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg) { $("#admin-status").textContent = msg; }
function norm(s) { return String(s || "").normalize("NFKC").trim().toLowerCase().replace(/\s+/g, " "); }
function splitNames(s) { return String(s || "").split(/[,，]/).map(x => x.trim()).filter(Boolean); }
function clone(value) { return JSON.parse(JSON.stringify(value)); }

async function jsend(path, method, body) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await r.json();
  return { ok: r.ok, status: r.status, body: j };
}

/* ================= 页面切换 ================= */

function showAdminView(name) {
  $$(".admin-view").forEach(el => el.classList.toggle("hidden", el.id !== `view-${name}`));
  $$("[data-admin-view]").forEach(btn => btn.classList.toggle("active", btn.dataset.adminView === name));
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
}

/* ================= 人员与声音 ================= */

let speakers = { persons: [], voices: [] };
let reviewingVoice = null;

const NAME_LABELS = {
  org: "Org",
  chinese: "中文",
  pinyin: "全拼",
  english_display: "英文",
  other: "其他",
};

async function loadSpeakers() {
  const r = await fetch("/api/speakers");
  speakers = await r.json();
  renderSpeakers();
}

function personNames(person) {
  return person.names || [{ value: person.name, type: "org", verified: true },
    ...(person.aliases || []).map(value => ({ value, type: "other", verified: true }))];
}

function renderNameBadges(person) {
  return personNames(person).map(n =>
    `<span class="name-badge"><i>${esc(NAME_LABELS[n.type] || "其他")}</i>${esc(n.value)}</span>`).join(" ");
}

function renderSpeakers() {
  const filter = $("#voice-filter").value.trim().toLowerCase();
  $("#n-persons").textContent = speakers.persons.length;
  const peopleBody = $("#persons-tbl tbody");
  peopleBody.innerHTML = "";
  for (const person of speakers.persons) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><b>${esc(person.display_name || person.name)}</b><br><span class="dim">${esc(person.id)}</span></td>` +
      `<td><div class="name-badges">${renderNameBadges(person)}</div></td>` +
      `<td>${person.voices}</td>` +
      `<td><button type="button" data-act="edit">编辑名称</button></td>`;
    $("[data-act=edit]", tr).onclick = () => openPersonEditor(person);
    peopleBody.appendChild(tr);
  }

  const voices = speakers.voices.filter(v => {
    const haystack = `${v.id} ${v.name || ""} ${v.label_hint || ""} ${(v.sources || []).join(" ")}`.toLowerCase();
    return !filter || haystack.includes(filter);
  });
  $("#n-voices").textContent = voices.length;
  const voiceBody = $("#voices-tbl tbody");
  voiceBody.innerHTML = "";
  for (const voice of voices) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><code>${esc(voice.id)}</code><br><span class="dim">${esc(voice.label_hint || "")}</span></td>` +
      `<td><audio class="voice-inline-audio" controls preload="none" src="/api/speakers/${encodeURIComponent(voice.id)}/sample"></audio></td>` +
      `<td>${voice.person_id ? esc(voice.name) : '<span class="status-pill pending">待确认</span>'}</td>` +
      `<td title="${esc((voice.sources || []).join(", "))}">${(voice.sources || []).length} 场</td>` +
      `<td class="acts"><button type="button" data-act="review">审核</button>` +
      (voice.person_id ? `<button type="button" data-act="unbind">解绑</button>` : "") +
      `<button type="button" data-act="merge">合并</button></td>`;
    $("[data-act=review]", tr).onclick = () => openVoiceReview(voice);
    $("[data-act=unbind]", tr)?.addEventListener("click", () => unbindVoice(voice.id));
    $("[data-act=merge]", tr).onclick = () => mergeVoice(voice.id);
    voiceBody.appendChild(tr);
  }
}

function openVoiceReview(voice) {
  reviewingVoice = voice;
  $("#voice-review-title").textContent = `审核声音 ${voice.id}`;
  $("#voice-review-meta").textContent = `${voice.label_hint || "无提示名"} · ${(voice.sources || []).length} 场来源`;
  $("#voice-review-audio").src = `/api/speakers/${encodeURIComponent(voice.id)}/sample`;
  $("#voice-person-input").value = voice.person_id ? voice.name : "";
  $("#voice-person-list").innerHTML = speakers.persons.flatMap(person =>
    personNames(person).map(n => `<option value="${esc(n.value)}">${esc(person.display_name || person.name)}</option>`)
  ).join("");
  $("#voice-candidates").innerHTML = "";
  $("#voice-review-mask").classList.remove("hidden");
  $("#voice-person-input").focus();
}

function closeVoiceReview() {
  $("#voice-review-audio").pause();
  $("#voice-review-mask").classList.add("hidden");
  reviewingVoice = null;
}

function renderVoiceCandidates(candidates) {
  const box = $("#voice-candidates");
  box.innerHTML = candidates.length ? '<div class="candidate-title">相似名称仅供选择，不会自动绑定</div>' :
    '<div class="dim">没有匹配的已确认名称，可以明确新建人员。</div>';
  for (const candidate of candidates) {
    const person = speakers.persons.find(p => p.id === candidate.id);
    const voice = person && speakers.voices.find(v => v.person_id === person.id);
    const card = document.createElement("div");
    card.className = "candidate-card";
    card.innerHTML = `<div><b>${esc(candidate.name)}</b>` +
      `${candidate.score ? `<span class="dim"> 名称相似度 ${Math.round(candidate.score * 100)}%</span>` : ""}` +
      `<div class="name-badges">${person ? renderNameBadges(person) : ""}</div></div>` +
      (voice ? `<audio controls preload="none" src="/api/speakers/${encodeURIComponent(voice.id)}/sample"></audio>` : "") +
      `<button type="button">选择</button>`;
    $("button", card).onclick = () => {
      $("#voice-person-input").value = (person?.display_name || candidate.name);
      box.innerHTML = "";
    };
    box.appendChild(card);
  }
}

async function bindReviewedVoice(create) {
  if (!reviewingVoice) return;
  const name = $("#voice-person-input").value.trim();
  if (!name) return;
  const r = await jsend("/api/speakers/bind", "POST", { voice: reviewingVoice.id, name, create });
  if (r.status === 409) {
    renderVoiceCandidates(r.body.detail?.candidates || []);
    return;
  }
  if (!r.ok) { toast(`绑定失败：${r.body.detail || r.status}`); return; }
  toast(`${reviewingVoice.id} 已绑定为 ${r.body.name}${r.body.how === "新建" ? "（待归属）" : ""}`);
  closeVoiceReview();
  await loadSpeakers();
}

async function unbindVoice(voiceId) {
  if (!confirm(`解绑 ${voiceId}？声纹会保留，人员关系会清除。`)) return;
  const r = await jsend("/api/speakers/unbind", "POST", { voice: voiceId });
  if (!r.ok) { toast(`解绑失败：${r.body.detail || r.status}`); return; }
  toast(`已解绑 ${voiceId}`);
  loadSpeakers();
}

async function mergeVoice(voiceId) {
  const keep = prompt(`把 ${voiceId} 合并到哪条声纹？请输入保留的 voice id。`);
  if (!keep) return;
  if (!confirm(`确认把 ${voiceId} 的人员关系和来源合并到 ${keep}？`)) return;
  const r = await jsend("/api/speakers/merge", "POST", { keep, drop: [voiceId] });
  if (!r.ok) { toast(`合并失败：${r.body.detail || r.status}`); return; }
  toast(`已合并到 ${keep}`);
  loadSpeakers();
}

function firstName(person, type) {
  return personNames(person).find(n => n.type === type)?.value || "";
}

function openPersonEditor(person) {
  $("#person-edit-id").value = person.id;
  $("#person-display-name").value = person.display_name || person.name;
  $("#person-org-name").value = firstName(person, "org") || person.name;
  $("#person-chinese-name").value = firstName(person, "chinese");
  $("#person-pinyin-name").value = firstName(person, "pinyin");
  $("#person-english-name").value = firstName(person, "english_display");
  $("#person-other-names").value = personNames(person).filter(n => n.type === "other").map(n => n.value).join(", ");
  $("#person-edit-mask").classList.remove("hidden");
}

function closePersonEditor() { $("#person-edit-mask").classList.add("hidden"); }

async function savePersonIdentity() {
  const id = $("#person-edit-id").value;
  const displayName = $("#person-display-name").value.trim();
  const names = [];
  const add = (value, type) => { if (value.trim()) names.push({ value: value.trim(), type, verified: true }); };
  add($("#person-org-name").value, "org");
  add($("#person-chinese-name").value, "chinese");
  add($("#person-pinyin-name").value, "pinyin");
  add($("#person-english-name").value, "english_display");
  for (const value of splitNames($("#person-other-names").value)) add(value, "other");
  const r = await jsend(`/api/speakers/person/${encodeURIComponent(id)}`, "PUT",
    { display_name: displayName, names });
  if (!r.ok) { toast(`保存失败：${r.body.detail || r.status}`); return; }
  closePersonEditor();
  toast(`首选显示名已更新为 ${r.body.display_name}`);
  loadSpeakers();
}

/* ================= Org Chart 图编辑 ================= */

let org = [];
let unplacedPeople = [];
let selectedOrgId = null;
let draggedOrgId = null;
let draggedPersonId = null;
let orgUndo = [];
let collapsedOrgIds = new Set();
let orgIndex = new Map();
let orgChildrenIndex = new Map();

function localOrgId() {
  return `o_local_${globalThis.crypto?.randomUUID?.() || `${Date.now()}_${Math.random()}`}`;
}

async function loadOrg() {
  const r = await fetch("/api/orgchart");
  const data = await r.json();
  org = data.entries;
  unplacedPeople = data.unplaced_people || [];
  selectedOrgId = null;
  orgUndo = [];
  indexOrg();
  collapsedOrgIds = defaultOrgCollapse();
  renderOrg();
}

function indexOrg() {
  orgIndex = new Map(org.map(entry => [entry.id, entry]));
  orgChildrenIndex = new Map();
  for (const entry of org) {
    const parent = entry.manager_id || null;
    if (!orgChildrenIndex.has(parent)) orgChildrenIndex.set(parent, []);
    orgChildrenIndex.get(parent).push(entry);
  }
}

function orgById(id) { return orgIndex.get(id); }
function orgChildren(id) { return orgChildrenIndex.get(id || null) || []; }

function defaultOrgCollapse(force = false) {
  if (!force && org.length <= 40) return new Set();
  const collapsed = new Set();
  const roots = org.filter(entry => !entry.manager_id || !orgById(entry.manager_id));
  const walk = (entry, depth, trail) => {
    if (trail.has(entry.id)) return;
    const children = orgChildren(entry.id);
    if (depth >= 1 && children.length) collapsed.add(entry.id);
    const next = new Set(trail);
    next.add(entry.id);
    for (const child of children) walk(child, depth + 1, next);
  };
  for (const root of roots) walk(root, 0, new Set());
  return collapsed;
}

function descendantIds(id) {
  const out = new Set();
  const walk = parent => {
    for (const child of orgChildren(parent)) {
      if (out.has(child.id)) continue;
      out.add(child.id);
      walk(child.id);
    }
  };
  walk(id);
  return out;
}

function rememberOrg() {
  orgUndo.push({ org: clone(org), unplacedPeople: clone(unplacedPeople) });
  if (orgUndo.length > 30) orgUndo.shift();
  $("#org-undo").disabled = false;
}

function undoOrg() {
  const previous = orgUndo.pop();
  if (!previous) return;
  org = previous.org;
  unplacedPeople = previous.unplacedPeople;
  if (selectedOrgId && !orgById(selectedOrgId)) selectedOrgId = null;
  $("#org-undo").disabled = orgUndo.length === 0;
  renderOrg();
}

function orgVisibleIds() {
  const q = norm($("#org-search").value);
  if (!q) return null;
  const visible = new Set();
  for (const entry of org) {
    const text = norm(`${entry.name} ${(entry.aliases || []).join(" ")} ${entry.title} ${entry.team}`);
    if (!text.includes(q)) continue;
    let cursor = entry;
    while (cursor) {
      visible.add(cursor.id);
      cursor = orgById(cursor.manager_id);
    }
  }
  return visible;
}

function renderOrg() {
  indexOrg();
  const box = $("#org-tree");
  box.innerHTML = "";
  const visible = orgVisibleIds();
  renderUnplacedPeople();
  const roots = org.filter(entry => !entry.manager_id || !orgById(entry.manager_id));
  if (!roots.length) {
    box.innerHTML = '<p class="placeholder">暂无节点。点“新增根节点”开始。</p>';
  } else {
    const ul = document.createElement("ul");
    ul.className = "org-root-list";
    for (const root of roots) {
      if (!visible || visible.has(root.id)) ul.appendChild(orgNode(root, visible, new Set()));
    }
    if (ul.childElementCount) box.appendChild(ul);
    else box.innerHTML = '<p class="placeholder">没有匹配的组织节点。</p>';
  }
  const unresolved = org.filter(e => e.status === "unresolved").length;
  const conflicts = org.filter(e => e.status === "conflict").length;
  const rootsCount = roots.length;
  $("#org-review-summary").textContent = `${org.length} 人 · ${rootsCount} 个根 · ${collapsedOrgIds.size} 处折叠 · ${unresolved} 待确认上级 · ${conflicts} 冲突`;
  renderOrgInspector();
}

function renderUnplacedPeople() {
  const box = $("#org-unplaced");
  if (!unplacedPeople.length) {
    box.innerHTML = "";
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = '<b>待归属</b><span class="dim">拖到上级节点</span>';
  for (const person of unplacedPeople) {
    const chip = document.createElement("div");
    chip.className = "unplaced-person";
    chip.draggable = true;
    chip.textContent = person.display_name;
    chip.title = (person.names || []).map(n => n.value).join(" · ");
    chip.addEventListener("dragstart", ev => {
      draggedPersonId = person.id;
      draggedOrgId = null;
      ev.dataTransfer.setData("text/plain", `person:${person.id}`);
    });
    box.appendChild(chip);
  }
}

function orgNode(entry, visible, trail) {
  const li = document.createElement("li");
  const row = document.createElement("div");
  row.className = "org-node-row";
  const allChildren = orgChildren(entry.id);
  const children = allChildren.filter(child => !visible || visible.has(child.id));
  const isCollapsed = !visible && collapsedOrgIds.has(entry.id);
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = `org-toggle${children.length ? "" : " spacer"}`;
  if (children.length) {
    toggle.textContent = isCollapsed ? "▸" : "▾";
    toggle.title = isCollapsed ? `展开 ${children.length} 个直属下属` : "折叠直属下属";
    toggle.setAttribute("aria-expanded", String(!isCollapsed));
    toggle.onclick = ev => {
      ev.stopPropagation();
      if (isCollapsed) collapsedOrgIds.delete(entry.id);
      else collapsedOrgIds.add(entry.id);
      renderOrg();
    };
  } else {
    toggle.tabIndex = -1;
    toggle.setAttribute("aria-hidden", "true");
  }
  row.appendChild(toggle);
  const card = document.createElement("div");
  card.className = `org-card status-${entry.status || "confirmed"}` +
    (entry.id === selectedOrgId ? " selected" : "");
  card.draggable = true;
  card.dataset.id = entry.id;
  card.innerHTML = `<div class="org-card-main"><b>${esc(entry.name)}</b>` +
    `<span>${esc([entry.title, entry.team].filter(Boolean).join(" · ") || "未填写职务")}</span></div>` +
    `<div class="org-card-side">` +
    (["unresolved", "conflict", "draft"].includes(entry.status)
      ? `<i>${entry.status === "unresolved" ? "待确认上级" : entry.status === "conflict" ? "关系冲突" : "提取草稿"}</i>` : "") +
    (allChildren.length ? `<small>${allChildren.length} 直属</small>` : "") + `</div>`;
  card.onclick = () => {
    $(".org-card.selected")?.classList.remove("selected");
    selectedOrgId = entry.id;
    card.classList.add("selected");
    renderOrgInspector();
  };
  card.addEventListener("dragstart", ev => {
    draggedOrgId = entry.id;
    draggedPersonId = null;
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", entry.id);
  });
  card.addEventListener("dragover", ev => { ev.preventDefault(); card.classList.add("drop-target"); });
  card.addEventListener("dragleave", () => card.classList.remove("drop-target"));
  card.addEventListener("drop", ev => {
    ev.preventDefault();
    card.classList.remove("drop-target");
    const payload = ev.dataTransfer.getData("text/plain");
    if (draggedPersonId || payload.startsWith("person:")) {
      placePersonInOrg(draggedPersonId || payload.slice(7), entry.id);
    } else {
      reparentOrg(draggedOrgId || payload, entry.id);
    }
  });
  row.appendChild(card);
  li.appendChild(row);

  if (trail.has(entry.id)) return li;
  const nextTrail = new Set(trail);
  nextTrail.add(entry.id);
  if (children.length && !isCollapsed) {
    const ul = document.createElement("ul");
    for (const child of children) ul.appendChild(orgNode(child, visible, nextTrail));
    li.appendChild(ul);
  }
  return li;
}

function placePersonInOrg(personId, managerId) {
  const person = unplacedPeople.find(item => item.id === personId);
  const manager = managerId ? orgById(managerId) : null;
  if (!person) return;
  const target = manager ? manager.name : "根节点";
  if (!confirm(`确认把“${person.display_name}”加入组织架构，上级设为“${target}”？`)) return;
  rememberOrg();
  const orgName = person.names?.find(n => n.type === "org")?.value || person.name || person.display_name;
  org.push({ id: localOrgId(), person_id: person.id, name: orgName, aliases: [], title: "",
    team: manager?.team || "", manager_id: managerId || null, leader: manager?.name || "",
    leader_raw: "", status: "confirmed", source_pages: [], conflicts: [], note: "" });
  unplacedPeople = unplacedPeople.filter(item => item.id !== person.id);
  if (managerId) collapsedOrgIds.delete(managerId);
  renderOrg();
}

function reparentOrg(childId, managerId) {
  const child = orgById(childId);
  const manager = managerId ? orgById(managerId) : null;
  if (!child || child.id === managerId || descendantIds(child.id).has(managerId)) {
    toast("不能把节点移动到自己或自己的下属下面");
    return;
  }
  if ((child.manager_id || null) === (managerId || null)) return;
  const target = manager ? manager.name : "根节点";
  if (!confirm(`确认把“${child.name}”的直接上级改为“${target}”？`)) return;
  rememberOrg();
  child.manager_id = managerId || null;
  child.leader = manager?.name || "";
  child.leader_raw = child.leader;
  child.status = "confirmed";
  child.conflicts = [];
  selectedOrgId = child.id;
  if (managerId) collapsedOrgIds.delete(managerId);
  renderOrg();
}

function renderOrgInspector() {
  const entry = orgById(selectedOrgId);
  $("#org-inspector-empty").classList.toggle("hidden", !!entry);
  $("#org-inspector-form").classList.toggle("hidden", !entry);
  if (!entry) return;
  $("#org-node-id").value = entry.id;
  $("#org-name").value = entry.name;
  $("#org-aliases").value = (entry.aliases || []).join(", ");
  $("#org-title").value = entry.title || "";
  $("#org-team").value = entry.team || "";
  $("#org-note").value = entry.note || "";
  const blocked = descendantIds(entry.id);
  const options = org.filter(e => e.id !== entry.id && !blocked.has(e.id));
  $("#org-manager").innerHTML = '<option value="">— 根节点 / 待归属 —</option>' +
    options.map(e => `<option value="${esc(e.id)}">${esc(e.name)}${e.title ? ` · ${esc(e.title)}` : ""}</option>`).join("");
  $("#org-manager").value = entry.manager_id || "";
  $("#org-node-meta").innerHTML =
    `<span class="status-pill ${esc(entry.status || "confirmed")}">${esc(entry.status || "confirmed")}</span>` +
    (entry.source_pages?.length ? ` 来源页 ${entry.source_pages.join("、")}` : "") +
    (entry.leader_raw && !entry.manager_id ? `<br>提取的上级原文：${esc(entry.leader_raw)}` : "") +
    (entry.conflicts?.length ? `<br>冲突候选：${esc(entry.conflicts.join("、"))}` : "");
}

function applyOrgInspector(ev) {
  ev.preventDefault();
  const entry = orgById($("#org-node-id").value);
  if (!entry) return;
  const name = $("#org-name").value.trim();
  if (!name) return;
  const managerId = $("#org-manager").value || null;
  if ((entry.manager_id || null) !== managerId) {
    const target = managerId ? orgById(managerId)?.name : "根节点 / 待归属";
    if (!confirm(`确认把“${name}”的直接上级改为“${target}”？`)) return;
  }
  rememberOrg();
  entry.name = name;
  entry.aliases = splitNames($("#org-aliases").value);
  entry.title = $("#org-title").value.trim();
  entry.team = $("#org-team").value.trim();
  entry.note = $("#org-note").value.trim();
  entry.manager_id = managerId;
  entry.leader = managerId ? orgById(managerId)?.name || "" : "";
  entry.leader_raw = entry.leader;
  entry.status = "confirmed";
  entry.conflicts = [];
  renderOrg();
  toast("节点修改已加入本地草稿，保存后写入");
}

function addOrgNode(managerId = null) {
  rememberOrg();
  const manager = orgById(managerId);
  const entry = { id: localOrgId(), person_id: null, name: "新成员", aliases: [], title: "",
    team: manager?.team || "", manager_id: managerId, leader: manager?.name || "",
    leader_raw: "", status: "confirmed", source_pages: [], conflicts: [], note: "" };
  org.push(entry);
  selectedOrgId = entry.id;
  if (managerId) collapsedOrgIds.delete(managerId);
  renderOrg();
  $("#org-name").select();
}

function deleteSelectedOrg() {
  const entry = orgById(selectedOrgId);
  if (!entry) return;
  const children = orgChildren(entry.id);
  if (!confirm(`删除“${entry.name}”？${children.length ? `其 ${children.length} 个直属下属会移动到当前上级。` : ""}`)) return;
  rememberOrg();
  for (const child of children) {
    child.manager_id = entry.manager_id || null;
    child.leader = entry.manager_id ? orgById(entry.manager_id)?.name || "" : "";
  }
  org = org.filter(e => e.id !== entry.id);
  collapsedOrgIds.delete(entry.id);
  selectedOrgId = null;
  renderOrg();
}

async function saveOrg() {
  const r = await jsend("/api/orgchart", "PUT", { entries: org });
  if (!r.ok) { toast(`保存失败：${r.body.detail || r.status}`); return; }
  toast(`已保存 ${r.body.count} 个组织节点`);
  await loadOrg();
}

async function mergeOrgDraft() {
  const r = await fetch("/api/orgchart/draft");
  const draft = await r.json();
  if (!draft.has_draft || !draft.entries.length) { toast("没有可合并的提取草稿"); return; }
  const currentByName = new Map(org.map(e => [norm(e.name), e]));
  const newCount = draft.entries.filter(e => !currentByName.has(norm(e.name))).length;
  const reviewCount = draft.entries.filter(e => ["unresolved", "conflict"].includes(e.status)).length;
  if (!confirm(`草稿包含 ${draft.entries.length} 条：新增 ${newCount} 条，${reviewCount} 条关系需确认。\n只补充新节点和空字段，不覆盖已确认上级，是否合并？`)) return;
  rememberOrg();
  const idMap = new Map();
  for (const item of draft.entries) {
    let target = currentByName.get(norm(item.name));
    if (!target) {
      target = { ...clone(item), id: org.some(e => e.id === item.id) ? localOrgId() : item.id,
        manager_id: null, status: item.status || "draft" };
      org.push(target);
      currentByName.set(norm(target.name), target);
    } else {
      if (!target.title) target.title = item.title || "";
      if (!target.team) target.team = item.team || "";
      target.source_pages = [...new Set([...(target.source_pages || []), ...(item.source_pages || [])])];
      if (item.conflicts?.length) {
        target.conflicts = [...new Set([...(target.conflicts || []), ...item.conflicts])];
        target.status = "conflict";
      }
    }
    idMap.set(item.id, target.id);
  }
  indexOrg();
  for (const item of draft.entries) {
    const target = orgById(idMap.get(item.id));
    if (!target.manager_id && item.manager_id && idMap.get(item.manager_id)) {
      target.manager_id = idMap.get(item.manager_id);
      target.leader = orgById(target.manager_id)?.name || item.leader || "";
    }
    if (!target.manager_id && item.leader_raw) {
      target.leader_raw = item.leader_raw;
      target.status = item.status || "unresolved";
    }
  }
  renderOrg();
  toast(`已合并草稿；请处理待确认关系后保存`);
}

/* ================= 参考文件 ================= */

async function loadOrgFiles() {
  const r = await fetch("/api/orgchart/files");
  const { files } = await r.json();
  const ul = $("#org-files");
  ul.innerHTML = "";
  for (const file of files) {
    const li = document.createElement("li");
    li.innerHTML = `<button type="button" data-act="view">${esc(file.name)}</button> ` +
      `<span class="dim">${file.kind} · ${file.pages} 页</span>` +
      (file.kind === "pdf" ? ` <button type="button" data-act="extract">提取草稿</button>` : "");
    $("[data-act=view]", li).onclick = () => viewOrgFile(file);
    $("[data-act=extract]", li)?.addEventListener("click", () => extractOrgFile(file.name));
    ul.appendChild(li);
  }
  if (!files.length) ul.innerHTML = '<li class="dim">暂无参考文件</li>';
}

async function extractOrgFile(name) {
  if (!confirm(`使用本地视觉模型读取“${name}”并生成待确认草稿？`)) return;
  const r = await jsend("/api/orgchart/extract", "POST", { name });
  if (!r.ok) { toast(`提取失败：${r.body.detail || r.status}`); return; }
  const id = r.body.id;
  toast(`提取作业 ${id} 已开始`);
  const timer = setInterval(async () => {
    const jr = await fetch(`/api/jobs/${id}`);
    const job = await jr.json();
    if (job.status === "done") {
      clearInterval(timer);
      toast("提取完成，可点击“合并提取草稿”检查变更");
    } else if (["failed", "cancelled"].includes(job.status)) {
      clearInterval(timer);
      toast(`提取作业 ${job.status}`);
    }
  }, 3000);
}

function viewOrgFile(file) {
  const box = $("#org-file-view");
  box.innerHTML = "";
  for (let n = 1; n <= file.pages; n++) {
    const img = document.createElement("img");
    img.src = `/api/orgchart/files/${encodeURIComponent(file.name)}/page/${n}`;
    img.alt = `${file.name} 第 ${n} 页`;
    box.appendChild(img);
  }
}

async function uploadOrgFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/orgchart/files", { method: "POST", body: fd });
  const body = await r.json();
  if (!r.ok) { toast(`上传失败：${body.detail || r.status}`); return; }
  toast(`已上传 ${body.name}`);
  loadOrgFiles();
}

/* ================= 事件 ================= */

function init() {
  $$("[data-admin-view]").forEach(btn => btn.onclick = () => showAdminView(btn.dataset.adminView));
  $("#voice-filter").addEventListener("input", renderSpeakers);
  $("#voice-bind-existing").onclick = () => bindReviewedVoice(false);
  $("#voice-create-person").onclick = () => bindReviewedVoice(true);
  $("#voice-review-cancel").onclick = closeVoiceReview;
  $("#voice-review-mask").addEventListener("click", ev => { if (ev.target.id === "voice-review-mask") closeVoiceReview(); });
  $("#person-edit-save").onclick = savePersonIdentity;
  $("#person-edit-cancel").onclick = closePersonEditor;
  $("#person-edit-mask").addEventListener("click", ev => { if (ev.target.id === "person-edit-mask") closePersonEditor(); });

  $("#org-add-root").onclick = () => addOrgNode(null);
  $("#org-add-child").onclick = () => addOrgNode(selectedOrgId);
  $("#org-delete").onclick = deleteSelectedOrg;
  $("#org-undo").onclick = undoOrg;
  $("#org-save").onclick = saveOrg;
  $("#org-reload").onclick = () => { if (confirm("放弃尚未保存的组织架构修改？")) loadOrg(); };
  $("#org-draft").onclick = mergeOrgDraft;
  $("#org-expand-all").onclick = () => { collapsedOrgIds.clear(); renderOrg(); };
  $("#org-collapse").onclick = () => { collapsedOrgIds = defaultOrgCollapse(true); renderOrg(); };
  let orgSearchTimer = null;
  $("#org-search").addEventListener("input", () => {
    clearTimeout(orgSearchTimer);
    orgSearchTimer = setTimeout(renderOrg, 120);
  });
  $("#org-inspector-form").addEventListener("submit", applyOrgInspector);
  $("#org-root-drop").addEventListener("dragover", ev => { ev.preventDefault(); ev.currentTarget.classList.add("drop-target"); });
  $("#org-root-drop").addEventListener("dragleave", ev => ev.currentTarget.classList.remove("drop-target"));
  $("#org-root-drop").addEventListener("drop", ev => {
    ev.preventDefault();
    ev.currentTarget.classList.remove("drop-target");
    const payload = ev.dataTransfer.getData("text/plain");
    if (draggedPersonId || payload.startsWith("person:")) {
      placePersonInOrg(draggedPersonId || payload.slice(7), null);
    } else {
      reparentOrg(draggedOrgId || payload, null);
    }
  });
  $("#org-upload-btn").onclick = () => $("#org-file-input").click();
  $("#org-file-input").addEventListener("change", ev => uploadOrgFile(ev.target.files[0]));

  loadSpeakers();
  loadOrg();
  loadOrgFiles();
  showAdminView(location.hash === "#org" ? "org" : "voices");
}

document.addEventListener("DOMContentLoaded", init);
