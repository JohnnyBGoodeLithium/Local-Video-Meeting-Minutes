# 当前开放风险

本文只记录仍需持续管理的风险，不保存已经解决的完整事故。当前状态看 [STATUS.md](STATUS.md)，历史根因和修复看 [history/ENGINEERING_CHANGES.md](history/ENGINEERING_CHANGES.md)。

## R-001 公开仓库与私有会议数据边界

- 等级：P0
- 影响：真实姓名、会议标题、逐字稿、截图、组织关系、路径或凭据一旦进入 Git，可能造成不可逆的信息暴露。
- 触发条件：使用真实会议制作测试夹具、在文档中记录内部试用细节、误提交导出包或私有汇报。
- 当前缓解：会议数据目录、导出物和 `private_reports/` 均被忽略；公开测试使用虚构数据；提交前执行敏感内容与 tracked-file 检查。
- 仍缺少：自动化敏感信息扫描只能作为辅助，仍需人工审阅上下文和图片。
- Owner：Maintainer
- 下一次检查时间：每次发布前
- 相关文档：[ARCHITECTURE.md](ARCHITECTURE.md)、[AGENTS.md](../AGENTS.md)

## R-002 单机系统被误用为多人生产服务

- 等级：P0
- 影响：缺少 SSO、会议级 ACL、租户隔离、配额和正式备份时，共享部署可能造成越权访问、资源争抢或数据丢失。
- 触发条件：把本机端口直接暴露到不受控网络，或多人共用同一文件系统与管理员权限。
- 当前缓解：产品明确定位为单机或受控网络 PoC；默认只监听受控接口；不静默上云。
- 仍缺少：正式身份系统、授权模型、TLS、租户隔离、支持与删除责任。
- Owner：Deployment owner
- 下一次检查时间：任何共享试点之前
- 相关文档：[OPERATIONS.md](OPERATIONS.md)、[runbooks/DEPLOYMENT.md](runbooks/DEPLOYMENT.md)

## R-003 大型前端装配控制器

- 等级：P1
- 影响：`web/static/app.js` 仍承担较多状态装配和副作用，局部修改可能引发不可见的交互回归。
- 触发条件：在没有模块边界和 Headless 旅程的情况下继续加入新流程。
- 当前缓解：规则模块与 view 模块逐步分离；只按稳定责任域拆分；保留真实浏览器测试。
- 仍缺少：部分旧状态和 DOM 仍直接耦合，Viewer 也保留历史局部样式。
- Owner：Frontend maintainer
- 下一次检查时间：下一次工作台主旅程修改前
- 相关文档：[UX.md](UX.md)、[ARCHITECTURE.md](ARCHITECTURE.md)

## R-004 依赖、模型和环境可复现性

- 等级：P1
- 影响：驱动、模型格式、provider 协议或本地服务变化可能造成相同代码在不同机器上表现不一致。
- 触发条件：未经固定实验直接替换模型或运行时；只在主要开发机器验证。
- 当前缓解：provider adapter、`make doctor`、硬件选择层、模型角色文档和显式回退。
- 仍缺少：更完整的 AMD、NVIDIA、CPU 矩阵与可复现性能基线。
- Owner：Model/runtime maintainer
- 下一次检查时间：模型或运行时升级前
- 相关文档：[reference/MODELS.md](reference/MODELS.md)、[runbooks/DEPLOYMENT.md](runbooks/DEPLOYMENT.md)

## R-005 CI 与真实长会议测试覆盖不足

- 等级：P1
- 影响：单元测试通过仍可能遗漏长会议、混合语言、复杂画面、恢复和资源压力下的端到端问题。
- 触发条件：只运行快速测试，或把单个真实会议表现当作普遍质量。
- 当前缓解：`make check`、隔离 smoke、Headless Chromium 旅程与虚构 fixture；真实验证只在私有环境进行。
- 仍缺少：脱敏长会议基准、不同输入路线和多硬件的固定回归矩阵。
- Owner：Maintainer
- 下一次检查时间：每个 minor release
- 相关文档：[runbooks/DEVELOPMENT.md](runbooks/DEVELOPMENT.md)、[research/EXPERIMENT_LOG.md](research/EXPERIMENT_LOG.md)

## R-006 RAG 质量尚未形成可重复结论

- 等级：P1
- 影响：能检索不等于能正确回答；引用、拒答、stale 和删除行为未经系统评测时，不适合扩大承诺。
- 触发条件：只看单次演示，或继续堆叠 embedding、reranker 和 VLM 而没有问题集。
- 当前缓解：严格区分 canonical 与 KB projection；保留引用；模型不可用时降级；下一阶段以固定问题集为先。
- 仍缺少：召回、答案支持度、无答案拒答、删除和 revision 的量化基线。
- Owner：RAG experiment owner
- 下一次检查时间：完成首轮固定问题集后
- 相关文档：[KNOWLEDGE_RAG.md](KNOWLEDGE_RAG.md)、[research/RAG_STUDY.md](research/RAG_STUDY.md)

## R-007 知识库权限与删除闭环

- 等级：P1
- 影响：下游知识库若权限、替换或删除失败，旧 projection 可能继续被检索。
- 触发条件：provider API 漂移、远端权限变化、只删除本地回执而未删除远端文档。
- 当前缓解：服务端凭据隔离、target allowlist、revision 幂等和发布回执。
- 仍缺少：更多 provider 版本、权限组合和远端删除的受控验证。
- Owner：Knowledge integration owner
- 下一次检查时间：每次 provider 升级及共享试点前
- 相关文档：[KNOWLEDGE_RAG.md](KNOWLEDGE_RAG.md)、[runbooks/WEKNORA.md](runbooks/WEKNORA.md)

## R-008 资源竞争与异常关机

- 等级：P1
- 影响：ASR、VL、文本模型和知识增强并发可能造成内存压力、任务中断或主机不可用。
- 触发条件：多个重任务同时常驻、知识库优化与会议处理并发、资源等待缺少上限。
- 当前缓解：统一资源策略、调度优先级、检查点、有限重试和 `waiting_resource` 状态。
- 仍缺少：长期硬件遥测与不同负载组合的稳定上限；系统日志仍需与应用日志分开诊断。
- Owner：Runtime maintainer
- 下一次检查时间：每次资源策略变更后
- 相关文档：[OPERATIONS.md](OPERATIONS.md)、[runbooks/PROCESSING_AND_RECOVERY.md](runbooks/PROCESSING_AND_RECOVERY.md)

## R-009 许可证与再分发授权尚未确认

- 等级：P1
- 影响：仓库公开可见不等于获得开源、转载、再分发或商业使用授权；错误添加许可证或发布资产可能扩大法律与公司政策风险。
- 触发条件：未经代码归属与公司政策核对就添加开源许可证、对外再分发或用于商业部署。
- 当前缓解：README 明确说明当前没有开源许可证；发布流程不自动添加 license 字段或许可证文件。
- 仍缺少：Owner 对代码归属、第三方材料与公司政策的正式确认。
- Owner：Repository owner
- 下一次检查时间：第一次正式 GitHub Application Release 前
- 相关文档：[README.md](../README.md)、[SECURITY.md](../SECURITY.md)、[runbooks/DISTRIBUTION.md](runbooks/DISTRIBUTION.md)
