#!/usr/bin/env python3
"""本地转写：WAV → 逐字稿(纯文本 transcript.txt + 带时间戳段落 transcript.ts.md + 字级 stamps.json)。

用法：
    bin/transcribe.py recordings/20260806171137.WAV
    bin/transcribe.py recordings/20260806171137.WAV --title 周会 --no-timestamps

输出目录：默认 meetings/<日期>_<录音时间或标题>/(每场会议自包含)。

说明：
    - qwen-asr 内部会把长音频按低能量边界切成 ≤180s 的段再逐段转写+对齐，
      本脚本直接整文件传入即可。
    - 隐私红线：全程本地推理；stdout 只打印元数据(语言/时长/段数/字符数)，
      不打印任何转写内容，避免内容进入云端 agent 上下文。
"""

import argparse
import json
import sys
import time
from pathlib import Path

from meeting_dir import for_recording
from meeting_core.hardware import configured_path, inference_device, inference_dtype
from meeting_core.terminology import configured_bank_dir, write_context_pack

HOME = Path.home()
ROOT = Path(__file__).resolve().parent.parent
ASR_PATH = configured_path(
    "MEETING_ASR_MODEL", HOME / ".local/share/models/hf/Qwen/Qwen3-ASR-1.7B")
ALIGNER_PATH = configured_path(
    "MEETING_ALIGNER_MODEL", HOME / ".local/share/models/hf/Qwen/Qwen3-ForcedAligner-0.6B")

SENT_END = tuple("。！？!?；;\n")


def _field(item, name):
    if isinstance(item, dict):
        return item[name]
    return getattr(item, name)


def _fmt_hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def reinsert_spaces(raw_text: str, stamp_texts: list) -> list:
    """ForcedAligner 的时间戳单元不含空格和标点 → 逐字拼接后英文粘连、标点丢失。
    用原始文本(含空格标点)做容错对齐: 匹配的字符推进 stamps 流;
    stamps 里不存在的字符(空格/标点)挂到当前单元尾部。
    连续 >12 个字符对不上或总匹配率 <90% 则放弃(原样返回)，宁缺毋错。"""
    if not raw_text or not stamp_texts:
        return stamp_texts
    out = list(stamp_texts)
    lens = [len(t) for t in stamp_texts]
    B = "".join(stamp_texts)
    cum = [0]
    for L in lens:
        cum.append(cum[-1] + L)
    g = 0               # stamps 流全局位置
    unit = -1           # 当前单元下标
    matched = misses = 0
    for ch in raw_text:
        if ch.isspace():
            if unit >= 0:
                out[unit] += " "
            continue
        if g < len(B) and ch == B[g]:
            g += 1
            matched += 1
            misses = 0
            while unit + 1 < len(out) and g - 1 >= cum[unit + 1]:
                unit += 1
            continue
        if unit >= 0:   # stamps 缺失的字符(标点等) → 挂当前单元
            out[unit] += ch
        misses += 1
        if misses > 12:
            return stamp_texts
    if matched < 0.9 * len(B):
        return stamp_texts
    return out


def stamps_to_paragraphs(stamps, max_chars: int = 80):
    """把字/词级时间戳聚合成带起始时间的段落。按句末标点或超长切分。"""
    paras, buf, start = [], [], None
    for it in stamps:
        t = _field(it, "text")
        st = float(_field(it, "start_time"))
        if start is None:
            start = st
        buf.append(t)
        if t.endswith(SENT_END) or len("".join(buf)) >= max_chars:
            paras.append((start, "".join(buf).strip()))
            buf, start = [], None
    if buf:
        paras.append((start if start is not None else 0.0, "".join(buf).strip()))
    return [(st, tx) for st, tx in paras if tx]


