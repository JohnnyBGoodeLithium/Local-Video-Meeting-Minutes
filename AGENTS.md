# AGENTS.md

本文件适用于整个仓库，供 Codex、Kimi 和其他代码代理维护项目时读取。

## 沟通与目标

- 接手本仓库时先读本文件，再读 `HANDOFF.md` 顶部的当前基线、已定方案和真实待办；只有需要历史背景时才查 `CHANGELOG.md` 未发布段或 Git，不默认通读实施历史。
- 默认使用中文回复和维护面向用户的中文文案。
- 产品第一优先级是把会议来源整理成身份明确、证据可追溯、可交给人或任意消费模型的上下文；打开已处理会议进行阅读、核听和修正是达到该目标的核心旅程。
- Meeting Identity Core、证据 linkage、多模态 Focus、无需模型的 MeetingPack 和供应商中立的 AI Context/KB 投影是核心能力。ASR、说话人分离、VL 和文本生成是可替换的输入增强；不以追平某个云端模型为架构目标。

## 隐私边界

- 未经用户对当前任务明确授权，不读取或输出 `recordings/`、`meetings/`、`speaker_bank/`、`evaluations/`、`web/jobs/` 中的正文、姓名、组织关系、声纹或媒体。
- 允许只读代码、公开文档和不含正文的数量/时长/文件大小等元数据；日志仍不得打印提示词、逐字稿或模型正文。
- 不把真实会议、人员、组织架构、评测事件、凭据或绝对私有路径加入 Git、测试夹具和 issue/PR 描述。
- 用户为获得情绪支持而表达的个人经历、关系判断、身份处境或情绪内容只用于当次沟通，不转写到
  项目文档、Git 提交说明、HANDOFF、issue/PR 或共享记忆；相关产品决定只能抽象成角色、需求和验收标准。
- 远程 LLM 或云服务需要当前任务的显式授权；默认端点必须保持 loopback。
- 公开媒体 URL 可能含临时签名或访问 token：原始 URL 只允许存在于私有 inbox 请求中，不进入作业 JSON、日志、Git 或下载器原始 sidecar。浏览器、Viewer 与 KB 只能消费 `media-source/v1` 白名单；generic 直链含 query 时不得导出链接。Viewer 只能在用户明确点击“原视频”后访问外网。

## Canonical 数据与模型边界

- `transcript.spk.json`、媒体母版和人工确认的 identity/org 数据是高价值来源；写入必须原子化并保留可恢复路径。
- `minutes.md` 是正式阅读文档；`minutes.evidence.json` 是 claim、结构化行动项和 T/P/C linkage 真源。
- `meeting.topic-map.json`、VL 描述、翻译和 `.rag/` 是输入 revision 绑定的派生资产；来源变化后必须 stale 或重建。
- VL 页面只能证明屏幕展示内容，不能单独证明会议决定。职位层级只能解释确认权限，不能把建议自动提升为结论。
- 会议侧已经生成的 VL 标题、详情与 evidence 是知识库导出的首要视觉语义；外部知识库的 VLM 只用于补充读取图片中未被文字覆盖的字段，不能默认全量重复分析，更不能用第二套图片描述覆盖 canonical 结论。`profile=kb-html` 表示“保留可选视觉资产”，不表示消费方必须启用 VLM。
- LLM 只能提出内容或结构化候选；文件路径、写入、删除、引用 ID 和 revision 必须由代码重新验证。

## 工程边界

