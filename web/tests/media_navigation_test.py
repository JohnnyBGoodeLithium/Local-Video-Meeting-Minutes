#!/usr/bin/env python3
"""媒体形态与叙事泳道的纯虚构回归。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))

from meeting_core.media_navigation import build_media_navigation, classify_media_format  # noqa: E402


mono = [{"speaker": "Example Host", "start": i * 30, "end": (i + 1) * 30}
        for i in range(8)]
assert classify_media_format(mono)["format"] == "monologue"
assert classify_media_format(mono)["show_speaker_lane"] is False

interview = []
for i in range(10):
    interview.append({"speaker": "Example Host" if i % 2 == 0 else "Example Guest",
                      "start": i * 20, "end": (i + 1) * 20})
profile = classify_media_format(interview)
assert profile["format"] == "interview" and profile["show_speaker_lane"] is True
assert profile["show_narrative_lane"] is False

topic_map = {"topics": [{
    "id": "M01", "title": "Fictional Architecture", "ranges": [[0, 100]],
    "children": [
        {"id": "M01-01", "type": "context", "title": "Background", "ranges": [[0, 20]]},
        {"id": "M01-02", "type": "argument", "title": "Claim", "ranges": [[20, 55]]},
        {"id": "M01-03", "type": "evidence", "title": "Evidence", "ranges": [[55, 85]]},
        {"id": "M01-04", "type": "conclusion", "title": "Result", "ranges": [[85, 100]]},
    ],
}]}
navigation = build_media_navigation(mono, topic_map)
assert [item["role"] for item in navigation["segments"]] == [
    "setup", "thesis", "evidence", "conclusion"]
assert navigation["segments"][2]["start"] == 55

print("media navigation: monologue/interview/narrative roles passed")
