/* 声纹库 + org chart 后台 */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg) { $("#admin-status").textContent = msg; }

async function jsend(path, method, body) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await r.json();
  return { ok: r.ok, status: r.status, body: j };
}

/* ================= 声纹库 ================= */

let speakers = { persons: [], voices: [] };

async function loadSpeakers() {
  const r = await fetch("/api/speakers");
  speakers = await r.json();
  renderSpeakers();
}

function renderSpeakers() {
  const filter = $("#voice-filter").value.trim().toLowerCase();
  $("#n-persons").textContent = speakers.persons.length;

  const pb = $("#persons-tbl tbody");
  pb.innerHTML = "";
  for (const p of speakers.persons) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><b>${esc(p.name)}</b><br><span class="dim">${esc(p.id)}</span></td>` +
      `<td>${(p.aliases || []).map(a => `<span class="chip sm">${esc(a)}</span>`).join(" ")}</td>` +
      `<td>${p.voices}</td>` +
      `<td><button type="button" data-act="alias">加别名</button></td>`;
    $("button", tr).onclick = () => addAlias(p.name);
    pb.appendChild(tr);
  }

  const voices = speakers.voices.filter(v =>
    !filter || (v.sources || []).some(s => s.toLowerCase().includes(filter)));
  $("#n-voices").textContent = voices.length;
  const vb = $("#voices-tbl tbody");
  vb.innerHTML = "";
  for (const v of voices) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><code>${esc(v.id)}</code></td>` +
      `<td>${v.person_id ? esc(v.name) : '<span class="dim">(未绑定)</span>'}</td>` +
      `<td>${esc(v.label_hint || "")}</td>` +
      `<td title="${esc((v.sources || []).join(", "))}">${(v.sources || []).length} 场</td>` +
      `<td class="acts">` +
      `<button type="button" data-act="bind">绑定</button>` +
      (v.person_id ? `<button type="button" data-act="unbind">解绑</button>` : "") +
      `<button type="button" data-act="merge">并入…</button>` +
      `</td>`;
    $$("button", tr).forEach(btn => {
      if (btn.dataset.act === "bind") btn.onclick = () => bindVoice(v.id);
      if (btn.dataset.act === "unbind") btn.onclick = () => unbindVoice(v.id);
      if (btn.dataset.act === "merge") btn.onclick = () => mergeVoice(v.id);
    });
    vb.appendChild(tr);
  }
}

async function bindVoice(voiceId) {
  const name = prompt(`把声纹 ${voiceId} 绑定给谁？（自动匹配声纹库/org chart，没命中则新建）`);
  if (!name) return;
  const r = await jsend("/api/speakers/bind", "POST", { voice: voiceId, name });
  if (r.status === 409) {
    const cands = (r.body.detail && r.body.detail.candidates) || [];
    alert("没有精确命中，候选：\n" + (cands.map(c => c.name).join("\n") || "(无)") +
      "\n请用更准的名字重试。");
    return;
  }
  if (!r.ok) { alert(`失败: ${r.body.detail || r.status}`); return; }
  toast(`已绑定 ${voiceId} → ${r.body.name}`);
  loadSpeakers();
}

async function unbindVoice(voiceId) {
  if (!confirm(`解绑 ${voiceId}？（声纹保留，只清除与人的关联）`)) return;
  const r = await jsend("/api/speakers/unbind", "POST", { voice: voiceId });
  if (!r.ok) { alert(`失败: ${r.body.detail || r.status}`); return; }
  toast(`已解绑 ${voiceId}`);
  loadSpeakers();
}

async function mergeVoice(voiceId) {
  const keep = prompt(`把 ${voiceId} 并入哪条声纹？输入保留方的 voice id（如 v_0003）`);
  if (!keep) return;
  const r = await jsend("/api/speakers/merge", "POST", { keep, drop: [voiceId] });
  if (!r.ok) { alert(`失败: ${r.body.detail || r.status}`); return; }
  toast(`已并入 ${keep}（${r.body.name}）`);
  loadSpeakers();
}

async function addAlias(personName) {
  const aliases = prompt(`给 ${personName} 加别名（逗号分隔）`);
  if (!aliases) return;
  const list = aliases.split(/[,，]/).map(s => s.trim()).filter(Boolean);
  const r = await jsend("/api/speakers/alias", "POST", { person: personName, aliases: list });
  if (!r.ok) { alert(`失败: ${r.body.detail || r.status}`); return; }
  toast(`别名已更新`);
  loadSpeakers();
}

