# 应用分发与发布包

## Current distribution model

当前支持两种分发方式：

1. **Source checkout**：从 Git 仓库运行，适合开发与受控部署。
2. **Application Release Bundle**：包含应用脚本、Web 静态资源、prompts、部署样例、轻量依赖锁和必要文档的经过校验目录。

当前明确不提供：

- PyPI package；
- 能够在任意目录启动的 wheel；
- 稳定的 Python public import API；
- 模型权重、CUDA/ROCm/PyTorch 的通用运行时包。

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

默认拒绝运行数据、`.env`、凭据、私有报告、会议目录、声纹身份数据、模型权重、大型缓存、绝对路径、`..` 路径和 symlink。speaker bank 只允许 `*.template.json`。

归档内包含 `release-manifest.json`；外部同时生成 ZIP、tar.gz、manifest 和 `SHA256SUMS`。ZIP 与 tar.gz 必须具有相同的顶层目录和文件集合。

## 验证层级

- 普通 PR 的 release-candidate：构建 dev bundle 并做结构、hash 与隐私边界验证。
- `make release-verify`：在全新临时目录中创建 venv，按 `ci.lock` 安装，运行 `package-check` 与 `make smoke`。
- tag Release workflow：重新执行正式 CI、构建 official bundle、完成全新目录验证，最后才创建 GitHub Release。

任何 Make target 都不会隐式创建 tag 或 GitHub Release。
