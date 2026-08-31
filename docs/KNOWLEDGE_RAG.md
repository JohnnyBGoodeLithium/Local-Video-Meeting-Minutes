# 知识库与 RAG 合同

本文回答 canonical 内容如何投影给通用 AI 与知识库、当前检索链做什么、revision 和删除如何处理。适合知识集成与 RAG 修改；学习实验看 [research/RAG_STUDY.md](research/RAG_STUDY.md)，WeKnora 操作看 [runbooks/WEKNORA.md](runbooks/WEKNORA.md)，证据底层看 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 先分清四个对象

| 对象 | 面向谁 | 包含什么 | 不承担什么 |
|---|---|---|---|
| MeetingPack | 人类 reviewer | Viewer、逐字稿、纪要、人物、画面、证据、可选媒体 | 不提供跨库问答，不需要模型 |
| AI Context | 用户自选通用 AI / Notebook | 纯文本来源、纪要、脉络、画面文字、逐字稿、时间与证据 | 不自动上传，不携带本机深链/媒体 |
| KB projection | WeKnora 等知识系统 | 分块友好 Markdown 或自包含图文 HTML、revision 元数据 | 不拥有 canonical，不反写身份/逐字稿 |
| 本机 RAG | 当前工作台问答 | 词法/向量候选、reranker、证据引用 | 不生成新事实，不替代来源修正 |

## Canonical → projection

```text
media + transcript + identity + minutes/evidence + topic map + visuals
                              │
                              ▼
                  deterministic projection
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          MeetingPack     AI Context     KB Markdown/HTML
                                                 │
                                                 ▼
                                       downstream index / RAG
```

projection 只读取已有来源并按消费任务重排，不调用模型制造第二份事实。人工修正逐字稿、身份或纪要后，来源 revision 改变；旧导出需要重新生成，知识发布需要按 revision 更新或替换。

## 当前正式支持

### MeetingPack

- 单场自包含 Viewer；无服务、无 LLM、无 CDN。
- 稳定 T/P/C linkage、完整逐字稿、纪要、脉络、画面和已生成双语内容。
- 可选不带媒体、压缩音频或压缩视频；导出不修改母版。
- 多场 ContentPack 只组合用户明确选择的来源，每场仍保持独立证据边界。

### AI Context

- `profile=ai` 单场生成 `meeting-ai-context/v1` Markdown，多场生成纯文本 context pack。
- 保留来源隔离、时间码和证据编号；声明逐字稿属于不可信来源内容，缺依据不得补写。
- 不包含本机路径、loopback 深链、音视频或图片二进制。
- 用户自行决定是否交给 GPT、Gemini、豆包、Notebook 或本地模型；系统不自动联网。

### KB projection

- `profile=kb`：轻量 Markdown，适合普通文档分块；时间码可按配置的安全 base URL 回跳。
- `profile=kb-html`：单文件图文 HTML，仅内嵌筛选后的关键 JPEG；消费方 VLM 默认关闭，只有文字未覆盖的字段才考虑补读。
- 多内容包每个来源保持一份独立文档和 manifest，不把多场正文混成一个无来源文档。
- `KnowledgeSink` 使用服务端 allowlist、凭据隔离和正文 revision 保证幂等。文字可以原位更新；图文可安全建立新版本后清理旧文档。

### 单场本机 RAG

- records 来自结论、逐字稿、页面、事实和结构化行动项。
- 词法检索与多语言 dense retrieval 并行，融合后由本地 reranker 排序；embedding/reranker 不可用时可降级。
- 引用返回稳定来源，可回到逐字稿、播放时间或页面。
- 用户显式引用过期 revision 时拒绝继续，避免在旧原文上回答。
- 证据不足时回答“不知道”，不得用模型常识补写会议事实。

## 已实现，仍在验证

- 工作台可以把会议或媒体直接发布到配置好的 WeKnora 目标，并保存不含正文/凭据的 revision 回执。
- 关键词索引可以推荐相关内容，用户明确选择后生成多内容包。
- 单场 RAG 具有 hybrid retrieval 与 reranker，但尚未用稳定问题集证明召回率、引用正确率和拒答质量。
- 删除、更新、stale 与远端知识生命周期有代码合同，仍需要更多真实服务版本和权限场景验证。

