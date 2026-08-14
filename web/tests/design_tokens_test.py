#!/usr/bin/env python3
"""设计 token 完整性：无回退的 var() 引用必须已定义；字号不得回退为字面值。

防的是 2026-08-14 真实事故：token 化漏定义 --sp-27…90，padding/gap 在
computed-value 阶段整声明作废，全站间距静默归零、文字贴边。
"""

from __future__ import annotations

import re
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"
css = "".join((STATIC / name).read_text(encoding="utf-8")
              for name in ("style.css", "theme.css"))

defined = set(re.findall(r"(--[\w-]+)\s*:", css))
used_with_fallback = set()
used_bare = set()
for match in re.finditer(r"var\(\s*(--[\w-]+)\s*(,[^)]*)?\)", css):
    name = match.group(1)
    (used_with_fallback if match.group(2) else used_bare).add(name)

missing = sorted((used_bare - defined))
assert not missing, f"无回退引用了未定义的 token: {missing}"

# 字号必须走阶梯 token（@media 常量与 letter-spacing 等不受影响）
bad_font = re.findall(r"font-size:\s*[\d.]+px", css)
assert not bad_font, f"font-size 字面值回潮: {bad_font[:5]}"

# 花括号平衡
assert css.count("{") == css.count("}"), "CSS 花括号不平衡"

print(f"Design tokens: {len(defined)} defined, {len(used_bare)} bare refs all resolve, "
      f"{len(used_with_fallback)} fallback refs OK")
