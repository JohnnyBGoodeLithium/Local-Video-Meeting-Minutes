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
              for name in ("fluent-foundation.css", "style.css", "theme.css"))

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

required_fluent = {
    "--colorNeutralBackground1", "--colorNeutralForeground1",
    "--colorBrandBackground", "--colorFocusStrokeInner",
    "--fontFamilyBase", "--spacingHorizontalM", "--borderRadiusMedium",
    "--shadow16", "--durationNormal",
}
assert required_fluent <= defined, \
    f"Fluent 语义 token 缺失: {sorted(required_fluent - defined)}"

foundation = (STATIC / "fluent-foundation.css").read_text(encoding="utf-8")
assert ":focus-visible" in foundation, "缺少统一键盘焦点合同"
assert "prefers-reduced-motion" in foundation, "缺少减少动态效果合同"
assert ".fluent-button" in foundation and ".fluent-tab" in foundation, \
    "公共原生组件合同不完整"

icons = (STATIC / "fluent-icons.svg").read_text(encoding="utf-8")
for icon in ("add", "settings", "more-horizontal", "dismiss", "arrow-left",
             "arrow-right", "zoom-in", "zoom-out"):
    assert f'id="fluent-{icon}"' in icons, f"Fluent 图标缺失: {icon}"

print(f"Design tokens: {len(defined)} defined, {len(used_bare)} bare refs all resolve, "
      f"{len(used_with_fallback)} fallback refs OK")
