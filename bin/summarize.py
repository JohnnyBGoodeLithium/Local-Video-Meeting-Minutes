#!/usr/bin/env python3
"""逐字稿 → 结构化会议纪要(走本机 llama.cpp 路由上的 Qwen3.6，不出本机)。

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
import time
import urllib.request
from pathlib import Path

from meeting_artifact import (
    CONCLUSION_POLICY,
    build_prompt_context,
    load_speaker_profiles,
    normalize_minutes_markdown,
    write_evidence_document,
)
import meeting_topic_map

ROUTER = "http://127.0.0.1:11435/v1/chat/completions"
MODEL = "qwen3.6-35b-a3b-operator"

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

STRUCTURED_PROMPT = """你是一名严谨的会议纪要编辑。输入是 `meeting-minutes-prompt/v1` JSON，
逐字稿可能有少量转写或说话人归属错误。请输出 Markdown：

# 会议纪要
## 总体摘要
- 主旨
- 关键结论（区分 已确认 / 方向共识 / 提议 / 未决）
## 待办事项
使用 Markdown 表格，列固定为“事项 / 负责人 / 期限 / 状态”；标题与表格之间保留空行。
每个事项独占一行并附 evidence marker；负责人或期限未明确时写“待确认”。
## 风险/待确认
## 议题详情

规则：
- turns 是决定、共识、行动和风险的唯一主证据。
- 岗位/职级只提供决策权限语境，不能把建议或单人观点自动升级为结论。
- 已确认结论需要明确决定/批准措辞，并由议题责任人作出，或得到多人明确确认且无未解决反对。
- 行动项按动作、接受责任、负责人和期限判断，不按职级判断。
- 每个事实性条目末尾附机器标记：
  `<!-- mm:evidence kind=decision status=confirmed confidence=high turns=T000001,T000003 -->`
  turns 只能写输入中存在的 T 编号；kind 可用 purpose/decision/alignment/action/risk/open_question/discussion。

结论策略：
{policy}

输入 JSON：
```json
{context}
```"""


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
    ap = argparse.ArgumentParser(description="本地生成会议纪要(Qwen3.6 @ llama-router)")
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

    if args.spk:
        if not args.spk.is_file():
            print(f"找不到说话人轮次文件: {args.spk}", file=sys.stderr)
            return 1
        turns = json.loads(args.spk.read_text(encoding="utf-8"))
        bank_dir = Path(os.environ.get("MEETING_WEB_BANK", args.spk.parent.parent.parent / "speaker_bank"))
        profiles = load_speaker_profiles(turns, bank_dir)
        context = build_prompt_context(turns, [], {}, profiles)
        text = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        prompt = STRUCTURED_PROMPT.format(
            policy=json.dumps(CONCLUSION_POLICY, ensure_ascii=False, indent=2), context=text)
    else:
        if not args.transcript.is_file():
            print(f"找不到输入文件: {args.transcript}", file=sys.stderr)
            return 1
        text = args.transcript.read_text(encoding="utf-8").strip()
        if not text:
            print("逐字稿为空", file=sys.stderr)
            return 1
        prompt = PROMPT.format(transcript=text)

    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": args.max_tokens,
        "temperature": 0.2,
        # 语音草稿需要尽快给用户可读正文。Qwen thinking 打开时可能把整个
        # completion budget 用在 reasoning_content，最终 content 为空。
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode("utf-8")

    t0 = time.time()
    req = urllib.request.Request(ROUTER, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[error] 请求本地路由失败({ROUTER}): {e}", file=sys.stderr)
        return 2
    elapsed = time.time() - t0

    msg = data["choices"][0]["message"]
    minutes = normalize_minutes_markdown((msg.get("content") or "").strip())
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
                        "text_model": MODEL, "vl_enabled": False,
                        "generation_stage": args.generation_stage})
        if not args.skip_topic_map:
            meeting_topic_map.generate_for_pipeline(args.spk.parent)

    usage = data.get("usage", {})
    print(f"[meta] 纪要生成 {elapsed:.1f}s | 输入 {usage.get('prompt_tokens','?')} tok"
          f" | 输出 {usage.get('completion_tokens','?')} tok | 纪要字符数={len(minutes)}")
    print(f"[meta] 输出: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
