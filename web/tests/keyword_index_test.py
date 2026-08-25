#!/usr/bin/env python3
"""关键字全局索引与相关内容建议：规范化合并、聚合、坏数据隔离、加权计分（全虚构）。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "bin"))
sys.path.insert(0, str(PROJECT / "web"))
import keyword_service as keywords  # noqa: E402


def make_meeting(root: Path, slug: str, entries: list[dict], title: str | None = None) -> Path:
    """造一个 ready 关键字 sidecar；revision 与虚构 minutes.md 绑定。"""
    mdir = root / slug
    mdir.mkdir(parents=True)
    (mdir / "minutes.md").write_text("# 会议纪要\n\n虚构正文。\n", encoding="utf-8")
    document = {"schema": "meeting-keywords/v1", "status": "complete",
                "source_revision": keywords._minutes_revision(mdir),
                "facts_revision": None, "language": "zh-CN", "model": "synthetic",
                "updated_at": 1000.0, "keywords": entries}
    (mdir / "meeting.keywords.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8")
    if title:
        (mdir / "meta.json").write_text(json.dumps(
            {"title": title, "updated_at": 2000.0}, ensure_ascii=False), encoding="utf-8")
    return mdir


# 规范化：全半角、大小写、空白差异都合并。
assert keywords.normalize_keyword("玄戒 O3") == keywords.normalize_keyword("玄戒O3")
assert keywords.normalize_keyword(" 玄戒  O3 ") == "玄戒o3"
assert keywords.normalize_keyword("ＩＣ Ｍｉｎｉ") == keywords.normalize_keyword("ic mini")
assert keywords.normalize_keyword("Nova-Lake") == "nova-lake"

with tempfile.TemporaryDirectory(prefix="keyword-index-test-") as tmp:
    root = Path(tmp) / "meetings"
    root.mkdir()

    make_meeting(root, "2026-08-01_alpha", [
        {"text": "玄戒 O3", "kind": "product"},
        {"text": "移动SoC", "kind": "topic"},
        {"text": "独有词A", "kind": "other"},
    ], title="Alpha 评审")
    make_meeting(root, "2026-08-02_beta", [
        {"text": "玄戒O3", "kind": "product"},
        {"text": "移动 SoC", "kind": "topic"},
    ], title="Beta 评审")
    make_meeting(root, "2026-08-03_gamma", [
        {"text": "玄戒 O3", "kind": "other"},
        {"text": "独有词A", "kind": "other"},
        {"text": "独有词C", "kind": "organization"},
    ])
    make_meeting(root, "2026-08-04_delta", [
        {"text": "无关词", "kind": "topic"},
    ])
    # 坏数据：非法 JSON sidecar 只被跳过，不影响整个索引。
    broken = root / "2026-08-05_broken"
    broken.mkdir()
    (broken / "minutes.md").write_text("# 会议纪要\n\n虚构正文。\n", encoding="utf-8")
    (broken / "meeting.keywords.json").write_text("{ not json", encoding="utf-8")
    # 未生成关键字的会议（missing）也不参与。
    (root / "2026-08-06_nokeywords").mkdir()
    (root / "2026-08-06_nokeywords" / "minutes.md").write_text(
        "# 会议纪要\n\n虚构正文。\n", encoding="utf-8")

    index = keywords.global_index(root)
    assert index["schema"] == "keyword-index/v1" and index["built_at"]
    by_normalized = {entry["normalized"]: entry for entry in index["entries"]}
    xuanjie = by_normalized["玄戒o3"]
    # 展示形取最常见原始写法；kinds 跨会议合并；会议按涉及数排序。
    assert xuanjie["text"] == "玄戒 O3", xuanjie
    assert set(xuanjie["kinds"]) == {"product", "other"}
    assert [m["slug"] for m in xuanjie["meetings"]] == [
        "2026-08-01_alpha", "2026-08-02_beta", "2026-08-03_gamma"]
    assert xuanjie["meetings"][0]["title"] == "Alpha 评审"
    assert xuanjie["meetings"][0]["updated_at"] == 2000.0
    assert by_normalized["移动soc"]["text"] == "移动SoC"
    assert len(by_normalized["移动soc"]["meetings"]) == 2
    assert len(by_normalized["独有词a"]["meetings"]) == 2
    assert "无关词" in by_normalized and len(by_normalized["无关词"]["meetings"]) == 1
    assert not any(e["normalized"] == "{notjson" for e in index["entries"])
    assert index["entries"][0]["normalized"] == "玄戒o3"  # 按涉及会议数降序
    # 无 meta.json 时 title 回退 slug。
    gamma_entry = next(m for m in xuanjie["meetings"] if m["slug"] == "2026-08-03_gamma")
    assert gamma_entry["title"] == "2026-08-03_gamma"

    # related：product/project=3，organization/topic=2，other=1；shared 即推荐理由。
    related = keywords.related(root, "2026-08-01_alpha")
    by_slug = {item["slug"]: item for item in related}
    assert set(by_slug) == {"2026-08-02_beta", "2026-08-03_gamma"}, by_slug
    assert by_slug["2026-08-02_beta"]["score"] == 3 + 2      # 玄戒O3(product) + 移动SoC(topic)
    assert by_slug["2026-08-03_gamma"]["score"] == 3 + 1     # 玄戒O3(product，按目标侧 kind) + 独有词A(other)
    assert related[0]["slug"] == "2026-08-02_beta"           # 分数降序
    assert related[0]["title"] == "Beta 评审"
    assert {s["text"] for s in by_slug["2026-08-02_beta"]["shared"]} == {"玄戒 O3", "移动SoC"}
    assert all("2026-08-05_broken" != item["slug"] for item in related)
    assert keywords.related(root, "2026-08-01_alpha", limit=1) == related[:1]
    # 无 ready sidecar / 不存在的会议 → 空结果，不抛错。
    assert keywords.related(root, "2026-08-06_nokeywords") == []
    assert keywords.related(root, "2026-08-99_missing") == []
    # 反向对称：beta 也能看到 alpha。
    back = keywords.related(root, "2026-08-02_beta")
    assert back and back[0]["slug"] == "2026-08-01_alpha"

print("keyword index: normalize/global-index/related passed")
