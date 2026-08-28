# Local Video Meeting Minutes

**当前产品版本：v0.14.0**（仓库根目录 `VERSION` 为单一真源）

本地会议上下文编译器：把录音、录屏、Teams VTT/DOCX、公开媒体链接以及已经存在的逐字稿，整理成身份明确、证据可追溯、可以交给同事、通用模型、Notebook 或知识库继续使用的上下文。

产品不再以“持续追赶云端 ASR/VL/文本模型效果”为核心目标。本地 ASR、说话人分离、VL 和纪要模型保留为可替换的输入增强；稳定核心是校正、证据和供应商中立的导出。四类能力仍绑定同一 canonical 数据：

- **Meeting Identity Core**：声纹证据 → 稳定 Person ID → 中文名/全拼/英文名等类型化名称 → 可编辑 Org Chart。它解决会议室共用麦克风只能显示设备名称、无法区分真人的问题。
- **Evidence Core**：纪要结论、行动项和风险绑定逐字稿 T ID、屏幕页 P ID 与 claim C ID；页面展示不能被自动升级为会议决定。
- **Multimodal Review**：会议脉络是首屏，播放器、时间轴、逐字稿、当前屏幕和结论共享 Focus；屏幕资料可放大、缩放并按时间前后切换。
- **Portable Context Core**：同一事实可确定性投影为离线 MeetingPack、单文件 AI Context Markdown、KB Markdown/HTML 或 revision 幂等的 WeKnora 文档。消费端可以更换，时间与证据 linkage 不丢失。

## 用户旅程

1. 先选择“会议”或“媒体”：已有 Teams VTT/DOCX 可直接作为转写来源；只有音视频时才使用配置的本地或兼容 ASR。来源原件固化，外部逐字稿不准时可忽略并重转写。
2. 确认最影响复用质量的信息：人员姓名、说话人归属、原语言逐字稿和关键结论证据。本地说话人、VL、翻译和纪要生成是可选增强，不是导出的供应商依赖。
3. 有录屏时后台可以继续抽取逻辑页面、理解共享画面并生成多模态终稿；急用时只要 canonical 逐字稿形成，就可以先导出核听或 AI 上下文快照。
4. 用户从会议脉络进入某个议题；时间操作改变播放位置，右侧节点选择只改变阅读 Focus。媒体内容会按实际形态自适应导航：单人口播显示“议题 + 叙事作用”，访谈显示“议题 + 人物”，混合内容同时保留两者。
5. 在纪要、逐字稿与画面之间核对证据，确认人员身份；必要时播放并修正单轮原语言文本，随后更新纪要和脉络。
6. 线下讨论中的白板、纸面或黑板照片可在会后补入：优先读取拍摄时间，也可按当前播放位置直接对齐或暂存为未定位资料；原图受保护，阅读副本进入 Web、Viewer、MeetingPack 和知识投影，但不会被单独冒充会议决定。
7. 按消费方交付：给同事核听用 MeetingPack；给 GPT、豆包、Gemini、NotebookLM 或其他模型用单场 `.context.md`；给 WeKnora 等知识库用 KB Markdown/HTML。外部上传前由用户确认公司政策和脱敏范围。
8. 多场同系列会议可以导出 `.contextpack.zip`，每场一份纯文本来源，另附来源索引、证据使用约定和通用起始提示词。历史模式、汇报训练或专题研究交给用户选择的下游模型完成，本应用不再建设第二套通用 Notebook。

## 架构概览

```text
音频 / 视频 / Teams VTT·DOCX / 公开媒体 URL / 已有逐字稿
        │
        ├─ 转写与字级对齐 ───────┐
        ├─ 说话人分离与声纹匹配 ─┼─ transcript.spk.json (T IDs)
        └─ 逻辑页面检测 + VL ────┘               │
                                                  ▼
                       完整事实层 + 当前纪要阅读投影
                          │       │          │          │
                          │       ▼          ▼          ▼
                          │   会议脉络     本地 RAG    结论审计
                          │       └──────────┬──────────┘
                          └─ 自然语言重组 ──┤
                                             ▼
                   Web 阅读器 / MeetingPack / AI Context / KB Projection
```