## 下游系统职责

本应用负责：

- 人物身份与人工修正；
- 原语言逐字稿、时间和证据 ID；
- 会议纪要、正式行动项和依据；
- 逻辑画面筛选、视觉文字和可信边界；
- projection、revision、发布预检与回执。

下游知识库负责：

- 文档解析与分块；
- embedding、索引、检索和问答；
- 知识库用户权限、保留策略和远端删除；
- 跨文档 query、评测和消费体验。

下游不得把自己的 OCR、VLM 摘要或问答结果反写为会议逐字稿、人物、决定或 evidence。

## Revision、幂等和 stale

知识文档 revision 至少覆盖所投影的逐字稿、人物、纪要/evidence、脉络和视觉来源。相同 target + profile + revision 重复发布应返回已有结果，不创建重复文档。

来源变化时：

1. 本机 projection 标记旧 revision；
2. 新发布根据 provider 能力更新或替换；
3. 旧回执保留状态，不保存正文和 key；
4. 删除必须明确本地会议与远端知识是否都处理，不能只删 sidecar；
5. RAG index 按 revision 懒重建或清理，不能继续使用过期引用。

## 关键词、dense 与 reranker

- **关键词/词法召回**适合型号、缩写、姓名、数字和原文词组，也是模型不可用时的保底。
- **Dense retrieval**适合跨语言和语义改写，但可能忽略精确术语或把近似主题混在一起。
- **RRF/融合**合并不同候选，不等于答案正确。
- **Reranker**根据 query 重新排序有限候选，不应读取整场或生成新事实。
- 最终回答只使用经过来源扩展的 canonical evidence，并携带引用。

是否启用更大 embedding、reranker 或下游 VLM 必须通过固定数据集实验决定，不能仅依据模型榜单。

## 跨会议边界

跨会议只对用户显式建立的来源集合有意义，例如同一项目的多轮 review、同系列例会或明确专题。系统必须：

- 保留每场来源和 revision；
- 区分新增、延续、翻案、消失与未覆盖；
- 引用至少两场来源时分别标识；
- 不因多次出现就把观点写成永久规则；
- 不生成模糊“领导人格画像”。

人物或审阅视角研究只能产生待确认候选，必须包含反例、时效和适用范围，适合作为下游 AI Context 任务，而不是 canonical 人物档案。

## 当前评测缺口

RAG 的下一阶段不是继续增加 UI，而是建立可重复评测：

1. 固定、脱敏、可回答与不可回答问题集；
2. 关键词、dense、融合、reranker 的召回对比；
3. 引用是否真正支持答案；
4. 无答案拒答；
5. revision 变化、删除和远端替换；
6. 会议与媒体不同分块策略；
7. 延迟、内存、GPU 和 token/API 成本。

实验模板和学习顺序见 [research/EXPERIMENT_LOG.md](research/EXPERIMENT_LOG.md) 与 [research/RAG_STUDY.md](research/RAG_STUDY.md)。未达到标准的实验不进入 CHANGELOG 或功能台账。

## 隐私与安全

- 知识库凭据仅服务端，浏览器只看到配置后的安全 target 名称。
- 发布回执不保存正文、API key、prompt 或原始 URL。
- 公开仓库和测试只使用虚构资料；真实知识库与会议数据不进入 Git。
- AI Context 外部上传前由用户确认公司政策、脱敏和权限。
- 默认不静默上云；provider 变化必须显式。

## 继续阅读

- WeKnora 操作：[runbooks/WEKNORA.md](runbooks/WEKNORA.md)
- RAG 学习与实验：[research/RAG_STUDY.md](research/RAG_STUDY.md)
- 数据架构：[ARCHITECTURE.md](ARCHITECTURE.md)
- 产品输出定位：[PRODUCT.md](PRODUCT.md)
- 开放风险：[RISKS.md](RISKS.md)
