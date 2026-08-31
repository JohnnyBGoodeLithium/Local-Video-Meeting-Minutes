# Local Video Meeting Minutes

## English summary

Local Video Meeting Minutes is a local-first workflow for turning meetings and first-party videos into evidence-linked, reusable context. It combines configurable speech recognition, speaker separation, visual understanding, and text generation while keeping the transcript, confirmed identities, revisions, and source links independent from any single model. Users can review who said what, return from a claim to the original audio or screen, correct source material, and export an offline MeetingPack, portable AI Context, or knowledge-base projection. Providers can run locally or through explicitly approved endpoints; the system never silently changes the privacy boundary. The current release is a controlled, single-machine proof of concept—not a production multi-user service—and meeting review is more validated than video analysis or cross-content RAG.

## 中文摘要

Local Video Meeting Minutes 是一个本地优先的会议与第一手视频上下文工作流。它把语音识别、人物区分、画面理解和纪要生成连接起来，但不把任何单一模型的输出直接当作事实真源。用户可以按人物核听，修正逐字稿与身份，从结论回到原声和画面，并把同一份可信来源交付为离线 MeetingPack、可交给通用 AI 的 AI Context，或知识库投影。系统默认在本机处理，远端 provider 必须显式配置，不会静默改变隐私边界。当前版本是单机受控 PoC：会议回顾主旅程已有真实验证，视频理解和跨内容 RAG 仍在持续评测，不是正式多人生产服务。

## 当前产品定位

- **Identity**：把“谁说了什么”变成可核听、可人工确认、可撤销的身份上下文。
- **Evidence**：纪要结论绑定逐字稿、原声和画面，页面内容不能单独证明会议决定。
- **Multimodal Review**：先让逐字稿和语音草稿可用，再补充共享画面、现场资料与正式纪要。
- **Portable Context**：以 MeetingPack、AI Context 和 KB projection 交给人、通用 AI 或知识库继续消费。

这不是 Teams 替代品、第二套 NotebookLM、通用多 Agent 平台，也不承诺无需人工核对的全自动结论。

## 当前成熟度

| 能力 | 成熟度 | 当前判断 |
|---|---|---|
| 会议导入、核听、逐字稿/身份修正、证据回跳、MeetingPack | 已真实验证（Validated） | 已在受控真实使用中驱动多轮改进 |
| 视频分析、AI Context、KB 发布、本机 RAG | 已实现，仍在验证（Implemented, under validation） | 可运行，仍缺稳定质量与规模基线 |
| 跨内容序列比较、视觉疑难页路由、新检索组合 | 实验中（Experimental） | 先进入实验记录，不作为稳定承诺 |
| SSO、ACL、租户隔离和正式多人服务 | 当前不在范围（Out of scope） | 不能把本机端口直接视为生产部署 |

完整状态与未来 30 天只在 [docs/STATUS.md](docs/STATUS.md) 维护。

## 快速开始

需要 Linux、Python 3.11+、`ffmpeg/ffprobe`；完整 AI 管线还需要与机器匹配的 PyTorch、模型和 `llama-server`。先阅读[部署 runbook](docs/runbooks/DEPLOYMENT.md)，避免安装过程覆盖可用的 CUDA/ROCm 环境。

```bash
git clone <repository-url> meeting-minutes
cd meeting-minutes
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

make doctor
make check
make run
```

浏览器打开 `http://127.0.0.1:8899/`。完整管线依赖、环境变量、模型角色与安全停止方式见 [OPERATIONS.md](docs/OPERATIONS.md)。`make smoke` 使用隔离临时数据根，不应读取真实会议。

## 文档入口

| 想回答的问题 | 文档 |
|---|---|
| 我应该先读什么？ | [文档导航](docs/INDEX.md) |
| 现在做到哪里？ | [当前状态](docs/STATUS.md) |
| 管理层或技术评审怎么介绍？ | [管理层摘要](docs/reporting/EXECUTIVE_BRIEF.md) · [技术摘要](docs/reporting/TECHNICAL_BRIEF.md) · [演示脚本](docs/reporting/DEMO_SCRIPT.md) |
| 产品长期定义和边界是什么？ | [产品说明](docs/PRODUCT.md) |
| 完整功能是否存在？ | [产品功能表](docs/PRODUCT_FUNCTIONS.md) |
| 数据、revision 和 provider 如何工作？ | [架构](docs/ARCHITECTURE.md) |
| 稳定交互原则是什么？ | [UX 合同](docs/UX.md) |
| 如何运行、恢复和维护？ | [运维入口](docs/OPERATIONS.md) |
| MeetingPack、AI Context、KB 和 RAG 如何分工？ | [知识库与 RAG](docs/KNOWLEDGE_RAG.md) |
| 当前还有哪些风险？ | [开放风险](docs/RISKS.md) |
| 每个版本改变了什么？ | [CHANGELOG](CHANGELOG.md) |

公开仓库只保存代码、虚构测试资料和脱敏文档。真实会议、人员、组织关系、导出物、凭据和个性化私有报告不得进入 Git。
