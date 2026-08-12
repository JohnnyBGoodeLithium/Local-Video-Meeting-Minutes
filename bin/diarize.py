#!/usr/bin/env python3
"""说话人分离(pyannote community-1, 全本地) + 与字级时间戳合并 → 带说话人的逐字稿。

用法：
    bin/diarize.py recordings/20260806171137.WAV
    bin/diarize.py meetings/2026-08-06_171137/audio.wav --from-segments meetings/2026-08-06_171137/diarization.json

输出(默认 meetings/<日期>_<时间或标题>/)：
    diarization.json   纯时间段 {start,end,speaker}，不含文字
    transcript.spk.md / transcript.spk.json   按说话人轮次组织的逐字稿

隐私红线：全程本地推理；stdout 只打印元数据(说话人数/时长/轮次)，不打印内容。
"""

import argparse
import json
import sys
import time
from pathlib import Path

from meeting_dir import for_recording
from meeting_core.hardware import configured_path, inference_device

HOME = Path.home()
ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = configured_path(
    "MEETING_PYANNOTE_MODEL",
    HOME / ".local/share/models/hf/pyannote/speaker-diarization-community-1")
SENT_END = tuple("。！？!?；;")


def _fmt_hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def smooth_dia(turns, min_dur: float = 1.0):
    """亚秒碎段并入前一段(防分离标签抖动把轮次切碎); 相邻同说话人直接合并。"""
    out = []
    for s, e, spk in turns:
        if out and e - s < min_dur:
            ps, _, pspk = out[-1]
            out[-1] = (ps, e, pspk)                 # 前段延长覆盖碎段
        elif out and out[-1][2] == spk:
            out[-1] = (out[-1][0], e, spk)
        else:
            out.append((s, e, spk))
    return out


def _join_text(a: str, b: str) -> str:
    """合并两轮文本：两边都是 ASCII 单词字符才补空格，中文直接相连。"""
    if not a or not b:
        return a + b
    if a[-1].isspace() or b[0].isspace():
        return a + b
    if a[-1].isascii() and a[-1].isalnum() and b[0].isascii() and b[0].isalnum():
        return a + " " + b
    return a + b


def coalesce_turns(turns, max_gap: float = 3.0):
    """同说话人相邻轮次、间隔 ≤max_gap 的合并(防静音/停顿切碎)。"""
    out = []
    for t in turns:
        if out and out[-1]["speaker"] == t["speaker"] and t["start"] - out[-1]["end"] <= max_gap:
            out[-1]["end"] = t["end"]
            out[-1]["text"] = _join_text(out[-1]["text"], t["text"])
        else:
            out.append(dict(t))
    return out


def assign_speakers(chars, turns):
    """每个字分配重叠最多的说话人；无重叠时取 1s 内最近的轮次。"""
    out = []
    for ch in chars:
        cs, ce = ch["start_time"], ch["end_time"]
        best, best_ov = None, 0.0
        for ts, te, spk in turns:
            ov = min(ce, te) - max(cs, ts)
            if ov > best_ov:
                best, best_ov = spk, ov
        if best is None and turns:
            mid = (cs + ce) / 2
            ts, te, best = min(turns, key=lambda t: min(abs(mid - t[0]), abs(mid - t[1])))
            if min(abs(mid - ts), abs(mid - te)) > 1.0:
                best = out[-1][0] if out else turns[0][2]
        out.append((best, ch["text"], cs, ce))
    return out


def to_turns(tagged, max_chars: int = 100, max_gap: float = 2.0):
    """(speaker, char, st, et) 序列 → 轮次列表。说话人切换/长停顿/句末超长则切。"""
    turns, buf, spk, start, last_end = [], [], None, None, None
    for s, t, st, et in tagged:
        gap = last_end is not None and (st - last_end) > max_gap
        too_long = len("".join(buf)) >= max_chars and buf and "".join(buf).rstrip().endswith(SENT_END)
        if buf and (s != spk or gap or too_long):
            turns.append({"speaker": spk, "start": start, "end": last_end, "text": "".join(buf).strip()})
            buf, start = [], None
        if start is None:
            start = st
        spk, last_end = s, et
        buf.append(t)
    if buf:
        turns.append({"speaker": spk, "start": start, "end": last_end, "text": "".join(buf).strip()})
    return [t for t in turns if t["text"]]