详细边界见 [系统架构](docs/ARCHITECTURE.md)，结论和 RAG schema 见 [导出与 RAG](docs/EXPORT_AND_RAG.md)，
发布节奏与标签规则见 [产品版本与发布规范](docs/RELEASES.md)。

## 快速开始

项目要求 Python 3.11+、`ffmpeg/ffprobe`，完整管线还需要与显卡匹配的 PyTorch 和 `llama-server`。新机器请先阅读 [跨机器与 GPU 部署](docs/DEPLOYMENT.md)，不要让 `pip` 意外覆盖已经可用的 CUDA/ROCm PyTorch。

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
# 先按 GPU 厂商安装 PyTorch，再安装完整管线依赖
.venv/bin/pip install -e '.[pipeline]'

make doctor
make check
make smoke
make run
```

浏览器入口（顶栏会显示当前产品版本）：

- `http://127.0.0.1:8899/`：会议回顾、证据、翻译、追问与导出
- `http://127.0.0.1:8899/admin`：人员身份、声纹试听和图形化 Org Chart
- `http://127.0.0.1:8899/product`：面向管理、产品、UX 和技术评估的中英双语产品介绍
- “更多 → 发布到知识库”：管理员配置 API 与目标白名单后，一键发布/更新 WeKnora；顶栏“知识库”仍用于打开独立服务

## 常用处理命令

```bash
# 录音：转写和分离并行，再生成纪要
.venv/bin/python bin/run_all.py /path/to/recording.wav --title 周会

# Teams 录屏：使用 VTT 或 DOCX 姓名，识别会议室内多个声音，并理解共享画面
.venv/bin/python bin/teams_minutes.py /path/to/meeting.mp4 /path/to/meeting.docx

# 无 VTT 录屏：本地 ASR + 说话人分离 + 屏幕理解
.venv/bin/python bin/video_minutes.py /path/to/meeting.mp4 --slug 项目评审

# 只重建多模态纪要或整场语义脉络
.venv/bin/python bin/minutes_by_page.py meetings/<meeting>/ --publish
.venv/bin/python bin/meeting_topic_map.py meetings/<meeting>/

# 导出离线阅读包；默认不携带媒体
.venv/bin/python bin/export_meeting.py meetings/<meeting>/ --media none

# 导出一个可直接交给通用模型或 Notebook 的 Markdown；不含本机链接和媒体
.venv/bin/python bin/export_meeting.py meetings/<meeting>/ --profile ai

# 多场同系列会议：每场一份 context.md + 来源索引 + 使用提示
.venv/bin/python bin/export_pack.py meetings/<one>/ meetings/<two>/ --profile ai

# 导出给 WeKnora 等知识库使用的轻量 Markdown 包；base URL 用于时间码回跳
.venv/bin/python bin/export_meeting.py meetings/<meeting>/ --profile kb \
  --base-url http://<本机局域网地址>:8899

# 导出可直接上传的单文件图文版；关键画面内嵌，不依赖图片路径或运行中的服务
.venv/bin/python bin/export_meeting.py meetings/<meeting>/ --profile kb-html \
  --base-url http://<本机局域网地址>:8899
```

工作台也可直接发布，不需要先下载再上传。服务端只把白名单目标 ID 暴露给浏览器，API key
保留在服务端；本地回执只记录 provider、目标、远端文档 ID、profile 和 revision，不保存正文或凭据。
最小配置见 [WeKnora 集成](docs/WEKNORA_INTEGRATION.md) 和 `deploy/meeting-minutes.env.example`。

