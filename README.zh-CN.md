# Meeting Context

[English](README.md) | 简体中文

[产品介绍站](https://johnnybgoodlithium.github.io/Local-Video-Meeting-Minutes/)

<!-- maturity: controlled-single-machine-poc -->
<!-- product-version: v0.16.0 -->

找到重点。
回到原始依据核对。
修正错误。
把可信上下文继续用下去。

Meeting Context 是一个本地优先的会议与视频上下文编译器。逐字稿、身份、议题、事实、
来源依据和画面不绑定任何单一模型，再由同一份 canonical context 投影到回顾与复用界面。

## 它能做什么

- **会议：**按人物理解谁说了什么，回顾决定和跟进事项，回到准确的原声、逐字稿或画面，
  并以 revision 历史修正身份或逐字稿错误。
- **视频：**先快速形成纪要，或执行完整画面分析；按论证与重要镜头浏览，需要核对时回到原始来源。

## 随处回顾

- **Workbench** 是本机深度回顾界面，用于逐字稿、身份、画面上下文、失败恢复与导出。
- **Companion** 是适配 Phone / Tablet / Laptop 的轻端：发送输入、查看任务、回顾来源相连的
  上下文和字幕、完成人物小决策。Hosted Chromium 已通过；真实 iPhone 与 Tailscale 传输仍待验证。
- **MeetingPack** 是无需服务、模型或 CDN 的便携离线回顾包。

纪要与知识库是结果延续层，不是新的回顾使用面。纪要整理这一场会议或这一段视频，并保留回到
原文、原声和原画面的入口；WeKnora 等知识库让核对后的结果在之后可检索、问答和跨内容使用，
但不会成为新的会议事实真源。

**纪要讲清这一次，知识库连接下一次。**

## 核心旅程

1. 导入会议、录屏、第一手视频，或明确授权的公开视频 URL。
2. 找到重要议题、决定、人物、逐字稿片段和画面资料。
3. 用原声、原文、屏幕或现场照片核对结论。
4. 在正确的数据层修正名称、人物归属或逐字稿事实。
5. 将可信结果继续用作 MeetingPack、AI Context、KB 投影或带依据的 RAG 输入。

## v0.16.0 重点

- Companion 在 Phone、Tablet、Laptop 上提供自适应回顾布局。
- 音频与视频使用统一播放模型，字幕支持关闭、原文、翻译和双语。
- Canonical 身份绑定、显示名修改与单个离线包 alias 分开处理。
- 先出快速纪要，后续画面增强复用已有逐字稿和人物结果。
- 实验性 Live Context 工作区支持经授权的公开、无 DRM 原生 HLS 来源。
- 来源回跳改用更自然的产品词：原文、画面、回到这段讨论。

## 当前成熟度

| 范围 | 成熟度 | 当前边界 |
|---|---|---|
| 会议回顾、身份修正、来源回跳、MeetingPack | Validated | 受控真实工作流，加合成与浏览器回归覆盖 |
| 视频分析、Companion 自适应回顾、字幕、AI Context、KB 投影 | Implemented / validating | 功能存在；目标设备、质量与规模基线仍不完整 |
| Live Context 与 Companion 私有传输 | Experimental | 仅有合成/重放和 Hosted Browser 证据；未做真实直播或 iPhone + Tailscale 验证 |
| SSO、ACL、租户隔离、多人生产服务 | Planned / out of scope | 本机端口或 tailnet 原型不等于生产审批 |

当前是受控单机 PoC。逐能力证据见 [v0.16.0 reality matrix](docs/releases/v0.16.0-reality-matrix.md)。

## 本地优先边界

Backend 默认只监听 localhost。Provider 可以在本机运行，或使用操作者明确批准和配置的端点；
应用不会静默越过这条边界。Companion 与具体 transport 解耦，Tailscale Serve 是首个私有原型，
默认关闭 Funnel。公开仓库中的夹具和文档均为虚构、脱敏内容。

## 快速开始

需要 Linux、Python 3.11+ 和 `ffmpeg` / `ffprobe`。完整模型运行还需要兼容的模型服务与硬件；
改变可用的 CUDA 或 ROCm 环境前，先阅读[部署 runbook](docs/runbooks/DEPLOYMENT.md)。

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

浏览器打开 `http://127.0.0.1:8899/`。`make smoke` 使用临时数据根和虚构夹具，不得读取真实会议。

## 文档导航

| 需要 | 权威来源 |
|---|---|
| 全部文档 | [文档导航](docs/INDEX.md) |
| 产品叙事 | [产品介绍站](https://johnnybgoodlithium.github.io/Local-Video-Meeting-Minutes/) |
| 最新发布候选 | [v0.16.0 发布说明](docs/releases/v0.16.0.md) |
| 能力清单 | [产品功能表](docs/PRODUCT_FUNCTIONS.md) |
| 当前验证状态 | [状态](docs/STATUS.md) |
| Canonical 数据与投影 | [架构](docs/ARCHITECTURE.md) |
| 部署与恢复 | [运维](docs/OPERATIONS.md) |
| 安全边界 | [安全说明](SECURITY.md) |

支持的分发方式是源码 checkout 与通过验证的 Application Release Bundle。当前不是 PyPI package，
也不提供稳定的 Python public API。

## 许可证状态

本仓库当前未附带开源许可证。转载、再分发或商业使用前，应先确认代码归属与公司政策。
