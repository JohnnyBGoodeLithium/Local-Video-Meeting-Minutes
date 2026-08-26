"""媒体内容形态与叙事泳道的确定性投影。

Topic Map 负责回答“讲了什么”；本模块只把已有 topic/child 时间范围投影为
“这段起什么作用”，并根据逐字稿轮次判断人物泳道是否有浏览价值。它不读取
正文重新推断事实，也不调用模型。
"""

from __future__ import annotations

from collections import defaultdict


SCHEMA = "media-navigation/v1"
ROLE_ORDER = ("setup", "thesis", "explanation", "evidence", "demo", "caveat", "conclusion")
ROLE_PRIORITY = {name: index for index, name in enumerate(ROLE_ORDER)}


def narrative_role(node_type: str | None) -> str:
    return {
        "context": "setup",
        "argument": "thesis",
        "discussion": "explanation",
        "evidence": "evidence",
        "demo": "demo",
        "counterpoint": "caveat",
        "risk": "caveat",
        "open_question": "caveat",
        "decision": "conclusion",
        "conclusion": "conclusion",
    }.get(str(node_type or ""), "explanation")


def classify_media_format(turns: list[dict]) -> dict:
    """按有效人物、发言占比和轮次交替判断口播/访谈/混合。

    这只是 UI 投影，不改变 canonical 说话人身份。阈值刻意保守：短暂提问不会
    把整场演讲误判成访谈；两位以上持续交替才进入 interview。
    """
    duration_by_speaker: dict[str, float] = defaultdict(float)
    turn_count: dict[str, int] = defaultdict(int)
    normalized = []
    for turn in turns:
        speaker = str(turn.get("speaker") or "未知")
        start = float(turn.get("start", 0) or 0)
        end = max(start, float(turn.get("end", start) or start))
        duration_by_speaker[speaker] += end - start
        turn_count[speaker] += 1
        normalized.append((speaker, start, end))
    total = sum(duration_by_speaker.values()) or 1.0
    meaningful = [speaker for speaker, seconds in duration_by_speaker.items()
                  if seconds >= max(10.0, total * .03) or turn_count[speaker] >= 3]
    shares = sorted((duration_by_speaker[speaker] / total for speaker in meaningful), reverse=True)
    dominant_share = shares[0] if shares else 1.0
    meaningful_set = set(meaningful)
    sequence = [speaker for speaker, _start, _end in normalized if speaker in meaningful_set]
    alternations = sum(left != right for left, right in zip(sequence, sequence[1:]))

    if len(meaningful) <= 1 or (dominant_share >= .88 and alternations <= 2):
        media_format = "monologue"
    elif len(meaningful) >= 2 and dominant_share <= .72 and alternations >= 3:
        media_format = "interview"
    else:
        media_format = "hybrid"
    return {
        "format": media_format,
        "show_narrative_lane": media_format != "interview",
        "show_speaker_lane": media_format != "monologue",
        "meaningful_speakers": len(meaningful),
        "dominant_share": round(dominant_share, 4),
        "alternations": alternations,
    }


def _ranges(node: dict) -> list[tuple[float, float]]:
    output = []
    for value in node.get("ranges") or []:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            continue
        start, end = float(value[0] or 0), float(value[1] or 0)
        if end > start:
            output.append((start, end))
    return output


def narrative_segments(topic_map: dict) -> list[dict]:
    """把 child ranges 压成互斥的叙事角色区段；无 child 覆盖处退回讲解。"""
    output = []
    for topic in topic_map.get("topics") or []:
        topic_id = str(topic.get("id") or "")
        for topic_start, topic_end in _ranges(topic):
            children = []
            boundaries = {topic_start, topic_end}
            for child in topic.get("children") or []:
                for start, end in _ranges(child):
                    start, end = max(topic_start, start), min(topic_end, end)
                    if end <= start:
                        continue
                    role = narrative_role(child.get("type"))
                    children.append((start, end, role, str(child.get("id") or ""),
                                     str(child.get("title") or "")))
                    boundaries.update((start, end))
            points = sorted(boundaries)
            for start, end in zip(points, points[1:]):
                if end - start < .05:
                    continue
                midpoint = (start + end) / 2
                covering = [item for item in children if item[0] <= midpoint < item[1]]
                if covering:
                    # 同一时间有多个作用时选择更接近产出端的角色，例如证据覆盖讲解。
                    chosen = max(covering, key=lambda item: ROLE_PRIORITY[item[2]])
                    role, node_id, title = chosen[2], chosen[3], chosen[4]
                else:
                    role, node_id, title = "explanation", topic_id, str(topic.get("title") or "")
                if (output and output[-1]["role"] == role
                        and output[-1]["topic_id"] == topic_id
                        and abs(output[-1]["end"] - start) < .1):
                    output[-1]["end"] = round(end, 3)
                else:
                    output.append({
                        "id": f"N{len(output) + 1:03d}", "role": role,
                        "topic_id": topic_id, "node_id": node_id,
                        "title": title, "start": round(start, 3), "end": round(end, 3),
                    })
    return output


def build_media_navigation(turns: list[dict], topic_map: dict) -> dict:
    profile = classify_media_format(turns)
    return {"schema": SCHEMA, **profile, "segments": narrative_segments(topic_map)}