知识库导出不会重复塞入 Viewer、媒体和多份 JSON。需要离线移交或手工上传时，只需要文字和最小体积，解压
`.kbpack.zip` 后上传 `<meeting>.kb.md`；希望保留关键截图时直接上传 `<meeting>.kb.html`。
会议应用已经生成画面标题、详细解读和 evidence，因此 WeKnora 的 VLM 默认可以关闭；只有需要
补读文字解读未覆盖的表格字段、图表或演示细节时才显式开启，避免重复分析与两套解释冲突。
图文版把筛选后的关键画面压成最长边 1600px 的 JPEG data URI，
口播、空白、会议 UI、过渡和已判定低价值的画面不嵌图，但文字解读仍保留。两种产物的时间码
都会跳回本应用，所以测试前应确认 `--base-url` 是知识库使用者实际可访问的地址，而不是只能
本机访问的 `127.0.0.1`。

Web 导入会把源文件固化到内容目录。同文件系统优先使用 CoW reflink，不支持时复制；公开链接先下载为受保护母版，再进入与本地视频相同的媒体分析管线，因此下载缓存或源页面变化后仍可回看。链接导入需要服务端具备外网访问能力，默认拒绝本机、局域网、直播、播放列表、超时长和超大内容。存储清理只删除可再生缓存，不删除母版和阅读资产。

## 目录与文件职责

```text
meeting-minutes/
├── bin/                       # CLI、处理管线、导出器和纯业务模块
│   └── meeting_core/          # LLM 协议、上下文预算、硬件选择、长会 Map/Reduce
├── web/                       # FastAPI 服务、RAG/翻译/审计服务和浏览器前端
│   ├── static/                # 在线工作台；app.js 装配入口 + modules/ 领域规则
│   └── tests/                 # 仅使用虚构/临时数据的回归测试
├── prompts/                   # 独立可审查的模型提示词
├── docs/                      # 产品、架构、部署、成本和工程文档
├── deploy/                    # 无凭据的环境变量与 systemd 示例
├── recordings/                # 私有输入与上传暂存；不进 Git
├── meetings/                  # 每场会议的 canonical 资产；不进 Git
├── speaker_bank/              # 私有人员、声纹和 Org Chart；不进 Git
├── evaluations/               # 私有结论审计事件；不进 Git
├── AGENTS.md                  # 代码代理的范围、隐私和验证约束
├── CHANGELOG.md               # 面向人的重要变更索引；Git 仍是完整历史真源
├── Makefile                   # 统一运行与验证入口
└── pyproject.toml             # Python 包与依赖声明
```

一场会议目录的关键资产：

| 文件 | 作用 | 是否可再生 |
|---|---|---|
| `source_video.*` / `source_audio.*` | 会议母版 | 否，受保护 |
| `source.json.source_info` | 公开媒体的平台、发布者、标题、日期、时长与安全 canonical URL 白名单 | 可从来源重建；不得保存 Cookie/请求头/下载器原始字典 |
| `audio.wav` | 16 kHz PCM 工作音轨 | 是 |
| `transcript.spk.json` | 带稳定 T ID 语义的具名逐字稿来源；长口播按受限时长切成可导航轮次 | 代价高，视为 canonical |
| `minutes.md` | 正式可读纪要 | 可由来源重算，但保留版本 |
| `minutes.evidence.json` | claim ↔ T/P linkage 与结构化行动项 | 可由纪要和来源重建 |
| `meeting.topic-map.json` | 3–8 个整场议题、证据范围及媒体自适应导航投影 | 可重建，输入变更即 stale |
| `slides.json` + `slides/` | 逻辑页、出现区间和阅读缩略图 | 可从视频重建 |
| `page_desc.json` | VL 对每个逻辑页的详细说明 | 可重建，成本较高 |
| `meeting.photos.json` + `photos/` | 现场照片、EXIF/人工时间对齐与受保护原图/阅读副本 | 原图不可再生；阅读副本可重建 |
| `meeting.knowledge-publications.json` | 不含正文/凭据的知识库发布回执与 revision | 可从远端状态重新建立 |
| `.rag/` | 本地 embedding/reranker 索引 | 是 |