def main() -> int:
    ap = argparse.ArgumentParser(description="本地 WAV 转写(Qwen3-ASR + ForcedAligner)")
    ap.add_argument("wav", type=Path, help="输入 WAV 文件(16kHz 单声道)")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出目录(默认 meetings/<日期>_<时间>，可用 --title 起名)")
    ap.add_argument("--title", default=None, help="会议标题(用于目录名)")
    ap.add_argument("--language", default=None, help="强制语言(如 Chinese)；默认自动检测")
    ap.add_argument("--no-timestamps", action="store_true", help="跳过 ForcedAligner，只出纯文本")
    ap.add_argument("--max-new-tokens", type=int, default=1024, help="每段最大生成 token 数")
    ap.add_argument("--batch-size", type=int, default=8, help="推理批大小")
    ap.add_argument("--context-title", default=None,
                    help="ASR context 使用的会议标题（默认取 --title 或输出目录名）")
    ap.add_argument("--no-context", action="store_true",
                    help="A/B 测试用：禁用会议标题与术语 context")
    args = ap.parse_args()

    if not args.wav.is_file():
        print(f"找不到输入文件: {args.wav}", file=sys.stderr)
        return 1
    out = args.out or for_recording(ROOT, args.wav.stem, args.title)

    asr_context = ""
    context_terms = 0
    if not args.no_context:
        bank_dir = configured_bank_dir(ROOT)
        try:
            asr_context, context_meta = write_context_pack(
                out, args.context_title or args.title or out.name, bank_dir,
                template_path=ROOT / "speaker_bank" / "terminology.template.json")
            context_terms = int(context_meta.get("term_count", 0))
        except Exception as exc:
            # Context 是增强层；失败不得阻断原有 ASR，也不能把正文/路径写入日志。
            print(f"[meta] ASR context 跳过 | {type(exc).__name__}", flush=True)

    import torch
    from qwen_asr import Qwen3ASRModel

    device = inference_device(torch, indexed=True)
    dtype = inference_dtype(torch, device)
    load_kwargs = dict(
        dtype=dtype,
        device_map=device,
        max_inference_batch_size=args.batch_size,
        max_new_tokens=args.max_new_tokens,
    )
    if not args.no_timestamps:
        load_kwargs["forced_aligner"] = str(ALIGNER_PATH)
        load_kwargs["forced_aligner_kwargs"] = dict(dtype=dtype, device_map=device)

    t0 = time.time()
    model = Qwen3ASRModel.from_pretrained(str(ASR_PATH), **load_kwargs)
    print(f"[meta] 模型加载 {time.time()-t0:.1f}s device={device} dtype={dtype}", flush=True)

    t0 = time.time()
    results = model.transcribe(
        audio=str(args.wav),
        context=asr_context,
        language=args.language,
        return_time_stamps=not args.no_timestamps,
    )
    elapsed = time.time() - t0
    r = results[0]

    out.mkdir(parents=True, exist_ok=True)
    txt_path = out / "transcript.txt"
    txt_path.write_text(r.text + "\n", encoding="utf-8")

    n_stamps, span, n_paras = 0, None, 0
    stamps = getattr(r, "time_stamps", None)
    if stamps:
        # aligner 单元不含空格 → 回填(对齐失败则保持原样)
        fixed_texts = reinsert_spaces(r.text, [_field(s, "text") for s in stamps])
        stamps = [{"text": t, "start_time": float(_field(s, "start_time")),
                   "end_time": float(_field(s, "end_time"))}
                  for t, s in zip(fixed_texts, stamps)]
        n_stamps = len(stamps)
        span = (stamps[0]["start_time"], stamps[-1]["end_time"])

        (out / "stamps.json").write_text(json.dumps({
            "language": r.language,
            "text": r.text,
            "time_stamps": stamps,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        paras = stamps_to_paragraphs(stamps)
        n_paras = len(paras)
        md = [f"# {args.wav.stem} 逐字稿\n", f"> 语言: {r.language} | 模型: Qwen3-ASR-1.7B + ForcedAligner-0.6B\n"]
        md += [f"[{_fmt_hms(st)}] {tx}\n" for st, tx in paras]
        (out / "transcript.ts.md").write_text("\n".join(md), encoding="utf-8")

    print(f"[meta] 转写耗时 {elapsed:.1f}s | 语言={r.language} | 字符数={len(r.text)}"
          f" | context术语={context_terms}"
          + (f" | 时间戳 {n_stamps} 条 覆盖 {span[0]:.1f}s–{span[1]:.1f}s | 段落 {n_paras}" if span else ""),
          flush=True)
    print(f"[meta] 输出目录: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
