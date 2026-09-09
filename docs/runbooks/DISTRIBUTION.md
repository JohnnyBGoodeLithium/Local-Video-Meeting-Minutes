# 应用分发与发布包

## Current distribution model

当前支持两种分发方式：

1. **Source checkout**：从 Git 仓库运行，适合开发与受控部署。
2. **Application Release Bundle**：包含应用脚本、Web 静态资源、prompts、部署样例、轻量依赖锁、必要文档及已固定版本的说话人模型的经过校验目录。

当前明确不提供：

- PyPI package；
- 能够在任意目录启动的 wheel；
- 稳定的 Python public import API；
- ASR/LLM/VL 权重或 CUDA/ROCm/PyTorch 的通用运行时包。

## 内置说话人模型

源码和应用 ZIP/tar.gz 均携带 `pyannote/speaker-diarization-community-1`，约增加 32 MiB。
权重使用普通 Git 文件保存，GitHub 下载 ZIP 和 `git clone` 不需要 Git LFS、HF 账号、token 或再次下载。
应用自动发现 `models/pyannote/speaker-diarization-community-1/`；`make doctor` 使用相同的发现顺序。
仅在覆盖内置模型时设置 `MEETING_PYANNOTE_MODEL`。目标机器仍需按硬件安装 PyTorch 和 pyannote.audio。

模型使用 CC BY 4.0；上游署名、许可链接、未修改声明及子模型归属保存在包内
`THIRD_PARTY_NOTICES.md` 和原始 model cards。版本与逐文件 SHA-256 固定在
[`release/diarization-model.json`](../../release/diarization-model.json)。升级模型须同时更新这些记录，
重新核对许可并在目标机器完成无 token、空 HF cache、禁用网络的加载验证。

`pip install -e .` 当前主要安装基础依赖与项目元数据。应用仍从 source checkout 或 Application Release Bundle 的目录布局运行。`[tool.setuptools] packages = []` 会保留到项目完成资源、入口点与 package data 的正式迁移设计。

## Application bundle 与 wheel

Application Release Bundle 是完整应用目录，保留 `bin/`、`web/`、`prompts/`、`deploy/`、requirements locks 和运行文档。Python wheel 面向可安装 Python 包，需要稳定模块、入口点和 package data；本项目目前尚不满足这些合同，因此不会构建一个缺少静态资源的名义 wheel。

## 依赖锁

```bash
.venv/bin/pip install -e '.[lock]'
make lock
make lock-check
make install-runtime
make install-ci
```

`requirements/runtime.lock` 锁定基础依赖，`requirements/ci.lock` 锁定基础依赖与 CI extra。两者由 Python 3.11 和固定 pip-tools 版本生成。

完整 pipeline 不生成统一 lock。PyTorch、CUDA、ROCm、qwen-asr、pyannote 与模型服务依赖硬件 profile 和安装来源；它们继续由 `pyproject.toml` 的允许范围、[模型参考](../reference/MODELS.md)、[部署 runbook](DEPLOYMENT.md) 和已验证硬件 profile 共同管理。

## 构建发布候选

```bash
make release-bundle
make release-verify
```

构建器只打包 Git 已跟踪且匹配 [bundle allowlist](../../release/bundle-include.txt) 的文件。它不会把整个仓库复制后再做排除，也不会因为某个文件处于 `.gitignore` 就认为它安全。

非 tag 构建使用类似：

```text
local-video-meeting-minutes-v0.15.1-dev-g86d2432/
```

dirty 本地构建会在名称和 manifest 中明确标记，不能用于正式 Release。正式构建要求干净工作区、当前 commit 上存在精确的 `v$(cat VERSION)` tag，并显式使用 `--official`。

## 安全边界

默认拒绝运行数据、`.env`、凭据、私有报告、会议目录、声纹身份数据、其他模型权重、大型缓存、绝对路径、`..` 路径和 symlink。speaker bank 只允许 `*.template.json`。

唯一模型例外是上述 manifest 固定的 9 个文件。构建和解压验证都检查许可记录、准确文件集合、大小及 SHA-256；
缺失权重、LFS 指针、篡改文件或额外模型不能通过发布检查。CI 只校验文件，不安装或运行模型。

归档内包含 `release-manifest.json`；外部同时生成 ZIP、tar.gz、manifest 和 `SHA256SUMS`。ZIP 与 tar.gz 必须具有相同的顶层目录和文件集合。

## 验证层级

- 普通 PR 的 release-candidate：构建 dev bundle 并做结构、hash 与隐私边界验证；只有发布脚本、锁、
  allowlist、Makefile 或 release workflow 发生变化时，才额外执行一次全新目录验证。
- `make release-verify`：在全新临时目录中创建 venv，按 `ci.lock` 安装，运行 `package-check` 与 `make smoke`。
  `package-check` 保留包内可运行的 Python、Node、文档、静态资源和版本测试；只跳过 Git 工作区与未进入发布包的
  `.github` 仓库治理合同。
- tag Release workflow：重新执行正式 CI、构建 official bundle、完成全新目录验证，最后才创建 GitHub Release。

任何 Make target 都不会隐式创建 tag 或 GitHub Release。