## 文档地图

| 文档 | 何时阅读 |
|---|---|
| [PROCESSING_GUIDE.md](docs/PROCESSING_GUIDE.md) | 第一次了解：一场会议如何处理、为何分阶段、看到各状态该做什么 |
| [PRODUCT_FUNCTIONS.md](docs/PRODUCT_FUNCTIONS.md) | 按四级编号查看当前功能、上线版本、关键 Git 与重要度 |
| [PRODUCT_UX.md](docs/PRODUCT_UX.md) | 理解产品定位、阅读旅程和交互原则 |
| [DESIGN_TOKENS.md](docs/DESIGN_TOKENS.md) | 了解 Fluent 2 适配、共享 token、图标与原生组件合同 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 理解处理流、canonical 数据和模块边界 |
| [EXPORT_AND_RAG.md](docs/EXPORT_AND_RAG.md) | 实现证据 linkage、MeetingPack 或 RAG 消费方 |
| [KB_RAG_LEARNING_GUIDE.md](docs/KB_RAG_LEARNING_GUIDE.md) | 从零理解 KB、分块、混合检索、reranker、引用与项目实验方法 |
| [WEKNORA_INTEGRATION.md](docs/WEKNORA_INTEGRATION.md) | 部署、资源调度、一键知识发布、文件回退与验收合同 |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | 在 NVIDIA、AMD 或 CPU 机器部署和验收 |
| [COST_MODEL.md](docs/COST_MODEL.md) | 查看 2 小时实测会议的云端/本地/套餐成本模型 |
| [MODELS.md](docs/MODELS.md) | 选择模型、显存策略和常驻方式 |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发、测试、配置和 Git 私有数据边界 |
| [ENGINEERING_REVIEW.md](docs/ENGINEERING_REVIEW.md) | 查看工程风险、重构顺序和未完成项 |
| [NEXT_PLAN.md](docs/NEXT_PLAN.md) | 下一阶段：同事自助提交、本机持久队列与受控结果交付 |
| [UX_REVIEW_AND_REFERENCES.md](docs/UX_REVIEW_AND_REFERENCES.md) | 查看 UX 走查、同类产品和开源参考 |
| [CHANGELOG.md](CHANGELOG.md) | 按功能阅读变更历史 |
| [HANDOFF.md](HANDOFF.md) | 代理/人类接手：当前基线、进行中任务和已定方案 |

## 配置与显卡兼容

业务代码不依赖 AMD。PyTorch 的 ROCm 版本也使用 `torch.cuda` API；项目会诊断实际 backend 为 `rocm` 或 `cuda`，NVIDIA 不支持 BF16 时自动回退 FP16。`llama.cpp` 则需要在目标机器安装对应的 CUDA 或 HIP backend。

模型路径、设备和端口都可通过环境变量覆盖；完整列表及 NVIDIA 验证矩阵见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。环境变量与多模型路由示例分别位于 [meeting-minutes.env.example](deploy/meeting-minutes.env.example) 和 [llama-models.ini.example](deploy/llama-models.ini.example)。

## 隐私与维护约束

- 默认模型端点只允许 loopback；远程模型必须针对当次处理得到明确授权，并设置 `MEETING_ALLOW_REMOTE_LLM=1`。
- `recordings/`、`meetings/`、`speaker_bank/`、`evaluations/` 和作业状态不进 Git，也不能进入测试夹具或诊断输出。
- 模型输出是候选事实；决定、行动和风险必须回链真实逐字稿证据。职位只提供权限语境，不是全局重要性权重。
- 测试不得读取真实会议。提交前至少运行 `make check && make smoke`。
- 仓库级代理规范见 [AGENTS.md](AGENTS.md)；它用于约束后续 Codex/Kimi 等维护者，不替代 README 或架构文档。

完整代码历史保存在当前私有 GitHub 仓库；`CHANGELOG.md` 只负责把重要产品变化翻译成人可以快速阅读的记录。
