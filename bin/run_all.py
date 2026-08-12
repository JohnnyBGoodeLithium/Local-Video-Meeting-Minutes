#!/usr/bin/env python3
"""一条命令跑完整管线：WAV → 逐字稿 + 分说话人逐字稿 + 分说话人会议纪要。

流程：
    [1/3] 转写(Qwen3-ASR, GPU) 与 说话人分离(pyannote) 并行(两个进程)
    [2/3] 用分离时间段 + 字级时间戳合并出分说话人逐字稿
    [3/3] 分说话人逐字稿 → 本地 Qwen3.6 → 纪要(待办归属到说话人)

输出：meetings/<日期>_<录音时间或标题>/，每场会议自包含。

用法：
    bin/run_all.py recordings/20260806171137.WAV
    bin/run_all.py recordings/x.WAV --title 周会 --num-speakers 2 --diarize-device cpu

stdout 全程只有元数据，不打印任何转写/纪要内容。
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from meeting_dir import for_recording, materialize_audio, materialize_source

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
PY = Path(os.environ.get("MEETING_PYTHON", sys.executable)).expanduser()


def main() -> int:
    ap = argparse.ArgumentParser(description="端到端：WAV → 逐字稿+说话人+纪要")
    ap.add_argument("wav", type=Path)
    ap.add_argument("--title", default=None, help="会议标题(用于目录名)")
    ap.add_argument("--language", default=None, help="强制语言(如 Chinese)")
    ap.add_argument("--num-speakers", type=int, default=None, help="已知说话人数")
    ap.add_argument("--diarize-device", default=None,
                    help="分离用 cpu/cuda(默认自动，与转写共享 GPU)")
    args = ap.parse_args()

    original = args.wav.resolve()
    if not original.is_file():
        print(f"找不到输入文件: {original}", file=sys.stderr)
        return 1
    folder = for_recording(ROOT, original.stem, args.title)
    folder.mkdir(parents=True, exist_ok=True)
    source_audio = materialize_source(
        original, folder / f"source_audio{original.suffix.lower() or '.audio'}")
    wav = materialize_audio(source_audio, folder / "audio.wav")
    t_start = time.time()
    env = dict(os.environ, HF_HUB_OFFLINE="1")

    tr_cmd = [str(PY), str(BIN / "transcribe.py"), str(wav), "--out", str(folder)]
    if args.language:
        tr_cmd += ["--language", args.language]
    dz_cmd = [str(PY), str(BIN / "diarize.py"), str(wav), "--segments-only", "--out", str(folder)]
    if args.num_speakers:
        dz_cmd += ["--num-speakers", str(args.num_speakers)]
    if args.diarize_device:
        dz_cmd += ["--device", args.diarize_device]

    print(f"[1/3] 并行：转写 + 说话人分离 → {folder}", flush=True)
    p_tr = subprocess.Popen(tr_cmd, env=env)
    p_dz = subprocess.Popen(dz_cmd, env=env)
    rc_tr, rc_dz = p_tr.wait(), p_dz.wait()
    if rc_tr or rc_dz:
        print(f"失败：transcribe rc={rc_tr} diarize rc={rc_dz}", file=sys.stderr)
        return 1
    (folder / "source.json").write_text(json.dumps(
        {"audio": str(source_audio), "wav": str(wav), "original_name": original.name},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print("[2/3] 合并说话人轮次 ...", flush=True)
    rc = subprocess.run([str(PY), str(BIN / "diarize.py"), str(wav),
                         "--from-segments", str(folder / "diarization.json"),
                         "--out", str(folder)],
                        env=env).returncode
    if rc:
        return 1

    print("[3/3] 生成分说话人纪要 ...", flush=True)
    rc = subprocess.run([str(PY), str(BIN / "summarize.py"), str(folder / "transcript.txt"),
                         "--spk", str(folder / "transcript.spk.json"),
                         "--max-tokens", "8192"]).returncode
    if rc:
        return 1

    print(f"[meta] 全链路完成，总耗时 {time.time()-t_start:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
