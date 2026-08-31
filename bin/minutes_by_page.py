#!/usr/bin/env python3
"""按"幻灯片页"为单元的会议纪要(全本地)。

输入: 会议目录内的 transcript.spk.json + slides.json(bin/slide_pages.py 产出)。
流程:
    1. 逐字稿按"说话时正显示哪页"切片(开场未共享画面的部分单列一块)
    2. VL 层(可 --no-vl 关): 本地 Miloco-7B 视觉模型逐页详细解读(原生分辨率帧,
       缓存 page_desc.json), 既作为页面内容参考喂给文本模型锚定术语/板块,
       也作为"画面内容"层插进最终纪要
    3. 第一遍模型: 总体摘要(主旨/结论/待办/风险) + 议题板块(连续页归并,
       deck 自带 agenda/章节结构优先)
    4. 第二遍模型: 有讨论的页按 8 页一组分次出 讨论要点/结论
       (分组防单次输出截断; 全程关思考模式, 否则隐藏推理会吃掉输出预算);
       漏页补问一次, 仍缺及无讨论的页确定性补"快速带过"
    5. 每个"第N页"标题下确定性插入该页截图+画面内容 → minutes.md(旧的备份为 minutes.prev.md)

用法: bin/minutes_by_page.py meetings/<会议目录> [--out PATH]
stdout 只打印元数据(字数/页数/tokens/耗时)，不打印任何会议内容。

content_type=media（meta.json）的内容走 MinutesProfile["media"]：公开视频论证结构
(核心观点/规格与参数/论证脉络/质疑保留)，不生成待办；shot 镜头页用媒体向 VL prompt。
会议行为不变，选择逻辑集中在 minutes_profile()。
"""
import argparse
import atexit
import concurrent.futures
import json
import os
import re
import socket
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from slide_pages import page_at
from vl_page_test import (DETAIL_PROMPT, PROMPT as COMPACT_PAGE_PROMPT,
                          MEDIA_DETAIL_PROMPT,
                          MEDIA_PROMPT as MEDIA_COMPACT_PAGE_PROMPT,
                          grab_fullres, chat_with_image, parse_json_loose)
from meeting_artifact import (
    CONCLUSION_POLICY,
    MARKER_RE,
    build_prompt_context,
    file_revision,
    load_speaker_profiles,
    normalize_minutes_markdown,
    write_evidence_document,
)
from meeting_structure import clean_model_text
from meeting_core.context_budget import ContextBudget
from meeting_core.minutes_overview import MEDIA_REQUIRED as MEDIA_OVERVIEW_REQUIRED
from meeting_core.minutes_overview import generate as generate_overview
from meeting_core.minutes_overview import generate_direct as generate_direct_overview
from meeting_core.minutes_overview import normalize_action_marker_scope
import meeting_topic_map
import meeting_generation
from meeting_core.hardware import configured_path
from meeting_core.llm import DEFAULT_MINUTES_MODEL, LocalLLMClient, validated_api_base
from meeting_core.resource_policy import prepare_stage
from meeting_core.progress_events import (output_ready, phase_done,
                                          progress as progress_event)

ROUTER = validated_api_base(os.environ.get(
    "MEETING_LLM_API", "http://127.0.0.1:11435/v1")) + "/chat/completions"
MODEL = DEFAULT_MINUTES_MODEL
VL_PORT = int(os.environ.get("MEETING_VL_PORT", "11436"))
VL_MODEL = configured_path(
    "MEETING_VL_MODEL", Path.home() / "视频/joyai-test/models/MiMo-VL-Miloco-7B_Q4_0.gguf")
VL_MMPROJ = configured_path(
    "MEETING_VL_MMPROJ",
    Path.home() / "视频/joyai-test/models/mmproj-MiMo-VL-Miloco-7B_BF16.gguf")
VL_GPU_LAYERS = os.environ.get("MEETING_VL_GPU_LAYERS", "999")
VL_MAXTOK = 2048
VL_REVIEW_MODEL = (configured_path("MEETING_VL_REVIEW_MODEL", "")
                   if os.environ.get("MEETING_VL_REVIEW_MODEL", "").strip() else None)
VL_REVIEW_MMPROJ = (configured_path("MEETING_VL_REVIEW_MMPROJ", "")
                    if os.environ.get("MEETING_VL_REVIEW_MMPROJ", "").strip() else None)
VL_REVIEW_PORT = int(os.environ.get("MEETING_VL_REVIEW_PORT", "11437"))
VL_REVIEW_MAX_PAGES = max(0, int(os.environ.get("MEETING_VL_REVIEW_MAX_PAGES", "12")))

MEDIA_REVIEW_PROMPT = MEDIA_DETAIL_PROMPT + (
    "\n这是疑难证据帧的第二次复核。请优先核对密集表格、复杂图表、坐标轴、图例、单位、"
    "规格名和关键数字；区分画面明确可见、作者引用和无法辨认的内容。不要根据常识补全"
    "被遮挡或模糊的文字；不确定时明确写‘无法确认’，并保持既定 Markdown 协议。"
)

EVIDENCE_RULES = """
证据与结论规则（必须遵守）：
1. `turns` 是会议决定、共识、行动、风险的唯一主证据；每轮有稳定 T 编号。
2. `pages.visual_*` 来自 VL，只证明页面展示了什么。它可以核对术语、数字和议题结构，
   但不能单独证明“会上说过”或“会议决定了”。页面用 P 编号引用。
3. `speaker_profiles` 的岗位、团队和 org_depth 只提供决策权限语境，不能把建议自动升级成结论。
   职级最多在发言明确表示决定/批准时，帮助判断此人是否可能有确认权限。
4. 结论状态严格区分：confirmed=明确决定/批准且权限或多人确认成立；
   working_alignment=方向共识但仍需最终确认；proposal=建议/方案；open=未决；
   informational=汇报或页面展示，不是决定。
5. 行动项必须有明确动作；负责人/期限没说就写“待确认”，不能根据职级猜。
6. 每个事实性条目末尾必须原样附一个机器标记（Markdown 阅读时会隐藏）：
   `<!-- mm:evidence kind=decision status=confirmed confidence=high turns=T000001,T000003 pages=P0002 -->`
   turns/pages 只能写输入中真实存在的 ID；没有页面依据时省略 pages，没有逐字稿依据的页面事实只能用
   kind=slide_fact status=informational，绝不能标成 decision/action。
   T/P/C 编号只能存在于上述 HTML 注释标记中；可读正文不得再写 `(T000001, ...)` 一类机器尾注。
7. `kind=action` 只允许出现在整场 `### 待办事项` 表格。逐页详情中的设备调试、确认到会、
   等人加入、介绍议程、汇报数字和会议流程都不是会后待办；即使句子含“确认/安排”，也必须按
   discussion/informational/proposal 等真实语义标注，不能写成 action。
"""

