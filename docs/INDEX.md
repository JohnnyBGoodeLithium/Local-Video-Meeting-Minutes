# 文档导航

本文只负责把读者路由到唯一权威文档，不保存产品正文。完整实施历史以 Git 为准。

> `archive/`、完整历史 CHANGELOG、完整功能表、工程事故全文和实验日志都不属于默认阅读。只有任务确实需要时才打开目标章节。

| 使用场景 | 默认读取 |
|---|---|
| 管理层或跨职能汇报 | [管理层摘要](reporting/EXECUTIVE_BRIEF.md) + [当前状态](STATUS.md) |
| 技术评审 | [技术摘要](reporting/TECHNICAL_BRIEF.md) + [架构](ARCHITECTURE.md) |
| 产品范围和用户旅程 | [当前状态](STATUS.md) + [产品说明](PRODUCT.md) |
| UX 修改 | [当前状态](STATUS.md) + [UX 合同](UX.md) |
| 处理、失败和恢复 | [当前状态](STATUS.md) + [处理与恢复 runbook](runbooks/PROCESSING_AND_RECOVERY.md) |
| 部署、模型和本机维护 | [运维入口](OPERATIONS.md) + 对应 [runbook](runbooks/DEPLOYMENT.md) / [模型参考](reference/MODELS.md) |
| RAG / 知识库 | [当前状态](STATUS.md) + [知识与 RAG 合同](KNOWLEDGE_RAG.md) |
| 功能盘点 | [产品功能表](PRODUCT_FUNCTIONS.md) |
| 版本发布与应用分发 | [当前状态](STATUS.md) + [版本摘要](../CHANGELOG.md) + [发布规范](runbooks/RELEASES.md) + [分发与发布包](runbooks/DISTRIBUTION.md) |
| 历史事故 | [工程变化](history/ENGINEERING_CHANGES.md) 的目标章节 |
| 研究实验 | [实验记录](research/EXPERIMENT_LOG.md) 的目标章节 |
| Coding agent | [AGENTS.md](../AGENTS.md) + [当前状态](STATUS.md) + 本文 + 一份目标文档 |

## 权威位置

| 事实 | 唯一真源 |
|---|---|
| 产品版本 | [`VERSION`](../VERSION) |
| 当前 Git | `git log -1` |
| 当前状态和近期优先级 | [STATUS.md](STATUS.md) |
| 长期产品定位 | [PRODUCT.md](PRODUCT.md) |
| 功能是否存在 | [PRODUCT_FUNCTIONS.md](PRODUCT_FUNCTIONS.md) + 代码 |
| 数据、schema 与 provider 边界 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 稳定 UX 原则 | [UX.md](UX.md) |
| 运维 | [OPERATIONS.md](OPERATIONS.md) / [部署 runbook](runbooks/DEPLOYMENT.md) |
| 知识库与 RAG 合同 | [KNOWLEDGE_RAG.md](KNOWLEDGE_RAG.md) |
| 开放风险 | [RISKS.md](RISKS.md) |
| 版本用户变化 | [CHANGELOG.md](../CHANGELOG.md) |
| 应用分发与发布包 | [DISTRIBUTION.md](runbooks/DISTRIBUTION.md) |
| 重大工程事故 | [ENGINEERING_CHANGES.md](history/ENGINEERING_CHANGES.md) |
| 实验结果 | [EXPERIMENT_LOG.md](research/EXPERIMENT_LOG.md) |

## 默认上下文预算

普通 coding task 默认只读 `AGENTS.md + STATUS.md + INDEX.md + 一份任务文档`，目标不超过约 8,000 tokens。不要为寻找“现在做到哪里”同时读取 README、HANDOFF、NEXT_PLAN 和完整 CHANGELOG；当前状态只看 STATUS。
