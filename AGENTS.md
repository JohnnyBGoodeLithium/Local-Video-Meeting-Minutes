# AGENTS.md

本文件适用于整个仓库，供 Codex、Kimi 和其他代码代理维护项目时读取。

## 沟通与目标

- 接手本仓库时先读 `HANDOFF.md`（当前基线、进行中任务和已定方案），再读本文件与 `CHANGELOG.md` 未发布段。
- 默认使用中文回复和维护面向用户的中文文案。
- 产品第一优先级是“打开已经处理好的会议进行阅读、追问和修正”；导入速度服务于这一目标。
- Meeting Identity Core、证据 linkage、多模态 Focus 和无需模型的 MeetingPack 是核心能力，改动不得把它们降级为普通转写摘要工具。

## 隐私边界

- 未经用户对当前任务明确授权，不读取或输出 `recordings/`、`meetings/`、`speaker_bank/`、`evaluations/`、`web/jobs/` 中的正文、姓名、组织关系、声纹或媒体。
- 允许只读代码、公开文档和不含正文的数量/时长/文件大小等元数据；日志仍不得打印提示词、逐字稿或模型正文。
- 不把真实会议、人员、组织架构、评测事件、凭据或绝对私有路径加入 Git、测试夹具和 issue/PR 描述。
- 用户为获得情绪支持而表达的个人经历、关系判断、身份处境或情绪内容只用于当次沟通，不转写到
  项目文档、Git 提交说明、HANDOFF、issue/PR 或共享记忆；相关产品决定只能抽象成角色、需求和验收标准。
- 远程 LLM 或云服务需要当前任务的显式授权；默认端点必须保持 loopback。

## Canonical 数据与模型边界

- `transcript.spk.json`、媒体母版和人工确认的 identity/org 数据是高价值来源；写入必须原子化并保留可恢复路径。
- `minutes.md` 是正式阅读文档；`minutes.evidence.json` 是 claim、结构化行动项和 T/P/C linkage 真源。
- `meeting.topic-map.json`、VL 描述、翻译和 `.rag/` 是输入 revision 绑定的派生资产；来源变化后必须 stale 或重建。
- VL 页面只能证明屏幕展示内容，不能单独证明会议决定。职位层级只能解释确认权限，不能把建议自动提升为结论。
- LLM 只能提出内容或结构化候选；文件路径、写入、删除、引用 ID 和 revision 必须由代码重新验证。

## 工程边界

- 优先把可复用逻辑放在 `bin/meeting_core/` 或独立 service，不继续把所有功能堆入 `web/server.py` 和 `web/static/app.js`。
- 在线 Web 与 `bin/meetingpack_viewer.html` 的阅读语义要同步；离线 Viewer 必须保持单 HTML、无 CDN、无服务端、无 LLM。
- 保持 CUDA、ROCm 和 CPU 可移植性。PyTorch GPU 选择走 `meeting_core.hardware`；模型路径和端点用环境变量，不新增机器专属绝对路径。
- 模型能力通过 provider/adapter 边界接入，业务流程不直接依赖 OS、硬件、模型品牌或单一服务协议。Context、时间戳等特殊能力必须显式声明并设计降级；跨 provider 回退只能由管理员配置，默认失败不得静默把私有内容发往远端。
- NVIDIA 与 AMD 使用不同 PyTorch/llama.cpp 构建产物；不要把厂商运行时写进通用 Python 依赖。
- 不覆盖用户未提交的无关改动，不使用破坏性 Git 命令，不以 `git add -f` 绕过私有数据 ignore。
- 功能验证通过后及时 commit 并 push，不在本地积压未推送提交。
- 非微小改动的 Git 提交必须是可交接、可审计的完整记录，不得只写一句空泛标题。标题简洁说明变更类型和对象；正文至少交代：(1) 用户行为/问题为何改变，(2) 主要代码、API、schema 或数据边界，(3) 兼容、隐私、失败隔离或运行风险，(4) 实际执行的验证命令与结果。只有拼写/注释等真正微小改动可使用单行提交。
- 提交前检查仓库级 `user.name` / `user.email`，使用当前执行 agent 的正确身份，不沿用上一个 agent 的作者配置。已推送的提交不随意改写；若用户明确要求修正刚推送的提交，只用 `--force-with-lease`，并先说明影响。
- 每批用户可见改动同步递增前端构建号（`web/static/index.html` 的 `v=` 参数与 `web/tests/smoke_test.py` 断言），排查"用户看到的是哪个版本"不靠猜。
- 产品版本、前端构建号、Git commit 和数据 schema 必须分开。产品版本只从根目录 `VERSION` 读取；普通提交不升版，一个可验收发布可包含多个工程提交。
- 发布产品版本时，同步更新 `VERSION`、`CHANGELOG.md` 和需要设版本基线的文档；验证、commit 与 push 后创建并推送 annotated Git tag。详见 `docs/RELEASES.md`。