MEDIA_EVIDENCE_RULES = """
证据与论证规则（必须遵守）：
1. `turns` 是公开视频的逐字稿，是视频作者观点与陈述的唯一主证据；每轮有稳定 T 编号。
2. 严格区分两类内容：
   - 作者观点/预测/评价：主观判断，只代表视频作者立场，标注时如实反映其确定性；
   - 客观规格事实：规格、跑分、价格等可核验数值，即使来自作者口述也按事实引用。
3. `pages.visual_*` 来自 VL，只证明画面展示了什么（规格表、对比图、跑分屏、真机演示）。
   画面用 P 编号引用，不能单独证明“作者说过”。
4. 这是公开视频分析，不是会议：绝不生成待办事项或行动项，绝不使用 kind=action；
   作者的购买建议、预测和评价按 discussion/informational 等真实语义标注。
5. 每个事实性条目末尾必须原样附一个机器标记（Markdown 阅读时会隐藏）：
   `<!-- mm:evidence kind=discussion status=informational confidence=high turns=T000001 -->`
   turns/pages 只能写输入中真实存在的 ID；没有逐字稿依据的画面事实只能用
   kind=slide_fact status=informational。
   T/P/C 编号只能存在于上述 HTML 注释标记中；可读正文不得再写 `(T000001, ...)` 一类机器尾注。
"""

SUM_PROMPT = """你是一名严谨的会议纪要编辑。你收到的是 `meeting-minutes-prompt/v1` JSON，
其中逐字稿可能有少量转写或说话人归属错误。请输出 Markdown，且只输出以下结构：

## 总体摘要
- **主旨**：一段话说明会议目的，并附证据标记
- **关键结论**：按重要性列出；若只有方向/提议要明确标注状态；没有就写“未形成已确认结论”
### 待办事项

必须使用下列 Markdown 表头：标题与表头之间保留空行，表头与分隔行必须紧邻；没有行动项时写“未形成明确待办”，不要输出空表：

| 事项 | 负责人 | 期限 | 状态 |
| --- | --- | --- | --- |

每个事项独占一行，并在“事项”单元格末尾附证据标记；负责人/期限未明确时写“待确认”

### 风险/待确认

分条列出

## 议题板块
把连续页面严格归并为 3–8 个整场主要议题；优先使用页面读出的 agenda/章节标题，但概括
必须有逐字稿依据。不要把每个页面或时间片直接当成一个议题。每块必须是独立列表项：
- 板块名（第X–Y页，mm:ss 起）：一句话概括，并附带含真实 turns 的证据标记。

输入中的 `voice_draft_checklist` 是在 VL 开始前从同一逐字稿提取的低信任覆盖清单，不是新证据，
也不能照抄。必须回到清单列出的原始 T 轮次重新核验：仍被逐字稿支持的决定、行动、风险和未决项
必须在终稿中保留或与同义事项合并；若画面资料或后文证明其错误、撤回或重复，可以纠正或省略，
但不得仅因为加入页面资料就静默丢失。所有保留内容仍须遵守下方证据规则。

{evidence_rules}

结论策略配置：
{policy}

输入 JSON：
```json
{context}
```"""

MEDIA_SUM_PROMPT = """你是一名严谨的视频内容分析编辑。你收到的是 `meeting-minutes-prompt/v1` JSON，
内容是一条公开视频（评测/发布会/上手）的逐字稿与画面资料，逐字稿可能有少量转写错误。
请输出 Markdown，且只输出以下结构：

## 总体摘要
- **主旨**：一段话说明视频主题与作者的总体结论倾向，并附证据标记
- **核心观点**：按重要性列出作者的观点、预测或评价；区分 明确主张 / 倾向判断 / 推测；
  没有就写“作者未给出明确观点”
## 规格与参数

分条列出视频中提到的规格、跑分、价格等带数值的事实；每条注明来源形态
（作者实测 / 引用官方或第三方 / 作者估计），并附证据标记；没有就写“未提及具体规格参数”

## 论证脉络
把连续镜头严格归并为 3–8 个论证环节（铺垫→论点→证据→结论）；优先使用画面读出的
章节/标题信息，但概括必须有逐字稿依据。不要把每个镜头或时间片直接当成一个环节。
每块必须是独立列表项：
- 环节名（第X–Y页，mm:ss 起）：一句话概括，并附带含真实 turns 的证据标记。

### 值得注意的质疑/保留意见

分条列出作者自己提出的不确定性、限制条件或保留意见；没有就写“作者未提出明显保留”

输入中的 `voice_draft_checklist` 是在 VL 开始前从同一逐字稿提取的低信任覆盖清单，不是新证据，
也不能照抄。必须回到清单列出的原始 T 轮次重新核验：仍被逐字稿支持的观点、事实和质疑
必须在终稿中保留或与同义内容合并；若画面资料或后文证明其错误、撤回或重复，可以纠正或省略，
但不得仅因为加入画面资料就静默丢失。所有保留内容仍须遵守下方证据规则。

{evidence_rules}

输入 JSON：
```json
{context}
```"""

GROUP_PROMPT = """你是一名严谨的会议纪要编辑。输入是 `meeting-minutes-prompt/v1` JSON，
只包含若干页面、这些页面显示时的逐字稿和说话人权限语境。

请为每页输出一个纪要块，严格按页码顺序：

### 第N页 [mm:ss] 一句话主题
- 讨论要点（2-4 条，每条一句话，带 [mm:ss] 和证据标记）
- **本页结论**：结论及其 confirmed/working alignment/proposal 状态，并附证据标记；
  没有就写“未形成结论”（这一句不需要伪造标记）

规则：只输出页块；每页不超过 6 行。VL 完整页面解释会由程序放进附录，正文只写会上实际讨论的内容。
页面数字若在发言中被明确引用，可同时标 turn 和 page；否则页面内容只能作 informational 页面事实。

{evidence_rules}

输入 JSON：
```json
{context}
```"""

