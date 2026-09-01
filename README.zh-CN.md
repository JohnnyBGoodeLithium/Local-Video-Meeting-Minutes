# Local Video Meeting Minutes

[English](README.md) | 简体中文

<!-- maturity: controlled-single-machine-poc -->
<!-- product-version: v0.15.1 -->

## 项目概览

Local Video Meeting Minutes 是一个本地优先的会议与第一手视频上下文工作流。它连接可配置的语音识别、人物区分、画面理解和文本生成，同时让逐字稿、已确认身份、revision 与来源链接独立于任何单一模型。

应用可以交付离线 MeetingPack、可移植 AI Context，以及面向知识库（KB）与后续 RAG 的投影。它不绑定特定模型：provider 可以运行在本机，也可以使用经过明确批准的端点；系统不会静默越过已经配置的隐私边界。

## 为什么做

会议摘要只有在用户能够检查内容来源、并在来源错误时进行修正的情况下才可信。本项目把回顾工作连接到原始音频、逐字稿、说话人身份、屏幕证据和第一手资料。模型输出用于辅助理解，不是事实真源。

项目同时探索：如何让一台受控本地机器为人、通用 AI 工具和知识系统编译可信上下文，而不要求把私有会议变成云端训练或故障排查材料。

## 核心能力

- **身份修正：**核对谁说了什么，确认或修正身份，并保留可撤销历史。
- **来源回证：**从结论回到相关逐字稿、原声、屏幕或提供的资料。
- **渐进会议处理：**先提供逐字稿与语音草稿，再完成可选画面增强。
- **MeetingPack：**导出离线、可回顾的会议包。
- **AI Context：**为明确选择的 AI 工具生成可移植上下文，不把会议绑定到单一模型。
- **KB 投影与 RAG：**把已核验材料投影为适合知识库的结构，并召回有证据链接的上下文。
- **会议与第一手视频路径：**处理会议，以及由操作者提供或明确授权的视频。

## 工作方式

工作流导入本地或明确授权的媒体，建立逐字稿与人物上下文，在可用时补充画面和现场资料，并投影为回顾与导出视图。Canonical 会议制品与模型特定输出保持分离；人工修正会形成新 revision，而不是静默改写证据历史。

默认 Web 工作流运行在一台受控主机上。本地 provider 优先；任何远端 provider 都必须被明确配置。页面描述、生成摘要或模型回答都不能独立证明一项会议决定。

## 当前成熟度

当前产品版本：**v0.15.1**。

| 范围 | 成熟度 | 当前边界 |
|---|---|---|
| 会议导入、逐字稿与身份修正、证据导航、MeetingPack | 已真实验证（Validated） | 已用于受控真实工作流，并有合成 CI 覆盖 |
| 第一手视频理解、AI Context、KB 投影、本机 RAG | 已实现，仍在验证（Implemented, under validation） | 可以运行，但质量与规模基线仍在建立 |
| 跨内容比较与实验性检索路径 | 实验中（Experimental） | 不是稳定产品承诺 |
| SSO、ACL、租户隔离和多人生产服务 | 当前不在范围（Out of scope） | 不能把本机端口当作生产部署 |

当前是受控单机 PoC，不是正式多人生产服务。会议回顾的验证程度高于视频理解和跨内容 RAG。持续维护的验证状态见[当前状态](docs/STATUS.md)。

## 快速开始

需要 Linux、Python 3.11+ 和 `ffmpeg/ffprobe`。完整模型执行还需要与硬件匹配的 PyTorch、模型服务和模型文件；修改可用的 CUDA 或 ROCm 环境前，请先阅读[部署 runbook](docs/runbooks/DEPLOYMENT.md)。

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

浏览器打开 `http://127.0.0.1:8899/`。`make smoke` 使用隔离临时数据根和虚构夹具，不得读取真实会议。

## 隐私与可信边界

公开仓库只包含代码、虚构夹具、模板和脱敏文档。不得提交真实会议、逐字稿、纪要、人名、声纹、组织结构、凭据、内部 URL、原始日志、导出物或私有报告。

本地优先不代表每个已配置 provider 都在本机。只有操作者明确批准和配置后才能使用远端端点。应用应明确失败，而不是静默改变隐私边界。参见 [SECURITY.md](SECURITY.md) 与[开放风险](docs/RISKS.md)。

## 文档导航

| 想回答的问题 | 权威文档 |
|---|---|
| 应该从哪里开始？ | [文档导航](docs/INDEX.md) |
| 当前验证到哪里？ | [当前状态](docs/STATUS.md) |
| 产品边界是什么？ | [产品说明](docs/PRODUCT.md) |
| 哪些能力已经存在？ | [产品功能表](docs/PRODUCT_FUNCTIONS.md) |
| Canonical 数据、revision 与 provider 如何工作？ | [架构](docs/ARCHITECTURE.md) |
| 哪些交互合同稳定？ | [UX](docs/UX.md) |
| 如何运行、恢复和维护？ | [运维入口](docs/OPERATIONS.md) |
| MeetingPack、AI Context、KB 投影和 RAG 如何分工？ | [知识库与 RAG](docs/KNOWLEDGE_RAG.md) |
| 还有哪些风险和未决问题？ | [风险](docs/RISKS.md) |
| 各版本改变了什么？ | [CHANGELOG](CHANGELOG.md) |

## 发布与安装状态

当前分发方式是源码 checkout。仓库正在建立经过验证的 **Application Release Bundle（应用发布包）**，其中包含应用脚本、Web 资源、prompts、部署样例、锁定的轻量依赖和必要文档。

它不是 PyPI package。`pip install -e .` 当前主要安装基础依赖和项目元数据；应用仍从仓库或发布包目录运行。项目目前没有稳定的 Python public import API，也不承诺通过 pip 安装后可以在任意目录直接启动。

## 许可证状态

本仓库当前未附带开源许可证。  
转载、再分发或商业使用前，应先确认代码归属与公司政策。