## 排障与验证模式（真实事故沉淀）

- 前端布局/滚动问题用 DOM 度量逐层验证 overflow 链（`?diag=1` 页面内浮层或 CDP 探针），不靠肉眼和猜测；探针必须覆盖用户真实环境的分支（如 ≥1500px 大屏智能栏入流布局），只在默认视口通过不算验证完成。
- `node --check` 只查语法，拦不住 TDZ 类运行时错误；Viewer 模板或前端初始化顺序改动必须跑无头浏览器启动回归（`web/tests/viewer_boot_test.py`）。
- 设计 token 化这类机械替换必须配"引用可解析"静态检查；`design_tokens_test.py`（无回退 `var()` 必须可解析、字号零字面值、花括号平衡）已在 `make check` 中，新增 token 引用照此约束。
- 证据 marker 是"模型手写、代码解析"的协议：模型会发明反引号包裹、独占待办表格状态列等包装，所有消费点按"可能被任意 Markdown 语法包裹"做防御；修解析器时同步给存量 sidecar 留读路径重拆兜底，优先做免重生成的修复。
- 小模型长输出会退化（自我修正循环烧光输出预算、截断尾部章节）：生成端必须有"检测 → `repeat_penalty` 重试 → 确定性清理"护栏，退化文本不得落盘；关键章节（总体摘要/待办）缺失或缺证据标记视为不合规并触发修复轮。
- 用户报告的 UI 问题修复后，明确告知是否需要硬刷新、是否需要重新生成，以及构建号是多少。

## 修改时同步的文档

- 用户旅程或产品信息架构变化：更新 `docs/PRODUCT_UX.md`。
- pipeline、schema、数据流或模块边界变化：更新 `docs/ARCHITECTURE.md`。
- 导出、evidence、action 或 RAG 记录变化：更新 `docs/EXPORT_AND_RAG.md`。
- 模型、显卡、环境变量或安装方式变化：更新 `docs/DEPLOYMENT.md` 和 `docs/MODELS.md`。
- 重要功能或修复：更新 `CHANGELOG.md`。Git 提交仍是完整历史真源。
- 新增用户可感知功能或对现有功能做重要增强：同步更新 `docs/PRODUCT_FUNCTIONS.md`；四级功能编号上线后不得复用或重排，版本号和 Git 号必须来自实际交付，不能写预计值。
- 工程事故的根因、修复与教训：更新 `docs/ENGINEERING_REVIEW.md` 已处理段。
- README 只保留稳定入口、结构和文档地图，不复制每份深度文档的全部细节。
- 产品版本、发布节奏或 Git tag 规则变化：更新 `docs/RELEASES.md`。

## 验证门槛

- Python/JS、prompt 或业务逻辑改动：`make check`。
- Web API、浏览器交互或 MeetingPack 改动：再运行 `make smoke`。
- GPU 兼容改动：运行 `make doctor` 和 `web/tests/hardware_test.py`；有目标机器时按 `docs/DEPLOYMENT.md` 的 NVIDIA/AMD 矩阵记录 backend、dtype、峰值显存和阶段耗时。
- 新测试只能使用临时目录与虚构名称/文本；不得枚举默认真实数据根。
- 提交前运行 `git diff --check`，确认 `git status --short` 中没有私有目录或无关文件。
