#!/usr/bin/env python3
"""逐字稿 → 结构化会议纪要(走本机 llama.cpp 路由的纪要专用模型，不出本机)。

用法：
    bin/summarize.py meetings/2026-08-06_171137/transcript.txt
    bin/summarize.py meetings/2026-08-06_171137/transcript.txt --spk meetings/2026-08-06_171137/transcript.spk.json

输出：默认与逐字稿同目录的 minutes.md(或 --spk 时的 minutes.spk.md)。

隐私红线：请求只发 127.0.0.1:11435(llama-router.service)；stdout 只打印元数据。
"""

import argparse
import json
import os
import sys
from pathlib import Path

from meeting_artifact import (
    CONCLUSION_POLICY,
    append_materials_section,
    build_prompt_context,
    load_speaker_profiles,
    normalize_minutes_markdown,
    write_evidence_document,
)
from meeting_core.llm import (DEFAULT_MINUTES_MODEL, LLMError, LocalLLMClient,
                              minutes_model_for_stage)
from meeting_core import photos as meeting_photos
from meeting_core import voice_draft
import meeting_topic_map

MODEL = DEFAULT_MINUTES_MODEL

PROMPT = """你是一名会议纪要助手。下面是会议录音的逐字稿(自动转写，可能有个别错字)。
请输出 Markdown 格式的结构化会议纪要，包含：

# 会议纪要
- **议题列表**：讨论过的主题，按出现顺序
- **每个议题的结论/共识**（没有结论就写"未形成结论"）
- **待办事项**：动作 + 负责人(如提到) + 期限(如提到)
- **风险/待确认**：悬而未决或需要再确认的点

只根据逐字稿内容总结，不要编造。逐字稿如下：

---
{transcript}
---"""

def _fmt_mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s//60:02d}:{s%60:02d}"


# 分说话人版本：说明输入格式，并要求待办/观点尽量归属到说话人
SPK_PROMPT = (PROMPT
              .replace("下面是会议录音的逐字稿(自动转写，可能有个别错字)。",
                       "下面是会议录音的分说话人逐字稿(自动转写 + 机器说话人分离，可能有个别错字和"
                       "归属错误)，格式为 `[mm:ss 说话人N] 文本`。")
              .replace("只根据逐字稿内容总结，不要编造。",
                       "只根据逐字稿内容总结，不要编造。待办和关键观点尽量归属到说话人(说话人N)；"
                       "归属不确定的写\"不明\"。"))


def main() -> int:
    ap = argparse.ArgumentParser(description="本地生成会议纪要(纪要专用模型 @ llama-router)")
    ap.add_argument("transcript", type=Path, help="逐字稿 .txt 文件")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出目录(默认与逐字稿同目录)")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--spk", type=Path, default=None,
                    help="分说话人轮次 transcript.spk.json；提供则按说话人归属生成纪要")
    ap.add_argument("--output-name", default=None,
                    help="输出文件名；渐进视频管线使用 minutes.md 发布语音草稿")
    ap.add_argument("--generation-stage", default="final",
                    choices=("voice_draft", "final"), help="写入 evidence generation 元数据")
    ap.add_argument("--skip-topic-map", action="store_true",
                    help="语音草稿阶段不提前生成 Topic Map")
    args = ap.parse_args()
    model = minutes_model_for_stage(args.generation_stage)

    if args.spk:
        if not args.spk.is_file():
            print(f"找不到说话人轮次文件: {args.spk}", file=sys.stderr)
            return 1
        turns = json.loads(args.spk.read_text(encoding="utf-8"))
        bank_dir = Path(os.environ.get("MEETING_WEB_BANK", args.spk.parent.parent.parent / "speaker_bank"))
        profiles = load_speaker_profiles(turns, bank_dir)
        materials = meeting_photos.prompt_materials(args.spk.parent, turns)
        context = build_prompt_context(turns, [], {}, profiles, materials=materials)
    else:
        if not args.transcript.is_file():
            print(f"找不到输入文件: {args.transcript}", file=sys.stderr)
            return 1
        text = args.transcript.read_text(encoding="utf-8").strip()
        if not text:
            print("逐字稿为空", file=sys.stderr)
            return 1
        prompt = PROMPT.format(transcript=text)

    client = LocalLLMClient(model=model)
    try:
        if args.spk:
            result = voice_draft.generate(
                context, CONCLUSION_POLICY, client=client, max_tokens=args.max_tokens,
                progress=lambda current, total: print(
                    f"[meta] 长会议草稿分段 {current}/{total}", flush=True),
            )
            raw_minutes = result.content
            elapsed = result.elapsed
            prompt_tokens = result.prompt_tokens
            completion_tokens = result.completion_tokens
            generation_mode = result.mode
            generation_chunks = result.chunks
        else:
            completion = client.complete(prompt, max_tokens=args.max_tokens, temperature=0.2)
            raw_minutes = completion.content
            elapsed = completion.elapsed
            prompt_tokens = int(completion.usage.get("prompt_tokens") or 0)
            completion_tokens = int(completion.usage.get("completion_tokens") or 0)
            generation_mode = "direct"
            generation_chunks = 1
    except LLMError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    minutes = normalize_minutes_markdown(raw_minutes.strip())
    if args.spk:
        minutes = append_materials_section(minutes, materials)
    if not minutes:
        print("[error] 模型返回为空（正文输出预算耗尽）", file=sys.stderr)
        return 3

    out_dir = args.out or args.transcript.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    output_name = args.output_name or ("minutes.spk.md" if args.spk else "minutes.md")
    if Path(output_name).name != output_name or not output_name.endswith(".md"):
        print("output-name 必须是当前目录内的 .md 文件名", file=sys.stderr)
        return 4
    out_path = out_dir / output_name
    out_path.write_text(minutes + "\n", encoding="utf-8")
    if args.spk:
        write_evidence_document(
            args.spk.parent, minutes + "\n", turns, [], {}, profiles,
            generation={"prompt_schema": "meeting-minutes-prompt/v1",
                        "conclusion_policy": CONCLUSION_POLICY["version"],
                        "text_model": model, "vl_enabled": bool(materials),
                        "photo_materials": len(materials),
                        "generation_stage": args.generation_stage,
                        "generation_mode": generation_mode,
                        "generation_chunks": generation_chunks})
        if not args.skip_topic_map:
            meeting_topic_map.generate_for_pipeline(args.spk.parent)

    print(f"[meta] 纪要生成 {elapsed:.1f}s | 模式 {generation_mode}"
          f" ({generation_chunks} 段) | 输入 {prompt_tokens or '?'} tok"
          f" | 输出 {completion_tokens or '?'} tok | 纪要字符数={len(minutes)}")
    print(f"[meta] 输出: {out_path}")
    return 0


def safe_main() -> int:
    """把未预期异常压成可审计、无正文的错误类型，供作业日志保留。"""
    try:
        return main()
    except Exception as exc:
        print(f"[error] 纪要生成内部异常 ({type(exc).__name__})", file=sys.stderr, flush=True)
        return 5


if __name__ == "__main__":
    sys.exit(safe_main())
