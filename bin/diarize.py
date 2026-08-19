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
from bisect import bisect_right
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


def _lexical_support(chars, start: float, end: float, *, starts=None, ends=None) -> int:
    """统计分离段内被 ASR 实际识别出的字母/数字/CJK 字符数。"""
    if not chars:
        return 0
    starts = starts if starts is not None else [float(ch["start_time"]) for ch in chars]
    ends = ends if ends is not None else [float(ch["end_time"]) for ch in chars]
    count = 0
    index = bisect_right(ends, start)
    for ch in chars[index:]:
        cs, ce = float(ch["start_time"]), float(ch["end_time"])
        if cs >= end:
            break
        if min(end, ce) <= max(start, cs):
            continue
        count += sum(c.isalnum() or "\u4e00" <= c <= "\u9fff"
                     for c in str(ch.get("text") or ""))
    return count


def smooth_dia(turns, min_dur: float = 1.0, chars=None):
    """去掉孤立标签抖动，同时保留有文字依据的真实短插话。

    旧策略无条件把所有亚秒段并给前一人，会抹掉真实插话。现在只有缺少文字依据的
    短段，或夹在同一说话人中间且只含一个字符的孤立新标签，才按抖动处理；会议中
    其他位置已有稳定发言的说话人，即使只说一个短词也保留。
    """
    turns = sorted((float(s), float(e), str(spk)) for s, e, spk in turns if e > s)
    total = {}
    stable = set()
    for s, e, spk in turns:
        total[spk] = total.get(spk, 0.0) + e - s
        if e - s >= min_dur:
            stable.add(spk)
    stable.update(spk for spk, duration in total.items() if duration >= 2 * min_dur)
    char_starts = [float(ch["start_time"]) for ch in chars] if chars else []
    char_ends = [float(ch["end_time"]) for ch in chars] if chars else []

    out = []
    for index, (s, e, spk) in enumerate(turns):
        if out and out[-1][2] == spk:
            out[-1] = (out[-1][0], max(out[-1][1], e), spk)
            continue

        duration = e - s
        if duration >= min_dur or not out:
            out.append((s, e, spk))
            continue

        next_spk = turns[index + 1][2] if index + 1 < len(turns) else None
        bridge_flicker = next_spk == out[-1][2] and spk != next_spk
        lexical = _lexical_support(
            chars, s, e, starts=char_starts, ends=char_ends)
        # 已在别处形成稳定声音簇：一个短词也足以保留；只出现一次的新标签在 ABA
        # 桥接位置至少需要两个可读字符，避免把单字时间戳噪声恢复成大量碎轮次。
        preserve = lexical > 0 and (spk in stable or lexical >= 2 or not bridge_flicker)
        if preserve:
            out.append((s, e, spk))
        else:
            ps, pe, pspk = out[-1]
            out[-1] = (ps, max(pe, e), pspk)
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

    chars = None
    if stamps_path.is_file():
        chars = json.loads(stamps_path.read_text(encoding="utf-8"))["time_stamps"]
    turns = smooth_dia(turns, chars=chars)

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
