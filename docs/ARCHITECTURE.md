# 系统架构

本文回答数据如何流动、哪些资产是真源、模型在哪里可替换，以及失败和 revision 如何保持可信。适合技术评审与实现修改；不回答当前周计划、部署命令或完整 RAG 教程。当前状态看 [STATUS.md](STATUS.md)，运行方式看 [OPERATIONS.md](OPERATIONS.md)，知识合同看 [KNOWLEDGE_RAG.md](KNOWLEDGE_RAG.md)。

## 一页摘要

```text
Source
  Teams VTT/DOCX · audio · recording · public media URL · live source · photos
  ↓
Local model-enhanced processing
  ASR · diarization · visual understanding · text generation
  ↓
Canonical transcript / identity / evidence
  ↓
Meeting and media projections
  ↓
Web · Viewer · AI Context · KB · RAG
```

系统的稳定边界不是某一模型的输出，而是来源、人工确认、稳定 ID、revision 与只读 projection。模型可以提出文字、人物或结构候选；代码负责路径、ID、证据、写入、删除和版本校验。

## 部署形态

当前是单机模块化单体（modular monolith）：

- FastAPI 提供工作台、媒体、导出、身份、任务和知识发布 API。
- 原生 ES modules 构成在线工作台；离线 Viewer 是自包含 HTML。
- Python 子进程执行 ASR、说话人、视觉、纪要、脉络、翻译和索引任务。
- 持久化 job JSON 保存受控状态，不保存会议正文。
- 本地模型服务通过 loopback 或进程内 provider 接入。

它不是生产级多人架构。正式共享服务还需要 SSO、会议级 ACL、租户隔离、TLS、配额、审计、备份、删除策略和明确支持责任；不能直接把本机端口暴露给不受控网络。

## 输入路线

| route | 来源 | 关键差异 |
|---|---|---|
| audio | 单个音频 | 本地 ASR → 说话人分离 → 纪要与检索 |
| video | 普通会议录屏 | 本地 ASR 与说话人 + 逻辑页面；完整模式继续 VL，快速模式直接生成语音版正式纪要与脉络 |
| teams | 录屏 + VTT/DOCX | 先读取外部文稿和姓名，再与本地声音对齐；同样支持快速纪要或完整分析 |
| media | 本地视频或受限公开链接 | 镜头、论证角色和第一手来源；不生成会议式待办 |
| retranscribe | 已有母版 | 从私有快照与当前 provider 重建逐字稿及下游资产 |
| regenerate / sync | 已有 canonical | 标准重生成可补缺；快速同步只复用完整 VL 缓存 |
| visual upgrade | 已有语音版结果 | 复用媒体、逐字稿、人物和逻辑页，只补画面理解、正式纪要与脉络 |
| live | 公开 HLS 或明确授权的会议/browser 来源 | 先写 `.live/` 暂定 signal 和 checkpoint；结束后 reconcile，复用 visual upgrade 补完画面，最后才写 canonical |

现场资料采用独立的补充路径：图片先原子固化为受保护原图和阅读 JPEG，再由批量
`photo_analysis` 作业调用本地 VL。视觉模型只读取图片，不读取逐字稿；分析完成后，
已确认定位仅把前后两分钟的 T ID 作为文本纪要的邻近上下文。已有终稿在缓存完整时
只重生成纪要与 evidence，不重跑 ASR、人物或页面 VL；仍在处理的会议由原终稿阶段吸收。
未定位图片仍进入资料解读，但不会伪造与某段发言的时间关联。

公开链接下载只接受受限单条媒体。原始 URL 只进入私有 inbox；工作台、Viewer 与 KB 只投影 `media-source/v1` 的白名单字段，含临时 query 的 generic URL 不导出。

Live 中间层位于单场目录的 `.live/`：尽量 append-only 保存 timed text、speaker/frame event 和脱敏 metrics，checkpoint 原子替换。主页关闭不改变 worker；重启时从 checkpoint 恢复媒体序号。该目录不进入 Git、应用发布包、MeetingPack 或 KB，也不作为事实真源。

