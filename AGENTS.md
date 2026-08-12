# AGENTS.md

本文件适用于整个仓库，供 Codex、Kimi 和其他代码代理维护项目时读取。

## 沟通与目标

- 默认使用中文回复和维护面向用户的中文文案。
- 产品第一优先级是“打开已经处理好的会议进行阅读、追问和修正”；导入速度服务于这一目标。
- Meeting Identity Core、证据 linkage、多模态 Focus 和无需模型的 MeetingPack 是核心能力，改动不得把它们降级为普通转写摘要工具。

## 隐私边界

- 未经用户对当前任务明确授权，不读取或输出 `recordings/`、`meetings/`、`speaker_bank/`、`evaluations/`、`web/jobs/` 中的正文、姓名、组织关系、声纹或媒体。
- 允许只读代码、公开文档和不含正文的数量/时长/文件大小等元数据；日志仍不得打印提示词、逐字稿或模型正文。
- 不把真实会议、人员、组织架构、评测事件、凭据或绝对私有路径加入 Git、测试夹具和 issue/PR 描述。
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
- NVIDIA 与 AMD 使用不同 PyTorch/llama.cpp 构建产物；不要把厂商运行时写进通用 Python 依赖。
- 不覆盖用户未提交的无关改动，不使用破坏性 Git 命令，不以 `git add -f` 绕过私有数据 ignore。

## 修改时同步的文档

- 用户旅程或产品信息架构变化：更新 `docs/PRODUCT_UX.md`。
- pipeline、schema、数据流或模块边界变化：更新 `docs/ARCHITECTURE.md`。
- 导出、evidence、action 或 RAG 记录变化：更新 `docs/EXPORT_AND_RAG.md`。
- 模型、显卡、环境变量或安装方式变化：更新 `docs/DEPLOYMENT.md` 和 `docs/MODELS.md`。
- 重要功能或修复：更新 `CHANGELOG.md`。Git 提交仍是完整历史真源。
- README 只保留稳定入口、结构和文档地图，不复制每份深度文档的全部细节。

## 验证门槛

- Python/JS、prompt 或业务逻辑改动：`make check`。
- Web API、浏览器交互或 MeetingPack 改动：再运行 `make smoke`。
- GPU 兼容改动：运行 `make doctor` 和 `web/tests/hardware_test.py`；有目标机器时按 `docs/DEPLOYMENT.md` 的 NVIDIA/AMD 矩阵记录 backend、dtype、峰值显存和阶段耗时。
- 新测试只能使用临时目录与虚构名称/文本；不得枚举默认真实数据根。
- 提交前运行 `git diff --check`，确认 `git status --short` 中没有私有目录或无关文件。
