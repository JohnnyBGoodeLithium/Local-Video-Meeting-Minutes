# Local Video Meeting Minutes

**当前产品版本：v0.8.2**（仓库根目录 `VERSION` 为单一真源）

本地多模态会议知识工作台：把录音、录屏、Teams VTT/DOCX 逐字稿、说话人声纹、组织架构和共享画面组织成一套可阅读、可核验、可追问、可修正、可离线分享的会议记录。

它已经不是“钉钉闪记的本地替代品”。产品的核心差异是把四类信息绑定在一起：

- **Meeting Identity Core**：声纹证据 → 稳定 Person ID → 中文名/全拼/英文名等类型化名称 → 可编辑 Org Chart。它解决会议室共用麦克风只能显示设备名称、无法区分真人的问题。
- **Evidence Core**：纪要结论、行动项和风险绑定逐字稿 T ID、屏幕页 P ID 与 claim C ID；页面展示不能被自动升级为会议决定。
- **Multimodal Review**：会议脉络是首屏，播放器、时间轴、逐字稿、当前屏幕和结论共享 Focus；屏幕资料可放大、缩放并按时间前后切换。
- **Knowledge Core**：本地混合检索、reranker、带来源问答、结论审计和版本化 MeetingPack，为后续跨会议 RAG 保留稳定 linkage。

## 用户旅程

1. 导入音频、录屏，或同时导入 Teams 录像与 VTT/DOCX 逐字稿；若外部逐字稿不准，可在导入时忽略或对已有会议改用本地 ASR，原文件保留可回退。
2. 先完成转写和说话人识别，尽快发布可阅读的语音草稿。
3. 后台继续抽取逻辑页面、理解共享画面、生成多模态终稿和整场会议脉络。
4. 用户从会议脉络进入某个议题；时间操作改变播放位置，右侧节点选择只改变阅读 Focus。
5. 在纪要、逐字稿与画面之间核对证据，确认人员身份，追问或预览纪要修改。
6. 导出一个 `viewer.html + README.txt + assets/` 的 MeetingPack；收件人无需 GPU、LLM 或本机服务。

## 架构概览

```text
音频 / 视频 / Teams VTT·DOCX
        │
        ├─ 转写与字级对齐 ───────┐
        ├─ 说话人分离与声纹匹配 ─┼─ transcript.spk.json (T IDs)
        └─ 逻辑页面检测 + VL ────┘               │
                                                  ▼
                               结构化纪要 + evidence claims
                                  │          │          │
                                  ▼          ▼          ▼
                              会议脉络     本地 RAG    结论审计
                                  └──────────┬──────────┘
                                             ▼
                              Web 阅读器 / MeetingPack Viewer
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
- `http://127.0.0.1:8899/product`：面向管理、产品、UX 和技术评估的产品介绍

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
```

Web 导入会把源文件固化到会议目录。同文件系统优先使用 CoW reflink，不支持时复制；因此下载目录清理后会议仍可播放。存储清理只删除可再生缓存，不删除母版和阅读资产。

## 目录与文件职责

```text
meeting-minutes/
├── bin/                       # CLI、处理管线、导出器和纯业务模块
│   └── meeting_core/          # LLM 协议、上下文预算、硬件选择、长会 Map/Reduce
├── web/                       # FastAPI 服务、RAG/翻译/审计服务和浏览器前端
│   ├── static/                # 在线工作台 HTML/CSS/JS
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
| `audio.wav` | 16 kHz PCM 工作音轨 | 是 |
| `transcript.spk.json` | 带稳定 T ID 语义的具名逐字稿来源 | 代价高，视为 canonical |
| `minutes.md` | 正式可读纪要 | 可由来源重算，但保留版本 |
| `minutes.evidence.json` | claim ↔ T/P linkage 与结构化行动项 | 可由纪要和来源重建 |
| `meeting.topic-map.json` | 3–8 个整场议题及证据范围 | 可重建，输入变更即 stale |
| `slides.json` + `slides/` | 逻辑页、出现区间和阅读缩略图 | 可从视频重建 |
| `page_desc.json` | VL 对每个逻辑页的详细说明 | 可重建，成本较高 |
| `.rag/` | 本地 embedding/reranker 索引 | 是 |

## 文档地图

| 文档 | 何时阅读 |
|---|---|
| [PRODUCT_UX.md](docs/PRODUCT_UX.md) | 理解产品定位、阅读旅程和交互原则 |
| [DESIGN_TOKENS.md](docs/DESIGN_TOKENS.md) | 更换主题（字体/配色/间距/圆角）或定制组件外观 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 理解处理流、canonical 数据和模块边界 |
| [EXPORT_AND_RAG.md](docs/EXPORT_AND_RAG.md) | 实现证据 linkage、MeetingPack 或 RAG 消费方 |
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

模型路径、设备和端口都可通过环境变量覆盖；完整列表及 NVIDIA 验证矩阵见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。示例配置位于 [deploy/meeting-minutes.env.example](deploy/meeting-minutes.env.example)。

## 隐私与维护约束

- 默认模型端点只允许 loopback；远程模型必须针对当次处理得到明确授权，并设置 `MEETING_ALLOW_REMOTE_LLM=1`。
- `recordings/`、`meetings/`、`speaker_bank/`、`evaluations/` 和作业状态不进 Git，也不能进入测试夹具或诊断输出。
- 模型输出是候选事实；决定、行动和风险必须回链真实逐字稿证据。职位只提供权限语境，不是全局重要性权重。
- 测试不得读取真实会议。提交前至少运行 `make check && make smoke`。
- 仓库级代理规范见 [AGENTS.md](AGENTS.md)；它用于约束后续 Codex/Kimi 等维护者，不替代 README 或架构文档。

完整代码历史保存在当前私有 GitHub 仓库；`CHANGELOG.md` 只负责把重要产品变化翻译成人可以快速阅读的记录。
