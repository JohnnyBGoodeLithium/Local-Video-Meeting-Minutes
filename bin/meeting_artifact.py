#!/usr/bin/env python3
"""纪要证据模型与 RAG 导出共享逻辑。

这个模块不调用模型。它把逐字稿、页面理解、人员身份和纪要中的轻量证据标记
整理成一个稳定的机器可读 sidecar，供 Web、便携查看器和后续 RAG 共用。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path


EVIDENCE_SCHEMA = "meeting-minutes-evidence/v1"
FACTS_SCHEMA = "meeting-facts/v1"
RAG_SCHEMA = "meeting-minutes-rag/v1"
MARKER_RE = re.compile(r"<!--\s*mm:evidence\s+([^<>]*?)\s*-->")
# 模型偶尔会在可读正文里同时写一份 ``（T000001, T000002）`` 引用。T ID 是
# evidence sidecar 的机器主键，不是员工/Teams ID；人读层只需要“依据 + 时间”。
# 仅清理“括号内完全由 T ID 组成”的尾注，避免误删正文里对编号本身的讨论。
VISIBLE_TURN_CITATION_RE = re.compile(
    r"[ \t]*[（(]\s*T\d{6}(?:\s*[,，、;/；]\s*T\d{6})*\s*[）)]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")
FORMAL_ACTION_SECTIONS = {
    "待办事项", "行动项", "后续行动", "后续事项",
    "actionitem", "actionitems", "nextstep", "nextsteps", "followup", "followups",
}

CONCLUSION_POLICY = {
    "version": "conclusion-policy/v1",
    "principles": [
        "逐字稿发言是会议决定、共识、行动和风险的唯一主证据。",
        "岗位/职级只提供决策权限语境；不能把提议、设想或单人观点自动升级为结论。",
        "已确认结论需要明确决定/批准措辞，并由议题责任人作出，或得到多人明确确认且无未解决反对。",
        "行动项按动作、接受责任、负责人和期限判定，不按职级判定。",
        "风险和待确认按影响、紧迫性和未解决程度判定，不按发言者职级判定。",
        "VL 页面理解证明页面展示了什么；页面内容本身不能证明会议作出了决定。",
    ],
    "decision_status": {
        "confirmed": "明确决定/批准，且权限或多人确认信号成立，没有仍在场的明确反对。",
        "working_alignment": "形成方向性共识，但权限、范围或最终确认仍不完整。",
        "proposal": "建议、方案、偏好或尚待批准的选择。",
        "open": "问题、风险或分歧仍未解决。",
        "informational": "陈述事实、汇报状态或展示材料，不是会议决定。",
    },
    "seniority_rule": "职级最多影响‘此人是否有权确认决定’的置信度，不改变发言行为本身的类别。",
    "visual_rule": "所有页面进入页面附录；只有与讨论或结论相关的页面进入正文证据链接。",
}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def file_revision(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return " ".join(value.split())


def turn_id(index: int) -> str:
    return f"T{index + 1:06d}"


def page_id(number: int) -> str:
    return f"P{int(number):04d}"


def _page_for_time(pages: list[dict], sec: float) -> dict | None:
    for page in pages:
        for start, end in page.get("ranges", []):
            if float(start) <= sec < float(end):
                return page
    previous = [p for p in pages if float(p.get("first", 0)) <= sec]
    return max(previous, key=lambda p: float(p.get("first", 0))) if previous else None


def _org_depth(entry: dict, by_id: dict[str, dict]) -> int | None:
    depth, cursor, seen = 0, entry, set()
    while cursor and cursor.get("manager_id"):
        manager_id = cursor.get("manager_id")
        if manager_id in seen or manager_id not in by_id:
            return None
        seen.add(manager_id)
        cursor = by_id[manager_id]
        depth += 1
    return depth


def load_speaker_profiles(turns: list[dict], bank_dir: Path | None) -> list[dict]:
    """只用稳定 person_id/voice 绑定或唯一精确名称关联身份；绝不模糊匹配。"""
    bank = _read_json(Path(bank_dir) / "bank.json", {}) if bank_dir else {}
    org_raw = _read_json(Path(bank_dir) / "orgchart.json", []) if bank_dir else []
    if isinstance(org_raw, dict):
        org_raw = org_raw.get("persons", [])
    persons = {str(p.get("id")): p for p in bank.get("persons", []) if p.get("id")}
    voices = {str(v.get("id")): v for v in bank.get("voices", []) if v.get("id")}

    org = [dict(item) for item in org_raw if isinstance(item, dict)]
    org_by_id = {str(o.get("id")): o for o in org if o.get("id")}
    # 兼容旧 leader 字段，但只接受唯一精确名字。
    org_name_ids: dict[str, list[str]] = {}
    for i, item in enumerate(org):
        oid = str(item.get("id") or f"legacy-{i}")
        item.setdefault("id", oid)
        org_by_id[oid] = item
        raw_names = [item.get("name", ""), *item.get("aliases", [])]
        raw_names += [n.get("value", "") if isinstance(n, dict) else n
                      for n in item.get("names", [])]
        for name in raw_names:
            if _norm(name):
                org_name_ids.setdefault(_norm(name), []).append(oid)
    for item in org:
        if item.get("manager_id") or not item.get("leader"):
            continue
        matches = list(dict.fromkeys(org_name_ids.get(_norm(item["leader"]), [])))
        if len(matches) == 1 and matches[0] != item["id"]:
            item["manager_id"] = matches[0]

    person_org: dict[str, dict] = {}
    for item in org:
        pid = str(item.get("person_id") or "")
        if pid and pid in persons and pid not in person_org:
            person_org[pid] = item
    # 老数据没有 person_id 时，仅用人员已确认名称唯一精确关联。
    for pid, person in persons.items():
        if pid in person_org:
            continue
        names = [person.get("name", ""), person.get("display_name", ""), *person.get("aliases", [])]
        names += [n.get("value", "") if isinstance(n, dict) else n
                  for n in person.get("names", []) if not isinstance(n, dict) or n.get("verified", True)]
        matched = set()
        for name in names:
            ids = list(dict.fromkeys(org_name_ids.get(_norm(name), [])))
            if len(ids) == 1:
                matched.add(ids[0])
        if len(matched) == 1:
            person_org[pid] = org_by_id[next(iter(matched))]

    speaker_voices: dict[str, list[str]] = {}
    for turn in turns:
        speaker = str(turn.get("speaker") or "未知")
        voice = str(turn.get("voice") or "")
        if voice and voice not in speaker_voices.setdefault(speaker, []):
            speaker_voices[speaker].append(voice)
        else:
            speaker_voices.setdefault(speaker, [])

    profiles = []
    for speaker, voice_ids in speaker_voices.items():
        pids = {str(voices[v].get("person_id")) for v in voice_ids
                if v in voices and voices[v].get("person_id") in persons}
        pid = next(iter(pids)) if len(pids) == 1 else None
        person = persons.get(pid, {}) if pid else {}
        entry = person_org.get(pid) if pid else None
        if entry is None:
            exact = list(dict.fromkeys(org_name_ids.get(_norm(speaker), [])))
            entry = org_by_id.get(exact[0]) if len(exact) == 1 else None
        profiles.append({
            "speaker": speaker,
            "voice_ids": voice_ids,
            "person_id": pid,
            "display_name": person.get("display_name") or person.get("name") or speaker,
            "identity_basis": "verified_voice_binding" if pid else "speaker_label_only",
            "title": str((entry or {}).get("title") or ""),
            "team": str((entry or {}).get("team") or ""),
            "org_depth": _org_depth(entry, org_by_id) if entry else None,
            "authority_context": "role_context_only" if entry else "unknown",
        })
    return profiles


def speaker_navigation(turns: list[dict], profiles: list[dict],
                       transcript_format: str | None = None) -> list[dict]:
    """给阅读器的最小人物选择投影。

    声纹绑定证明跨会议稳定身份；VTT/DOCX 姓名只证明本场标签可靠；未具名但已有
    voice_id 的分离簇也足以在本场跳播。只有没能提取出声音簇的短片段保持禁选。
    """
    named_transcript = str(transcript_format or "").lower().lstrip(".") in {"vtt", "docx"}
    profile_by_speaker = {str(p.get("speaker") or ""): p for p in profiles}
    names = list(dict.fromkeys(str(turn.get("speaker") or "未知") for turn in turns))
    voices_by_speaker = {
        name: {str(turn.get("voice")) for turn in turns
               if str(turn.get("speaker") or "未知") == name and turn.get("voice")}
        for name in names
    }

    def anonymous(name: str) -> bool:
        compact = re.sub(r"\s+", "", name).lower()
        return (not compact or "(声音" in name or compact in {"未知", "未具名", "unknown"}
                or re.fullmatch(r"(?:说话人|speaker)\d+", compact) is not None)

    out = []
    for name in names:
        profile = profile_by_speaker.get(name, {})
        if profile.get("person_id"):
            basis, selectable = "verified_voice_binding", True
        elif named_transcript and not anonymous(name):
            basis, selectable = "imported_transcript_label", True
        elif profile.get("voice_ids") or voices_by_speaker.get(name):
            basis, selectable = "session_voice_cluster", True
        else:
            basis, selectable = "insufficient_voice_sample", False
        out.append({"speaker": name, "selectable": selectable, "identity_basis": basis})
    return out


def build_prompt_context(turns: list[dict], pages: list[dict], descs: dict[int, str],
                         profiles: list[dict], *, detail: bool = False,
                         page_numbers: set[int] | None = None) -> dict:
    selected_pages = [p for p in pages if page_numbers is None or int(p["page"]) in page_numbers]
    selected_numbers = {int(p["page"]) for p in selected_pages}
    page_rows = []
    for page in selected_pages:
        number = int(page["page"])
        description = str(descs.get(number, ""))
        row = {
            "id": page_id(number),
            "number": number,
            "first": round(float(page.get("first", 0)), 3),
            "ranges": page.get("ranges", []),
            "visual_summary": " ".join(description.split())[:500],
        }
        if detail:
            row["visual_detail"] = description
        page_rows.append(row)
    turn_rows = []
    by_voice = {v: p for p in profiles for v in p.get("voice_ids", [])}
    for index, turn in enumerate(turns):
        mid = (float(turn.get("start", 0)) + float(turn.get("end", 0))) / 2
        page = _page_for_time(pages, mid)
        number = int(page["page"]) if page else None
        if page_numbers is not None and number not in selected_numbers:
            continue
        profile = by_voice.get(str(turn.get("voice") or ""))
        turn_rows.append({
            "id": turn_id(index),
            "index": index,
            "start": round(float(turn.get("start", 0)), 3),
            "end": round(float(turn.get("end", 0)), 3),
            "speaker": str(turn.get("speaker") or "未知"),
            "voice_id": turn.get("voice"),
            "person_id": (profile or {}).get("person_id"),
            "page_id": page_id(number) if number is not None else None,
            "text": str(turn.get("text") or ""),
        })
    return {
        "schema": "meeting-minutes-prompt/v1",
        "speaker_profiles": profiles,
        "pages": page_rows,
        "turns": turn_rows,
    }


def _marker_values(raw: str) -> dict[str, str]:
    values = {}
    for token in raw.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _ids(value: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(x for x in value.split(",") if re.fullmatch(prefix + r"\d+", x)))


def _clean_markdown_text(value: str) -> str:
    value = MARKER_RE.sub("", value)
    value = strip_visible_evidence_ids(value)
    value = re.sub(r"!\[[^]]*]\([^)]*\)", "", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    value = re.sub(r"^[\s>*#-]+", "", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    return " ".join(value.split()).strip()


def strip_visible_evidence_ids(value: str) -> str:
    """移除人读正文中的冗余 T-ID 尾注，隐藏 marker 与 sidecar linkage 保持不变。"""
    return VISIBLE_TURN_CITATION_RE.sub("", str(value or ""))


def _table_cells(line: str) -> list[str]:
    """读取模型常见的简单 Markdown 表格行；不尝试解释单元格内的复杂 Markdown。"""
    value = MARKER_RE.sub("", str(line or "")).strip().replace("｜", "|")
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")] if "|" in value else []


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(TABLE_SEPARATOR_CELL_RE.fullmatch(cell.replace(" ", ""))
                               for cell in cells)


def normalize_minutes_markdown(minutes: str) -> str:
    """只修复确定可判定的 Markdown 表格语法，不改写纪要事实。

    小模型常把 `- **待办事项**：` 与下一行表格直接相连，Markdown 会把整张表
    当作列表正文。本函数在真正的表头+分隔行前补空行，并兼容全角竖线；旧纪要
    因而无需重新调用模型。
    """
    trailing_newline = str(minutes or "").endswith("\n")
    lines = str(minutes or "").splitlines()
    normalized = list(lines)
    for index in range(len(normalized) - 1):
        current = normalized[index]
        following = normalized[index + 1]
        # 只有下一行确实是表格分隔行时，才把整个连续表格块的全角竖线归一化。
        if len(_table_cells(current)) < 2 or not _is_table_separator(following):
            continue
        normalized[index] = current.replace("｜", "|")
        normalized[index + 1] = following.replace("｜", "|")
        cursor = index + 2
        while cursor < len(normalized) and normalized[cursor].strip():
            if len(_table_cells(normalized[cursor])) < 2:
                break
            normalized[cursor] = normalized[cursor].replace("｜", "|")
            cursor += 1
    out: list[str] = []
    for index, line in enumerate(normalized):
        is_header = (index + 1 < len(normalized)
                     and len(_table_cells(line)) >= 2
                     and _is_table_separator(normalized[index + 1]))
        if is_header and out and out[-1].strip():
            out.append("")
        out.append(line)
    result = "\n".join(out)
    return result + "\n" if trailing_newline else result


READING_DETAIL_SECTION_RE = re.compile(
    r"^##\s+(?:分页详情|逐页详情|按页详情|页面详情|"
    r"附录\s*[:：-]?\s*(?:页面|屏幕)(?:详解|详情|分析).*)\s*$",
    re.M,
)


def _markdown_cell(value) -> str:
    """把结构化字段安全放回 Markdown 表格单元格。"""
    text = " ".join(str(value or "").replace("\n", " ").split()).strip()
    return text.replace("|", "\\|")


def _grounded_actions_table(evidence: dict) -> str:
    """只投影带逐字稿主证据的行动项，避免把建议伪装成正式待办。"""
    status_names = {
        "confirmed": "已确认",
        "working_alignment": "方向共识",
        "proposal": "提议",
        "open": "待确认",
        "informational": "记录",
    }
    # 旧 sidecar 可能把逐页详情里的 `kind=action` 全部保存为 actions；读取时也要
    # 从 claims 重新投影，不能因历史缓存继续污染正式待办。
    actions = (action_items_from_claims(evidence.get("claims", []))
               if "claims" in evidence else evidence.get("actions", []))
    rows, seen = [], set()
    for action in actions:
        claim_id = str(action.get("claim_id") or "").strip()
        text = _markdown_cell(action.get("text"))
        turn_ids = [str(value) for value in action.get("turn_ids", []) if str(value)]
        if not (claim_id and text and turn_ids):
            continue
        owner = _markdown_cell(action.get("owner")) or "待确认"
        deadline = _markdown_cell(action.get("deadline")) or "待确认"
        status = (_markdown_cell(action.get("status"))
                  or status_names.get(str(action.get("claim_status") or ""), "待确认"))
        key = (text, owner, deadline, status)
        if key in seen:
            continue
        seen.add(key)
        rows.append(f"| {text} [依据](#mm-{claim_id}) | {owner} | {deadline} | {status} |")
    if not rows:
        return "未形成有逐字稿依据的明确待办。"
    return "\n".join([
        "| 事项 | 负责人 | 期限 | 状态 |",
        "| --- | --- | --- | --- |",
        *rows,
    ])


def _replace_section_body(markdown: str, title: str, replacement: str) -> str:
    match = re.search(rf"^(?P<marks>#{{1,6}})\s+{re.escape(title)}\s*$", markdown, re.M)
    if not match:
        return markdown
    level = len(match.group("marks"))
    end = len(markdown)
    for heading in HEADING_RE.finditer(markdown, match.end()):
        if len(heading.group(1)) <= level:
            end = heading.start()
            break
    before = markdown[:match.end()].rstrip()
    after = markdown[end:].lstrip("\n")
    return before + "\n\n" + replacement.strip() + "\n\n" + after


def _remove_section(markdown: str, title: str) -> str:
    match = re.search(rf"^(?P<marks>#{{1,6}})\s+{re.escape(title)}\s*$", markdown, re.M)
    if not match:
        return markdown
    level = len(match.group("marks"))
    end = len(markdown)
    for heading in HEADING_RE.finditer(markdown, match.end()):
        if len(heading.group(1)) <= level:
            end = heading.start()
            break
    return (markdown[:match.start()].rstrip() + "\n\n" + markdown[end:].lstrip("\n")).rstrip() + "\n"


def minutes_reading_markdown(minutes: str, evidence: dict | None = None, *,
                             include_topic_section: bool = True) -> str:
    """投影面向阅读与分享的常规纪要，不丢弃 canonical 逐页事实。

    逐页详情仍保留在原始 ``minutes.md``，供 evidence、RAG 与屏幕内容视图使用；
    Web 纪要和 MeetingPack 的 ``minutes.md`` 只呈现逐页详情之前的常规纪要，避免
    同一批页面事实同时出现在纪要、章节和屏幕内容三个入口。
    """
    normalized = normalize_minutes_markdown(minutes)
    match = READING_DETAIL_SECTION_RE.search(normalized)
    reading = normalized if not match else normalized[:match.start()].rstrip() + "\n"
    if evidence is not None:
        reading = _replace_section_body(
            reading, "待办事项", _grounded_actions_table(evidence))
    # 整场语义脉络已有独立视图；常规纪要不再重复铺一份容易失控的模型长列表。
    if not include_topic_section:
        reading = _remove_section(reading, "议题板块")
    return strip_visible_evidence_ids(reading)


def _action_fields(value: str) -> dict:
    cells = [_clean_markdown_text(cell) for cell in _table_cells(value)]
    # 状态列常只放 evidence marker，剥离后留下尾部空单元格；只丢尾部空，
    # 不能全表过滤，否则整行会退化成含竖线的纯文本。
    while cells and not cells[-1]:
        cells.pop()
    if len(cells) >= 4:
        # 事项中偶尔出现未转义的竖线；负责人/期限/状态从尾部稳定取值。
        return {
            "text": " | ".join(cells[:-3]),
            "owner": cells[-3],
            "deadline": cells[-2],
            "status": cells[-1],
        }
    if len(cells) == 3:
        # marker 占了状态列（或模型没写状态列）；状态交给 claim_status 兜底。
        return {
            "text": cells[0],
            "owner": cells[1],
            "deadline": cells[2],
            "status": None,
        }
    return {
        "text": _clean_markdown_text(value),
        "owner": None,
        "deadline": None,
        "status": None,
    }


def is_formal_action_claim(claim: dict) -> bool:
    """判断 claim 是否有资格进入正式待办，而不是普通过程记录。

    模型仍可在逐页详情中产生 action 线索，但正式任务只由整场待办章节投影。
    这样既保留原始 claim，又不会把“确认到会/介绍议程/汇报数字”算成待办。
    """
    section = re.sub(r"[\s_\-:：/]+", "", str(claim.get("section") or "")).casefold()
    return (
        claim.get("kind") == "action"
        and section in FORMAL_ACTION_SECTIONS
        and claim.get("status") != "informational"
        and bool(claim.get("turn_ids"))
    )


def action_items_from_claims(claims: list[dict]) -> list[dict]:
    """把有证据的 action claim 投影为稳定字段，供 Web、导出和 RAG 共用。"""
    actions = []
    for claim in claims:
        if not is_formal_action_claim(claim):
            continue
        fields = dict(claim.get("action") or _action_fields(str(claim.get("text", ""))))
        if "|" in str(fields.get("text") or ""):
            # 旧 sidecar / 小模型偶尔把整行或前三个单元格塞进 text，同时又把
            # text/owner/deadline 向右复制一遍。先重拆被污染的 text；这比继续信任
            # 已经非原子化的 owner 更可靠，且合法单元格内的竖线本就必须转义。
            reparsed = _action_fields(str(fields.get("text") or ""))
            if reparsed.get("owner"):
                reparsed["status"] = fields.get("status") or reparsed.get("status")
                fields = reparsed
        if fields.get("owner") is None and "|" in str(claim.get("text") or ""):
            # marker 占状态列的旧 sidecar：退回完整 claim 原文重拆。
            reparsed = _action_fields(str(claim.get("text") or ""))
            if reparsed.get("owner"):
                fields = reparsed
        if not fields.get("text"):
            fields["text"] = str(claim.get("text") or "").strip()
        actions.append({
            "id": f"A{len(actions) + 1:05d}",
            "claim_id": claim.get("id"),
            **fields,
            "claim_status": claim.get("status"),
            "confidence": claim.get("confidence"),
            "turn_ids": list(claim.get("turn_ids", [])),
            "page_ids": list(claim.get("page_ids", [])),
            "evidence_ids": list(claim.get("evidence_ids", [])),
            "start": claim.get("start"),
        })
    return actions


def project_action_semantics(evidence: dict, minutes: str | None = None) -> dict:
    """为新旧 evidence 统一重建正式待办，并标记未晋级的 action claim。"""
    claims = evidence.get("claims", [])
    for claim in claims:
        claim["formal_action"] = is_formal_action_claim(claim)
    actions = action_items_from_claims(claims)
    evidence["actions"] = actions
    if minutes is not None:
        evidence["action_candidates"] = action_candidates_from_minutes(minutes, actions)
    linkage = evidence.setdefault("linkage", {})
    linkage["formal_action_count"] = len(actions)
    linkage["nonformal_action_claim_count"] = sum(
        claim.get("kind") == "action" and not claim.get("formal_action") for claim in claims)
    return evidence


def action_candidates_from_minutes(minutes: str, grounded_actions: list[dict] | None = None) -> list[dict]:
    """保留总体待办表中尚未绑定 T ID 的候选，不把“无依据”误解成“应删除”。"""
    normalized = normalize_minutes_markdown(minutes)
    match = re.search(r"^(?P<marks>#{1,6})\s+待办事项\s*$", normalized, re.M)
    if not match:
        return []
    level = len(match.group("marks"))
    end = len(normalized)
    for heading in HEADING_RE.finditer(normalized, match.end()):
        if len(heading.group(1)) <= level:
            end = heading.start()
            break
    grounded_texts = {
        " ".join(str(item.get("text") or "").split()).casefold()
        for item in (grounded_actions or []) if item.get("text")
    }
    candidates, seen = [], set()
    for line in normalized[match.end():end].splitlines():
        cells = _table_cells(line)
        if len(cells) < 4 or _is_table_separator(line):
            continue
        fields = _action_fields(line)
        text = " ".join(str(fields.get("text") or "").split()).strip()
        if not text or text in {"事项", "行动项", "待办"}:
            continue
        key = text.casefold()
        if key in grounded_texts or key in seen:
            continue
        seen.add(key)
        candidates.append({
            "id": f"U{len(candidates) + 1:05d}",
            "text": text,
            "owner": fields.get("owner") or "待确认",
            "deadline": fields.get("deadline") or "待确认",
            "original_status": fields.get("status") or "待确认",
            "verification_state": "unlinked",
        })
    return candidates


def parse_claims(minutes: str, valid_turns: set[str], valid_pages: set[str]) -> list[dict]:
    claims, heading, previous_line = [], "", ""
    lines = minutes.splitlines()
    for line_number, line in enumerate(lines, 1):
        hm = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if hm:
            heading = hm.group(1).strip()
        matches = list(MARKER_RE.finditer(line))
        for match in matches:
            values = _marker_values(match.group(1))
            turns = [x for x in _ids(values.get("turns", ""), "T") if x in valid_turns]
            pages = [x for x in _ids(values.get("pages", ""), "P") if x in valid_pages]
            if not turns and not pages:
                continue
            raw_text = line[:match.start()].strip() or previous_line
            text = _clean_markdown_text(raw_text)
            if not text:
                continue
            claim = {
                "id": f"C{len(claims) + 1:05d}",
                "text": text,
                "section": heading,
                "kind": values.get("kind", "discussion"),
                "status": values.get("status", "informational"),
                "confidence": values.get("confidence", "medium"),
                "turn_ids": turns,
                "page_ids": pages,
                "evidence_ids": turns + pages,
                "line": line_number,
                "marker": match.group(0),
            }
            if claim["kind"] == "action":
                # marker 可能位于事项单元格中间，也可能单独跟在整行后面；解析完整行。
                action_line = MARKER_RE.sub("", line).strip() or previous_line
                claim["action"] = _action_fields(action_line)
            claims.append(claim)
        if line.strip() and not matches:
            previous_line = line.strip()
    return claims


def _meeting_uid(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"meeting-minutes:meeting:{slug}"))


def _artifact_uid(slug: str, transcript_revision: str | None, minutes_revision: str) -> str:
    raw = f"meeting-minutes:artifact:{slug}:{transcript_revision or 'no-transcript'}:{minutes_revision}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def build_evidence_document(mdir: Path, minutes: str, turns: list[dict], pages: list[dict],
                            descs: dict[int, str], profiles: list[dict],
                            generation: dict | None = None) -> dict:
    transcript_revision = file_revision(mdir / "transcript.spk.json")
    minutes_revision = hashlib.sha256(minutes.encode("utf-8")).hexdigest()[:16]
    slug = mdir.name
    meeting_uid = _meeting_uid(slug)
    artifact_uid = _artifact_uid(slug, transcript_revision, minutes_revision)
    profile_by_voice = {v: p for p in profiles for v in p.get("voice_ids", [])}
    turn_sources = []
    for index, turn in enumerate(turns):
        mid = (float(turn.get("start", 0)) + float(turn.get("end", 0))) / 2
        page = _page_for_time(pages, mid)
        profile = profile_by_voice.get(str(turn.get("voice") or ""), {})
        turn_sources.append({
            "id": turn_id(index),
            "index": index,
            "start": round(float(turn.get("start", 0)), 3),
            "end": round(float(turn.get("end", 0)), 3),
            "speaker": str(turn.get("speaker") or "未知"),
            "voice_id": turn.get("voice"),
            "person_id": profile.get("person_id"),
            "page_id": page_id(page["page"]) if page else None,
            "text": str(turn.get("text") or ""),
        })
    page_sources = []
    for page in pages:
        number = int(page["page"])
        pid = page_id(number)
        related = [t["id"] for t in turn_sources if t.get("page_id") == pid]
        page_sources.append({
            "id": pid,
            "number": number,
            "first": round(float(page.get("first", 0)), 3),
            "ranges": page.get("ranges", []),
            "image": f"slides/{page.get('image')}" if page.get("image") else None,
            "visual_description": str(descs.get(number, "")),
            "discussion_turn_ids": related,
            "display_status": "discussed" if related else "display_only",
        })
    valid_turns = {t["id"] for t in turn_sources}
    valid_pages = {p["id"] for p in page_sources}
    claims = parse_claims(minutes, valid_turns, valid_pages)
    turn_by_id = {t["id"]: t for t in turn_sources}
    for claim in claims:
        linked = [turn_by_id[x] for x in claim["turn_ids"] if x in turn_by_id]
        claim["turn_indexes"] = [t["index"] for t in linked]
        claim["start"] = min((t["start"] for t in linked), default=None)
        claim["end"] = max((t["end"] for t in linked), default=None)
        claim["speakers"] = list(dict.fromkeys(t["speaker"] for t in linked))
        claim["person_ids"] = list(dict.fromkeys(t["person_id"] for t in linked if t.get("person_id")))
    document = {
        "schema": EVIDENCE_SCHEMA,
        "meeting_id": meeting_uid,
        "artifact_id": artifact_uid,
        "slug": slug,
        "revisions": {
            "transcript": transcript_revision,
            "minutes": minutes_revision,
            "slides": file_revision(mdir / "slides.json"),
            "page_descriptions": file_revision(mdir / "page_desc.json"),
        },
        "policy": CONCLUSION_POLICY,
        "generation": generation or {},
        "speaker_profiles": profiles,
        "sources": {"transcript": turn_sources, "pages": page_sources},
        "claims": claims,
        "actions": [],
        "action_candidates": [],
        "linkage": {
            "claim_count": len(claims),
            "claims_with_transcript": sum(bool(c["turn_ids"]) for c in claims),
            "claims_with_pages": sum(bool(c["page_ids"]) for c in claims),
        },
    }
    return project_action_semantics(document, minutes)


def build_fact_document(evidence: dict) -> dict:
    """把生成纪要里的全部 claim 固化为与阅读版式解耦的事实快照。

    快照只复制 claim 与来源引用，不复制逐字稿/页面正文。纪要重组后 evidence
    可以只描述当前阅读文档，而事实快照仍保留生成终稿时的完整信息库存。
    """
    revisions = evidence.get("revisions", {})
    claims = json.loads(json.dumps(evidence.get("claims", []), ensure_ascii=False))
    return {
        "schema": FACTS_SCHEMA,
        "meeting_id": evidence.get("meeting_id"),
        "source_artifact_id": evidence.get("artifact_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_revisions": {
            "transcript": revisions.get("transcript"),
            "slides": revisions.get("slides"),
            "page_descriptions": revisions.get("page_descriptions"),
        },
        "source_minutes_revision": revisions.get("minutes"),
        "policy": evidence.get("policy", CONCLUSION_POLICY),
        "speaker_profiles": json.loads(json.dumps(
            evidence.get("speaker_profiles", []), ensure_ascii=False)),
        "claims": claims,
        "stats": {
            "claims": len(claims),
            "with_transcript": sum(bool(item.get("turn_ids")) for item in claims),
            "with_pages": sum(bool(item.get("page_ids")) for item in claims),
            "formal_actions": sum(bool(item.get("formal_action")) for item in claims),
        },
    }


def fact_document_state(mdir: Path, document: dict | None = None) -> str:
    """事实快照只跟随原始来源；改变纪要版式不会令它过期。"""
    mdir = Path(mdir)
    value = document if document is not None else _read_json(mdir / "meeting.facts.json", {})
    if value.get("schema") != FACTS_SCHEMA:
        return "missing"
    expected = value.get("source_revisions", {})
    current = {
        "transcript": file_revision(mdir / "transcript.spk.json"),
        "slides": file_revision(mdir / "slides.json"),
        "page_descriptions": file_revision(mdir / "page_desc.json"),
    }
    return "ready" if expected == current else "stale"


def write_fact_document(mdir: Path, evidence: dict) -> tuple[Path, dict]:
    mdir = Path(mdir)
    document = build_fact_document(evidence)
    path = mdir / "meeting.facts.json"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path, document


def refresh_fact_document_sources(mdir: Path, evidence: dict) -> tuple[Path, dict]:
    """在说话人等确定性来源变化后重绑完整事实，不用窄纪要覆盖库存。

    纪要重组后 ``evidence.claims`` 可能只是当前阅读投影。此时人员绑定或显示名
    变化仍需要刷新事实中的 speaker/person/time，但绝不能据此删除未展示 claims。
    """
    mdir = Path(mdir)
    current = _read_json(mdir / "meeting.facts.json", {})
    if current.get("schema") != FACTS_SCHEMA:
        return write_fact_document(mdir, evidence)
    revisions = evidence.get("revisions", {})
    source_revisions = {
        "transcript": revisions.get("transcript"),
        "slides": revisions.get("slides"),
        "page_descriptions": revisions.get("page_descriptions"),
    }
    speaker_profiles = evidence.get("speaker_profiles", [])
    path = mdir / "meeting.facts.json"
    if (current.get("source_revisions") == source_revisions
            and current.get("speaker_profiles", []) == speaker_profiles):
        return path, current
    document = json.loads(json.dumps(current, ensure_ascii=False))
    document["source_revisions"] = source_revisions
    document["speaker_profiles"] = json.loads(json.dumps(
        speaker_profiles, ensure_ascii=False))
    document["updated_at"] = datetime.now(timezone.utc).isoformat()
    turn_by_id = {
        str(turn.get("id")): turn
        for turn in evidence.get("sources", {}).get("transcript", [])
        if turn.get("id")
    }
    for claim in document.get("claims", []):
        linked = [turn_by_id[str(value)] for value in claim.get("turn_ids", [])
                  if str(value) in turn_by_id]
        claim["turn_indexes"] = [int(turn.get("index", 0)) for turn in linked]
        claim["start"] = min((turn.get("start") for turn in linked), default=None)
        claim["end"] = max((turn.get("end") for turn in linked), default=None)
        claim["speakers"] = list(dict.fromkeys(
            str(turn.get("speaker") or "未知") for turn in linked))
        claim["person_ids"] = list(dict.fromkeys(
            str(turn["person_id"]) for turn in linked if turn.get("person_id")))
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path, document


def ensure_fact_document(mdir: Path, evidence: dict) -> tuple[str, dict]:
    """读取当前事实层；旧会议首次使用时从现有完整 evidence 无模型迁移。"""
    mdir = Path(mdir)
    current = _read_json(mdir / "meeting.facts.json", {})
    state = fact_document_state(mdir, current)
    if state == "ready":
        return state, current
    if evidence.get("schema") != EVIDENCE_SCHEMA or not evidence.get("claims"):
        return state, {}
    _path, document = write_fact_document(mdir, evidence)
    return "ready", document


def write_evidence_document(mdir: Path, minutes: str, turns: list[dict], pages: list[dict],
                            descs: dict[int, str], profiles: list[dict],
                            generation: dict | None = None, *,
                            update_facts: bool = True) -> tuple[Path, dict]:
    document = build_evidence_document(
        mdir, minutes, turns, pages, descs, profiles, generation=generation)
    path = mdir / "minutes.evidence.json"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    if update_facts:
        write_fact_document(mdir, document)
    return path, document


# 模型常把 marker 包在反引号里（`<!-- mm:evidence … -->`）；不拆掉反引号的话，
# 替换出的“依据”链接会被 Markdown 当成行内代码渲染成纯文本。
WRAPPED_MARKER_RE = re.compile(r"`?[ \t]*(<!--\s*mm:evidence\s+[^<>]*?-->)[ \t]*`?")


def markdown_with_evidence_links(minutes: str, evidence: dict, *, label: str = "依据") -> str:
    """把不可见 marker 转成很轻的 Markdown“依据”链接；其余 marker 一律剥离。"""
    by_marker: dict[str, list[dict]] = {}
    for claim in evidence.get("claims", []):
        by_marker.setdefault(claim.get("marker", ""), []).append(claim)

    def replace(match):
        queue = by_marker.get(match.group(1), [])
        claim = queue.pop(0) if queue else None
        return f" [{label}](#mm-{claim['id']})" if claim else ""

    return WRAPPED_MARKER_RE.sub(replace, minutes)


def _minutes_sections(minutes: str) -> list[dict]:
    clean = MARKER_RE.sub("", minutes)
    matches = list(HEADING_RE.finditer(clean))
    sections = []
    for i, match in enumerate(matches):
        level = len(match.group(1))
        end = len(clean)
        for later in matches[i + 1:]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        text = clean[match.end():end]
        text = _clean_markdown_text(text)
        if text:
            sections.append({"heading": match.group(2).strip(), "level": level, "text": text})
    return sections


def rag_records(evidence: dict, minutes: str, facts: dict | None = None) -> list[dict]:
    """生成可直接写 JSONL 的检索记录；结论和原始证据用 ID 显式相连。"""
    meeting_id = evidence["meeting_id"]
    artifact_id = evidence["artifact_id"]
    common = {"schema": RAG_SCHEMA, "meeting_id": meeting_id, "artifact_id": artifact_id,
              "meeting_slug": evidence["slug"]}
    records = []
    for claim in evidence.get("claims", []):
        record = {
            **common,
            "id": f"{artifact_id}:claim:{claim['id']}",
            "record_type": "claim",
            "claim_type": claim["kind"],
            "status": claim["status"],
            "confidence": claim["confidence"],
            "text": claim["text"],
            "section": claim["section"],
            "start": claim.get("start"),
            "end": claim.get("end"),
            "speakers": claim.get("speakers", []),
            "person_ids": claim.get("person_ids", []),
            "evidence_ids": claim["evidence_ids"],
            "turn_ids": claim["turn_ids"],
            "page_ids": claim["page_ids"],
            "formal_action": bool(claim.get("formal_action")),
            "retrieval_priority": 1.0 if (
                claim["kind"] == "decision" or claim.get("formal_action")) else 0.8,
        }
        if claim.get("formal_action"):
            record["action"] = claim.get("action") or _action_fields(claim.get("text", ""))
        records.append(record)
    # 当前阅读纪要可以有意筛选事实；完整事实层中的未展示项仍进入 RAG，
    # 但不重复索引已经出现在当前纪要中的 marker。
    current_markers = {str(claim.get("marker") or "")
                       for claim in evidence.get("claims", [])}
    for index, claim in enumerate((facts or {}).get("claims", []), 1):
        marker = str(claim.get("marker") or "")
        if not marker or marker in current_markers:
            continue
        record = {
            **common,
            "id": f"{artifact_id}:fact:F{index:05d}",
            "source_id": f"F{index:05d}",
            "record_type": "fact",
            "claim_type": claim.get("kind", "discussion"),
            "status": claim.get("status", "informational"),
            "confidence": claim.get("confidence", "medium"),
            "text": claim.get("text", ""),
            "source_section": claim.get("section", ""),
            "start": claim.get("start"),
            "end": claim.get("end"),
            "speakers": claim.get("speakers", []),
            "person_ids": claim.get("person_ids", []),
            "evidence_ids": claim.get("evidence_ids", []),
            "turn_ids": claim.get("turn_ids", []),
            "page_ids": claim.get("page_ids", []),
            "formal_action": bool(claim.get("formal_action")),
            "retrieval_priority": 0.95 if (
                claim.get("kind") == "decision" or claim.get("formal_action")) else 0.76,
        }
        if claim.get("formal_action"):
            record["action"] = claim.get("action") or _action_fields(claim.get("text", ""))
        records.append(record)
    for turn in evidence.get("sources", {}).get("transcript", []):
        records.append({
            **common,
            "id": f"{artifact_id}:source:{turn['id']}",
            "source_id": turn["id"],
            "record_type": "transcript",
            "text": turn["text"],
            "speaker": turn["speaker"],
            "person_id": turn.get("person_id"),
            "start": turn["start"],
            "end": turn["end"],
            "page_id": turn.get("page_id"),
            "retrieval_priority": 0.7,
        })
    for page in evidence.get("sources", {}).get("pages", []):
        if not page.get("visual_description"):
            continue
        records.append({
            **common,
            "id": f"{artifact_id}:source:{page['id']}",
            "source_id": page["id"],
            "record_type": "slide",
            "text": page["visual_description"],
            "page_number": page["number"],
            "start": page["first"],
            "display_status": page["display_status"],
            "discussion_turn_ids": page["discussion_turn_ids"],
            "image": page.get("image"),
            "retrieval_priority": 0.55 if page["display_status"] == "discussed" else 0.35,
        })
    claim_by_section: dict[str, list[str]] = {}
    for claim in evidence.get("claims", []):
        claim_by_section.setdefault(claim["section"], []).append(claim["id"])
    for i, section in enumerate(_minutes_sections(minutes), 1):
        records.append({
            **common,
            "id": f"{artifact_id}:minutes:S{i:04d}",
            "record_type": "minutes_section",
            "text": section["text"],
            "section": section["heading"],
            "level": section["level"],
            "claim_ids": claim_by_section.get(section["heading"], []),
            "retrieval_priority": 0.75,
        })
    return records
