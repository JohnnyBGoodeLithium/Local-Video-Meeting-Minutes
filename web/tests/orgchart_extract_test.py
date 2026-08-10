#!/usr/bin/env python3
"""Org Chart 模型输出解析回归；只使用虚构文本。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from orgchart_extract import add_entry, parse_lines  # noqa: E402


raw = """<think>
用户现在需要从组织架构图中提取人员信息，格式是姓名 | 职务 | 上级姓名。
</think>Alice Example | Director | 
Bob Example | Manager | Alice Example
"""
rows = parse_lines(raw)
assert rows == [
    ("Alice Example", "Director", ""),
    ("Bob Example", "Manager", "Alice Example"),
], rows

leaked = """用户现在需要整理信息，格式是姓名 | 职务 | 上级姓名。
</think>Carol Example | Engineer | Bob Example
姓名 | 职务 | 上级姓名
"""
assert parse_lines(leaked) == [("Carol Example", "Engineer", "Bob Example")]

entries = {}
add_entry(entries, "Carol Example", "Engineer", "Bob Example", 1)
add_entry(entries, "Carol Example", "Engineer", "Bob Example", 2)
assert len(entries) == 1
assert entries["carol example"]["source_pages"] == {1, 2}

print("Org Chart parser: reasoning/prompt leakage rejected")
