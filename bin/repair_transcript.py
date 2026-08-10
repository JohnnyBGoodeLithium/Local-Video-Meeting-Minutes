#!/usr/bin/env python3
"""修复存量会议的逐字稿(全本地, 不重跑模型):

    1. 空格回填: 老版 stamps.json 的字级单元不含空格(英文单词粘连),
       用 stamps.json 里存的原始 text 双指针对齐回填
    2. 分离段平滑: diarization.json 的亚秒碎段并入前段(防标签抖动切碎轮次)
    3. 重放合并(diarize.py --from-segments)重建 transcript.spk.json/md
       (重放自带 同说话人≤3s 合并)
    4. 回填 voice 字段(backfill_voice_ids.py)

用法: bin/repair_transcript.py meetings/<会议目录>
stdout 只打印元数据。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe import reinsert_spaces  # noqa: E402
from diarize import smooth_dia  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: repair_transcript.py meetings/<会议目录>", file=sys.stderr)
        return 1
    mdir = Path(sys.argv[1])
    stamps_p = mdir / "stamps.json"
    dia_p = mdir / "diarization.json"
    if not stamps_p.is_file() or not dia_p.is_file() or not (mdir / "audio.wav").is_file():
        print("需要会议目录里有 stamps.json / diarization.json / audio.wav", file=sys.stderr)
        return 1

    # 1) 空格回填
    data = json.loads(stamps_p.read_text(encoding="utf-8"))
    stamps = data["time_stamps"]
    before = sum(s["text"].count(" ") for s in stamps)
    fixed = reinsert_spaces(data.get("text", ""), [s["text"] for s in stamps])
    after = sum(t.count(" ") for t in fixed)
    if after > before:
        for s, t in zip(stamps, fixed):
            s["text"] = t
        stamps_p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[meta] 空格回填: {before} → {after}", flush=True)

    # 2) 分离段平滑
    segs = json.loads(dia_p.read_text(encoding="utf-8"))
    smoothed = smooth_dia([(float(t["start"]), float(t["end"]), str(t["speaker"])) for t in segs])
    if len(smoothed) != len(segs):
        dia_p.write_text(json.dumps(
            [{"start": round(s, 3), "end": round(e, 3), "speaker": spk}
             for s, e, spk in smoothed], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[meta] 分离段: {len(segs)} → {len(smoothed)}", flush=True)

    # 3) 重放合并
    rc = subprocess.run([str(PY), str(ROOT / "bin" / "diarize.py"), str(mdir / "audio.wav"),
                         "--from-segments", str(dia_p), "--out", str(mdir)]).returncode
    if rc:
        return rc
    turns = json.loads((mdir / "transcript.spk.json").read_text(encoding="utf-8"))
    print(f"[meta] 重建轮次: {len(turns)}", flush=True)

    # 4) voice 字段回填
    subprocess.run([str(PY), str(ROOT / "bin" / "backfill_voice_ids.py")],
                   check=False, capture_output=True)
    print("[meta] 修复完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
