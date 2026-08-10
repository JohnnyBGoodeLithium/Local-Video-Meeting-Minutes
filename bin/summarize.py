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
import sys
import time
import urllib.request
from pathlib import Path

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
    args = ap.parse_args()

    if args.spk:
        if not args.spk.is_file():
            print(f"找不到说话人轮次文件: {args.spk}", file=sys.stderr)
            return 1
        turns = json.loads(args.spk.read_text(encoding="utf-8"))
        text = "\n".join(f"[{_fmt_mmss(t['start'])} {t['speaker']}] {t['text']}" for t in turns)
        prompt = SPK_PROMPT.format(transcript=text)
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
    }).encode("utf-8")

    t0 = time.time()
    req = urllib.request.Request(ROUTER, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"请求本地路由失败({ROUTER}): {e}", file=sys.stderr)
        return 2
    elapsed = time.time() - t0

    msg = data["choices"][0]["message"]
    minutes = (msg.get("content") or "").strip()
    if not minutes:
        print("模型返回为空(可能 token 全耗在推理上)", file=sys.stderr)
        return 3

    out_dir = args.out or args.transcript.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("minutes.spk.md" if args.spk else "minutes.md")
    out_path.write_text(minutes + "\n", encoding="utf-8")

    usage = data.get("usage", {})
    print(f"[meta] 纪要生成 {elapsed:.1f}s | 输入 {usage.get('prompt_tokens','?')} tok"
          f" | 输出 {usage.get('completion_tokens','?')} tok | 纪要字符数={len(minutes)}")
    print(f"[meta] 输出: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
