#!/usr/bin/env python3
"""orgchart.json → orgchart.mmd(Mermaid graph TD, 自上而下层级图)。

- 多个根节点并列布局; leader 引用悬空的补虚线占位节点; 环路/孤岛挂到"检查"节点下
- 输出 speaker_bank/orgchart.mmd; VS Code 装 Mermaid 预览扩展即可查看
- stdout 只打印元数据(条目/连线数)，不打印人名

用法: bin/orgchart_mermaid.py [orgchart.json 路径] [-o 输出.mmd]
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "speaker_bank"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def main() -> int:
    ap = argparse.ArgumentParser(description="orgchart.json → Mermaid 层级图")
    ap.add_argument("src", nargs="?", default=str(BANK / "orgchart.json"))
    ap.add_argument("-o", default=str(BANK / "orgchart.mmd"))
    args = ap.parse_args()

    entries = json.loads(Path(args.src).read_text(encoding="utf-8"))
    by_norm = {}
    for e in entries:                       # 同名(规范化)只留第一份
        by_norm.setdefault(norm(e["name"]), e)
    nodes = list(by_norm.values())
    id_of = {norm(e["name"]): f"n{i}" for i, e in enumerate(nodes)}

    edges, stubs = [], set()
    for e in nodes:
        ld = norm(e.get("leader", ""))
        if not ld:
            continue
        if ld in id_of:
            edges.append((id_of[ld], id_of[norm(e["name"])]))
        else:
            stubs.add(ld)                    # 悬空上级 → 占位节点
            sid = f"s{len(stubs)}"
            id_of.setdefault(ld, sid)
            edges.append((sid, id_of[norm(e["name"])]))

    # 环路/孤岛检测: 从所有根(无上级)出发走不到的节点
    children = {}
    for a, b in edges:
        children.setdefault(a, []).append(b)
    roots = [id_of[norm(e["name"])] for e in nodes if not norm(e.get("leader", ""))]
    seen = set()
    stack = list(roots) + [id_of[s] for s in stubs]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        stack.extend(children.get(x, []))
    stranded = [i for i in id_of.values() if i not in seen and not i.startswith("s")]

    def label(e):
        t = e.get("name", "?")
        if e.get("title"):
            t += f"<br/><i>{e['title']}</i>"
        return t.replace('"', "'")

    lines = ["graph TD"]
    for e in nodes:
        lines.append(f'  {id_of[norm(e["name"])]}["{label(e)}"]')
    for s in stubs:
        lines.append(f'  {id_of[s]}["{s}(缺条目)"]:::stub')
    for a, b in edges:
        lines.append(f"  {a} --> {b}")
    if stranded:
        lines.append('  check["⚠ 检查:环/孤岛"]:::warn')
        for i in stranded:
            lines.append(f"  check --> {i}")
    lines.append("  classDef stub stroke-dasharray: 5 5,color:#c25050")
    lines.append("  classDef warn fill:#5a3c3c,color:#fff")

    Path(args.o).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[meta] 节点 {len(nodes)}(+占位 {len(stubs)}) | 连线 {len(edges)}"
          f" | 根 {len(roots)} | 环/孤岛 {len(stranded)} | 输出: {args.o}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
