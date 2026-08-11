#!/usr/bin/env python3
"""从 canonical evidence 构造无需 LLM 的离线阅读视图与会议知识图。"""

from __future__ import annotations

from collections import OrderedDict


VIEWS_SCHEMA = "meeting-views/v1"


def evidence_integrity(evidence: dict) -> dict:
    claims = evidence.get("claims", [])
    linked = sum(bool(claim.get("turn_ids") or claim.get("page_ids")) for claim in claims)
    transcript_linked = sum(bool(claim.get("turn_ids")) for claim in claims)
    if claims and linked == len(claims):
        state = "ready"
    else:
        state = "partial"
    warnings = []
    if not claims:
        warnings.append("这份纪要没有结论级证据链接；仍可阅读完整逐字稿和播放媒体，但不能逐条核实纪要结论。")
    elif linked < len(claims):
        warnings.append(f"{len(claims) - linked} 条纪要结论没有关联逐字稿或页面证据。")
    return {
        "state": state,
        "claims": len(claims),
        "linked_claims": linked,
        "transcript_linked_claims": transcript_linked,
        "coverage": round(linked / len(claims), 3) if claims else 0.0,
        "warnings": warnings,
    }


def _ids(claims: list[dict], *, statuses: set[str] | None = None,
         kinds: set[str] | None = None, sections: tuple[str, ...] = (), limit: int = 12) -> list[str]:
    result = []
    for claim in claims:
        section = str(claim.get("section") or "").lower()
        if statuses is not None and claim.get("status") not in statuses:
            continue
        if kinds is not None and claim.get("kind") not in kinds:
            continue
        if sections and not any(token in section for token in sections):
            continue
        result.append(claim["id"])
        if len(result) >= limit:
            break
    return result


def _group(title: str, claim_ids: list[str], empty: str = "本次会议没有识别到此类内容。") -> dict:
    return {"title": title, "claim_ids": claim_ids, "empty": empty}


def build_views(evidence: dict) -> dict:
    claims = evidence.get("claims", [])
    integrity = evidence_integrity(evidence)
    action_tokens = ("行动", "待办", "follow", "action", "next step", "后续")
    confirmed = _ids(claims, statuses={"confirmed"}, limit=12)
    alignment = _ids(claims, statuses={"working_alignment"}, limit=12)
    open_items = _ids(claims, statuses={"open"}, limit=12)
    proposals = _ids(claims, statuses={"proposal"}, limit=12)
    actions = list(dict.fromkeys([
        *_ids(claims, kinds={"action"}, limit=16),
        *_ids(claims, sections=action_tokens, limit=16),
    ]))[:16]
    information = _ids(claims, statuses={"informational"}, limit=12)

    views = [
        {
            "id": "exec_quick", "audience": "exec", "depth": "quick",
            "title": "管理层 · 快速了解", "description": "决定、方向、风险和需要关注的后续。",
            "groups": [
                _group("已确认决定", confirmed[:8]),
                _group("方向性共识", alignment[:6]),
                _group("风险与未决问题", open_items[:6]),
                _group("关键行动", actions[:6]),
            ],
        },
        {
            "id": "exec_deep", "audience": "exec", "depth": "deep",
            "title": "管理层 · 精细回看", "description": "区分已确认决定、方向、提议和未决问题。",
            "groups": [
                _group("已确认决定", confirmed),
                _group("方向性共识", alignment),
                _group("仍待确认", open_items),
                _group("提议与方案", proposals),
                _group("重要背景", information[:8]),
            ],
        },
        {
            "id": "working_quick", "audience": "working", "depth": "quick",
            "title": "执行层 · 快速跟进", "description": "下一步、阻塞、待确认事项及其会议依据。",
            "groups": [
                _group("立即跟进", actions[:10]),
                _group("阻塞与未决", open_items[:8]),
                _group("尚未批准的方案", proposals[:6]),
                _group("执行所依据的决定", confirmed[:6]),
            ],
        },
    ]

    section_groups: OrderedDict[str, list[str]] = OrderedDict()
    for claim in claims:
        section = str(claim.get("section") or "其他讨论")
        section_groups.setdefault(section, []).append(claim["id"])
    views.append({
        "id": "working_deep", "audience": "working", "depth": "deep",
        "title": "执行层 · 精细回看", "description": "按原纪要章节保留完整事实和状态。",
        "groups": [_group(section, ids[:16]) for section, ids in list(section_groups.items())[:16]],
    })

    topics = []
    for section, claim_ids in list(section_groups.items())[:16]:
        topics.append({"id": f"topic-{len(topics) + 1}", "title": section,
                       "claim_ids": claim_ids[:16]})
    graph = {
        "title": "会议理解图",
        "description": "按议题展示决定、方向、提议和未决问题；点击节点核实原始证据。",
        "topics": topics,
    }
    return {"schema": VIEWS_SCHEMA, "integrity": integrity, "views": views, "graph": graph}
