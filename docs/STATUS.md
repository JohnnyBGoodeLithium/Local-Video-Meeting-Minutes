<!-- current-status-source -->
# 当前状态

- 更新时间：2026-09-04
- 产品版本：v0.16.0（release candidate）
- 最近发布版本：v0.15.3
- 发布状态：v0.16.0 release candidate
- Web 构建号：20260904p119
- Workbench asset baseline：20260904p117
- Release candidate 基线：`release/v0.16.0`；正式 tag 尚未创建
- 源代码基线：`release/v0.16.0`，base `e93d22cc7cc9a1ff0992d266717d516476bbd67e`
- Owner：Local AI PoC maintainer
- 当前阶段：受控 PoC 验证（Controlled PoC validation）

## 一句话状态

项目已经形成可运行的本地会议上下文编译流程：把会议或视频转成可核听、可回证、可修正并可交给人、通用 AI 工具或知识库继续使用的上下文；会议回顾主旅程已真实验证，视频与跨内容知识使用仍需系统评测。

## 已真实验证（Validated）

- 单机本地完成音频、录屏和 Teams VTT/DOCX 的导入、逐字稿、人物核听、纪要和证据回跳。
- 真实内部试用推动了人物选择、逐段回听、逐字稿修正、处理进度、失败恢复和导出体验的多轮迭代；公开仓库不记录人员与会议身份。
- MeetingPack 可在无服务、无模型、无 CDN 的环境中回听并核对逐字稿、纪要、人物和画面。
- 人工修正逐字稿后，完整视觉缓存可被严格复用，快速发布新纪要与 evidence；缓存不足时拒绝伪完整结果。
- 人物核听、canonical 人物确认、撤销和来源回跳已经过真实受控工作流与合成回归共同验证。

## 已实现，仍在验证（Implemented, under validation）

- Companion 已扩展为 Phone／Tablet／Laptop 自适应 review：Home 固定 5 条最近内容，任务轮询不再夺取导航；详情提供概览、章节、人物、逐字稿四个 Tab，并共享音频／视频播放器与原文、翻译、双语字幕。Hosted Chromium 已通过；真实 iPhone／Tablet 仍待验证。
- 匿名人物可确认已有人员或新建并绑定；已确认人物可单独预览并修改 canonical 显示名，跨会议修改有 revision guard 与撤销，简单绑定和显示改名均为 0 model calls。
- MeetingPack Viewer 的匿名人物改名仍是按包隔离的本地 alias，不会变成 canonical 身份；新包可携带确定性 caption cue，旧包继续启动。

- 公开视频链接与本地产品/发布会/讲解视频共用媒体分析核心，但叙事切分、复杂图表理解和长期质量矩阵仍弱于会议主旅程。
- AI Context、KB Markdown/HTML 与 provider-neutral `KnowledgeSink` 已实现；真实知识库的权限、删除、规模和评测仍需受控验证。
- 本地关键词、dense retrieval 与 reranker 已可用于单场证据问答；跨会议价值尚未形成稳定评测结论。
- NVIDIA、AMD 与 CPU 的配置边界已抽象，当前验证深度仍集中在主要开发机器。
- 视频导入可以选择快速纪要或完整分析；快速模式仍生成正式纪要和会议脉络，后续画面补充只重跑视觉及下游结果，不重跑 ASR 或说话人。

## 实验中（Experimental）

- Live Context 可在开启 `MEETING_LIVE_CONTEXT=1` 后直接接收能安全解析为公开、无 DRM 原生 HLS 的直播页面或 HLS 地址，执行无浏览器后台分析；启动后进入可随时退出的 Live 工作区，读取真实滚动文字与采集状态，结束后再交给现有 canonical pipeline 收尾。实时要点模型尚未接入运行时，为避免与 ASR 抢占资源，当前明确在停止后统一提炼。
- Browser-assisted 音频尚未在当前 AMD/PipeWire 主机上证明可靠静音捕获；能力不足时必须请用户保持来源窗口，不会自动播放、抓取全系统音频或切换捕获方式。
- Companion 私有 tailnet 原型已实现应用内配对、URL/小文件发送、进度、安全轻量 review、evidence 回听和人物确认；真实 iPhone 15 Pro 与 X Ultra 的 Tailscale Serve transport 仍为 **NOT TESTED**，默认关闭且不使用 Funnel。传输原型存在不代表已经获得企业部署批准。
- 跨会议序列比较、主题演进和部门知识交付。
- 新 embedding、reranker、模型替换和视觉疑难页路由。
- 由历史材料生成汇报演练辅助；必须保持证据、反例、时效和人工确认，不能固化人物画像。

## 当前边界

- 当前是单机或受控网络部署，不是正式多人生产系统；没有完整 SSO、会议级 ACL、配额和租户隔离。
- 默认本地优先，不静默上云；远端 provider 必须由管理员显式配置并承担合规责任。
- 模型变化快，模型输出不是事实真源；人工身份、canonical 逐字稿和 evidence linkage 必须保持独立。
- Live 期间的 `.live/` 是可恢复中间层，不是 canonical 事实源，不进入 Git、MeetingPack、KB 或应用发布包。
- 会议场景验证强于视频和跨会议 RAG；尚未证明所有模型、硬件和内容类型都能等价替换。
- 下游知识库负责分块、索引、检索和问答，但不是 canonical 真源，不能反写会议事实。

## 当前三个优先事项

1. 用固定问题集评测 RAG 的召回、引用和删除/stale 行为。
2. 记录逐字稿修正到新纪要的真实耗时，确认快速同步的收益与失败边界。
3. 用少量受控用户验证 MeetingPack、AI Context 和 KB projection 分别解决了什么交付任务。

## 未来 30 天

- 建立不含内部数据的会议、视频和知识投影测试矩阵。
- 完成 RAG 基线：关键词、dense、reranker、引用正确率和无答案拒答。
- 收集快速同步的阶段耗时与资源数据，暂不建设复杂局部增量缓存。
- 用一条管理层主旅程和一条技术评审主旅程演示，不遍历全部功能。
- 明确受控试点所需的身份、ACL、存储生命周期和支持责任。

## 暂不推进

- 为追逐榜单频繁替换新模型。
- 通用多 Agent 平台或第二套 NotebookLM。
- 没有真实用户和反例约束的跨会议人物画像。
- 未验证的新业务场景、公开互联网大规模爬取或正式多人服务。

## 待决策事项

- 第一批试点更适合个人本地工具、团队共享设备，还是受控部门服务。
- RAG 成功标准优先采用证据召回、答案正确、引用可回跳还是节省时间。
- 哪些导出需要长期兼容保证，哪些只保留为高级接口。

## 当前开放风险

开放风险及 Owner、检查时间见 [RISKS.md](RISKS.md)，本文件不复制风险详情。

## v0.16.0 验证索引

逐能力证据、Hosted CI、真机缺口与公开表述见 [v0.16.0 Reality Matrix](releases/v0.16.0-reality-matrix.md)。