/* ================= Org chart 树编辑 ================= */

let org = [];  // 扁平 list，树按 leader 字段组装

async function loadOrg() {
  const r = await fetch("/api/orgchart");
  org = (await r.json()).entries;
  renderOrgTree();
}

function childrenOf(name) {
  return org.filter(e => (e.leader || "") === (name || ""));
}

function descendants(name) {
  const out = new Set();
  const walk = n => {
    for (const c of childrenOf(n)) { out.add(c.name); walk(c.name); }
  };
  walk(name);
  return out;
}

function renderOrgTree() {
  const box = $("#org-tree");
  box.innerHTML = "";
  const roots = childrenOf("");
  if (!roots.length) {
    box.innerHTML = '<p class="placeholder">空。点「＋根节点」开始。</p>';
    return;
  }
  const ul = document.createElement("ul");
  for (const r of roots) ul.appendChild(nodeEl(r));
  box.appendChild(ul);
}

function nodeEl(entry) {
  const li = document.createElement("li");
  const head = document.createElement("div");
  head.className = "org-node";
  head.innerHTML =
    `<span class="org-name">${esc(entry.name)}</span>` +
    `<span class="dim">${[entry.title, entry.team].filter(Boolean).map(esc).join(" · ")}</span>` +
    `<span class="acts">` +
    `<button type="button" data-act="add" title="加子节点">＋</button>` +
    `<button type="button" data-act="rename" title="改名">✎</button>` +
    `<button type="button" data-act="props" title="编辑 别名/title/team/note">⚙</button>` +
    `<button type="button" data-act="move" title="移动到其他 leader">⤴</button>` +
    `<button type="button" data-act="del" title="删除（子节点上移）">✕</button>` +
    `</span>`;
  $$("button", head).forEach(btn => {
    btn.onclick = () => orgOp(btn.dataset.act, entry);
  });
  li.appendChild(head);
  const kids = childrenOf(entry.name);
  if (kids.length) {
    const ul = document.createElement("ul");
    for (const k of kids) ul.appendChild(nodeEl(k));
    li.appendChild(ul);
  }
  return li;
}

function orgOp(act, entry) {
  if (act === "add") {
    const name = prompt(`在 ${entry.name} 下新增成员，姓名：`);
    if (!name) return;
    if (org.some(e => e.name === name)) { alert("已存在同名成员"); return; }
    org.push({ name, aliases: [], title: "", team: entry.team || "", leader: entry.name, note: "" });
  } else if (act === "rename") {
    const name = prompt("新名字：", entry.name);
    if (!name || name === entry.name) return;
    if (org.some(e => e.name === name)) { alert("已存在同名成员"); return; }
    const old = entry.name;
    entry.name = name;
    for (const e of org) if (e.leader === old) e.leader = name;  // 级联子节点
  } else if (act === "props") {
    const aliases = prompt("别名（逗号分隔）", (entry.aliases || []).join(","));
    if (aliases === null) return;
    entry.aliases = aliases.split(/[,，]/).map(s => s.trim()).filter(Boolean);
    const title = prompt("title：", entry.title || "");
    if (title === null) return;
    entry.title = title.trim();
    const team = prompt("team：", entry.team || "");
    if (team === null) return;
    entry.team = team.trim();
    const note = prompt("note：", entry.note || "");
    if (note === null) return;
    entry.note = note.trim();
  } else if (act === "move") {
    const desc = descendants(entry.name);
    const options = org.filter(e => e.name !== entry.name && !desc.has(e.name));
    const target = prompt(
      `移动到谁的下面？可选：\n${options.map(e => e.name).join(", ")}\n` +
      `（输入名字；留空 = 移到根）`);
    if (target === null) return;
    const t = target.trim();
    if (t && !options.some(e => e.name === t)) { alert("没有这个人或会形成环"); return; }
    entry.leader = t;
  } else if (act === "del") {
    if (!confirm(`删除 ${entry.name}？其直属子节点会上移到 ${entry.leader || "根"}。`)) return;
    for (const e of org) if (e.leader === entry.name) e.leader = entry.leader || "";
    org = org.filter(e => e !== entry);
  }
  renderOrgTree();
}

