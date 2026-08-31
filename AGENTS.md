# Agent 工程规则

本文件定义代码代理在本仓库工作的默认边界。当前状态只读 [docs/STATUS.md](docs/STATUS.md)，完整实现仍以代码与 Git 为准。

## 默认阅读顺序与上下文预算

普通任务默认只读取：

1. `AGENTS.md`
2. `docs/STATUS.md`
3. `docs/INDEX.md`
4. 与当前任务唯一相关的一份专项文档

按任务选择专项文档：

- 产品范围：`docs/PRODUCT.md`
- UX：`docs/UX.md`
- 数据、schema、canonical、provider：`docs/ARCHITECTURE.md`
- 处理与恢复：`docs/runbooks/PROCESSING_AND_RECOVERY.md`
- 部署和模型：`docs/OPERATIONS.md` + 对应 runbook/reference
- RAG / 知识库：`docs/KNOWLEDGE_RAG.md`
- 功能盘点：`docs/PRODUCT_FUNCTIONS.md`
- 发布：`CHANGELOG.md` + `docs/runbooks/RELEASES.md`
- 汇报：`docs/reporting/` 的目标文件
- 历史事故或实验：只读 `docs/history/` 或 `docs/research/` 的目标章节

默认文档上下文目标不超过约 8,000 tokens。若任务确实需要超过，先说明原因。默认禁止读取 `docs/archive/`、完整历史 CHANGELOG/HANDOFF、`ENGINEERING_CHANGES.md` 全文、`PRODUCT_FUNCTIONS.md` 全表、`EXPERIMENT_LOG.md` 全文及与任务无关的 reporting/deployment/model/RAG 文档。不得为了寻找当前状态同时读取 README、HANDOFF、STATUS、NEXT_PLAN 和完整 CHANGELOG。

## 语言与公开仓库边界

- 仓库文档以中文为主；用户明确要求的对外材料按目标语言。公开 reporting 的双语内容必须同批更新。
- 不提交真实人员、会议标题、组织关系、客户或内部业务正文、逐字稿、截图、声纹、用户情绪/个人处境、本机绝对路径、原始 URL query、凭据或模型私有输出。
- 公开测试只使用抽象角色和虚构资料。个性化汇报进入 ignored `private_reports/`，不得 `git add -f`。
- 真实会议数据只在用户明确授权的目标范围内诊断；不把诊断内容复制进文档、测试或提交信息。

## Canonical、证据与写入

- 媒体母版、`transcript.spk.json`、人工 identity、`minutes.md` / evidence 与事实层的边界以 `docs/ARCHITECTURE.md` 为准。
- 模型输出是候选，不是事实真源。人工确认身份不得被自动相似扩展静默覆盖。
- 页面画面只能证明“展示了什么”，不能单独把数字、方案或建议写成会议决定。
- Viewer、AI Context、KB、RAG、翻译、脉络和索引是 revision-bound projection；下游知识库不得反写 canonical。
- 高价值写入校验路径、revision 和恢复边界；覆盖人工修改、重跑 ASR、删除母版或改变隐私边界前必须显式确认。

## Provider、资源与隐私

- 业务流程依赖能力合同，不写死具体模型供应商、GPU 或操作系统；配置与回退由 provider adapter 管理。
- 默认本地优先，不静默上云，不静默切换模型或高质量恢复路径。远端端点必须由管理员显式配置并符合政策。
- 资源问题优先等待、卸载空闲模型或从检查点恢复；不能通过无限重试让主机 OOM。
- WeKnora 是受支持的下游消费方，不是 canonical 真源；凭据、数据库和真实知识数据不得进入仓库。

## 修改与验证

- 修改前检查 `git status`、当前分支和相关测试；现有变更属于用户，避免覆盖无关文件。
- 使用 `rg` 搜索；不可用时使用 `grep`/`find`。文件编辑优先 `apply_patch`，批量纯机械移动使用 `git mv`。
- 不以减少行数为目的机械拆模块。只有责任域高频变化、输入输出清楚且能独立测试时才拆分。
- 诊断请求默认只读；用户要求修复或构建时才写入。不得用 `git reset --hard` 或其他破坏性命令清理工作区。
- Commit 使用 `OpenAI Codex <codex@openai.com>`。提交正文说明用户变化、根因/边界、验证和剩余限制；可独立验证的变更及时提交，不在本地长期堆积。
- 推送前确认目标远端和公开/私有边界；对公开远端的敏感风险必须再次核对。版本发布按 `docs/runbooks/RELEASES.md` 执行。

验证按风险选择：

- Python/JS/文档变更：相关专项测试、`make check`、`git diff --check`。
- Web、路由、HTML、JS 或用户界面：再运行 `make smoke` 与相关 Headless Chromium 旅程。
- Viewer：生成虚构包并验证无服务启动、主要 DOM、播放/时间码和语言切换。
- GPU/provider：运行 `make doctor` 和目标专项测试；只有明确需要时执行真实模型测试。
- 纯文档重构且未改 UI/服务代码：无需消耗 GPU 跑完整 smoke，但最终报告必须说明。

## 文档唯一真源与更新矩阵

唯一真源见 [docs/INDEX.md](docs/INDEX.md)。同一事实不要在 README、HANDOFF、STATUS 和计划文档中重复维护。

| 变化类型 | 必须更新 | 通常不更新 |
|---|---|---|
| 重要 Bug 修复 | CHANGELOG 的 Unreleased | PRODUCT、ARCHITECTURE |
| 当前状态或近期计划 | STATUS | README、PRODUCT |
| 产品定位或非目标 | PRODUCT、相关公开汇报 | OPERATIONS |
| 核心用户旅程 | UX | ARCHITECTURE，除非数据也变化 |
| API、schema、canonical、隐私 | ARCHITECTURE | EXECUTIVE_BRIEF |
| 部署或恢复 | OPERATIONS / runbook | PRODUCT |
| RAG 实验 | EXPERIMENT_LOG / RAG_STUDY | CHANGELOG、PRODUCT_FUNCTIONS |
| 实验正式采纳 | CHANGELOG、PRODUCT_FUNCTIONS、相关合同 | 无关文档 |
| 当前风险变化 | RISKS、STATUS 摘要 | ENGINEERING_CHANGES |
| 正式发布 | VERSION、CHANGELOG、STATUS | 其他文档按实际合同变化更新 |

不要因为一个小功能机械更新七八份文档。功能表按能力组织，CHANGELOG 按时间组织，Git 保存完整逐行历史。
