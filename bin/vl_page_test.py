#!/usr/bin/env python3
"""VL 模型读页测试：让视觉模型逐页描述幻灯片截图(全本地)。

对会议目录 slides.json 里每个 kind==slide 的页，把截图发给本地 llama-server
(OpenAI 兼容, 需带 mmproj 起服务)，让它输出 页面类型/标题/一句话摘要 的 JSON。

产出: <mdir>/vl_test_<tag>.json (含每页原始回答, 属会议内容, 云端不读)
stdout 只打印元数据(页数/耗时/tokens/解析成功率/重复率)，不打印描述内容。

用法:
    # 先起服务: llama-server --model X.gguf --mmproj Y.gguf --port 11436 --gpu-layers 999
    bin/vl_page_test.py meetings/<会议目录> --tag qwen3vl8b --port 11436
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROMPT = (
    "这是会议中共享屏幕的一张截图。请输出 JSON："
    "{\"type\":\"页面类型(标题页/目录页/图表页/表格页/文字页/混合/其他)\","
    "\"title\":\"页面标题或主题(照抄原文,没有就写空字符串)\","
    "\"summary\":\"一句话说明这页在讲什么(不超过50字)\"}。"
    "只输出 JSON，不要输出其它内容。"
)

DETAIL_PROMPT = (
    "这是会议中共享屏幕的一张截图。请详细解读这一页，用 Markdown 输出：\n"
    "## 标题\n这页的标题或主题(照抄原文)\n"
    "## 页面角色\n只写以下一个值：content / agenda / cover / section / transition / blank / meeting_ui / demo\n"
    "## 信息价值\n只写 high / medium / low，再用一句话解释。high 表示包含可复用的数据、结构、方案或结论；"
    "medium 表示标题、议程或辅助背景；low 表示空白、过渡、装饰、会议界面或没有实质业务信息\n"
    "## 页面内容\n逐条列出页面上的要点、数据、结论句，图表说明它展示了什么(坐标轴/趋势/对比)，"
    "表格列出关键的行和列——关键文字和数字尽量照抄，不要漏小字\n"
    "## 这页想说明什么\n一两句话总结这页的论点\n"
    "只根据画面里真实存在的内容写，看不清的就说看不清，不要编。"
    "不要输出思考过程，不要输出 <think>、<analysis> 或前后解释。"
)


def grab_fullres(video: Path, t: float, out: Path):
    """按 captured 时间戳从原视频抓原生分辨率帧。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                    "-frames:v", "1", "-q:v", "2", str(out)], check=True)


def chat_with_image(api: str, model: str, img: Path, max_tokens: int, prompt: str = PROMPT):
    b64 = base64.b64encode(img.read_bytes()).decode()
    body = json.dumps({
        "model": model, "temperature": 0.1, "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}],
    }).encode()
    req = urllib.request.Request(f"{api}/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    msg = data["choices"][0]["message"].get("content", "").strip()
    return msg, data.get("usage", {})


def parse_json_loose(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="VL 模型逐页读图测试(全本地)")
    ap.add_argument("mdir", type=Path)
    ap.add_argument("--tag", required=True, help="输出文件 vl_test_<tag>.json")
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--model", default=None, help="API 模型名(默认取服务器第一个)")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--max-pages", type=int, default=0, help="只测前 N 页(0=全部)")
    ap.add_argument("--pages", default=None, help="只测指定页码, 逗号分隔(如 2,9,11)")
    ap.add_argument("--detail", action="store_true",
                    help="详细解读模式: 详细 prompt + 原生分辨率重抓(需 --video)")
    ap.add_argument("--video", type=Path, default=None, help="原视频(detail 模式重抓全尺寸帧用)")
    args = ap.parse_args()
    mdir = args.mdir
    api = f"http://127.0.0.1:{args.port}/v1"
    if args.detail and not args.video:
        print("--detail 需要 --video", file=sys.stderr)
        return 1
    max_tokens = 1024 if args.detail and args.max_tokens == 256 else args.max_tokens

    with urllib.request.urlopen(f"{api}/models", timeout=30) as resp:
        models = json.loads(resp.read())["data"]
    model = args.model or models[0]["id"]

    tl = json.loads((mdir / "slides.json").read_text(encoding="utf-8"))
    pages = [x for x in tl if x.get("kind") == "slide"]
    if args.pages:
        want = {int(x) for x in args.pages.split(",")}
        pages = [p for p in pages if p["page"] in want]
    if args.max_pages:
        pages = pages[: args.max_pages]
    out_path = mdir / f"vl_test_{args.tag}.json"

    results, fails, t_all = [], 0, time.time()
    for p in pages:
        img = mdir / "slides" / p["image"]
        if args.detail:
            img = mdir / "slides" / f"full_{p['page']:02d}.jpg"
            grab_fullres(args.video, p.get("captured", p["first"]), img)
        t0 = time.time()
        try:
            raw, usage = chat_with_image(api, model, img, max_tokens,
                                         DETAIL_PROMPT if args.detail else PROMPT)
        except Exception as e:  # 单页失败不终止, 记录后继续
            fails += 1
            results.append({"page": p["page"], "image": p["image"], "error": type(e).__name__})
            print(f"[meta] 第{p['page']}页 失败: {type(e).__name__}", flush=True)
            continue
        results.append({"page": p["page"], "image": img.name,
                        "latency": round(time.time() - t0, 2),
                        "tokens": usage.get("completion_tokens"),
                        "parsed": None if args.detail else parse_json_loose(raw), "raw": raw})
        print(f"[meta] 第{p['page']}页 {time.time()-t0:.1f}s"
              f" tokens={usage.get('completion_tokens','?')}", flush=True)

    out_path.write_text(json.dumps({"model": model, "mode": "detail" if args.detail else "json",
                                    "results": results}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    ok = [r for r in results if "raw" in r]
    parsed = sum(1 for r in ok if r.get("parsed"))
    raws = [r["raw"] for r in ok]
    dup = len(raws) - len(set(raws))
    lat = [r["latency"] for r in ok]
    print(f"[meta] 完成 {len(ok)}/{len(pages)} 页(失败 {fails}) | JSON解析成功 {parsed}"
          f" | 完全重复输出 {dup} | 平均 {sum(lat)/max(1,len(lat)):.1f}s/页"
          f" | 总耗时 {time.time()-t_all:.0f}s | 输出: {out_path}", flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