- 优先把可复用逻辑放在 `bin/meeting_core/` 或独立 service，不继续把所有功能堆入 `web/server.py` 和 `web/static/app.js`。
- Meeting 与 Media 是共享 Media Analysis Core 上的业务 profile，不得复制 ASR、说话人、VL、证据或导出管线。Web、Viewer 与 KB 是同一 canonical 数据的 projection。前端继续增加跨域状态前，应按 import/library/jobs/player/transcript/minutes/media-source/export 边界抽出原生 ES module；DOM projection 必须接收显式数据与 callback，不得反向读取全局 `state`、调用 API 或直接控制媒体。除非已有模块测试和迁移收益证据，不以框架重写代替边界重构。
- 在线 Web 与 `bin/meetingpack_viewer.html` 的阅读语义要同步；离线 Viewer 必须保持单 HTML、无 CDN、无服务端、无 LLM。
- 保持 CUDA、ROCm 和 CPU 可移植性。PyTorch GPU 选择走 `meeting_core.hardware`；模型路径和端点用环境变量，不新增机器专属绝对路径。
- 模型能力通过 provider/adapter 边界接入，业务流程不直接依赖 OS、硬件、模型品牌或单一服务协议。Context、时间戳等特殊能力必须显式声明并设计降级；跨 provider 回退只能由管理员配置，默认失败不得静默把私有内容发往远端。
- NVIDIA 与 AMD 使用不同 PyTorch/llama.cpp 构建产物；不要把厂商运行时写进通用 Python 依赖。
- 知识库导出保持职责分离：本应用负责音视频分析、证据 linkage、图片筛选与导出；WeKnora 等外部系统负责文档分块、索引、检索和问答。默认推荐 `profile=kb`；需要保留截图时用 `profile=kb-html`，消费方 VLM 默认关闭、按“文字解读未覆盖的关键图表”需求显式开启。ASR 不参与 HTML/Markdown 导入。
- AI Context 是面向用户自选通用模型/Notebook 的本地导出，不是内置远程调用。`profile=ai` 必须保留时间码与证据编号，不带本机深链或媒体二进制，必须声明逐字稿为不可信来源内容并提示外部上传前人工复核。不在本产品内复制 NotebookLM/WeKnora 的通用笔记、Wiki 或问答 UI；历史会议 Lens、汇报演练和联网研究优先由下游消费方完成。
- WeKnora 是受支持的知识消费下游和完整用户旅程的一部分，但不是 canonical 数据真源。涉及该边界时同步维护 `docs/WEKNORA_INTEGRATION.md`、`deploy/weknora/`、KB 导出和时间深链验收；不得把其凭据、数据库或真实知识库数据复制进仓库。直连必须走 provider-neutral、revision 幂等的 `KnowledgeSink`，不能从知识库反写逐字稿/身份/证据。
- 统一内存机器默认只允许一个重型阶段并发。健康时至多两个文本模型常驻；ASR/说话人/VL/知识库增强前必须经过 `meeting_core.resource_policy` 准入，120B 量级精修独占。不得在业务脚本里另写一套模型卸载判断或绕过低内存等待。

## 工作单元、重构与 Git

