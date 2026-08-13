"""本地会议结论审计记录。

评测文件只保存 claim ID、结构指纹和人工标签，不复制逐字稿或纪要正文。
结构指纹包含该 claim 引用的来源内容，因此修改无关段落不会让所有验收失效，
修改相关逐字稿、说话人或页面说明则会把对应验收标为过期。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path


SCHEMA = "meeting-minutes-evaluation/v1"
LABELS = [
    {"id": "correct", "label": "结论与依据一致", "group": "pass", "shortcut": "1"},
    {"id": "proposal_not_decision", "label": "把提议写成决定", "group": "issue", "shortcut": "2"},
    {"id": "should_be_decision", "label": "遗漏或弱化了决定", "group": "issue", "shortcut": "3"},
    {"id": "wrong_evidence", "label": "引用依据不对应", "group": "issue", "shortcut": "4"},
    {"id": "wrong_owner_deadline", "label": "负责人/期限错误", "group": "issue", "shortcut": "5"},
    {"id": "unsupported", "label": "缺少原文支持", "group": "issue", "shortcut": "6"},
    {"id": "cannot_judge", "label": "暂时无法审计", "group": "uncertain", "shortcut": "7"},
]
VALID_LABELS = {item["id"] for item in LABELS}
LABEL_GROUPS = {item["id"]: item["group"] for item in LABELS}
PRIORITY_KINDS = {"decision", "alignment", "proposal", "action", "risk", "open_question"}


def audit_priority(claim: dict) -> bool:
    """默认审计真正影响结论/执行的内容；全部证据仍可由前端展开。"""
    if claim.get("status") == "informational":
        return False
    if claim.get("kind") == "action":
        return bool(claim.get("formal_action"))
    return claim.get("kind") in PRIORITY_KINDS


def empty_store(slug: str) -> dict:
    return {
        "schema": SCHEMA,
        "meeting_slug": slug,
        "created_at": None,
        "updated_at": None,
        "events": [],
    }


def load_store(path: Path, slug: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_store(slug)
    if data.get("schema") != SCHEMA or data.get("meeting_slug") != slug:
        return empty_store(slug)
    if not isinstance(data.get("events"), list):
        data["events"] = []
    return data


def _source_snapshot(claim: dict, evidence: dict) -> dict:
    sources = evidence.get("sources", {})
    turns = {item.get("id"): item for item in sources.get("transcript", [])}
    pages = {item.get("id"): item for item in sources.get("pages", [])}
    return {
        "turns": [
            {
                "id": tid,
                "start": turns.get(tid, {}).get("start"),
                "end": turns.get(tid, {}).get("end"),
                "speaker": turns.get(tid, {}).get("speaker"),
                "person_id": turns.get(tid, {}).get("person_id"),
                "text": turns.get(tid, {}).get("text"),
            }
            for tid in claim.get("turn_ids", [])
        ],
        "pages": [
            {
                "id": pid,
                "display_status": pages.get(pid, {}).get("display_status"),
                "visual_description": pages.get(pid, {}).get("visual_description"),
            }
            for pid in claim.get("page_ids", [])
        ],
    }


def claim_fingerprint(claim: dict, evidence: dict) -> str:
    """指纹只用于失效判断；来源正文不会写入评测文件。"""
    material = {
        "text": claim.get("text"),
        "section": claim.get("section"),
        "kind": claim.get("kind"),
        "status": claim.get("status"),
        "confidence": claim.get("confidence"),
        "turn_ids": claim.get("turn_ids", []),
        "page_ids": claim.get("page_ids", []),
        "speakers": claim.get("speakers", []),
        "person_ids": claim.get("person_ids", []),
        "sources": _source_snapshot(claim, evidence),
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def save_review(path: Path, slug: str, evidence: dict, claim: dict,
                label: str, note: str, now: float | None = None) -> dict:
    if label not in VALID_LABELS:
        raise ValueError("未知审计标签")
    note = note.strip()
    if len(note) > 1000:
        raise ValueError("备注不能超过 1000 字")
    store = load_store(path, slug)
    timestamp = round(now if now is not None else time.time(), 3)
    event = {
        "id": uuid.uuid4().hex[:12],
        "claim_id": claim["id"],
        "claim_fingerprint": claim_fingerprint(claim, evidence),
        "label": label,
        "note": note,
        "reviewed_at": timestamp,
        "artifact_id": evidence.get("artifact_id"),
        "claim_shape": {
            "kind": claim.get("kind"),
            "status": claim.get("status"),
            "turn_count": len(claim.get("turn_ids", [])),
            "page_count": len(claim.get("page_ids", [])),
        },
    }
    store["events"].append(event)
    store["created_at"] = store.get("created_at") or timestamp
    store["updated_at"] = timestamp
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return event


def build_payload(slug: str, evidence: dict, store: dict, evidence_state: str) -> dict:
    latest_by_claim = {}
    for event in store.get("events", []):
        if event.get("claim_id"):
            latest_by_claim[event["claim_id"]] = event

    claims = []
    for original in evidence.get("claims", []):
        claim = dict(original)
        fingerprint = claim_fingerprint(claim, evidence)
        latest = latest_by_claim.get(claim.get("id"))
        current = latest if latest and latest.get("claim_fingerprint") == fingerprint else None
        claim["fingerprint"] = fingerprint
        claim["review"] = current
        claim["review_stale"] = bool(latest and current is None)
        claim["previous_review"] = latest if latest and current is None else None
        claim["has_transcript_evidence"] = bool(claim.get("turn_ids"))
        claim["has_page_evidence"] = bool(claim.get("page_ids"))
        claim["audit_priority"] = audit_priority(claim)
        claims.append(claim)

    reviewed = [claim for claim in claims if claim.get("review")]
    issues = [claim for claim in reviewed
              if LABEL_GROUPS.get(claim["review"]["label"]) == "issue"]
    uncertain = [claim for claim in reviewed
                 if LABEL_GROUPS.get(claim["review"]["label"]) == "uncertain"]
    passed = [claim for claim in reviewed
              if LABEL_GROUPS.get(claim["review"]["label"]) == "pass"]
    counts = {item["id"]: 0 for item in LABELS}
    for claim in reviewed:
        label = claim["review"].get("label")
        if label in counts:
            counts[label] += 1
    total = len(claims)
    summary = {
        "total": total,
        "reviewed": len(reviewed),
        "pending": total - len(reviewed),
        "passed": len(passed),
        "issues": len(issues),
        "uncertain": len(uncertain),
        "stale": sum(bool(claim.get("review_stale")) for claim in claims),
        "with_transcript_evidence": sum(bool(claim.get("turn_ids")) for claim in claims),
        "with_page_evidence": sum(bool(claim.get("page_ids")) for claim in claims),
        "counts": counts,
    }
    priority_claims = [claim for claim in claims if claim.get("audit_priority")]
    priority_reviewed = [claim for claim in priority_claims if claim.get("review")]
    priority_groups = [LABEL_GROUPS.get(claim["review"]["label"])
                       for claim in priority_reviewed]
    priority_summary = {
        "total": len(priority_claims),
        "reviewed": len(priority_reviewed),
        "pending": len(priority_claims) - len(priority_reviewed),
        "passed": priority_groups.count("pass"),
        "issues": priority_groups.count("issue"),
        "uncertain": priority_groups.count("uncertain"),
        "stale": sum(bool(claim.get("review_stale")) for claim in priority_claims),
        "with_transcript_evidence": sum(bool(claim.get("turn_ids")) for claim in priority_claims),
        "with_page_evidence": sum(bool(claim.get("page_ids")) for claim in priority_claims),
    }
    return {
        "schema": SCHEMA,
        "meeting_slug": slug,
        "evidence_state": evidence_state,
        "artifact_id": evidence.get("artifact_id"),
        "labels": LABELS,
        "summary": summary,
        "priority_summary": priority_summary,
        "claims": claims,
        "updated_at": store.get("updated_at"),
    }