`CONNECTING → LIVE → STALLED/RECOVERING → ENDING → FINALIZING → COMPLETE`
是结构化状态合同。HLS `ENDLIST` 是强结束信号；无进展只先进入宽限期，恢复后回到 `LIVE`。输入冻结后，finalizer 按来源优先级融合信号，物化已选画面，调用现有 `minutes_by_page.py`/`summarize.py`；不重跑 ASR、说话人或已有 logical frame。

## Canonical 数据真源

Canonical 表示来源变化和人工修正必须安全写回的权威状态，而不是“模型认为最完整”的文本。

| 资产 | 角色 | 写入边界 |
|---|---|---|
| 媒体母版 | 可恢复原始来源 | 固化后受保护；导出和缓存清理不修改 |
| `transcript.spk.json` | 原语言逐字稿、时间和本场人物轮次真源 | 原子写入、revision、私有快照和撤销 |
| identity / org 数据 | 人工确认身份与关系 | 人工锁优先；自动候选不可覆盖确认 |
| `minutes.md` | 正式可读纪要 | 结构/证据/revision 校验后发布并保留历史 |
| `minutes.evidence.json` | claim、正式行动项与 T/P/C linkage 真源 | 由确定性代码从合规 marker 和来源重建 |
| `meeting.facts.json` | 不随阅读版式改变的事实库存 | 与来源 revision 绑定，用于重组和导出 |

`minutes.md` 是正式阅读文本，但不能脱离 evidence 单独成为事实数据库。人工自然语言重组产生独立阅读 view，不覆盖 canonical 纪要；修改正式纪要则必须先预览或经过确定性校验并可恢复上一版。

## 稳定 ID 与 evidence

- `T` 标识逐字稿轮次，可回到人物、原声和时间。
- `P` 标识逻辑页面或视觉材料，可回到画面和显示区间。
- `C` 标识纪要中的结构化 claim，可引用一组 T/P 来源。

LLM 可以生成包含 evidence marker 的候选，但解析器必须容忍 Markdown 包装并重新验证 ID。视觉页面只能证明“屏幕展示了什么”，不能单独把方案、数字或建议升级为会议决定。职位或组织层级可以帮助理解确认权限，但不能自动改变结论语气。

## 派生资产与 revision

下列内容都是 revision-bound derivative：

- `meeting.topic-map.json` 与媒体 narrative navigation；
- VL 页面描述、缩略图和阅读 JPEG；
- 纪要、逐字稿、脉络和画面翻译；
- 关键字、相关内容索引和 `.rag/`；
- AI 纪要 view、Viewer、AI Context 和 KB projection；
- 知识库发布回执。

来源 revision 包括相关逐字稿、人物身份、页面画面、现场资料 sidecar 和正式纪要指纹。相关来源变化时，派生资产必须变成 stale、排队更新或在下次读取时懒重建。没有现场资料 sidecar 的旧会议保持原 revision 形状，避免仅因升级代码而全部误判过期。旧结果可以保留用于恢复，但不能继续展示为当前版本。

逐字稿快速同步是独立安全路径：

1. 视频会议必须确认 `slides.json` 中每个逻辑页都有非空 `page_desc.json`；
2. 使用 `reuse-vl-cache-only`，不启动 ASR、说话人或 VL；
3. 先发布新 `minutes.md` 与 evidence；
4. Topic Map、翻译和关键字作为低优先级派生任务继续；RAG 按 revision 懒重建；
5. 任一页面缓存缺失就拒绝快速路径，标准重生成仍可补跑视觉。

导入时的快速纪要与逐字稿修正后的“快速同步”不是同一条路径。前者用 `--no-vl` 明确跳过
画面模型，但仍提取逻辑页、生成正式纪要和 Topic Map，并在 `meeting.generation.json` 记录
`result_mode=voice_only` 与 `visual_mode=skipped_by_user`。用户稍后触发 `visual-upgrade` 时，系统只运行
`minutes_by_page.py` 的画面及下游生成：缓存完整则严格复用，缓存不完整才补跑 VL；两种情况都不重跑
ASR、说话人或覆盖当前可读结果。该模式不改变 canonical schema，只增加作业与生成状态投影。

