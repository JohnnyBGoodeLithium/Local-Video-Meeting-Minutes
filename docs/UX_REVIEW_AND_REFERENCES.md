# UX 走查与同类项目参考

- 走查日期：2026-08-11；P0 实施复核：2026-08-12
- 范围：当前部署在 `127.0.0.1:8899` 的会议列表、详情阅读、播放时间线、逐字稿、结论审计、助手与导出入口；同时复核前端状态管理、响应式规则和 GitHub 同类项目。
- 隐私边界：界面截图只用全虚构夹具在本机 `/tmp` 临时生成；本文不记录真实逐字稿、纪要、人名或组织信息。

## 1. 结论

> 2026-08-12 进展：下述“连续性不足”和主要状态/布局摩擦已完成 P0 修正。当前页面会恢复有效 revision 下的阅读锚点与分栏，使用资料/证据/分享状态、紧凑播放器、双层时间线、右侧 AI/证据智能栏、中文作业阶段和导出预检；1024px 及以下会议库改为抽屉。历史发现保留在本文，供后续回归对照。

当前产品最有价值、也最区别于普通 AI 录音工具的部分已经形成：逐字稿与媒体常驻、纪要结论可回到证据、模型修改先预览再写入、多人/声纹/组织架构有人工确认边界、MeetingPack 可以离线核证。下一阶段不应继续横向堆“摘要按钮”，而应把这些能力串成更连贯的阅读产品。

本轮发现的三项主问题：

1. **连续性不足**：刷新后停在空白“选择会议”，没有恢复上次会议、阅读位置、语言模式和面板比例；用户每次都要重新进入工作状态。
2. **系统状态没有转译成用户状态**：处理中只显示原始 slug 与英文 `running`，旧会议 evidence 不完整时入口仍像正常可验收；用户分不清“可读旧版本、正在重算、证据不足、译文过期”。
3. **核心知识仍被困在单次会议里**：已有 claim/evidence/RAG，但决定、行动、风险和人员关系还没有成为可跟踪、可更新、可跨会议引用的对象。

工程上没有必要立即把项目整体改写为 Tauri/Next.js。推荐保留 FastAPI、本地模型服务和文件型会议资产，先抽出共享 domain core、拆分 API 路由，再渐进迁移到 Vue 3 + TypeScript + Vite。Tauri 只在“自动检测并录制系统音频、安装包、托盘和原生权限”成为核心需求时再加壳。

## 2. 当前用户旅程走查

| 阶段 | 已经做对的 | 主要摩擦 | 建议 |
|---|---|---|---|
| 进入应用 | 会议列表可读，导入入口明确 | 首屏不自动打开最近/上次会议；导入比“继续阅读”更抢眼 | 恢复上次会议及阅读状态；已有会议时将导入收成一个紧凑按钮 |
| 处理中的会议 | 可以边处理边看列表，也能取消作业 | 原始 slug 换行、`running` 英文状态、无阶段/完成量；同一会议的已完成版本与新作业关系不清 | 显示“转写/分离/理解画面/生成纪要/建索引”阶段、完成量和“当前仍可阅读旧版本” |
| 播放与时间线 | 播放器、时间线和逐字稿确实常驻左侧；点击时间可回放 | 视频按 16:9 常驻时占掉大量逐字稿高度；固定栏宽不可调整；一小时会议刻度和议题标记拥挤且缺少图例 | 增加紧凑播放器/展开画面、可拖动分栏并记忆比例；时间线分成播放进度、章节/页面两层并显示当前时间 |
| 逐字稿阅读 | 说话人、时间码、跟随播放、原文/中文/双语都在同一上下文 | 长英文名挤压正文；全部轮次一次性进入 DOM；长会定位只能滚动或靠播放跟随 | 说话人 chip 截断并悬停看全名；1000+ 轮启用虚拟列表；增加当前议题、说话人和文本筛选 |
| 纪要阅读 | 正文宽度尚可，纪要/结论审计不离开会议；在线与离线都按“会议纪要 / 章节脉络 / 屏幕内容”组织 | 长纪要没有常驻目录；证据不完整的会议仍需更醒目的可核证状态 | 增加轻量目录；默认突出会议纪要，把脉络和屏幕内容作为理解与核查的次级入口；标题区显示 evidence `ready/partial/stale` |
| 核对依据 | 证据能跳到逐字稿与媒体，质量标签不会直接改正式纪要 | 依据卡以浮层覆盖正文；某些旧会议没有 claim 时，用户要点进去后才知道不能验收 | 在右栏内使用可收缩 evidence drawer，保留正文上下文；证据不足时禁用或改名为“补全证据” |
| 追问与修正 | 助手常驻；引用原文是可选操作；修改先预览、再保存并可撤销 | 空白输入缺少可发现的典型问题；等待期间只有一句状态，不能停止；无法选中纪要明确指定修改目标 | 提供 3–4 个随会议状态变化的建议问题；按“检索证据→组织回答”流式显示并可停止；支持纪要选区作为目标 |
| 导出分享 | MeetingPack v4 已有完整逐字稿、压缩媒体跳转、证据、章节脉络与屏幕内容，且顶层只有 Viewer/README/assets；默认打开会议纪要 | 导出仍需要真实收件人验证屏幕可读性和视频压缩质量 | 分享前展示压缩后预计大小、evidence 状态和媒体规格；项目母版与分享副本严格分离；导出前统一清洗 VL 标题 |
| 会议库维护 | 有搜索、可删除 | 重复处理的同源会议并列；删除不可恢复；没有项目/标签/日期分组 | 用源文件/转写 revision 指纹提示重复；先进入回收站；增加最近、处理中、待核对、项目/标签筛选 |

