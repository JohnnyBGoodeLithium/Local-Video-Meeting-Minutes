#!/usr/bin/env python3
"""修复存量会议的逐字稿(全本地, 不重跑模型):

    1. 空格回填: 老版 stamps.json 的字级单元不含空格(英文单词粘连),
       用 stamps.json 里存的原始 text 双指针对齐回填
    2. 分离段平滑: 结合字级时间戳过滤孤立标签抖动，保留有文字依据的短插话
    3. 重放合并(diarize.py --from-segments)重建 transcript.spk.json/md
       (重放自带 同说话人≤3s 合并)
    4. 回填 voice 字段(backfill_voice_ids.py)

用法: bin/repair_transcript.py meetings/<会议目录>
stdout 只打印元数据。
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe import reinsert_spaces  # noqa: E402
from diarize import smooth_dia  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"


def _snapshot(mdir: Path) -> Path:
    base = mdir / ".versions" / f"before-transcript-timing-{time.strftime('%Y%m%d-%H%M%S')}"
    destination = base
    suffix = 1
    while destination.exists():
        suffix += 1
        destination = base.with_name(f"{base.name}-{suffix}")
    destination.mkdir(parents=True)
    copied = []
    for name in ("transcript.spk.json", "transcript.spk.md", "transcript.review.json"):
        source = mdir / name
        if source.is_file():
            shutil.copy2(source, destination / name)
            copied.append(name)
    (destination / "manifest.json").write_text(json.dumps({
        "schema": "meeting-transcript-timing-backup/v1", "created_at": time.time(),
        "operation": "transcript-timing", "files": copied,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def preserve_identity(new_turns: list[dict], old_turns: list[dict]) -> list[dict]:
    """按最大时间重叠把已确认姓名/voice 带到新的语义时间段。"""
    for turn in new_turns:
        start, end = float(turn.get("start", 0)), float(turn.get("end", 0))
        candidates = []
        for old in old_turns:
            overlap = min(end, float(old.get("end", 0))) - max(start, float(old.get("start", 0)))
            if overlap > 0:
                candidates.append((overlap, old))
        if not candidates and old_turns:
            midpoint = (start + end) / 2
            chosen = min(old_turns, key=lambda old: abs(
                midpoint - (float(old.get("start", 0)) + float(old.get("end", 0))) / 2))
        elif candidates:
            chosen = max(candidates, key=lambda item: item[0])[1]
        else:
            continue
        turn["speaker"] = chosen.get("speaker") or turn.get("speaker") or "未知"
        for key in ("voice", "person_id"):
            if key in chosen:
                turn[key] = chosen.get(key)
    return new_turns


def _write_turns(mdir: Path, turns: list[dict]) -> None:
    path = mdir / "transcript.spk.json"
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)
    md = [f"# {mdir.name} 逐字稿(具名)\n"]
    md += [f"[{int(float(t['start']))//3600:02d}:{int(float(t['start']))%3600//60:02d}:"
           f"{int(float(t['start']))%60:02d}] **{t['speaker']}**: {t['text']}\n" for t in turns]
    md_path = mdir / "transcript.spk.md"
    md_temp = md_path.with_name(f".{md_path.name}.tmp-{os.getpid()}")
    md_temp.write_text("\n".join(md), encoding="utf-8")
    os.replace(md_temp, md_path)


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
    old_turns = json.loads((mdir / "transcript.spk.json").read_text(encoding="utf-8")) \
        if (mdir / "transcript.spk.json").is_file() else []
    snapshot = _snapshot(mdir)

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
    chars = json.loads(stamps_p.read_text(encoding="utf-8"))["time_stamps"]
    smoothed = smooth_dia(
        [(float(t["start"]), float(t["end"]), str(t["speaker"])) for t in segs],
        chars=chars)
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
    turns = preserve_identity(turns, old_turns)
    _write_turns(mdir, turns)
    print(f"[meta] 重建轮次: {len(turns)}", flush=True)

    # 4) 已确认身份按时间重叠继承，不调用全库 backfill，避免无关会议被修改。
    preserved = sum(turn.get("voice") is not None for turn in turns)
    print(f"[meta] 身份继承: {preserved}/{len(turns)} 轮 | 快照 {snapshot.name}", flush=True)
    print("[meta] 修复完成；纪要、证据与脉络需使用当前逐字稿重新生成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
