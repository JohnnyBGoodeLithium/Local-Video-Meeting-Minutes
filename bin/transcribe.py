#!/usr/bin/env python3
"""可配置 ASR：WAV → 原语言逐字稿、时间戳与音频复核记录。

用法：
    bin/transcribe.py recordings/20260806171137.WAV
    bin/transcribe.py recordings/20260806171137.WAV --title 周会 --no-timestamps

输出目录：默认 meetings/<日期>_<录音时间或标题>/(每场会议自包含)。

说明：
    - 默认使用本机 Qwen3-ASR；也可显式配置 OpenAI-compatible 音频端点。
    - 不会静默把音频回退到云端。stdout 只打印元数据，不打印逐字稿正文。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from meeting_dir import for_recording
from meeting_core.asr import create_provider
from meeting_core.terminology import configured_bank_dir, write_context_pack
from meeting_core.transcript_review import safe_review_term_confusions, write_review

ROOT = Path(__file__).resolve().parent.parent

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


def write_transcript_outputs(out: Path, wav_stem: str, language: str,
                             text: str, stamps: list[dict]) -> tuple[int, tuple[float, float] | None]:
    """ASR 完成后的确定性落盘，可从已保存 stamps 恢复而不重跑模型。"""
    out.mkdir(parents=True, exist_ok=True)
    span = None
    if stamps:
        span = (float(stamps[0]["start_time"]), float(stamps[-1]["end_time"]))
        (out / "stamps.json").write_text(json.dumps({
            "language": language, "text": text, "time_stamps": stamps,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        paras = stamps_to_paragraphs(stamps)
        md = [f"# {wav_stem} 逐字稿\n",
              f"> 语言: {language} | 模型: Qwen3-ASR-1.7B + ForcedAligner-0.6B\n"]
        md += [f"[{_fmt_hms(st)}] {tx}\n" for st, tx in paras]
        (out / "transcript.ts.md").write_text("\n".join(md), encoding="utf-8")
    else:
        paras = []
    (out / "transcript.txt").write_text(text + "\n", encoding="utf-8")
    return len(paras), span


def main() -> int:
    ap = argparse.ArgumentParser(description="WAV 转写（本地原生或显式配置的兼容端点）")
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
    ap.add_argument("--reuse-stamps", action="store_true",
                    help="故障恢复：从当前输出目录的完整 stamps.json 继续，不加载 ASR")
    args = ap.parse_args()

    if not args.wav.is_file():
        print(f"找不到输入文件: {args.wav}", file=sys.stderr)
        return 1
    out = args.out or for_recording(ROOT, args.wav.stem, args.title)

    if args.reuse_stamps:
        try:
            cached = json.loads((out / "stamps.json").read_text(encoding="utf-8"))
            language = str(cached["language"])
            corrected_text = str(cached["text"])
            stamps = cached["time_stamps"]
            if not isinstance(stamps, list) or not stamps:
                raise ValueError("empty_stamps")
            n_paras, span = write_transcript_outputs(
                out, args.wav.stem, language, corrected_text, stamps)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"已保存时间戳不可恢复: {type(exc).__name__}", file=sys.stderr)
            return 2
        print(f"[meta] 复用已完成 ASR | 语言={language} | 字符数={len(corrected_text)}"
              f" | 时间戳 {len(stamps)} 条 覆盖 {span[0]:.1f}s–{span[1]:.1f}s"
              f" | 段落 {n_paras}", flush=True)
        return 0

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

    t0 = time.time()
    provider = create_provider(batch_size=args.batch_size, max_new_tokens=args.max_new_tokens,
                               with_aligner=not args.no_timestamps)
    device_note = (f" device={provider.device} dtype={provider.dtype}"
                   if hasattr(provider, "device") else " adapter=portable")
    print(f"[meta] ASR provider={provider.name} 加载 {time.time()-t0:.1f}s{device_note}", flush=True)

    t0 = time.time()
    results = provider.transcribe(
        audio=str(args.wav),
        context=asr_context,
        language=args.language,
        return_time_stamps=not args.no_timestamps,
    )
    elapsed = time.time() - t0
    result = results[0]

    out.mkdir(parents=True, exist_ok=True)
    n_stamps, span, n_paras = 0, None, 0
    corrected_text = result.text
    stamps = result.time_stamps
    if stamps:
        # aligner 单元不含空格 → 回填(对齐失败则保持原样)
        fixed_texts = reinsert_spaces(result.text, [_field(s, "text") for s in stamps])
        stamps = [{"text": t, "start_time": float(_field(s, "start_time")),
                   "end_time": float(_field(s, "end_time"))}
                  for t, s in zip(fixed_texts, stamps)]
        if os.environ.get("MEETING_ASR_REVIEW", "1") != "0":
            corrected_text, stamps, review = safe_review_term_confusions(
                provider, args.wav, corrected_text, stamps, asr_context,
                configured_bank_dir(ROOT), language=args.language or result.language,
                template_path=ROOT / "speaker_bank" / "terminology.template.json")
            write_review(out / "transcript.review.json", review)
        n_stamps = len(stamps)
        span = (stamps[0]["start_time"], stamps[-1]["end_time"])

    n_paras, written_span = write_transcript_outputs(
        out, args.wav.stem, result.language, corrected_text, stamps or [])
    span = written_span or span

    context_path = out / "asr.context.json"
    if context_path.is_file():
        try:
            audit = json.loads(context_path.read_text(encoding="utf-8"))
            audit["provider"] = provider.name
            audit["context_applied"] = bool(result.context_applied)
            temp = context_path.with_name(f".{context_path.name}.tmp-{os.getpid()}")
            temp.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, context_path)
        except Exception:
            pass

    print(f"[meta] 转写耗时 {elapsed:.1f}s | 语言={result.language} | 字符数={len(corrected_text)}"
          f" | context术语={context_terms} | context应用={'是' if result.context_applied else '否'}"
          + (f" | 时间戳 {n_stamps} 条 覆盖 {span[0]:.1f}s–{span[1]:.1f}s | 段落 {n_paras}" if span else ""),
          flush=True)
    print(f"[meta] 输出目录: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
