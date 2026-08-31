# Technical Brief — Local Meeting Context Compiler

- Prepared date: 2026-08-31
- Product version: v0.15.1
- Source Git commit: `c47d3a0`
- Source status date: 2026-08-31
- Classification: Public-safe technical brief

## English

### Why the user cares

A useful meeting artifact must survive model errors and product changes. Users need to correct names and words once, trace conclusions to source evidence, resume after a failed stage, and send the result to different consumers without running the entire pipeline again.

```text
Teams / Audio / Recording / Product Video
                    │
                    ▼
       Local model-enhanced workflow
       ASR · Speaker · Visual · Generation
                    │
                    ▼
     Canonical transcript · identity · evidence
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
   Offline Viewer  AI Context  Local KB / RAG
```

### System properties

- **Local-first:** default providers use local processes or loopback endpoints. A remote endpoint requires explicit administrator configuration; the system does not silently move private content to cloud services.
- **Model-agnostic:** ASR, diarization, visual understanding, text generation, embedding, and reranking enter through role-specific provider boundaries. Special capabilities such as timestamps or ASR context declare their support and degradation behavior.
- **Evidence-linked:** stable transcript, page, and claim identifiers connect readable conclusions to original words, playback time, and visual material. A screen page can prove what was displayed, not that the meeting approved it.
- **Recoverable:** persistent `job-progress/v2` records route-specific phases, available outputs, checkpoints, ETA ranges, structured failures, and attempts. Recovery reuses the latest safe assets instead of replaying an opaque command.

### Canonical and derived data

“Canonical” means the authoritative state that user corrections must update safely. The original media, `transcript.spk.json`, confirmed identity data, `minutes.md`, and `minutes.evidence.json` form the high-value source boundary. Topic maps, translations, visual descriptions, keywords, and retrieval indexes are revision-bound derivatives. When a source changes, stale derivatives remain identifiable and must be rebuilt or replaced; they cannot continue to appear current.

### Projection boundary

The Web workspace, self-contained Viewer, AI Context, KB documents, and RAG records are projections of the same source. They do not own identity or meeting truth. MeetingPack favors human review; AI Context favors portable source material for a user-selected general AI tool; KB projection favors downstream chunking and retrieval. A downstream knowledge base is a consumer, not the fact source.

### Processing and failure model

Each route builds only the phases that actually run: imported Teams transcripts differ from local ASR; audio differs from video; regeneration differs from retranscription. First usable output and full output are separate states. Resource waiting, optional degradation, cancellation, recoverable failure, and blocked failure are not collapsed into one red state. After transcript corrections, fast synchronization is allowed only when every logical visual page already has readable analysis; otherwise standard regeneration must fill the gap.

### Resource and deployment boundary

The current architecture is a modular monolith on one capable machine: FastAPI, native ES modules, Python subprocess jobs, persistent job JSON, and local model services. Heavy stages are serialized and model residency contracts under pressure. This is not yet a production multi-user architecture; SSO, per-meeting ACL, tenant isolation, quota, lifecycle enforcement, and audited remote access require a separate service boundary.

### Current validation

The repository uses fictional isolated fixtures for canonical, progress, failure, identity, photo, export, RAG, and browser journeys. v0.15.1 passed `make check` and isolated smoke 215/215. This establishes implementation confidence, not universal model accuracy or production readiness.

## 中文

### 用户为什么在意

有用的会议资产必须能跨越模型错误和产品变化。用户需要一次修正姓名和原话，把结论回到来源证据，在某阶段失败后继续，并把同一结果交给不同消费方，而不是重新运行全部处理。

```text
Teams / 音频 / 录屏 / 产品视频
                    │
                    ▼
          本地模型增强工作流
       ASR · 人物 · 视觉 · 文本生成
                    │
                    ▼
       Canonical 逐字稿 · 身份 · 证据
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
   离线 Viewer    AI Context   本地 KB / RAG
```

### 系统属性

- **本地优先（Local-first）：**默认 provider 使用本地进程或 loopback 端点。远端端点必须由管理员显式配置，系统不会静默把私有内容移到云端。
- **模型无关（Model-agnostic）：**ASR、说话人分离、视觉理解、文本生成、embedding 和 reranker 通过角色化 provider 边界接入。时间戳、ASR Context 等特殊能力必须声明支持与降级方式。
- **证据关联（Evidence-linked）：**稳定逐字稿、页面和结论 ID 将可读结论连接到原话、播放时间和画面。页面只能证明展示了什么，不能证明会议批准了什么。
- **可恢复（Recoverable）：**持久化 `job-progress/v2` 记录 route 阶段、可用输出、检查点、ETA 范围、结构化失败和多次尝试。恢复复用最近安全资产，不重放不透明命令。

### Canonical 与派生数据

Canonical 指用户修正必须安全更新的权威状态。媒体母版、`transcript.spk.json`、人工确认身份、`minutes.md` 和 `minutes.evidence.json` 构成高价值来源边界。Topic Map、翻译、视觉描述、关键字和检索索引是 revision 绑定的派生资产。来源变化后，旧派生结果必须可识别为 stale 并重建或替换，不能继续伪装为当前版本。

### Projection 边界

Web 工作台、自包含 Viewer、AI Context、KB 文档和 RAG records 都是同一来源的 projection，不拥有身份或会议事实。MeetingPack 面向人核听；AI Context 面向用户自选通用 AI；KB projection 面向下游分块与检索。下游知识库是消费方，不是事实真源。

### 处理与失败模型

每条 route 只生成真实发生的阶段：导入 Teams 文稿不同于本地 ASR，音频不同于视频，重生成不同于重新转写。第一份可读结果和完整结果分别表达。资源等待、可选增强降级、取消、可恢复失败和阻断失败不会合并成一个红色状态。逐字稿修正后的快速同步只有在全部逻辑页面已有可读解读时才允许，否则必须走标准重生成补齐缺口。

### 资源和部署边界

当前架构是在一台高能力机器上的模块化单体：FastAPI、原生 ES modules、Python 子进程作业、持久化 job JSON 和本地模型服务。重阶段串行执行，资源压力下收缩模型驻留。它尚不是生产级多人架构；SSO、会议级 ACL、租户隔离、配额、生命周期和审计远程访问需要另行建设服务边界。

### 当前验证

仓库使用虚构隔离夹具验证 canonical、进度、失败、人物、照片、导出、RAG 和浏览器旅程。v0.15.1 的 `make check` 与隔离 smoke 215/215 通过。这证明实现具有回归信心，不代表所有模型精度或生产成熟度。
