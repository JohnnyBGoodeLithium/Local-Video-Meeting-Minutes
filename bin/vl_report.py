#!/usr/bin/env python3
"""把 vl_page_test.py 的产出 JSON 转成可读的 Markdown 评审报告。

用法: bin/vl_report.py meetings/<会议目录>/vl_test_<tag>.json
产出: 同目录同名 .md（每页: 截图 + 类型/标题/摘要; 解析失败的放原始回答）
stdout 只打印元数据。
"""
import json
import sys
from pathlib import Path


def mmss(sec: float) -> str:
    s = int(sec)
    return f"{s//60:02d}:{s%60:02d}"


def main() -> int:
    src = Path(sys.argv[1])
    d = json.loads(src.read_text(encoding="utf-8"))
    mdir = src.parent
    first_seen = {}
    sj = mdir / "slides.json"
    if sj.is_file():
        for x in json.loads(sj.read_text(encoding="utf-8")):
            if x.get("kind") == "slide":
                first_seen[x["page"]] = x["first"]

    lines = [f"# VL 读页评审: {d.get('model','?')}", ""]
    ok = parsed = 0
    for r in d["results"]:
        n = r["page"]
        t = first_seen.get(n)
        lines.append(f"### 第{n}页" + (f" [{mmss(t)}]" if t is not None else ""))
        lines.append(f"![](slides/{r['image']})")
        if "error" in r:
            lines.append(f"- ⚠ 调用失败: {r['error']}\n")
            continue
        ok += 1
        lines.append(f"- 耗时 {r.get('latency','?')}s | tokens {r.get('tokens','?')}")
        if d.get("mode") == "detail":      # 详细模式: 直接渲染 Markdown 原文
            lines.append("")
            lines.append(r.get("raw", "").strip())
            lines.append("")
        elif r.get("parsed"):
            parsed += 1
            p = r["parsed"]
            lines.append(f"- **类型**: {p.get('type','')}")
            lines.append(f"- **标题**: {p.get('title','')}")
            lines.append(f"- **摘要**: {p.get('summary','')}\n")
        else:
            lines.append("- ⚠ 未按 JSON 格式输出，原始回答:\n")
            lines.append("```")
            lines.append(r.get("raw", "").strip())
            lines.append("```\n")
    src.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[meta] 报告: {src.with_suffix('.md')} | 页数 {len(d['results'])}"
          f" | 成功 {ok} | 解析 {parsed}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
