#!/usr/bin/env python3
"""一条命令跑完整管线：WAV → 逐字稿 + 分说话人逐字稿 + 分说话人会议纪要。

流程：
    [1/3] 转写(Qwen3-ASR, GPU) 与 说话人分离(pyannote) 并行(两个进程)
    [2/3] 用分离时间段 + 字级时间戳合并出分说话人逐字稿
    [2.5/3] 声纹入库(跨会议命中即具名; 失败只警告, 不中断)
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
from meeting_core.transcript_review import bind_review_to_transcript
from meeting_core.resource_policy import prepare_stage
from meeting_core.llm import DEFAULT_DRAFT_MODEL
from meeting_core.progress_events import (output_ready, phase_done,
                                          progress as progress_event)

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
    ap.add_argument("--meeting-dir", type=Path, default=None,
                    help="在已有纯音频会议目录中重跑（只供受控包装器调用）")
    args = ap.parse_args()

    original = args.wav.resolve()
    if not original.is_file():
        print(f"找不到输入文件: {original}", file=sys.stderr)
        return 1
    if args.meeting_dir is not None:
        data_root = Path(os.environ.get(
            "MEETING_DATA_ROOT", os.environ.get("MEETING_MINUTES_ROOT", ROOT))).resolve()
        folder = args.meeting_dir.resolve()
        if folder.parent != (data_root / "meetings").resolve() or not folder.is_dir():
            print("已有会议目录不在受控 meetings 边界内", file=sys.stderr)
            return 2
    else:
        folder = for_recording(ROOT, original.stem, args.title)
    folder.mkdir(parents=True, exist_ok=True)
    progress_event("prepare")
    source_audio = materialize_source(
        original, folder / f"source_audio{original.suffix.lower() or '.audio'}")
    wav = materialize_audio(source_audio, folder / "audio.wav")
    phase_done("prepare")
    t_start = time.time()
    env = dict(os.environ, HF_HUB_OFFLINE="1")

    tr_cmd = [str(PY), str(BIN / "transcribe.py"), str(wav), "--out", str(folder)]
    tr_cmd += ["--context-title", args.title or folder.name]
    if args.language:
        tr_cmd += ["--language", args.language]
    dz_cmd = [str(PY), str(BIN / "diarize.py"), str(wav), "--segments-only", "--out", str(folder)]
    if args.num_speakers:
        dz_cmd += ["--num-speakers", str(args.num_speakers)]
    if args.diarize_device:
        dz_cmd += ["--device", args.diarize_device]

    print(f"[1/3] 并行：转写 + 说话人分离 → {folder}", flush=True)
    progress_event("speech_processing")
    prepare_stage("audio", keep=[DEFAULT_DRAFT_MODEL], progress_phase="speech_processing")
    p_tr = subprocess.Popen(tr_cmd, env=env)
    p_dz = subprocess.Popen(dz_cmd, env=env)
    rc_tr, rc_dz = p_tr.wait(), p_dz.wait()
    if rc_tr or rc_dz:
        print(f"失败：transcribe rc={rc_tr} diarize rc={rc_dz}", file=sys.stderr)
        return 1
    source_path = folder / "source.json"
    try:
        source_meta = json.loads(source_path.read_text(encoding="utf-8")) \
            if source_path.is_file() else {}
    except Exception:
        source_meta = {}
    if not isinstance(source_meta, dict):
        source_meta = {}
    source_meta.update({"audio": str(source_audio), "wav": str(wav),
                        "original_name": original.name, "transcript_source": "local_asr"})
    temp = source_path.with_name(f".{source_path.name}.tmp-{os.getpid()}")
    temp.write_text(json.dumps(source_meta, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, source_path)

    print("[2/3] 合并说话人轮次 ...", flush=True)
    rc = subprocess.run([str(PY), str(BIN / "diarize.py"), str(wav),
                         "--from-segments", str(folder / "diarization.json"),
                         "--out", str(folder)],
                        env=env).returncode
    if rc:
        return 1

    print("[2.5/3] 声纹入库 ...", flush=True)
    rc = subprocess.run([str(PY), str(BIN / "voice_enroll.py"), str(folder)],
                        env=env).returncode
    if rc:
        print(f"警告：声纹入库失败(rc={rc})，不影响纪要生成；可稍后手动运行 "
              f"bin/voice_enroll.py {folder}", file=sys.stderr)
    bind_review_to_transcript(folder)
    phase_done("speech_processing")
    output_ready("transcript")
    output_ready("speaker_navigation")

    print("[3/3] 生成分说话人纪要 ...", flush=True)
    progress_event("final_minutes")
    rc = subprocess.run([str(PY), str(BIN / "summarize.py"), str(folder / "transcript.txt"),
                         "--spk", str(folder / "transcript.spk.json"),
                         "--max-tokens", "8192"]).returncode
    if rc:
        return 1
    phase_done("final_minutes")
    output_ready("final_minutes")

    print(f"[meta] 全链路完成，总耗时 {time.time()-t_start:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