## Provider 边界

模型角色通过 provider/adapter 接入，业务流程不写死模型品牌、GPU 厂商或操作系统。

| 角色 | 必需合同 | 可选能力与降级 |
|---|---|---|
| ASR | 文本、时间戳、语言信息 | Context 不支持时禁用；缺必要时间戳时不得发布对齐逐字稿 |
| diarization | 时间区间与声音标签 | 极短/重叠语音无法可靠区分时保持待确认 |
| VL | 图片输入与可读文本 | 失败保留未解析，不把空输出缓存为成功 |
| text generation | 可读正文与受控错误 | thinking、上下文和输出预算由统一客户端管理 |
| embedding | 文本向量 | 不可用时退化为词法召回 |
| reranker | 候选相关性排序 | 不可用时保留融合排序，不生成新事实 |
| KnowledgeSink | 预检、revision 幂等发布和删除 | 凭据仅服务端；远端内容不得反写 canonical |

远端 provider 只有在管理员显式配置且符合政策时才允许使用。失败不得静默更换隐私边界；兼容回退必须在配置和 UI 中可解释。

## 处理状态合同

新作业以 `job-progress/v2` 为权威状态，不依赖前后端分别解释自然语言日志。对象稳定记录：

- `route`、`state`、当前 `phase` 和动态 `phases`；
- `done / total / unit` 与真实阶段耗时；
- `available_outputs`，区分逐字稿、人物导航、语音草稿、视觉、终稿和脉络；
- 可信 ETA 范围与样本置信度；
- 结构化 `failure`、checkpoint、retry options 和 attempt；
- `retry_of / recovered_by` 关系。

主路径通过受控 `[progress]`、`[phase_done]`、`[output_ready]`、`[failure]` 和 `[recovery]` JSON 事件更新 job store。事件不含正文、人名、绝对路径、原始 URL 或模型完整输出。旧作业可以通过明确标记的 legacy fallback 投影，但不能伪装为精确阶段。

## 失败与恢复

等待资源、暂停、取消、非关键增强降级、可恢复失败和阻断失败具有不同语义：

- 临时资源不足优先进入 `waiting_resource`，有限重试并停止 ETA 递减；
- 有检查点的阶段失败优先从最近安全单元继续；
- 输入损坏或 provider 缺能力时先要求更换来源/服务，不提供无效重复按钮；
- 可选翻译、embedding 或视觉复核失败不能把主结果伪装成完全失败；
- 降级完成必须写明缺少什么，例如“语音版结果不包含剩余画面事实”；
- 从头 ASR、覆盖人工修改、删除母版或改变本地/云端边界必须显式确认。

普通 API 只暴露业务原因、影响、保留资产、推荐操作和脱敏 diagnostic ID；raw traceback、stdout/stderr、脚本、端口和 prompt 不进入用户界面。

## Web、Viewer 与知识投影

- **Web workspace**：可写工作台，负责导入、处理、修正、恢复、阅读和发布操作。
- **MeetingPack Viewer**：只读、自包含、无 CDN/服务端/LLM；保留播放、人物、脉络、纪要、画面和证据跳转。
- **AI Context**：纯文本便携来源，给用户自选模型或 Notebook 使用，不自动上传。
- **KB projection**：分块友好的 Markdown 或自包含图文 HTML；凭据和 target 只在服务端。
- **RAG**：从当前 revision 构建词法/向量候选并返回证据引用；不能覆盖 canonical。

这些 projection 可以有不同信息密度，但不能生成互相竞争的事实版本。来源变化后，旧 Viewer/Pack 必须重新导出；旧知识发布通过 revision 回执更新或标记 stale。

## 单机资源模型

统一资源策略负责 ASR、说话人、VL、文本模型和知识增强的准入：健康时可保留少量文本模型；音频/视觉重阶段收缩并发；超大精修模型独占；低内存先卸载空闲模型并等待，而不是让多个业务脚本各自抢资源。CUDA、ROCm 与 CPU 使用不同构建产物，但共享业务合同和硬件选择层。

## 模块边界

