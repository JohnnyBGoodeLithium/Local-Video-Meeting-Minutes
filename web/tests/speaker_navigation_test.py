"""说话人跳播身份边界测试（全合成数据，不读取真实会议或声纹库）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "bin"))

from meeting_artifact import speaker_navigation  # noqa: E402


turns = [
    {"speaker": "Imported Example", "voice": "v_named"},
    {"speaker": "说话人2", "voice": "v_anon"},
    {"speaker": "Verified Example", "voice": "v_bound"},
]
profiles = [
    {"speaker": "Imported Example", "person_id": None},
    {"speaker": "说话人2", "person_id": None},
    {"speaker": "Verified Example", "person_id": "p_synthetic"},
]


def by_name(rows):
    return {row["speaker"]: row for row in rows}


audio = by_name(speaker_navigation(turns, profiles, "wav"))
assert audio["Imported Example"] == {
    "speaker": "Imported Example", "selectable": True,
    "identity_basis": "session_voice_cluster",
}
assert audio["说话人2"]["selectable"] is True
assert audio["说话人2"]["identity_basis"] == "session_voice_cluster"
assert audio["Verified Example"]["selectable"] is True
assert audio["Verified Example"]["identity_basis"] == "verified_voice_binding"

for transcript_format in ("vtt", ".docx", "DOCX"):
    imported = by_name(speaker_navigation(turns, profiles, transcript_format))
    assert imported["Imported Example"]["selectable"] is True
    assert imported["Imported Example"]["identity_basis"] == "imported_transcript_label"
    assert imported["Imported Example"].get("person_id") is None
    assert imported["说话人2"]["selectable"] is True
    assert imported["说话人2"]["identity_basis"] == "session_voice_cluster"
    assert imported["Verified Example"]["identity_basis"] == "verified_voice_binding"

too_short = by_name(speaker_navigation(
    [{"speaker": "说话人3", "voice": None}],
    [{"speaker": "说话人3", "voice_ids": [], "person_id": None}], "wav"))
assert too_short["说话人3"] == {
    "speaker": "说话人3", "selectable": False,
    "identity_basis": "insufficient_voice_sample",
}

print("speaker navigation: verified/imported/session/short-sample boundary passed")
