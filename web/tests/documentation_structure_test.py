#!/usr/bin/env python3
"""Public documentation architecture and link contracts.

This test reads repository documentation only. It never enumerates meeting data.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]

REQUIRED = {
    "README.md", "README.zh-CN.md", "SECURITY.md", "CONTRIBUTING.md",
    ".github/pull_request_template.md",
    "AGENTS.md", "HANDOFF.md", "CHANGELOG.md", "VERSION",
    "docs/INDEX.md", "docs/STATUS.md", "docs/PRODUCT.md",
    "docs/ARCHITECTURE.md", "docs/UX.md", "docs/OPERATIONS.md",
    "docs/KNOWLEDGE_RAG.md", "docs/RISKS.md", "docs/PRODUCT_FUNCTIONS.md",
    "docs/reporting/EXECUTIVE_BRIEF.md",
    "docs/reporting/TECHNICAL_BRIEF.md",
    "docs/reporting/DEMO_SCRIPT.md",
    "docs/history/ENGINEERING_CHANGES.md",
    "docs/research/EXPERIMENT_LOG.md", "docs/research/RAG_STUDY.md",
    "docs/research/UX_REFERENCES.md",
    "docs/runbooks/DEPLOYMENT.md",
    "docs/runbooks/PROCESSING_AND_RECOVERY.md",
    "docs/runbooks/WEKNORA.md", "docs/runbooks/DEVELOPMENT.md",
    "docs/runbooks/RELEASES.md",
    "docs/reference/DESIGN_SYSTEM.md", "docs/reference/MODELS.md",
    "docs/reference/COST_MODEL.md",
}

COMPATIBILITY = {
    "docs/PRODUCT_UX.md", "docs/SPEAKER_CORRECTION_UX.md",
    "docs/ENGINEERING_REVIEW.md", "docs/NEXT_PLAN.md",
    "docs/EXPORT_AND_RAG.md", "docs/WORKSPACE_UX_V015_PLAN.md",
    "docs/DEPLOYMENT.md", "docs/PROCESSING_GUIDE.md",
    "docs/DEVELOPMENT.md", "docs/RELEASES.md",
    "docs/WEKNORA_INTEGRATION.md", "docs/DESIGN_TOKENS.md",
    "docs/MODELS.md", "docs/COST_MODEL.md",
    "docs/KB_RAG_LEARNING_GUIDE.md", "docs/UX_REVIEW_AND_REFERENCES.md",
}

EXPECTED_FUNCTION_IDS = """
1.1.1.1 1.1.1.2 1.1.1.3 1.1.1.4 1.1.2.1 1.2.1.1 1.2.1.2
1.2.1.3 1.2.1.4 1.2.1.5 1.2.2.1 1.2.2.2 1.2.2.3 1.2.2.4
1.2.2.5 1.2.2.6 2.1.1.1 2.1.1.2 2.1.1.3 2.1.1.4 2.1.1.5
2.1.2.1 2.1.2.2 2.1.2.3 2.1.3.1 2.1.3.2 2.2.1.1 2.2.1.2
3.1.1.1 3.1.1.2 3.1.2.1 3.1.2.2 3.1.2.3 3.2.1.1 3.2.1.2
4.1.1.1 4.1.1.2 4.1.1.3 4.1.2.1 4.1.2.2 4.1.2.3 4.1.2.4
4.2.1.1 5.1.1.1 5.1.1.2 5.1.1.3 5.1.1.4 5.1.1.5 5.1.2.1
5.2.1.1 5.2.1.2 5.2.2.1 5.2.2.2 5.2.2.3 5.3.1.1 5.3.1.2
5.3.1.3 6.1.1.1 6.1.1.2 6.1.1.3 6.1.2.1 6.1.2.2 6.2.1.1
6.2.1.2 6.2.1.3 6.2.1.4 6.2.1.5 6.2.2.1 6.2.2.2 6.2.2.3
7.1.1.1 7.1.1.2 7.1.2.1 7.1.2.2 7.1.2.3 7.2.1.1 7.2.1.2
8.1.1.1 8.1.1.2 8.1.1.3 8.1.1.4 8.1.1.5 8.1.1.6 8.1.2.1
8.1.2.2 8.1.2.3 8.1.2.4 8.1.2.5 8.1.2.6 9.1.1.1 9.1.1.2
9.1.2.1 9.1.2.2 9.1.2.3 9.1.2.4 9.1.2.5 9.1.3.1
""".split()


for relative in REQUIRED | COMPATIBILITY:
    assert (ROOT / relative).exists(), f"required documentation missing: {relative}"


def markdown_files() -> list[Path]:
    tracked = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, text=True,
        capture_output=True, check=True,
    ).stdout.splitlines()
    paths = {ROOT / item for item in tracked}
    paths.update((ROOT / "docs").rglob("*.md"))
    paths.update(ROOT.glob("*.md"))
    return sorted(path for path in paths if path.is_file() and "private_reports" not in path.parts)


LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
broken: list[str] = []
for source in markdown_files():
    text = source.read_text(encoding="utf-8")
    for raw in LINK_RE.findall(text):
        target = raw.strip()
        if re.search(r"<[^>]+>", target) or target.startswith(("…", "...")):
            # Documentation placeholders are examples, not repository links.
            continue
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        if target.startswith(("http://", "https://", "mailto:", "data:", "#")):
            continue
        target = target.split("#", 1)[0].strip()
        if not target:
            continue
        # Optional Markdown title follows the path after whitespace.
        target = target.split(maxsplit=1)[0]
        resolved = (source.parent / unquote(target)).resolve()
        if not resolved.exists():
            broken.append(f"{source.relative_to(ROOT)} -> {target}")
assert not broken, "broken Markdown links:\n" + "\n".join(broken)

readme = (ROOT / "README.md").read_text(encoding="utf-8")
readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
assert "[简体中文](README.zh-CN.md)" in readme
assert "[English](README.md)" in readme_zh

english_sections = [
    "Overview", "Why it exists", "Core capabilities", "How it works",
    "Current maturity", "Quick start", "Privacy and trust boundary",
    "Documentation", "Release and installation status", "License status",
]
chinese_sections = [
    "项目概览", "为什么做", "核心能力", "工作方式", "当前成熟度", "快速开始",
    "隐私与可信边界", "文档导航", "发布与安装状态", "许可证状态",
]
assert re.findall(r"^## (.+)$", readme, re.MULTILINE) == english_sections
assert re.findall(r"^## (.+)$", readme_zh, re.MULTILINE) == chinese_sections
assert len(re.findall(r"[\u4e00-\u9fff]", readme)) < 40, "English README contains a Chinese body"
assert len(readme_zh) > 3_000 and len(re.findall(r"[\u4e00-\u9fff]", readme_zh)) > 800
assert "<!-- maturity: controlled-single-machine-poc -->" in readme
assert "<!-- maturity: controlled-single-machine-poc -->" in readme_zh

quick_start_commands = [
    "git clone <repository-url> meeting-minutes", "cd meeting-minutes",
    "python3 -m venv .venv", ".venv/bin/pip install --upgrade pip",
    ".venv/bin/pip install -e .", "make doctor", "make check", "make run",
]
for command in quick_start_commands:
    assert command in readme and command in readme_zh, f"README quick start drift: {command}"

for target in ("docs/INDEX.md", "docs/STATUS.md", "docs/PRODUCT_FUNCTIONS.md"):
    assert target in readme, f"English README must link to {target}"
    assert target in readme_zh, f"Chinese README must link to {target}"
assert "未来 30 天" not in readme_zh and "30-day plan" not in readme.lower()

pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
assert 'readme = "README.md"' in pyproject

status = (ROOT / "docs/STATUS.md").read_text(encoding="utf-8")
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
for marker in (
    "<!-- current-status-source -->", "更新时间：", f"产品版本：v{version}",
    "Web 构建号：", "源代码基线：", "## 已真实验证",
    "## 已实现，仍在验证", "## 实验中", "## 当前边界",
):
    assert marker in status, f"STATUS missing marker: {marker}"

reporting = [
    ROOT / "docs/reporting/EXECUTIVE_BRIEF.md",
    ROOT / "docs/reporting/TECHNICAL_BRIEF.md",
    ROOT / "docs/reporting/DEMO_SCRIPT.md",
]
metadata_values: list[tuple[str, str, str]] = []
for path in reporting:
    text = path.read_text(encoding="utf-8")
    assert "## English" in text and "## 中文" in text, f"bilingual sections missing: {path.name}"
    date = re.search(r"(?:Prepared date|准备日期)：?\s*`?([^`\n]+)`?", text)
    product = re.search(r"(?:Product version|产品版本)：?\s*`?([^`\n]+)`?", text)
    commit = re.search(r"(?:Source Git commit|Git commit|源代码提交)：?\s*`?([^`\n]+)`?", text)
    assert date and product and commit, f"reporting metadata incomplete: {path.name}"
    metadata_values.append((date.group(1).strip(), product.group(1).strip(), commit.group(1).strip()))
assert len(set(metadata_values)) == 1, f"reporting metadata mismatch: {metadata_values}"

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
release_headers = list(re.finditer(r"^## (v\d+\.\d+\.\d+) — ([0-9-]+)$", changelog, re.MULTILINE))
assert release_headers, "CHANGELOG has no formal releases"
for index, match in enumerate(release_headers):
    next_heading = re.search(r"^## ", changelog[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(changelog)
    bullets = re.findall(r"^- ", changelog[match.end():end], re.MULTILINE)
    assert 3 <= len(bullets) <= 5, f"{match.group(1)} must contain 3-5 top-level bullets, got {len(bullets)}"

function_text = (ROOT / "docs/PRODUCT_FUNCTIONS.md").read_text(encoding="utf-8")
function_ids = re.findall(r"^\| (\d+\.\d+\.\d+\.\d+) \|", function_text, re.MULTILINE)
assert function_ids == EXPECTED_FUNCTION_IDS, "PRODUCT_FUNCTIONS IDs changed, reordered, or were reused"
assert "最近重大增强版本" in function_text and "当前成熟度" in function_text

agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
assert "默认禁止读取 `docs/archive/`" in agents
assert "8,000 tokens" in agents
default_context_bytes = sum(
    (ROOT / item).stat().st_size for item in ("AGENTS.md", "docs/STATUS.md", "docs/INDEX.md")
)
assert default_context_bytes <= 32_000, f"default documentation context exceeds approximate 8k-token budget: {default_context_bytes} bytes"

handoff_lines = (ROOT / "HANDOFF.md").read_text(encoding="utf-8").splitlines()
assert len(handoff_lines) <= 30, f"HANDOFF must stay <=30 lines, got {len(handoff_lines)}"

gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
assert "/private_reports/" in gitignore, "private_reports must be ignored"
tracked = subprocess.run(
    ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=True,
).stdout.splitlines()
assert not any(path.startswith("private_reports/") for path in tracked), "private report content is tracked"

for relative in COMPATIBILITY:
    lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 20, f"compatibility entry must stay <=20 lines: {relative}"

status_markers = sum(
    path.read_text(encoding="utf-8").count("<!-- current-status-source -->")
    for path in markdown_files()
)
assert status_markers == 1, "exactly one document may declare the current-status source"

absolute_home = re.compile(r"/home/[A-Za-z0-9._-]+/")
absolute_path_hits = [
    str(path.relative_to(ROOT)) for path in markdown_files()
    if absolute_home.search(path.read_text(encoding="utf-8"))
]
assert not absolute_path_hits, f"public docs contain absolute user-home paths: {absolute_path_hits}"

print(
    f"documentation structure: {len(markdown_files())} files, links valid, "
    f"{len(function_ids)} function IDs, default context {default_context_bytes} bytes"
)
