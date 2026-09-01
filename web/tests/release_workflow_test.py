#!/usr/bin/env python3
"""Static contracts for the release workflow and repository intake files."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def require(text: str, marker: str, source: str) -> None:
    if marker not in text:
        raise AssertionError(f"{source} is missing required marker: {marker}")


def main() -> int:
    workflow_path = ROOT / ".github" / "workflows" / "release.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    required_workflow_markers = [
        'tags:',
        '- "v*"',
        "workflow_dispatch:",
        "Existing tag to validate and release",
        "permissions:",
        "contents: write",
        "fetch-depth: 0",
        "persist-credentials: false",
        'test "$RELEASE_TAG" = "v$(cat VERSION)"',
        "release/authorized-tag.txt",
        'test "$authorized_tag" = "$RELEASE_TAG"',
        'docs/releases/$RELEASE_TAG.md',
        "make lock-check",
        "make check",
        "make smoke",
        "scripts/build_release_bundle.py --official",
        "scripts/verify_release_bundle.py --full",
        "gh release create",
        "--draft",
        "--verify-tag",
        "--prerelease",
    ]
    for marker in required_workflow_markers:
        require(workflow, marker, str(workflow_path))
    assert "pull_request_target" not in workflow
    assert "self-hosted" not in workflow
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("uses:"):
            assert stripped.startswith("uses: actions/"), f"non-official action: {stripped}"

    ci_path = ROOT / ".github" / "workflows" / "ci.yml"
    ci = ci_path.read_text(encoding="utf-8")
    for marker in (
        "release-candidate:",
        "needs: check-and-smoke",
        "scripts/build_release_bundle.py",
        "scripts/verify_release_bundle.py",
        "actions/upload-artifact@v7",
        "retention-days: 7",
        "id: release-scope",
        "git diff --quiet",
        "steps.release-scope.outputs.full == 'true'",
        "scripts/verify_release_bundle.py --full",
    ):
        require(ci, marker, str(ci_path))

    dependabot_path = ROOT / ".github" / "dependabot.yml"
    dependabot = dependabot_path.read_text(encoding="utf-8")
    require(dependabot, "package-ecosystem: github-actions", str(dependabot_path))
    require(dependabot, "interval: monthly", str(dependabot_path))
    require(dependabot, "open-pull-requests-limit: 3", str(dependabot_path))
    assert "pip" not in dependabot

    notes_path = ROOT / "docs" / "releases" / "TEMPLATE.md"
    notes = notes_path.read_text(encoding="utf-8")
    headings = [
        "# vX.Y.Z",
        "## English",
        "### Highlights",
        "### Compatibility and migration",
        "### Known limitations",
        "### Validation",
        "## 中文",
        "### 主要变化",
        "### 兼容与迁移",
        "### 已知限制",
        "### 验证",
    ]
    positions = [notes.index(heading) for heading in headings]
    assert positions == sorted(positions), "release note headings are missing or out of order"

    bug_path = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
    bug = bug_path.read_text(encoding="utf-8").lower()
    for marker in (
        "diagnostic id",
        "synthetic",
        "meeting files",
        ".env",
        "api keys",
        "internal urls",
    ):
        require(bug, marker, str(bug_path))

    print("release workflow: tag gate, official actions, candidate artifact and intake contracts passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