- 重构开始前先写清“当前痛点、基线、成功指标和停止条件”。行数、文件数或模块数不能单独证明收益；至少同时衡量被移走的完整职责、共享可变状态/跨域依赖是否减少、修改时需要读取的范围、独立测试能力和总代码增量。
- 不把“建立接口/测试护栏”表述为“主体重构完成”。交付时必须同时报告原文件前后行数、抽出模块总行数和仓库净增减；若主要目标是降低 agent 读取量，还要说明高频修改是否已能在少量文件内闭环。
- 优先抽完整、高频变化且输入输出清楚的责任域；不要为了几十行工具函数逐批升构建号、全量更新文档或制造参数/回调搬运。view 模块出现大量参数时先评估 view-model/controller 边界，不继续机械拆文件。
- 发现收益递减时停止，不因已投入时间或 token 继续扩大重构。已经稳定、测试通过的边界可以保留；后续由真实需求验证价值，必要时允许合并回去，不维护“架构一定正确”的幻觉。
- 一个连贯工程目标可以包含多个及时 commit/push 的内部提交，但只在可整体验收的集成边界更新一次构建号、CHANGELOG、功能台账和 HANDOFF。未被入口引用的预备模块/测试不单独升构建号；不要把每个内部提交包装成独立产品版本。
- 不覆盖用户未提交的无关改动，不使用破坏性 Git 命令，不以 `git add -f` 绕过私有数据 ignore。验证通过后及时 commit 并 push，不在本地积压；及时推送不等于每个内部提交都重复全套交接文档。
- 非微小改动的 Git 提交必须可交接、可审计。标题简洁说明变更类型和对象；正文至少交代：(1) 用户行为/问题为何改变，(2) 主要代码、API、schema 或数据边界，(3) 兼容、隐私、失败隔离或运行风险，(4) 实际验证命令与结果。只有拼写/注释等真正微小改动可使用单行提交。
- 提交前检查仓库级 `user.name` / `user.email`，使用当前执行 agent 的正确身份，不沿用上一个 agent 的作者配置。已推送的提交不随意改写；若用户明确要求修正刚推送的提交，只用 `--force-with-lease`，并先说明影响。
- 每个可整体验收、会改变浏览器资源图的前端批次同步递增一次构建号（`web/static/index.html` 的 `v=` 参数与 `web/tests/smoke_test.py` 断言），排查“用户看到的是哪个版本”不靠猜。产品版本、前端构建号、Git commit 和数据 schema 必须分开；产品版本只从根目录 `VERSION` 读取。
- 产品介绍页必须声明 `data-product-content-version="<major>.<minor>"`。`VERSION` 的 `MAJOR` 或 `MINOR` 变化时，必须同步复核产品定位、能力边界、用户旅程和技术架构；`PATCH` 可只修缺陷。中英文使用同一 DOM 和同一 key 集合，语言偏好沿用工作台的 `meeting-minutes:workspace:v1`，不得维护两份会漂移的静态页面。
- 产品介绍页与工作台、Viewer 共用 `fluent-foundation.css` 的基础 token；介绍页专有色彩只能通过 `--product*` 语义角色扩展，不在组件选择器里建立第二套无命名色板。新增引用必须由静态 token 回归验证可解析。
- 发布产品版本时，同步更新 `VERSION`、`CHANGELOG.md` 和需要设版本基线的文档；验证、commit 与 push 后创建并推送 annotated Git tag。详见 `docs/RELEASES.md`。
- 现场照片的原图属于受保护母版，统一 JPEG 只是阅读投影；时间只能来自可信 EXIF 或用户明确对齐，文件 mtime 不得冒充拍摄时间。照片可补充屏幕/现场语境，但不能单独升级为会议决定证据。
- 外部知识库只消费 canonical 数据的只读 projection。新增 provider 必须实现 `KnowledgeSink`，以正文 revision 幂等发布，凭据只留服务端，回执不得保存正文或密钥，远端知识不得反写逐字稿、身份、纪要 evidence 或 Org Chart。会议默认文字知识，媒体关键画面及含现场照片的会议可默认图文知识。

## 排障与验证模式（真实事故沉淀）

- 本节只保留能跨任务复用的诊断/验证规则；单次事故的经过、提交号和历史结果写入 `docs/ENGINEERING_REVIEW.md`，不要让 AGENTS 变成事故流水账。