MEDIA_GROUP_PROMPT = """你是一名严谨的视频内容分析编辑。输入是 `meeting-minutes-prompt/v1` JSON，
只包含若干镜头页面、这些镜头画面出现时的公开视频逐字稿和出镜人语境。

请为每页输出一个纪要块，严格按页码顺序：

### 第N页 [mm:ss] 一句话主题
- 内容要点（2-4 条，每条一句话：该镜头期间作者讲了什么、画面展示了什么，
  带 [mm:ss] 和证据标记）
- **论证角色**：该镜头在整条视频论证中的角色（铺垫/背景、提出论点、给出证据、演示、
  总结结论），一句话说明，并附证据标记；纯过渡镜头写“过渡/铺垫”（这一句不需要伪造标记）

规则：只输出页块；每页不超过 6 行。VL 完整画面解读会由程序放进附录，正文只写作者实际
讲述与画面直接展示的内容。画面数字若在讲述中被明确引用，可同时标 turn 和 page；否则画面
内容只能作 informational 画面事实。绝不生成待办事项，绝不使用 kind=action。

{evidence_rules}

输入 JSON：
```json
{context}
```"""


def mmss(sec: float) -> str:
    s = int(sec)
    return f"{s//60:02d}:{s%60:02d}"


def endpoint_has_model(model_id: str, model_path: Path) -> bool:
    """宽松匹配 llama.cpp 的模型 ID，但拒绝把别的模型端点当成目标服务。"""
    expected = Path(model_path).name.rsplit(".", 1)[0].lower()
    actual = str(model_id).rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    return bool(expected and actual and (expected in actual or actual in expected))