- `bin/meeting_core/`：provider、硬件、资源、进度事件、canonical 与通用处理规则。
- `bin/*.py`：route orchestration 与可独立执行的处理阶段。
- `web/job_store.py`、`job_progress.py`、`job_recovery.py`：持久任务、投影和恢复。
- `web/routers/`：HTTP 业务入口，不复制任务与 canonical 规则。
- `web/static/modules/`：无构建原生 ES modules；规则模块不操作 DOM，view 模块不调用 API 或读取全局 state。
- `bin/meetingpack_viewer.html`：离线只读 projection，与在线阅读语义保持一致。

`web/static/app.js` 仍是较大的装配 controller，是当前开放风险之一；后续只在高频变化且输入输出清楚的责任域继续拆分，不以行数为目标做机械重构。

## 不变量

1. 私有会议、人员、组织、凭据和日志不进入 Git。
2. 不静默上云，不静默改变 provider 或高质量模型。
3. 人工确认不能被自动相似扩展覆盖。
4. 页面画面不能独立证明会议决定。
5. 下游知识库不能反写 canonical。
6. 所有高价值写入校验路径、revision 和恢复边界。
7. 旧会议至少保持可读；schema 演进提供明确兼容或迁移。

## 继续阅读

- 用户旅程与交互合同：[UX.md](UX.md)
- 运行与恢复：[OPERATIONS.md](OPERATIONS.md)
- 处理细节：[runbooks/PROCESSING_AND_RECOVERY.md](runbooks/PROCESSING_AND_RECOVERY.md)
- 模型角色：[reference/MODELS.md](reference/MODELS.md)
- 知识与 RAG：[KNOWLEDGE_RAG.md](KNOWLEDGE_RAG.md)
- 重大事故：[history/ENGINEERING_CHANGES.md](history/ENGINEERING_CHANGES.md)
## Companion 边缘投影

Experimental Companion 的 transport 固定为 `Phone → tailnet HTTPS → Tailscale Serve → http://127.0.0.1:<port>`。Serve 与 Funnel 是不同边界；本原型禁止 Funnel，也不把 FastAPI 改为 `0.0.0.0`。

`/api/companion/**` 是独立 controller/projection 层。它复用现有 jobs、canonical meeting、evidence/media 和 speaker correction 服务，不拥有第二套会议、人物或队列状态。应用授权由哈希保存的一次性 pairing token、可撤销 HttpOnly session、能力白名单、同源检查和双提交 CSRF 共同约束。Tailscale identity header 只作为近似 metadata，不能替代应用 session。

### Review、media 与 caption 合同

- `GET /library` 使用 opaque offset cursor，服务端限制每页最多 50；Home 请求 5，完整 Library 请求 20。
- `GET /items/{id}` 只返回 allowlist 概览；章节和逐字稿分别按需读取，逐字稿每页最多 50。
- `GET /items/{id}/media/{audio|video}` 复用 Starlette `FileResponse`，首包为 200，合法 byte range 为 206，并返回 `Accept-Ranges`／`Content-Range`。
- `GET /items/{id}/captions/{source|translation|bilingual}.vtt` 以当前逐字稿和人物 display revision 投影 WebVTT；translation 只接受 revision 匹配的 ready sidecar，否则 409 stale。
- MeetingPack 可选写入相同 caption cue 数据；Viewer 运行时安装原生 `TextTrack`，旧包缺少 cue 时保持无字幕兼容路径。

导航状态只由 `companion-router.js` 管理，后台 job poll 只更新安全 sessionStorage 指针和卡片，不得调用路由。播放器状态独立于 Tab／人物 projection，所以人物确认或显示改名不会重置时间。

### 人物显示与语义身份

简单 bind 改变 voice→person attribution；display rename 只改变已确认 person 的首选显示名。二者都只重建逐字稿显示、people/evidence/caption 等确定性投影，不触发 ASR、diarization、VL、纪要、Topic Map 或翻译模型。跨会议 display rename 在私有 bank history 中保存 bank 与相关逐字稿 revision 快照，撤销前拒绝覆盖更新的数据。旧纪要自然语言正文不做全局字符串替换。
