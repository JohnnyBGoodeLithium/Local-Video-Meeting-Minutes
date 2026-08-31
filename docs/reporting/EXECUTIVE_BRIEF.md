# Local AI Meeting & Video Knowledge Workflow

- Prepared date: 2026-08-31
- Product version: v0.15.1
- Source Git commit: `c47d3a0`
- Source status date: 2026-08-31
- Classification: Public-safe project brief

## English

### Context

Knowledge-heavy teams spend significant time replaying meetings, identifying who said what, reconciling imperfect transcripts, and converting first-hand material into documents that others can reuse. Cloud tools may solve part of the problem, but internal content often requires a controlled local workflow.

### Business problem

The difficult part is not producing another summary. It is preserving identity, evidence, corrections, and handoff: a reviewer must be able to find the relevant person, hear the original words, inspect the screen shown at that moment, correct an error, and distribute a result without rebuilding context manually.

### Current solution

This controlled PoC runs a local multi-stage workflow for meetings and high-information videos. It connects transcript, speaker identity, shared visuals, minutes, and evidence on one timeline, then projects the same source into an offline MeetingPack, portable AI Context, or a knowledge-base document. Model components can change without making a model output the permanent source of truth.

### Evidence of use

Meeting review and speaker-focused listening have been used in a real internal pilot. Feedback from that use has directly changed the navigation, transcript correction, progress, recovery, and export experience. Public documentation intentionally excludes identifiable people, meetings, and business content.

### Why it matters

The workflow can reduce repeated listening and manual repackaging while demonstrating a practical local-AI workload for capable edge devices. Its durable value is the evidence-linked context layer—not a claim that one model can replace established meeting or knowledge products.

### Current boundaries

- Meeting review: **Validated** in a controlled internal setting.
- Video understanding: **Working PoC** with an incomplete content-quality matrix.
- Personal or team KB / RAG: **Early validation**; retrieval evaluation and governance are not complete.
- Deployment: single machine or controlled environment, without production SSO, ACL, tenancy, or support operations.

### Next step

Measure retrieval quality with a fixed question set, measure the time saved by fast transcript-to-minutes synchronization, and run a small controlled pilot around clearly defined handoff tasks.

### Feedback requested

Which first user group and workflow would create the strongest evidence: individual review, a shared local meeting device, or a controlled team knowledge handoff?

## 中文

### 背景

信息密集型团队需要花大量时间回听会议、确认谁说了什么、修正不准确的逐字稿，并把第一手材料重新整理成他人可以继续使用的文档。云端工具可以解决部分问题，但内部内容往往需要受控的本地工作流。

### 业务问题

真正困难的不是再生成一份摘要，而是保留身份、证据、修正和交付关系：复核者应该能找到相关人物、听到原话、看到当时画面、修正错误，并在不重新手工拼装上下文的情况下分发结果。

### 当前方案

这个受控 PoC 为会议和高信息密度视频提供本地多阶段工作流，把逐字稿、人物身份、共享画面、纪要和证据连接在同一时间线上，再将同一来源投影为离线 MeetingPack、可移植 AI Context 或知识库文档。模型组件可以变化，但模型输出不会成为永久事实真源。

### 使用验证

会议回顾和按人物核听已经在真实内部试用中使用。真实反馈直接推动了导航、逐字稿修正、处理进度、失败恢复和导出体验的迭代。公开文档主动排除可识别人员、会议和业务正文。

### 战略意义

该工作流有机会减少重复回听与手工搬运，也能展示高能力边缘设备上的实际 Local AI 工作负载。它的长期价值是可回证的上下文层，而不是宣称一个模型可以替代成熟会议或知识产品。

### 当前边界

- 会议回顾：受控内部场景中**已真实验证**。
- 视频理解：**工作原型**，内容质量矩阵仍不完整。
- 个人或团队 KB / RAG：**早期验证**，检索评测和治理尚未完成。
- 部署：单机或受控环境，没有生产级 SSO、ACL、租户和支持体系。

### 下一步

用固定问题集评测检索质量，测量逐字稿快速同步纪要节省的等待时间，并围绕明确的交付任务进行小规模受控试点。

### 希望获得的反馈

哪类首批用户与旅程最容易形成强证据：个人回顾、共享本地会议设备，还是受控团队知识交付？
