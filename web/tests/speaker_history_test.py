"""说话人修改事务、逐轮保护与撤销测试（不读取真实会议）。"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

WEB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WEB))

import speaker_corrections as corrections  # noqa: E402
import speaker_history as history  # noqa: E402


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    meeting = root / "meeting"
    bank = root / "bank"
    meeting.mkdir()
    (bank / "emb").mkdir(parents=True)
    before_turns = [
        {"start": 1.0, "end": 2.0, "voice": "v1", "speaker": "A"},
        {"start": 3.0, "end": 4.0, "voice": "v1", "speaker": "A"},
    ]
    write(bank / "bank.json", '{"voices":[]}')
    np.save(bank / "emb" / "v1.npy", np.array([1.0, 0.0], dtype=np.float32))
    write(meeting / "transcript.spk.json",
          json.dumps(before_turns, ensure_ascii=False))
    write(meeting / "transcript.spk.md", "[00:01] **A**: before")

    # 成功事务可以发现并撤销，且恢复新增/修改过的 embedding。
    with history.transaction(meeting, bank, "split"):
        write(bank / "bank.json", '{"voices":[{"id":"v2"}]}')
        np.save(bank / "emb" / "v1.npy", np.array([0.0, 1.0], dtype=np.float32))
        np.save(bank / "emb" / "v2.npy", np.array([0.5, 0.5], dtype=np.float32))
        changed = [dict(before_turns[0], voice="v2", speaker="B"), before_turns[1]]
        write(meeting / "transcript.spk.json", json.dumps(changed, ensure_ascii=False))
        write(meeting / "transcript.spk.md", "[00:01] **B**: after")
        corrections.lock_turns(
            meeting, changed, [0], person_id="p2", voice_id="v2", operation="split")

    available = history.latest_available(meeting, bank)
    assert available is not None
    history.restore(available[0], meeting, bank, require_current=True)
    assert json.loads((meeting / "transcript.spk.json").read_text()) == before_turns
    assert not (meeting / "speaker.corrections.json").exists()
    assert not (bank / "emb" / "v2.npy").exists()
    assert np.allclose(np.load(bank / "emb" / "v1.npy"), [1.0, 0.0])

    # 失败事务自动回滚，不留下半改状态。
    try:
        with history.transaction(meeting, bank, "bind"):
            write(bank / "bank.json", '{"broken":true}')
            raise RuntimeError("expected")
    except RuntimeError:
        pass
    assert (bank / "bank.json").read_text() == '{"voices":[]}'

    # 锁按时间指纹匹配，不保存逐字稿正文。
    corrections.lock_turns(
        meeting, before_turns, [1], person_id="p1", voice_id="v1", operation="bind")
    assert corrections.locked_indexes(meeting, before_turns) == {1}
    raw_lock = (meeting / "speaker.corrections.json").read_text()
    assert "before" not in raw_lock

print("speaker history: transaction, protection and undo passed")