### 响应式与可访问性

当前 CSS 在 1050px 以下仍要求阅读两栏最小宽度合计约 780px，同时保留 210px 左侧会议栏；因此大约 `821–990px` 存在被裁切风险，到 820px 才改为上下堆叠。移动布局也仍保留 190px 会议栏，不能视为真正的窄屏模式。

下一轮至少要验证 1600×900、1366×768、1024×768 和 390×844 四档：

- 1024px 以下会议库改为抽屉，阅读区占满宽度；
- 逐字稿/纪要可通过分段控制切换，不强行把两个窄栏并排；
- 所有只有 hover 才出现的引用/删除操作也能键盘聚焦；
- icon-only 控件有可读名称，焦点顺序遵循“会议→播放→逐字稿→纪要→助手”；
- 颜色之外再用文字/图标表达 evidence、质量和作业状态。

## 3. 下一版推荐交互

### 3.1 首屏与详情状态

默认恢复 `last_meeting_slug + transcript_turn_id + minutes_heading + language_mode + pane_ratio`。会议已删除或 revision 变化时安全回退到最近会议顶部，不尝试恢复不存在的 DOM 滚动像素。

标题区只保留三个用户状态：

- **资料状态**：处理中 / 可阅读 / 纪要需更新；
- **证据状态**：可核证 / 部分证据 / 已过期；
- **分享状态**：可导出 / 缺媒体 / 需先重建证据。

模型名、端口和索引细节继续留在设置/健康页，不占阅读主界面。

### 3.2 阅读布局

- 左侧媒体区默认使用紧凑高度；用户点“看画面”时在左栏放大或进入模态全屏，不永久牺牲逐字稿空间。
- 逐字稿与纪要之间增加拖动分隔条，比例保存在本机。
- 右侧默认打开会议纪要，并把它作为最明显的主入口；章节脉络和屏幕内容保持次级页签。离线 Viewer 不提供管理层/执行层、快速/精细模式选择，需要特定受众版本时在导出动作中生成一份明确命名的独立成品。
- evidence drawer 占右栏的一部分宽度并可固定，点击来源时左侧逐字稿定位、媒体 seek、右侧 evidence 同步高亮。

### 3.3 助手

保持“无需选择问答/编辑模式”的现有方向。补充：

1. 初始建议问题来自确定性结构，例如“这次确认了什么”“我需要跟进什么”“仍有哪些未决问题”；没有 claim 时改成“按原文梳理讨论主题”，不能假装有结论。
2. 流式输出以段落/引用块为单位，来源编号一旦展示不得在后续 token 中重排。
3. 状态文案是“正在检索证据”“正在核对原文”“正在组织回答”，旁边提供停止；停止后已显示内容保留并标为“未完成”。
4. 每个回答提供“转为纪要修改”“加入行动项草稿”“仅复制”三个确定性后续动作。

### 3.4 逐字稿修正

借鉴同类应用的 inline edit，但保持本项目的 evidence 约束：

- 编辑单轮时同时保存原文、修订文、修订者类型和时间；
- 影响到的 claim、翻译、纪要和向量索引标记为 stale，不自动改写结论；
- 支持批量术语替换预览，但姓名近似匹配仍不得自动绑定人员；
- 重新生成前可比较“原转写 / 人工修正”，人工版本优先作为事实来源。

### 3.5 视频解析产品复核（2026-08-12）

本轮针对豆包视频总结、YouTube 与 Bilibili 生态的视频总结工具重新检查后，结论不是“再增加一种摘要”，而是严格分开时间导航和语义结构：