async function saveOrg() {
  const r = await jsend("/api/orgchart", "PUT", { entries: org });
  if (!r.ok) { alert(`保存失败: ${r.body.detail || r.status}`); return; }
  toast(`已保存 ${r.body.count} 条`);
}

/* ================= 参考文件 ================= */

async function loadOrgFiles() {
  const r = await fetch("/api/orgchart/files");
  const { files } = await r.json();
  const ul = $("#org-files");
  ul.innerHTML = "";
  for (const f of files) {
    const li = document.createElement("li");
    li.innerHTML = `<button type="button">${esc(f.name)}</button> <span class="dim">${f.kind} · ${f.pages}页</span>` +
      (f.kind === "pdf" ? ` <button type="button" class="extract" title="VL 逐页读取人名/层级 → 草稿">提取草稿</button>` : "");
    $("button", li).onclick = () => viewOrgFile(f);
    const ex = $(".extract", li);
    if (ex) ex.onclick = () => extractOrgFile(f.name);
    ul.appendChild(li);
  }
  if (!files.length) ul.innerHTML = '<li class="dim">暂无</li>';
}

async function extractOrgFile(name) {
  if (!confirm(`用视觉模型逐页读取「${name}」并生成 org chart 草稿？\n每页约 30 秒，作业在后台跑，完成后会提示你检查草稿。`)) return;
  const r = await jsend("/api/orgchart/extract", "POST", { name });
  if (!r.ok) { alert(`失败: ${r.body.detail || r.status}`); return; }
  const jid = r.body.id;
  toast(`提取作业 ${jid} 已开始…`);
  const timer = setInterval(async () => {
    const jr = await fetch(`/api/jobs/${jid}`);
    const j = await jr.json();
    if (j.status === "done") {
      clearInterval(timer);
      const dr = await fetch("/api/orgchart/draft");
      const d = await dr.json();
      if (d.entries.length && confirm(`提取完成：${d.entries.length} 条。\n载入编辑器检查？（不会自动保存，确认无误后请点「保存」）`)) {
        org = d.entries;
        renderOrgTree();
        toast(`已载入草稿 ${d.entries.length} 条，请检查后点保存`);
      } else {
        toast("提取完成但未载入（草稿为空或你已取消）");
      }
    } else if (j.status === "failed" || j.status === "cancelled") {
      clearInterval(timer);
      toast(`提取作业 ${jid} ${j.status}`);
    }
  }, 3000);
}

function viewOrgFile(f) {
  const box = $("#org-file-view");
  box.innerHTML = "";
  for (let n = 1; n <= f.pages; n++) {
    const img = document.createElement("img");
    img.src = `/api/orgchart/files/${encodeURIComponent(f.name)}/page/${n}`;
    img.alt = `${f.name} 第${n}页`;
    box.appendChild(img);
  }
}

async function uploadOrgFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/orgchart/files", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) { alert(`上传失败: ${j.detail || r.status}`); return; }
  toast(`已上传 ${j.name}（${j.pages} 页）`);
  loadOrgFiles();
}

async function loadOrgDraft() {
  const r = await fetch("/api/orgchart/draft");
  const d = await r.json();
  if (!d.has_draft || !d.entries.length) {
    toast("没有提取草稿（先在参考文件上点「提取草稿」）");
    return;
  }
  if (!confirm(`草稿有 ${d.entries.length} 条，载入编辑器？\n（不会自动保存；当前未保存的改动会被覆盖，确认无误后请点「保存」）`)) return;
  org = d.entries;
  renderOrgTree();
  toast(`已载入草稿 ${d.entries.length} 条，检查后点「保存」`);
}

/* ================= 事件 ================= */

function init() {
  $("#voice-filter").addEventListener("input", renderSpeakers);
  $("#org-add-root").onclick = () => {
    const name = prompt("根节点姓名：");
    if (!name) return;
    if (org.some(e => e.name === name)) { alert("已存在同名成员"); return; }
    org.push({ name, aliases: [], title: "", team: "", leader: "", note: "" });
    renderOrgTree();
  };
  $("#org-save").onclick = saveOrg;
  $("#org-reload").onclick = loadOrg;
  $("#org-draft").onclick = loadOrgDraft;
  $("#org-upload-btn").onclick = () => $("#org-file-input").click();
  $("#org-file-input").addEventListener("change", e => uploadOrgFile(e.target.files[0]));

  loadSpeakers();
  loadOrg();
  loadOrgFiles();
}

document.addEventListener("DOMContentLoaded", init);