def main() -> int:
    ap = argparse.ArgumentParser(description="说话人分离 + 逐字稿合并(pyannote community-1)")
    ap.add_argument("wav", type=Path)
    ap.add_argument("--stamps", type=Path, default=None,
                    help="transcribe.py 的字级时间戳 json；默认 <会议目录>/transcript.json 或 stamps.json")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出目录(默认 meetings/<日期>_<时间>，可用 --title 起名)")
    ap.add_argument("--title", default=None, help="会议标题(用于目录名)")
    ap.add_argument("--num-speakers", type=int, default=None, help="已知说话人数(可选)")
    ap.add_argument("--segments-only", action="store_true",
                    help="只跑分离、输出时间段后退出(不和逐字稿合并)")
    ap.add_argument("--from-segments", type=Path, default=None,
                    help="跳过分离推理，直接用已有 diarization.json 做合并")
    ap.add_argument("--device", default=None, help="cpu 或 cuda(默认自动)")
    args = ap.parse_args()

    if not args.from_segments and not args.wav.is_file():
        print(f"找不到输入文件: {args.wav}", file=sys.stderr)
        return 1
    out = args.out or for_recording(ROOT, args.wav.stem, args.title)
    stamps_path = args.stamps or (out / "stamps.json")

    if args.from_segments:
        raw = json.loads(Path(args.from_segments).read_text(encoding="utf-8"))
        turns = sorted((float(t["start"]), float(t["end"]), str(t["speaker"])) for t in raw)
        elapsed = 0.0
    else:
        import torch
        import soundfile as sf
        from pyannote.audio import Pipeline

        device = args.device or inference_device(torch)
        t0 = time.time()
        pipeline = Pipeline.from_pretrained(str(MODEL_DIR))
        pipeline.to(torch.device(device))
        print(f"[meta] pyannote 加载 {time.time()-t0:.1f}s device={device}", flush=True)

        # 自己读音频，绕过 torchcodec 依赖
        wav, sr = sf.read(str(args.wav), dtype="float32", always_2d=True)
        audio = {"waveform": torch.from_numpy(wav.T), "sample_rate": sr}

        t0 = time.time()
        kw = {"num_speakers": args.num_speakers} if args.num_speakers else {}
        output = pipeline(audio, **kw)
        elapsed = time.time() - t0
        annotation = getattr(output, "speaker_diarization", output)
        turns = sorted((t.start, t.end, spk) for t, _, spk in annotation.itertracks(yield_label=True))

    turns = smooth_dia(turns)   # 亚秒碎段平滑(重放旧段文件同样受益)

    speakers = sorted({spk for _, _, spk in turns})
    # 段文件里存的已是 说话人N 标签；--from-segments 重放时不再重映射
    name_of = ({spk: spk for spk in speakers} if args.from_segments
               else {spk: f"说话人{i+1}" for i, spk in enumerate(speakers)})
    speech = {spk: sum(e - s for s, e, x in turns if x == spk) for spk in speakers}

    out.mkdir(parents=True, exist_ok=True)
    stem = args.wav.stem
    (out / "diarization.json").write_text(json.dumps(
        [{"start": round(s, 3), "end": round(e, 3), "speaker": name_of[x]} for s, e, x in turns],
        ensure_ascii=False, indent=1), encoding="utf-8")

    if args.segments_only:
        print(f"[meta] 分离耗时 {elapsed:.1f}s | 说话人 {len(speakers)} 个"
              f" | 分离段数 {len(turns)}(仅时间段，未合并)", flush=True)
        print(f"[meta] 输出目录: {out}", flush=True)
        return 0

    n_turns = 0
    if stamps_path.is_file():
        chars = json.loads(stamps_path.read_text(encoding="utf-8"))["time_stamps"]
        tagged = assign_speakers(chars, turns)
        spk_turns = coalesce_turns(to_turns(tagged))   # 同说话人小间隔合并
        for t in spk_turns:
            t["speaker"] = name_of[t["speaker"]]
            t["start"] = round(t["start"], 3)
            t["end"] = round(t["end"], 3)
        n_turns = len(spk_turns)
        (out / "transcript.spk.json").write_text(
            json.dumps(spk_turns, ensure_ascii=False, indent=1), encoding="utf-8")
        md = [f"# {stem} 分说话人逐字稿\n",
              f"> 说话人分离: pyannote community-1 | 转写: Qwen3-ASR-1.7B\n"]
        md += [f"[{_fmt_hms(t['start'])}] **{t['speaker']}**: {t['text']}\n" for t in spk_turns]
        (out / "transcript.spk.md").write_text("\n".join(md), encoding="utf-8")
    else:
        print(f"[meta] 未找到 {stamps_path}，只输出分离时间段", flush=True)

    stats = " | ".join(f"{name_of[s]} {speech[s]:.0f}s" for s in speakers)
    print(f"[meta] 分离耗时 {elapsed:.1f}s | 说话人 {len(speakers)} 个: {stats}"
          f" | 分离段数 {len(turns)} | 合并轮次 {n_turns}", flush=True)
    print(f"[meta] 输出目录: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
