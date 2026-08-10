#!/usr/bin/env python3
"""org chart 参考文件 → VL 提取人员/层级草稿(全本地)。

读取 speaker_bank/orgchart_files/<名字>/page-*.png，逐页让本地 VL 模型
(默认 Miloco, 经 minutes_by_page.ensure_vl_server 自动拉起)提取
"姓名 | 职务 | 上级姓名" 行，跨页只做完全一致去重，并把不确定上级/冲突/来源页
保留给人工确认（规则见 prompts/orgchart_extract.md），
写成 speaker_bank/orgchart_draft.json。

**不直接写 orgchart.json**——草稿在 /admin 页面里由人工检查后再保存。
提取 prompt 读取自 prompts/orgchart_extract.md(其他团队复用同一份)。
stdout 只打印元数据(页数/条数), 不打印任何人名。

用法: bin/orgchart_extract.py <参考文件名, 如 Notes_Organization>
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from minutes_by_page import ensure_vl_server, VL_MAXTOK  # noqa: E402
from vl_page_test import chat_with_image  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "speaker_bank"

# 内置兜底 prompt；canonical 版本在 prompts/orgchart_extract.md
PROMPT = (
    "这是一页组织架构图（或人员名单）。请提取页面上出现的所有人员，每行一条，格式：\n"
    "姓名 | 职务 | 上级姓名\n"
    "规则：\n"
    "- 上级根据连线或缩进层级判断；判断不出上级就留空（行末的 | 保留）\n"
    "- 只输出上述格式的行，不要标题、不要解释、不要 markdown\n"
    "- 看不清的名字不要猜，跳过该行\n"
    "- 没有人员的页面输出空\n"
    "- 姓名以页面上的完整写法为准，不要翻译、转拼音、缩写、补全或合并；\n"
    "  同一个人可能在本文件的其他页面重复出现，照常输出即可，合并由后处理完成"
)


def load_prompt() -> str:
    p = ROOT / "prompts" / "orgchart_extract.md"
    if p.is_file():
        m = re.search(r"```text\n(.*?)```", p.read_text(encoding="utf-8"), re.S)
        if m:
            return m.group(1).strip()
    return PROMPT


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def parse_lines(text: str):
    """松散解析 '姓名 | 职务 | 上级' 行。返回 [(name, title, leader)]。"""
    out = []
    for ln in text.splitlines():
        ln = ln.strip().strip("|").strip()
        if "|" not in ln:
            continue
        parts = [p.strip().strip("*` ") for p in ln.split("|")]
        parts += [""] * (3 - len(parts))
        name, title, leader = parts[0], parts[1], parts[2]
        name = re.sub(r"^[0-9]+[.、)]\s*", "", name)     # 去列表序号
        if not name or len(name) > 40 or name.lower() in ("姓名", "name"):
            continue
        out.append((name, title, leader))
    return out


def add_entry(entries: dict, nm: str, title: str, leader: str, page: int):
    """只合并规范化后完全一致的姓名；相似名称留给人工身份确认。"""
    key = norm(nm)
    if key in entries:
        e = entries[key]
        e["source_pages"].add(page)
        if title and not e["title"]:
            e["title"] = title
        if leader:
            if not e["leader"]:
                e["leader"] = leader
            elif norm(leader) != norm(e["leader"]):
                e["conflicts"].add(leader)
        return
    entries[key] = {"name": nm.strip(), "title": title, "leader": leader,
                    "aliases": set(), "conflicts": set(), "source_pages": {page}}


def resolve_leader(entries: dict, leader: str):
    """leader 字符串 → 条目主键(先精确再别名)。找不到返回 None。"""
    key = norm(leader)
    if key in entries:
        return key
    for k, e in entries.items():
        if any(norm(a) == key for a in e["aliases"]):
            return k
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: orgchart_extract.py <参考文件名>", file=sys.stderr)
        return 1
    name = sys.argv[1]
    d = BANK / "orgchart_files" / name
    pages = sorted(d.glob("page-*.png"))
    if not pages:
        print(f"没有页图: {d} (PDF 需已在 /admin 上传渲染)", file=sys.stderr)
        return 1

    api, _proc = ensure_vl_server()
    if not api:
        print("VL 服务不可用", file=sys.stderr)
        return 2
    import urllib.request
    with urllib.request.urlopen(f"{api}/models", timeout=10) as resp:
        mid = json.loads(resp.read())["data"][0]["id"]

    prompt = load_prompt()
    entries = {}
    t0 = time.time()
    for i, png in enumerate(pages, 1):
        try:
            raw, usage = chat_with_image(api, mid, png, VL_MAXTOK, prompt)
        except Exception as e:
            print(f"[meta] 第{i}页失败: {type(e).__name__}", flush=True)
            continue
        for nm, title, leader in parse_lines(raw):
            add_entry(entries, nm, title, leader, i)
        if i % 5 == 0 or i == len(pages):
            print(f"[meta] 页 {i}/{len(pages)} | 累计条目 {len(entries)}", flush=True)

    # leader 只做精确解析；悬空关系保留给图形编辑器确认，不虚构占位人员。
    n_unresolved = 0
    for e in list(entries.values()):
        if not e["leader"]:
            continue
        if norm(e["leader"]) == norm(e["name"]):
            e["leader"] = ""
            continue
        k = resolve_leader(entries, e["leader"])
        if k is None:
            n_unresolved += 1
        else:
            e["leader"] = entries[k]["name"]   # 归一到正式写法

    out = []
    for e in entries.values():
        note = f"VL提取自{name}"
        if e["conflicts"]:
            note += " | leader冲突:" + "|".join(sorted(e["conflicts"]))
        unresolved = bool(e["leader"] and resolve_leader(entries, e["leader"]) is None)
        status = "conflict" if e["conflicts"] else ("unresolved" if unresolved else "draft")
        out.append({"name": e["name"], "aliases": sorted(e["aliases"]),
                    "title": e["title"], "team": "", "leader": e["leader"],
                    "leader_raw": e["leader"], "status": status,
                    "source_pages": sorted(e["source_pages"]),
                    "conflicts": sorted(e["conflicts"]), "note": note})
    dst = BANK / "orgchart_draft.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_conflict = sum(1 for e in entries.values() if e["conflicts"])
    print(f"[meta] 提取完成: {len(pages)} 页 → {len(out)} 条(待确认上级 {n_unresolved},"
          f" leader冲突 {n_conflict}) | {time.time()-t0:.0f}s | 草稿: {dst}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