- 前端布局/滚动问题用 DOM 度量逐层验证 overflow 链（`?diag=1` 页面内浮层或 CDP 探针），不靠肉眼和猜测；探针必须覆盖用户真实环境的分支（如 ≥1500px 大屏智能栏入流布局），只在默认视口通过不算验证完成。
- `node --check` 只查语法，拦不住 TDZ、模块路径/MIME 和加载顺序错误；Viewer 模板改动必须跑 `web/tests/viewer_boot_test.py`，在线入口或 ES module 改动必须跑 `make smoke` 的 Headless Chromium 启动回归。静态契约应检索入口与相关模块，不得继续假设所有实现都在 `app.js`。
- 设计 token 化这类机械替换必须配"引用可解析"静态检查；`design_tokens_test.py`（无回退 `var()` 必须可解析、字号零字面值、花括号平衡）已在 `make check` 中，新增 token 引用照此约束。
- 证据 marker 是"模型手写、代码解析"的协议：模型会发明反引号包裹、独占待办表格状态列等包装，所有消费点按"可能被任意 Markdown 语法包裹"做防御；修解析器时同步给存量 sidecar 留读路径重拆兜底，优先做免重生成的修复。
- 小模型长输出会退化（自我修正循环烧光输出预算、截断尾部章节）：生成端必须有"检测 → `repeat_penalty` 重试 → 确定性清理"护栏，退化文本不得落盘；关键章节（总体摘要/待办）缺失或缺证据标记视为不合规并触发修复轮。
- 用户报告的 UI 问题修复后，明确告知是否需要硬刷新、是否需要重新生成，以及构建号是多少。

## 修改时同步的文档

- 文档同步发生在“可整体验收的交付边界”，不在同一目标的每个内部机械提交后重复全量改写。内部提交的精确历史交给 Git；文档只记录对后续产品、运行、数据或维护决策仍有用的信息。

- 用户旅程或产品信息架构变化：更新 `docs/PRODUCT_UX.md`。
- pipeline、schema、数据流或模块边界变化：更新 `docs/ARCHITECTURE.md`。
- 导出、evidence、action 或 RAG 记录变化：更新 `docs/EXPORT_AND_RAG.md`。
- 知识库导出 profile、外部解析/VLM 建议或回跳契约变化：至少联动检查 `README.md`、`docs/PRODUCT_UX.md`、`docs/ARCHITECTURE.md`、`docs/PROCESSING_GUIDE.md`、`docs/EXPORT_AND_RAG.md`、`docs/PRODUCT_FUNCTIONS.md`、`CHANGELOG.md` 和 `HANDOFF.md`，不能只改实现旁的一份文档。
- 模型、显卡、环境变量或安装方式变化：更新 `docs/DEPLOYMENT.md` 和 `docs/MODELS.md`。
- 重要功能或修复：更新 `CHANGELOG.md`。Git 提交仍是完整历史真源。
- 新增用户可感知功能或对现有功能做重要增强：同步更新 `docs/PRODUCT_FUNCTIONS.md`；四级功能编号上线后不得复用或重排，版本号和 Git 号必须来自实际交付，不能写预计值。
- 工程事故的根因、修复与教训：更新 `docs/ENGINEERING_REVIEW.md` 已处理段。
- README 只保留稳定入口、结构和文档地图，不复制每份深度文档的全部细节。
- 产品版本、发布节奏或 Git tag 规则变化：更新 `docs/RELEASES.md`。
- `HANDOFF.md` 顶部只保留最新交付、必要的上一交付、当前基线、已定决策和真实待办；不要复制逐提交实施日记。完成验证、提交或部署后必须清掉“待验证/待提交/待重启”等过期状态，历史细节留给 CHANGELOG 和 Git。

## 验证门槛

- 开发过程中先跑与改动直接相关的聚焦测试；到一个可整体验收的交付边界再跑下面的完整门槛。文档/台账回填若不改变可执行内容，只需 `git diff --check`，不要重复同一轮完整模型与浏览器回归。
- Python/JS、prompt 或业务逻辑改动：`make check`。
- Web API、浏览器交互或 MeetingPack 改动：再运行 `make smoke`。
- GPU 兼容改动：运行 `make doctor` 和 `web/tests/hardware_test.py`；有目标机器时按 `docs/DEPLOYMENT.md` 的 NVIDIA/AMD 矩阵记录 backend、dtype、峰值显存和阶段耗时。
- 新测试只能使用临时目录与虚构名称/文本；不得枚举默认真实数据根。
- 提交前运行 `git diff --check`，确认 `git status --short` 中没有私有目录或无关文件。