- [YouTube 官方章节](https://support.google.com/youtube/answer/9884579)把视频切成连续、可跳转的时间段；[官方逐字稿](https://support.google.com/youtube/answer/15930243)跟随当前播放并可用于定位章节。值得借鉴的是稳定的时间导航，不是把每一帧或每一次页面变化都变成章节。
- 火山引擎开发者社区对[豆包浏览器插件视频总结](https://developer.volcengine.com/articles/7541274202767425555)的展示包括亮点目录、多级目录和思维导图，信息组织是“主题—子主题—重点”，不是按截图顺序罗列页面。
- [BibiGPT 总结页](https://docs.bibigpt.co/en/getting-started/bibigpt-summary-page-features)把概要、思维导图、逐字稿和文章视图分开；其[合集归纳说明](https://docs.bibigpt.co/function-usage/platform-function/collection-summary)强调可展开引用与原视频回溯。B 站本身提供视频载体，用户需要的“脑图 + 时间戳 + 截图”主要由这一类总结产品补足。

据此采用以下产品约束：

1. Chapter 只表示连续语义段，屏幕 Segment 不能直接冒充 Chapter；空白、过渡、会议 UI 等低信息画面归入相邻章节；
2. 以全部 Chapter 构建整场会议的纵向连续脉络；章内的讨论依据、形成结果、后续动作、待确认和关键屏幕只在展开态出现，叶子必须可回到逐字稿/页面来源；
3. 屏幕内容单独保留完整 VL 解释和每次出现区间，并标记核心/参考/低信息；默认隐藏低信息但允许查看，不能静默删除；
4. 章节脉络使用独立、版本化的 Topic 节点与 T/P/C 来源 linkage；页面、时间段和视觉布局不直接产生主题。同一主题跨多个非连续时间出现时合并为一个分支，时间区间只承担回放导航；
5. 模型 `<think>/<analysis>` 属输出污染：展示层必须隐藏，生成层必须在落盘前清洗；清洗后无可靠答案时标记重新解析，不能把 reasoning 当标题。

## 4. GitHub 同类项目对照

| 项目 | 技术/定位 | 值得借鉴 | 边界 |
|---|---|---|---|
| [Meetily](https://github.com/Zackriya-Solutions/meetily) | Tauri + Rust + Next.js，本地 SQLite，自包含桌面应用，MIT | 断点恢复、后台模型下载、模型 readiness、模板切换、富文本编辑、跨平台安装 | 当前项目已有独立大模型/ASR 服务，立即重写会增加 Rust/Node/打包维护面；先借交互，不迁内核 |
| [minutes](https://github.com/silverstein/minutes) | 共享 Rust core，CLI/MCP/Tauri 多界面；Markdown/YAML 是耐久资料，MIT | `core → CLI/MCP/UI` 单一领域层；typed actions/decisions/people；speaker confidence；stable URI；所有知识保留 provenance | 其 agent-first/跨会记忆方向值得学，但本项目仍需更强的页面/VL 和离线 Viewer |
| [Speakr](https://github.com/murtaza-nasir/speakr) | Flask/SQLAlchemy + Vue 3/Tailwind，PWA，多用户自托管，AGPL/商业双许可 | 浮动/可停靠单会对话、全库 Inquire、文件夹/Smart Tags、词表、保留策略、权限分享、版本化 REST API | AGPL 代码不能直接拷入闭源/内部分发方案；只借产品和架构模式，除非明确接受许可证义务 |
| [Muesli](https://github.com/Muesli-HQ/muesli) | Swift/AppKit/SwiftUI 原生本地应用，MIT | 日历“Join & Record”、个人词典、会前/会后可切模板重新摘要、PDF/Markdown 导出、逐步 onboarding 与崩溃续接 | 强绑定 macOS/Apple 模型栈，不适合作为本机 AMD/Linux 的工程底座 |
| [OpenWhispr](https://github.com/OpenWhispr/openwhispr) | React 19 + TypeScript + Tailwind/shadcn + Electron，本地/云端可切，MIT | 组件化 UI、API/MCP、文件夹与团队空间、跨平台安装、可访问的 Radix primitives | Electron 体积和双运行时不适合当前“本机 Web + 重模型服务”；可参考组件边界和权限模型 |
| [screenpipe](https://github.com/screenpipe/screenpipe) | 本地连续屏幕/音频时间线和搜索，source-available | 时间/应用/来源过滤，搜索结果直接返回截图和音频片段，事件驱动采样 | 目标范围比会议纪要大很多，且商业使用受许可证限制；不复制代码，不扩张到 24/7 记录 |
| [MOSS-Transcribe-Diarize](https://github.com/OpenMOSS/MOSS-Transcribe-Diarize) | 0.9B 端到端多语种转写+分离+时间戳，Apache-2.0 | 可作为当前 ASR + pyannote 组合的 A/B 候选，尤其用于长会议和多语言；带自定义 prompt/hotword 能力 | 是模型候选而非产品框架；必须用本项目真实噪声、重叠说话和人员一致性测试后再决定 |

### 关于“8000+ 纪要模板”

同类开源产品通常只提供少量内置模板和自定义模板，真正可扩展的是“模板变量 + 标签/文件夹规则 + 可重新生成”，不是维护数千份独立 prompt。当前项目更适合建立组合式 `view recipe`：

```text
audience: exec | working | external
goal: brief | follow_up | decision_review | risk_review | project_update
depth: quick | standard | deep
language: original | zh-CN | en
sections: decisions/actions/risks/context/pages
evidence_policy: strict | readable
```

少量维度即可覆盖大量场景，同时所有 recipe 仍消费同一 canonical claims/evidence，不形成 8000 套互相漂移的事实提取 prompt。

## 5. 推荐工程演进

### 5.1 不做整体重写

当前 `web/server.py`、`web/static/app.js`、`style.css` 已分别达到约 1360/1338/839 行，继续在单文件上叠加流式输出、版本浏览、跨会检索和响应式布局，会显著增加状态耦合。但问题是模块边界，不是 Python/FastAPI 本身。

推荐目标：

```text
meeting_core/
├── artifacts/          # transcript/minutes/evidence/views 的读写与 revision
├── identity/           # person/voice/org，不依赖 Web
├── retrieval/          # lexical/dense/rerank 与索引生命周期
├── actions/            # 决定/行动/风险的状态和 provenance
└── schemas/            # Pydantic API/domain schema
web/
├── api/v1/             # meetings/jobs/assistant/quality/identity/export routers
├── services/           # Web 用例编排，不含 HTTP 细节的领域逻辑
└── frontend/           # Vue 3 + TypeScript + Vite
workers/                # 可恢复作业与阶段事件
viewer/                 # MeetingPack 单文件静态构建，继续无联网依赖
mcp/                    # 未来只读 local interface；ACL 前不开放跨用户
```

会议目录仍是正文与媒体的 canonical source。可以新增 SQLite catalog，但第一阶段只存会议索引、作业、UI 状态、标签和 ACL 元数据，不把全部逐字稿迁入数据库，避免破坏现有可移植性和 Git 隐私边界。

### 5.2 分阶段迁移

1. **先拆 Python，不换 UI**：建立 `meeting_core`、FastAPI `APIRouter`、Pydantic response schema 和 `/api/v1`；旧 `/api` 保持兼容。新增作业阶段事件和 UI 状态接口。
2. **再迁详情页**：用 Vue 3 + TypeScript + Vite 重做会议列表、详情 panes、evidence drawer 和 assistant；保留现有 API，使用 Vitest + Playwright 覆盖用户旅程。管理后台随后迁移。
3. **补知识生命周期**：将 claim 投影为 typed decision/action/risk，支持 `open/done/superseded/cancelled`、负责人、期限和来源；跨会议搜索先以项目/人员/日期/权限过滤，再检索。
4. **最后决定桌面壳**：只有自动录制、系统托盘、原生权限、崩溃恢复成为必须时才评估 Tauri；远程同事查看仍走 Web/MeetingPack，不由桌面壳承担。

## 6. 优先级与验收标准

### P0：下一轮直接改善阅读旅程

- [x] 恢复上次会议、语言、T ID/纪要标题和 pane ratio；revision 变化时安全回到顶部。
- [x] 标题区明确资料、evidence 与分享状态；不再用一个可点击按钮掩盖证据不足。
- [x] 紧凑/展开播放器、可拖动分栏、双层时间线；1366×768 下保持连续阅读空间。
- [x] 作业显示中文阶段与完成量，使用可读会议名；读取旧版本和后台重建可并存。
- [x] 导出向导显示证据状态、媒体可用性和预计大小。
- [x] 底部宽助手改为右侧 AI/证据智能栏；四档视口完成合成数据视觉检查。

### P1：把 AI 交互做成可控过程

- 助手 SSE 流式输出、停止、阶段状态和稳定来源编号。
- 在线与 MeetingPack 继续共用“会议纪要 / 章节脉络 / 屏幕内容”的阅读层级和 VL 标题清洗规则，不维护两套信息架构。
- 逐字稿单轮修正、纪要 stale 提示、成套版本浏览/恢复。
- 会议库增加重复候选、回收站、项目/标签和待核对筛选。

### P2：从会议文件到组织知识

- typed decision/action/risk 生命周期与跨会议 supersedes 关系；所有状态变化保留原会议 provenance。
- 组合式 view recipe 与个人/团队默认值，替代模板数量竞赛。
- 权限模型完成后提供跨会议 Inquire、只读 MCP 和稳定资源 URI。
- 建立 MOSS 等 ASR/diarization 候选的真实评测集，不按 GitHub 榜单直接替换现有管线。

每项 UX 改动至少用桌面四档视口和键盘主路径测试；涉及 evidence、转写或纪要写入时，仍需通过 revision 冲突、历史备份和私有数据隔离回归。