def ensure_vl_server(port: int = VL_PORT):
    """VL 服务可用则直接用，否则用本地 Miloco 模型拉起一个。返回 (api_base, proc|None)。"""
    api = f"http://127.0.0.1:{port}/v1"
    try:
        with urllib.request.urlopen(f"{api}/models", timeout=5) as resp:
            mid = json.loads(resp.read())["data"][0]["id"]
        print(f"[meta] VL 服务已在 :{port} ({mid})", flush=True)
        return api, None
    except Exception:
        pass
    if not VL_MODEL.is_file() or not VL_MMPROJ.is_file():
        print("[meta] 未找到 Miloco 模型文件, 跳过 VL 层", flush=True)
        return None, None
    print("[meta] 拉起 Miloco VL 服务 ...", flush=True)
    proc = subprocess.Popen(
        ["llama-server", "--model", str(VL_MODEL), "--mmproj", str(VL_MMPROJ),
         "--host", "127.0.0.1", "--port", str(port), "--gpu-layers", VL_GPU_LAYERS,
         "--ctx-size", "16384", "--parallel", "1", "--flash-attn", "auto",
         "--jinja", "--no-webui"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(proc.terminate)
    for _ in range(90):
        try:
            with urllib.request.urlopen(f"{api}/models", timeout=5) as resp:
                mid = json.loads(resp.read())["data"][0]["id"]
            print(f"[meta] VL 服务就绪 ({mid})", flush=True)
            return api, proc
        except Exception:
            time.sleep(2)
    proc.terminate()
    print("[meta] VL 服务启动超时, 跳过 VL 层", flush=True)
    return None, None


def ensure_vl_review_server(port: int = VL_REVIEW_PORT):
    """按需拉起疑难页视觉复核模型；未配置时明确跳过，不绑定具体供应商。"""
    if not VL_REVIEW_MODEL or not VL_REVIEW_MMPROJ:
        return None, None
    if not VL_REVIEW_MODEL.is_file() or not VL_REVIEW_MMPROJ.is_file():
        print("[meta] 疑难页视觉复核模型未就绪，保留主力 VL 结果", flush=True)
        return None, None
    requested_port = port
    api = f"http://127.0.0.1:{port}/v1"
    try:
        with urllib.request.urlopen(f"{api}/models", timeout=5) as resp:
            mid = json.loads(resp.read())["data"][0]["id"]
        if endpoint_has_model(mid, VL_REVIEW_MODEL):
            print(f"[meta] 疑难页视觉复核服务已在 :{port} ({mid})", flush=True)
            return api, None
        # 端口活着不代表目标模型就绪。embedding/reranker 等常驻端点不能被
        # 当成 VL 复核器，也不能由本任务停止；为本轮模型另选空闲端口。
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        api = f"http://127.0.0.1:{port}/v1"
        print(f"[meta] :{requested_port} 已由其他模型占用 ({mid})，"
              f"疑难页复核改用临时端口 :{port}", flush=True)
    except Exception:
        pass
    print("[meta] 拉起疑难页视觉复核模型 ...", flush=True)
    proc = subprocess.Popen(
        ["llama-server", "--model", str(VL_REVIEW_MODEL), "--mmproj", str(VL_REVIEW_MMPROJ),
         "--host", "127.0.0.1", "--port", str(port), "--gpu-layers", VL_GPU_LAYERS,
         "--ctx-size", "16384", "--parallel", "1", "--flash-attn", "auto",
         "--jinja", "--no-webui"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(proc.terminate)
    for _ in range(150):
        try:
            with urllib.request.urlopen(f"{api}/models", timeout=5) as resp:
                mid = json.loads(resp.read())["data"][0]["id"]
            print(f"[meta] 疑难页视觉复核服务就绪 ({mid})", flush=True)
            return api, proc
        except Exception:
            time.sleep(2)
    proc.terminate()
    print("[meta] 疑难页视觉复核启动超时，保留主力 VL 结果", flush=True)
    return None, None


def stop_local_model(proc):
    """只停止本函数启动的模型进程；外部常驻端点不受影响。"""
    if not proc or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


_MEDIA_COMPLEX_RE = re.compile(
    r"(?:表格|图表|柱状图|折线图|散点图|雷达图|坐标轴|图例|跑分|基准测试|规格|参数|"
    r"性能对比|价格|功耗|频率|带宽|table|chart|graph|plot|axis|legend|benchmark|"
    r"spec(?:ification)?|score|latency|throughput|power)", re.I)
_MEDIA_UNCERTAIN_RE = re.compile(
    r"(?:看不清|无法辨认|无法确认|文字模糊|数字模糊|分辨率不足|遮挡|"
    r"unreadable|illegible|cannot (?:read|confirm)|too (?:small|blurred))", re.I)


def media_review_candidates(pages: list[dict], descs: dict[int, str],
                            limit: int = VL_REVIEW_MAX_PAGES) -> list[dict]:
    """从主力 VL 结果中挑疑难证据帧；口播/空镜不进入大模型复核。"""
    ranked = []
    for page in pages:
        number = int(page.get("page") or 0)
        text = clean_model_text(descs.get(number, ""))
        if not page.get("shot") or page.get("talking_head") or not text:
            continue
        role_match = re.search(
            r"(?:论证角色|argument role)\s*[:：]?\s*`?"
            r"(evidence|demo|context|transition|blank)", text, re.I)
        role = role_match.group(1).lower() if role_match else ""
        uncertain = bool(_MEDIA_UNCERTAIN_RE.search(text))
        complex_frame = bool(_MEDIA_COMPLEX_RE.search(text))
        if not uncertain and not (role == "evidence" and complex_frame):
            continue
        score = (6 if uncertain else 0) + (3 if role == "evidence" else 0) \
            + (2 if complex_frame else 0)
        ranked.append((score, number, page))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:max(0, int(limit))]]


def review_media_pages(mdir: Path, pages: list[dict], descs: dict[int, str],
                       api: str, video: Path = None) -> tuple[dict[int, str], dict]:
    """用较强 VL 覆盖少量疑难页；单页失败时保留主力结果并继续。"""
    cache_p = mdir / "page_desc.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.is_file() else {}
    reviewed = {int(value) for value in cache.get("reviewed_pages", [])
                if str(value).isdigit()}
    candidates = [page for page in media_review_candidates(pages, descs)
                  if int(page["page"]) not in reviewed]
    if not candidates:
        return descs, {"candidates": 0, "reviewed": len(reviewed), "failed": 0,
                       "model": cache.get("models", {}).get("review")}
    with urllib.request.urlopen(f"{api}/models", timeout=10) as resp:
        mid = json.loads(resp.read())["data"][0]["id"]
    failed = 0
    for index, page in enumerate(candidates, 1):
        number = int(page["page"])
        image = mdir / "slides" / page["image"]
        full_image = mdir / "slides" / f"full_{number:02d}.jpg"
        if full_image.is_file():
            image = full_image
        elif video and Path(video).is_file():
            # 原媒体可能已按存储策略被清理；full 帧是可复用的分析资产。
            # 重抓失败也只影响这一页，不能让已缓存的整场 VL 结果失效。
            try:
                grab_fullres(video, page.get("captured", page["first"]), full_image)
                image = full_image
            except Exception as exc:
                print(f"[meta] 第{number}页原生帧重抓失败: {type(exc).__name__}，"
                      "改用已导出的分析截图", flush=True)
        try:
            raw, _usage = chat_with_image(api, mid, image, 3072, MEDIA_REVIEW_PROMPT)
            cleaned = clean_model_text(raw)
            if not cleaned:
                raise ValueError("empty_vl_review")
            descs[number] = cleaned
            reviewed.add(number)
            print(f"[meta] 疑难页视觉复核 {index}/{len(candidates)} | 第{number}页", flush=True)
        except Exception as exc:
            failed += 1
            print(f"[meta] 疑难页视觉复核第{number}页失败: {type(exc).__name__}，保留主力结果",
                  flush=True)
        current = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.is_file() else {}
        primary = current.get("models", {}).get("primary") or current.get("model")
        payload = {"model": primary or mid,
                   "models": {"primary": primary or mid, "review": mid},
                   "reviewed_pages": sorted(reviewed), "desc": descs}
        temp = cache_p.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(cache_p)
    return descs, {"candidates": len(candidates), "reviewed": len(reviewed),
                   "failed": failed, "model": mid}


def vl_prompts(page: dict):
    """shot 页（media 镜头检测产出，slides.json 里 shot:true）用媒体向 VL 口径；
    会议 slide 页保持原 prompt 不变。"""
    if page.get("shot"):
        return MEDIA_DETAIL_PROMPT, MEDIA_COMPACT_PAGE_PROMPT, "镜头类型"
    return DETAIL_PROMPT, COMPACT_PAGE_PROMPT, "页面类型"


def describe_pages(mdir: Path, pages, api: str, video: Path = None):
    """逐页 VL 详细解读(带 page_desc.json 缓存, 重跑只补缺的页)。返回 {页码: 文本}。
    缺页用有界并发请求(MEETING_VL_WORKERS, 默认 2)，实际上限由 VL 服务的
    --parallel 槽位数决定；每完成一页即原子落缓存，中断后续跑只补缺的。"""
    cache_p = mdir / "page_desc.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.is_file() else {}
    descs = {}
    for key, value in cache.get("desc", {}).items():
        cleaned = clean_model_text(value)
        if cleaned:
            descs[int(key)] = cleaned
    # 清洗后为空不是成功缓存：旧的 reasoning-only/空正文页面必须自动补算。
    todo = [p for p in pages if not descs.get(p["page"], "").strip()]
    if not todo:
        print(f"[meta] VL 页面解读全部命中缓存({len(descs)} 页)", flush=True)
        return descs
    with urllib.request.urlopen(f"{api}/models", timeout=10) as resp:
        mid = json.loads(resp.read())["data"][0]["id"]
    t0 = time.time()
    lock = threading.Lock()

    def persist():
        temp = cache_p.with_suffix(".tmp")
        temp.write_text(json.dumps({"model": mid, "desc": descs},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(cache_p)

    def work(p):
        detail_prompt, compact_prompt, type_label = vl_prompts(p)
        img = mdir / "slides" / p["image"]
        if video:
            img = mdir / "slides" / f"full_{p['page']:02d}.jpg"
            grab_fullres(video, p.get("captured", p["first"]), img)
        raw, usage = chat_with_image(api, mid, img, VL_MAXTOK, detail_prompt)
        cleaned = clean_model_text(raw)
        if not cleaned:
            print(f"[meta] VL 第{p['page']}页详细正文为空，降级为紧凑读取", flush=True)
            raw, retry_usage = chat_with_image(
                api, mid, img, 512, compact_prompt)
            compact = parse_json_loose(clean_model_text(raw))
            if compact:
                title = str(compact.get("title") or "").strip()
                page_type = str(compact.get("type") or "其他").strip()
                summary = str(compact.get("summary") or "").strip()
                if title or summary:
                    fallback_title = title or f"第{p['page']}页屏幕内容"
                    cleaned = (f"## 标题\n{fallback_title}\n"
                               f"## 页面内容\n- {type_label}：{page_type}\n"
                               f"- {summary or '紧凑视觉读取未提供摘要。'}")
            usage = {
                "completion_tokens": int(usage.get("completion_tokens") or 0)
                + int(retry_usage.get("completion_tokens") or 0)
            }
        if not cleaned:
            raise ValueError("empty_vl_content")
        return p["page"], cleaned, usage

    workers = max(1, int(os.environ.get("MEETING_VL_WORKERS", "2")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, p): p for p in todo}
        for fut in concurrent.futures.as_completed(futures):
            p = futures[fut]
            try:
                page_no, cleaned, usage = fut.result()
            except Exception as e:
                print(f"[meta] VL 第{p['page']}页失败: {type(e).__name__}", flush=True)
                # 把已存在的空缓存移除并原子覆盖当前成功结果；下次会继续补算。
                with lock:
                    descs.pop(p["page"], None)
                    persist()
                progress_event("visual_understanding", done=len(descs), total=len(pages),
                               unit="pages")
                continue
            with lock:
                descs[page_no] = cleaned
                persist()
            print(f"[meta] VL 第{page_no}页 tokens={usage.get('completion_tokens','?')}",
                  flush=True)
            progress_event("visual_understanding", done=len(descs), total=len(pages),
                           unit="pages")
    print(f"[meta] VL 解读 {len(todo)} 页(累计 {len(descs)}/{len(pages)})"
          f" | {time.time()-t0:.0f}s", flush=True)
    return descs


def overview_direct(summary_prompt: str, context_json: str,
                    profile: "MinutesProfile" = None):
    """模块级接缝：直出总体纪要（与 map/reduce 共用护栏），测试可替换。"""
    profile = profile or MINUTES_PROFILES["meeting"]
    if profile.kind == "media":
        # 媒体口径没有待办章节：必需章节换成媒体结构，不触发待办定点修复。
        return generate_direct_overview(
            summary_prompt, profile.evidence_rules, notes=context_json,
            client=LocalLLMClient(model=MODEL), max_tokens=6144,
            required=profile.overview_required, validator=None)
    return generate_direct_overview(
        summary_prompt, profile.evidence_rules, notes=context_json,
        client=LocalLLMClient(model=MODEL), max_tokens=6144)


def chat(prompt: str, max_tokens: int = 8192, model: str = MODEL):
    body = json.dumps({"model": model, "temperature": 0.2, "max_tokens": max_tokens,
                       "chat_template_kwargs": {"enable_thinking": False},  # 思考模式会吃掉输出预算
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(ROUTER, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as resp:
        data = json.loads(resp.read())
    return clean_model_text(
        data["choices"][0]["message"].get("content", "")), data.get("usage", {})


def load_inputs(mdir: Path):
    turns = json.loads((mdir / "transcript.spk.json").read_text(encoding="utf-8"))
    tl = json.loads((mdir / "slides.json").read_text(encoding="utf-8"))
    pages = [x for x in tl if x.get("kind") == "slide"]
    return turns, pages


def slice_turns(turns, pages):
    """按说话中点时刻显示的页切片；首页出现前的开场单列。"""
    first0 = pages[0]["first"] if pages else 0.0
    opening, per_page = [], {p["page"]: [] for p in pages}
    for t in turns:
        mid = (t["start"] + t["end"]) / 2
        if pages and mid >= first0:
            p = page_at(pages, mid)
            per_page[(p or pages[0])["page"]].append(t)
        else:
            opening.append(t)
    return opening, per_page


def block_text(opening, per_page, pages, descs=None, desc_limit=None) -> str:
    def fmt(ts):
        return "\n".join(f"[{mmss(t['start'])} {t['speaker']}] {t['text']}" for t in ts)
    lines = []
    if opening:
        lines += ["【开场(未共享画面)】", fmt(opening)]
    for p in pages:
        ts = per_page.get(p["page"], [])
        lines.append(f"【第{p['page']}页 显示自 {mmss(p['first'])}】")
        d = (descs or {}).get(p["page"])
        if d:
            d = " ".join(d.split())              # 压成一行, 便于控制篇幅
            if desc_limit and len(d) > desc_limit:
                d = d[:desc_limit] + "…"
            lines.append(f"【页面内容】{d}")
        lines.append(fmt(ts) if ts else "(本页无对应讨论)")
    return "\n".join(lines)


RETRY_PROMPT = """你是一名严谨的会议纪要编辑。下面是 `meeting-minutes-prompt/v1` JSON。
请只为这些页输出纪要块，严格按页码顺序，格式：

### 第N页 [mm:ss] 一句话主题
- 讨论要点（1-3 条，各带 [mm:ss] 和证据标记）
- **本页结论**：xxx（没有就写“未形成结论”）

标注了"(本页无对应讨论)"的页只输出一行 `### 第N页 [mm:ss] （快速带过）`。
只根据 turns 总结，不要编造；VL 只作页面展示资料。

{evidence_rules}

输入 JSON：

```json
{context}
```"""

MEDIA_RETRY_PROMPT = """你是一名严谨的视频内容分析编辑。下面是 `meeting-minutes-prompt/v1` JSON，
内容来自一条公开视频。请只为这些镜头页输出纪要块，严格按页码顺序，格式：

### 第N页 [mm:ss] 一句话主题
- 内容要点（1-3 条，各带 [mm:ss] 和证据标记）
- **论证角色**：铺垫/论点/证据/演示/结论（纯过渡写“过渡/铺垫”）

标注了"(本页无对应讨论)"的页只输出一行 `### 第N页 [mm:ss] （快速带过）`。
只根据 turns 总结，不要编造；VL 只作画面展示资料。绝不生成待办事项或 kind=action。

{evidence_rules}

输入 JSON：

```json
{context}
```"""


@dataclass(frozen=True)
class MinutesProfile:
    """一套纪要生成口径：prompt 组、文档骨架标题与总体纪要护栏按内容类型并列。"""
    kind: str
    evidence_rules: str
    summary_prompt: str
    group_prompt: str
    retry_prompt: str
    doc_title: str
    detail_heading: str
    overview_required: tuple


MINUTES_PROFILES = {
    "meeting": MinutesProfile(
        kind="meeting",
        evidence_rules=EVIDENCE_RULES,
        summary_prompt=SUM_PROMPT,
        group_prompt=GROUP_PROMPT,
        retry_prompt=RETRY_PROMPT,
        doc_title="# 会议纪要",
        detail_heading="## 分页详情",
        overview_required=("## 总体摘要", "### 待办事项"),
    ),
    "media": MinutesProfile(
        kind="media",
        evidence_rules=MEDIA_EVIDENCE_RULES,
        summary_prompt=MEDIA_SUM_PROMPT,
        group_prompt=MEDIA_GROUP_PROMPT,
        retry_prompt=MEDIA_RETRY_PROMPT,
        doc_title="# 视频分析纪要",
        detail_heading="## 分镜头详情",
        overview_required=MEDIA_OVERVIEW_REQUIRED,
    ),
}


def minutes_profile(mdir: Path) -> MinutesProfile:
    """meta.json 的 content_type 是会议/媒体纪要差异的总开关（缺字段/未知值按会议，
    与 web/deps 口径一致）；调用方签名不变，选择逻辑集中在这一处。"""
    try:
        meta = json.loads((Path(mdir) / "meta.json").read_text(encoding="utf-8"))
        kind = meta.get("content_type")
    except Exception:
        kind = None
    return MINUTES_PROFILES.get(kind, MINUTES_PROFILES["meeting"])

REFINE_PROMPT = """你是一名资深会议纪要编辑。下面是一份按页成稿的会议纪要（总体摘要 + 议题板块 + 逐页详情），
由较小的模型生成，可能有重复、板块划分不当、措辞不统一的问题。请在不改变任何事实的前提下整体重写。

信息分层纪律（必须遵守）：
- 讨论要点/结论只来自发言内容；页面截图的视觉解读仅用于锚定议题结构和核对术语，
  不要把画面描述写进正文（它们会单独进附录）
- 岗位/职级只能提供决策权限语境；不能把建议或单人观点自动升级为结论
- **总体摘要**：主旨凝练；关键结论/待办/风险去重合并；待办保持独立标题与表格，
  列固定为事项/负责人/期限/状态，标题后留空行，表头和分隔行紧邻
- **议题板块**：校准板块划分与命名（可合并或拆分；页码范围必须使用原文出现过的页码）
- **逐页详情**：润色语句、统一术语、去掉跨页重复；"本页结论"与总体摘要的关键结论保持一致
- **严禁**新增原文没有的事实、数字、人名；保留所有 [mm:ss] 时间戳 与 `### 第N页` 标题结构
- 所有 `<!-- mm:evidence ... -->` 标记必须逐字保留，不能删除、改写、移动到其他事实后面或新增
- 直接输出完整新版纪要（Markdown），不要解释、不要前后寒暄

纪要原文：

---
{minutes}
---"""


def _page_theme(desc: str) -> str:
    """从 VL 详解里取一行页面主题(优先'## 标题'节的首行)。"""
    lines = [l.strip() for l in (desc or "").splitlines()]
    for i, l in enumerate(lines):
        if re.match(r"^#{1,4}\s*标题", l):
            for nxt in lines[i + 1:]:
                if nxt and not nxt.startswith("#"):
                    return nxt.lstrip("-* ")[:80]
    for l in lines:
        if l and not l.startswith("#"):
            return l.lstrip("-* ")[:80]
    return ""


def insert_images(md: str, pages, descs=None) -> str:
    """每个 '### 第N页' 标题下插入截图 + 一行页面主题(VL 详解全文不进正文, 见附录)。"""
    img = {p["page"]: p["image"] for p in pages}
    descs = descs or {}
    out = []
    for ln in md.splitlines():
        out.append(ln)
        m = re.match(r"\s*#{3,4}\s*第\s*(\d+)\s*页", ln)
        if m and int(m.group(1)) in img:
            n = int(m.group(1))
            out.append(f"\n![第{n}页](slides/{img[n]})\n")
            theme = _page_theme(descs.get(n, ""))
            if theme:
                out.append(f"**页面主题**(视觉模型): {theme}\n")
    return "\n".join(out)


def appendix_md(pages, descs, per_page=None, kind: str = "meeting") -> str:
    """VL 逐页详解全部沉到附录，并明确区分“有讨论”和“仅展示”。"""
    if not descs:
        return ""
    media = kind == "media"
    first = {p["page"]: p["first"] for p in pages}
    per_page = per_page or {}
    out = ["\n## 附录: 镜头详解(视觉模型逐镜头解读)\n" if media
           else "\n## 附录: 页面详解(视觉模型逐页解读)\n",
           "> 本附录完整保留画面展示信息。标记为“仅画面”的镜头没有对应逐字稿讲解；"
           "画面内容本身不代表视频作者的观点。\n" if media else
           "> 本附录完整保留页面展示信息。标记为“仅展示”的页面没有对应逐字稿讨论；"
           "页面内容本身不代表会议结论。\n"]
    for n in sorted(descs):
        d = re.sub(r"^#{1,4}\s*", "##### ", descs[n], flags=re.M)  # 标题降级, 不抢结构
        if media:
            status = "有讲解" if per_page.get(n) else "仅画面"
        else:
            status = "有讨论" if per_page.get(n) else "仅展示"
        out.append(f"### 页面 P{n:04d} · 第{n}页 · {status} [{mmss(first.get(n, 0))}]\n\n{d}\n")
    return "\n".join(out)


def _extract_blocks(text: str):
    """模型输出 → {页码: 块文本(含 ### 标题行)}。"""
    blocks = {}
    parts = re.split(r"(?=^#{3,4}\s*第\s*\d+\s*页)", text, flags=re.M)
    for part in parts:
        m = re.match(r"^#{3,4}\s*第\s*(\d+)\s*页", part)
        if m:
            blocks[int(m.group(1))] = part.strip()
    return blocks


def generate(mdir: Path, out: Path = None, vl: bool = True, video: Path = None,
             refine_model: str = None, reuse_vl_cache_only: bool = False,
             _identity_retry: int = 1):
    requested_model = refine_model or MODEL
    workload = "exclusive" if any(token in requested_model.lower()
                                      for token in ("120b", "122b")) \
        else ("visual" if vl and not reuse_vl_cache_only else "text")
    prepare_stage(workload, keep=[requested_model])
    profile = minutes_profile(mdir)
    turns, pages = load_inputs(mdir)
    if not pages:
        raise RuntimeError("slides.json 里没有幻灯片页")

    descs = {}
    vl_review = {"candidates": 0, "reviewed": 0, "failed": 0, "model": None}
    if vl:
        progress_event("visual_understanding", done=0, total=len(pages), unit="pages")
    if vl and reuse_vl_cache_only:
        cache = json.loads((mdir / "page_desc.json").read_text(encoding="utf-8")) \
            if (mdir / "page_desc.json").is_file() else {}
        for key, value in cache.get("desc", {}).items():
            cleaned = clean_model_text(value)
            if str(key).isdigit() and cleaned:
                descs[int(key)] = cleaned
        reviewed_pages = [value for value in cache.get("reviewed_pages", [])
                          if str(value).isdigit()]
        vl_review = {"candidates": 0, "reviewed": len(reviewed_pages), "failed": 0,
                     "model": cache.get("models", {}).get("review")}
        print(f"[meta] 复用 VL 页面解读缓存 {len(descs)} 页，不重跑视觉模型", flush=True)
    elif vl:
        api, _proc = ensure_vl_server()
        if api:
            descs = describe_pages(mdir, pages, api, video)
            if profile.kind == "media" and VL_REVIEW_MODEL and VL_REVIEW_MMPROJ:
                review_cache = json.loads((mdir / "page_desc.json").read_text(encoding="utf-8")) \
                    if (mdir / "page_desc.json").is_file() else {}
                reviewed = {int(value) for value in review_cache.get("reviewed_pages", [])
                            if str(value).isdigit()}
                pending_review = [page for page in media_review_candidates(pages, descs)
                                  if int(page["page"]) not in reviewed]
                if not pending_review:
                    vl_review = {"candidates": 0, "reviewed": len(reviewed), "failed": 0,
                                 "model": review_cache.get("models", {}).get("review")}
                    print(f"[meta] 疑难页视觉复核全部命中缓存({len(reviewed)} 页)", flush=True)
                else:
                    # 视觉复核模型与主力模型顺序驻留；先释放本函数拉起的 MiMo，给
                    # dense 27B 留出统一内存。外部常驻 VL 服务不由本进程停止。
                    stop_local_model(_proc)
                    review_api, review_proc = ensure_vl_review_server()
                    if review_api:
                        descs, vl_review = review_media_pages(
                            mdir, pages, descs, review_api, video)
                        stop_local_model(review_proc)
                        print(f"[meta] 疑难页视觉复核完成 {vl_review['reviewed']} 页"
                              f" | 本轮失败 {vl_review['failed']}", flush=True)
    if vl:
        phase_done("visual_understanding", done=len(descs), total=len(pages), unit="pages")
        if descs:
            output_ready("visuals", state="ready" if len(descs) >= len(pages) else "partial")

    # VL can take tens of minutes. Speaker corrections are intentionally allowed
    # while it runs, so the transcript loaded before VL is only a page-extraction
    # input, never the identity source for the final minutes. Reload immediately
    # before text synthesis and fence publication with this revision.
    turns, latest_pages = load_inputs(mdir)
    pages = latest_pages
    transcript_revision = file_revision(mdir / "transcript.spk.json")
    opening, per_page = slice_turns(turns, pages)
    content_pages = [p for p in pages if per_page.get(p["page"])]
    final_batches = 1 + (len(content_pages) + 7) // 8
    progress_event("final_minutes", done=0, total=final_batches, unit="batches")
    bank_dir = Path(os.environ.get("MEETING_WEB_BANK", mdir.parent.parent / "speaker_bank"))
    profiles = load_speaker_profiles(turns, bank_dir)
    summary_context = build_prompt_context(turns, pages, descs, profiles)
    draft_checklist = meeting_generation.voice_draft_checklist(mdir)
    if draft_checklist["items"]:
        summary_context["voice_draft_checklist"] = draft_checklist
    context_json = json.dumps(summary_context, ensure_ascii=False, separators=(",", ":"))
    print(f"[meta] 逐字稿 {len(turns)} 轮/{len(context_json)} 字结构化输入 | 页数 {len(pages)}"
          f" | 开场 {len(opening)} 轮 | VL解读 {len(descs)} 页", flush=True)

    t0 = time.time()
    summary_prompt = profile.summary_prompt.format(
        evidence_rules=profile.evidence_rules,
        policy=json.dumps(CONCLUSION_POLICY, ensure_ascii=False, indent=2),
        context=context_json,
    )
    if ContextBudget(output_tokens=8192).fits(summary_prompt):
        # 直出与 map/reduce 共用同一套退化/章节/待办合规护栏（notes 传完整上下文供修复轮引用）。
        completion = overview_direct(summary_prompt, context_json, profile)
        part1 = clean_model_text(completion.content)
        u1 = completion.usage
        overview_mode, overview_chunks = "direct", 1
    else:
        overview = generate_overview(
            summary_context, CONCLUSION_POLICY, profile.evidence_rules,
            client=LocalLLMClient(model=MODEL),
            progress=lambda current, total: print(
                f"[meta] 总体纪要长文本分段 {current}/{total}", flush=True),
            kind=profile.kind,
        )
        part1 = clean_model_text(overview.content)
        u1 = {"prompt_tokens": overview.prompt_tokens,
              "completion_tokens": overview.completion_tokens}
        overview_mode, overview_chunks = overview.mode, overview.chunks
    print(f"[meta] 总体摘要+板块 {len(part1)} 字 | 模式 {overview_mode}"
          f" ({overview_chunks} 段) | tokens {u1.get('completion_tokens','?')}"
          f" | {time.time()-t0:.0f}s", flush=True)
    progress_event("final_minutes", done=1, total=final_batches, unit="batches")

    def pages_context(group):
        numbers = {int(p["page"]) for p in group}
        return json.dumps(
            build_prompt_context(turns, pages, descs, profiles, detail=True,
                                 page_numbers=numbers),
            ensure_ascii=False, separators=(",", ":"))

    # 逐页详情：有讨论的页按 8 页一组分次调用(防单次输出截断); 空页走确定性占位
    blocks = {}
    t0 = time.time()
    for gi in range(0, len(content_pages), 8):
        grp = content_pages[gi:gi + 8]
        g_out, u_g = chat(profile.group_prompt.format(
            evidence_rules=profile.evidence_rules,
            context=pages_context(grp)), max_tokens=4096)
        got = _extract_blocks(g_out)
        blocks.update(got)
        print(f"[meta] 页块 第{grp[0]['page']}-{grp[-1]['page']}页: 得 {len(got)}/{len(grp)}"
              f" | tokens {u_g.get('completion_tokens','?')}", flush=True)
        progress_event("final_minutes", done=1 + gi // 8 + 1,
                       total=final_batches, unit="batches")

    by_page = {p["page"]: p for p in pages}
    missing = [n for n in by_page if n not in blocks and per_page.get(n)]
    if missing:  # 分组仍漏的页 → 只带缺页切片补问一次
        r_out, u3 = chat(profile.retry_prompt.format(
            evidence_rules=profile.evidence_rules,
            context=pages_context([by_page[n] for n in missing])), max_tokens=4096)
        got = _extract_blocks(r_out)
        for n in missing:
            if n in got:
                blocks[n] = got[n]
        print(f"[meta] 缺页补问: {len(missing)} → 得 {len(set(got) & set(missing))}"
              f" | tokens {u3.get('completion_tokens','?')}", flush=True)

    n_model = len(blocks)
    part2 = "\n\n".join(
        blocks.get(p["page"]) or f"### 第{p['page']}页 [{mmss(p['first'])}] （快速带过）"
        for p in pages)
    print(f"[meta] 分页详情: 模型出 {n_model} 页 + 占位 {len(pages) - n_model} 页"
          f" | {time.time()-t0:.0f}s", flush=True)

    part1 = re.sub(r"^# (?:会议纪要|视频分析纪要)\s*", "", part1)
    body = (f"{profile.doc_title}\n\n" + part1.strip()
            + f"\n\n{profile.detail_heading}\n\n" + part2 + "\n")
    refined = False
    if refine_model and profile.kind == "media":
        # 精修 prompt 是会议口径（待办表格纪律），媒体纪要暂不做精修重写。
        print("[meta] 媒体内容不走会议精修 prompt，已跳过精修", flush=True)
    elif refine_model:
        t0 = time.time()
        r_out, u4 = chat(REFINE_PROMPT.replace("{minutes}", body), model=refine_model)
        markers_before = [m.group(0) for m in MARKER_RE.finditer(body)]
        markers_after = [m.group(0) for m in MARKER_RE.finditer(r_out)]
        # 结构与证据双校验：少页、删除/改写/移动证据标记都弃用精修稿。
        structure_ok = len(re.findall(r"^#{3,4}\s*第\s*\d+\s*页", r_out, re.M)) >= len(pages)
        if structure_ok and markers_before == markers_after:
            body = r_out if r_out.lstrip().startswith("#") else "# 会议纪要\n\n" + r_out
            refined = True
            print(f"[meta] 大模型精修({refine_model}) {len(r_out)} 字"
                  f" | tokens {u4.get('completion_tokens','?')} | {time.time()-t0:.0f}s", flush=True)
        else:
            reason = "页块缺失" if not structure_ok else "证据标记变化"
            print(f"[meta] 精修稿{reason}, 保留原稿", flush=True)
    md = normalize_minutes_markdown(normalize_action_marker_scope(
        insert_images(body, pages, descs)))
    md += appendix_md(pages, descs, per_page, kind=profile.kind)
    current_transcript_revision = file_revision(mdir / "transcript.spk.json")
    if current_transcript_revision != transcript_revision:
        if _identity_retry > 0:
            print("[meta] 文本生成期间说话人身份已更新，复用 VL 缓存重跑纪要", flush=True)
            return generate(
                mdir, out, vl=vl, video=video, refine_model=refine_model,
                reuse_vl_cache_only=bool(vl), _identity_retry=_identity_retry - 1)
        raise RuntimeError("transcript_changed_during_minutes_generation")
    out = Path(out) if out else mdir / "minutes.md"
    if out.exists():
        shutil.move(str(out), str(out.with_name("minutes.prev.md")))
    out.write_text(md, encoding="utf-8")
    _evidence_path, evidence = write_evidence_document(
        mdir, md, turns, pages, descs, profiles,
        generation={
            "prompt_schema": "meeting-minutes-prompt/v1",
            "content_type": profile.kind,
            "conclusion_policy": CONCLUSION_POLICY["version"],
            "text_model": MODEL,
            "vl_enabled": bool(vl),
            "vl_pages": len(descs),
            "vl_review_model": vl_review.get("model"),
            "vl_reviewed_pages": int(vl_review.get("reviewed") or 0),
            "vl_review_failures": int(vl_review.get("failed") or 0),
            "generation_stage": "final",
            "overview_mode": overview_mode,
            "overview_chunks": overview_chunks,
            "refined": refined,
            "refine_model": refine_model if refined else None,
        })
    phase_done("final_minutes", done=final_batches, total=final_batches, unit="batches")
    output_ready("final_minutes")
    return out, {"pages": len(pages), "page_blocks": len(pages), "chars": len(md),
                 "vl_pages": len(descs), "refined": refined,
                 "claims": len(evidence["claims"])}


def main() -> int:
    ap = argparse.ArgumentParser(description="按页为单元的会议纪要(总体摘要+议题板块+逐页详情+VL画面内容)")
    ap.add_argument("mdir", type=Path, help="会议目录(含 transcript.spk.json 与 slides.json)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-vl", action="store_true", help="不做 VL 画面内容层")
    ap.add_argument("--video", type=Path, default=None,
                    help="原视频(给了则按 captured 时间戳重抓原生分辨率帧给 VL, 否则用 slides/ 图)")
    ap.add_argument("--reuse-vl-cache-only", action="store_true",
                    help="严格只读 page_desc.json，不启动或调用视觉模型；用于存量文本/脉络重建")
    ap.add_argument("--refine-model", default=None,
                    help="大模型精修重写(如 qwen3.5-122b-a10b-planner; 首次调用需加载, 分钟级)")
    ap.add_argument("--publish", action="store_true",
                    help="成功后发布 ready 状态（Web 重生成/失败恢复使用）")
    args = ap.parse_args()
    if not (args.mdir / "transcript.spk.json").is_file() or not (args.mdir / "slides.json").is_file():
        print("会议目录缺 transcript.spk.json 或 slides.json", file=sys.stderr)
        return 1
    out, stats = generate(args.mdir, args.out, vl=not args.no_vl, video=args.video,
                          refine_model=args.refine_model,
                          reuse_vl_cache_only=args.reuse_vl_cache_only)
    if args.publish:
        meeting_generation.finalize(
            args.mdir, pages=stats["pages"], vl_pages=stats["vl_pages"])
    meeting_topic_map.generate_for_pipeline(args.mdir)
    if args.publish:
        print(f"[meta] 多模态终稿已发布 | VL {stats['vl_pages']}/{stats['pages']} 页",
              flush=True)
    print(f"[meta] 纪要: {out} | {stats['chars']} 字 | VL页数 {stats['vl_pages']}"
          f"{' | 已精修' if stats['refined'] else ''}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
