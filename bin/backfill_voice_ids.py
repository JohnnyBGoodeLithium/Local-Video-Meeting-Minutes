#!/usr/bin/env python3
"""给存量会议的 transcript.spk.json 补 voice 字段(best-effort)。

映射规则: 每轮的 speaker 显示名 ↔ 声纹库里 voice 的 label_hint(如 "设备名(声音1)")
或其绑定后的 person.name。对不上的 voice=None(网页里该 chip 置灰, 不可绑定)。
stdout 只打印元数据。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_bank as vb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "speaker_bank"


def main() -> int:
    bank = vb.load_bank(BANK)
    name2voice = {}
    for v in bank["voices"]:
        for key in {v.get("label_hint"), vb.display_name(bank, v)}:
            if key:
                name2voice.setdefault(key, v["id"])
    n_ok = n_null = 0
    for ts in sorted((ROOT / "meetings").glob("*/transcript.spk.json")):
        turns = json.loads(ts.read_text(encoding="utf-8"))
        changed = False
        for t in turns:
            if "voice" in t:
                continue
            t["voice"] = name2voice.get(t["speaker"])
            changed = True
            n_ok += t["voice"] is not None
            n_null += t["voice"] is None
        if changed:
            ts.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[meta] {ts.parent.name}: {len(turns)} 轮已补", flush=True)
    print(f"[meta] 完成: 映射成功 {n_ok} 轮 | 未映射 {n_null} 轮", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
