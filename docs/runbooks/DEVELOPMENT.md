# 开发与验证

## 环境

项目使用 Python 3.11+。现有机器为保留 ROCm/系统包兼容性，虚拟环境使用 `--system-site-packages`；不要在未核对 GPU 版本时重新安装 PyTorch。

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
# 管线依赖仅在确认不会覆盖现有 ROCm torch 后安装：
.venv/bin/pip install -e '.[pipeline]'
```

## 常用命令

```bash
make doctor   # 检查模块、二进制、模型路径和本机路由
make check    # Python/JavaScript 语法与 diff whitespace
make smoke    # 一次性数据根 + 假声纹库 + dry-run Web 全链路
make assistant-live  # 仅用虚构文本验证真实本地 LLM 问答/编辑协议
make run      # 127.0.0.1:8899
```

`make smoke` 使用 `tempfile.TemporaryDirectory`。服务、上传、会议、声纹、作业 JSON 全在该目录内，结束后自动清理；它不会枚举或修改真实 `meetings/`。


## GitHub CI 与三层验证

`.github/workflows/ci.yml` 在每个 Pull Request、推送到 `main` 和人工触发时运行。hosted runner
创建干净的 Python 3.11 虚拟环境，安装基础 Web 依赖与轻量 `.[ci]` 依赖，再执行完整
`make check` 和 `make smoke`。CI 不安装 `.[pipeline]`，不下载模型，不连接本机服务，
也不读取真实会议目录。

`.[ci]` 只包含非 live 测试实际需要的 NumPy、Pillow 和 soundfile。浏览器旅程是正式门禁：
工作流在测试前要求 Chrome/Chromium 存在，找不到时直接失败，不能让 smoke 以 `SKIP` 伪装为全绿。

验证分为三层：

1. 开发中运行受影响的专项测试；
2. 提交 PR 前至少本地运行 `make check`，涉及 Web/API/Viewer/schema/导出/人物核对/进度恢复或
   smoke 本身时再先跑 `make smoke`；
3. GitHub hosted CI 运行完整 `check-and-smoke`。涉及模型、GPU 或真实 WeKnora 的正式版本，
   仍需在 Lenovo 设备上运行 `make doctor`、相应 live test 和获准的合成或测试会议验证。

代码默认走 feature branch → Pull Request → `check-and-smoke` 通过 → 合并。仓库管理员还需在
GitHub Rulesets 或 Branch protection 中为 `main` 启用“必须经 PR”和“必须通过
`check-and-smoke`”，并阻止 force push；仅有工作流不能阻止失败提交直接进入未保护的 `main`。
本仓库公开可见，不得把办公 ThinkCentre 直接注册为 self-hosted runner。

## 在线前端模块

`web/static/app.js` 是无构建原生 ES module 装配入口；可复用、无 DOM 的领域规则放在 `web/static/modules/`。当前边界覆盖媒体来源、导入、任务面板、内容库、核听导航、逐字稿搜索/分段、导出规则和纪要视图/证据状态；`transcript-view.js` 与 `minutes-view.js` 接管两块阅读 DOM projection，并通过显式数据与 callback 连接入口 controller。view 模块不得反向读取全局 `state`、调用 API 或直接控制媒体；状态更新、滚动/播放协调、证据抽屉和写入/撤销副作用继续留在入口。其他新增纯规则不要再直接堆回 `app.js`。模块须能被 `web/tests/frontend_modules_test.mjs` 独立导入；入口或加载顺序变化还须通过 `make smoke` 的 Headless Chromium 在线启动检查，并断言核心阅读 DOM 实际生成。静态契约测试检索整个模块图，不得假设实现仍位于 `app.js` 单文件。

## 页面排障入口

- `http://127.0.0.1:8899/?diag=1`：页面内布局链诊断浮层，逐层报告滚动容器的 scrollHeight/clientHeight/overflow/position，用于远程定位"滚动条消失/内容被裁"类问题。
- `?meeting={slug}`：直达指定会议，便于分享复现链接。
- 左上角 logo 悬停显示当前前端构建号（从 app.js 的 `v=` 参数读取），确认用户看到的版本不靠猜；每批可见改动随 `web/static/index.html` 与 `web/tests/smoke_test.py` 同步递增。

## 运行配置

| 变量 | 默认值 | 用途 |
|---|---|---|
| `MEETING_DATA_ROOT` | 仓库根 | 私有 `recordings/meetings` 数据根 |
| `MEETING_WEB_BANK` | `<data>/speaker_bank` | 声纹与组织架构目录 |
| `MEETING_WEB_JOBS` | `web/jobs` | 作业状态目录 |
| `MEETING_WEB_PORT` | `8899` | 本机监听端口 |
| `MEETING_PYTHON` | `.venv/bin/python` | 管线子进程解释器 |
| `MEETING_LLM_API` | `http://127.0.0.1:11435/v1` | 本机 OpenAI-compatible API |
| `MEETING_LLM_MODEL` | `qwen3.6-35b-a3b-operator` | 助手模型 |
| `MEETING_DRAFT_MODEL` | 跟随 `MEETING_LLM_MODEL` | 视频会议早期语音草稿模型 |
| `MEETING_MINUTES_MODEL` | `qwen3.8-27b-minutes` | 纯音频正式纪要与多模态终稿模型 |
| `MEETING_RECOVERY_REFINE_MODEL` | 未设置 | 用户明确选择高质量重试时的精修模型 |
| `MEETING_LLM_CONTEXT_SIZE` | `65536` | 文本模型服务实际上下文窗口，供请求预算与长文本切分 |
| `MEETING_ALLOW_REMOTE_LLM` | 未设置 | 只有明确授权远程处理时才可设为 `1` |
| `MEETING_DEVICE` | `auto` | PyTorch 设备；ROCm 与 CUDA 都使用 `cuda` 设备语义 |
| `MEETING_TORCH_DTYPE` | `auto` | 自动 BF16/FP16/FP32，或显式覆盖 |
| `MEETING_ASR_MODEL` | 用户模型缓存 | Qwen3-ASR 路径 |
| `MEETING_ALIGNER_MODEL` | 用户模型缓存 | ForcedAligner 路径 |
| `MEETING_PYANNOTE_MODEL` | 用户模型缓存 | pyannote 路径 |
| `MEETING_VL_MODEL` / `MEETING_VL_MMPROJ` | 用户模型缓存 | llama.cpp VL 模型和 projector |
| `MEETING_VL_PORT` | `11436` | 按需 VL 服务端口 |
| `MEETING_VL_WORKERS` | `2` | VL 逐页解读并发数；需与 VL 服务 `--parallel` 槽位匹配 |
| `MEETING_VL_GPU_LAYERS` | `999` | VL GPU offload 层数 |
| `MEETING_WEB_DRYRUN` | 未设置 | 测试时管线只执行 `--help` |

旧变量 `MEETING_MINUTES_ROOT` 仍兼容，但新部署应使用 `MEETING_DATA_ROOT`。
跨 NVIDIA/AMD/CPU 的安装顺序、环境模板和验收矩阵见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## Git 与私有数据

`.gitignore` 排除了录音、会议、声纹/人员数据、组织架构、虚拟环境、缓存和作业状态。提交前仍需运行：

```bash
git status --short
git diff --cached --name-only
```

不得用 `git add -f` 绕过私有目录规则。

Git 是完整代码历史的唯一真源：每个可独立验证的功能、修复或重构使用单独提交，
提交保留作者、时间、父提交和逐行差异。`CHANGELOG.md` 是便于产品和管理回看的阅读索引，
不能代替 Git 历史。重大功能提交前应同步更新工程走查与变更日志，并在提交说明或工程
走查中记录验证命令和仍有限制。

仓库当前按公开仓库的安全边界维护；正常 push 会上传当前分支可达的全部历史提交，
而不只是最终快照。发布前必须再次执行敏感路径检查：

```bash
git status --short
git ls-files meetings recordings speaker_bank evaluations web/jobs
git check-ignore -v meetings/example/transcript.spk.json recordings/example.wav
```

第二条命令只允许出现明确公开的模板或 `.gitkeep`。不得把真实会议、录音、人员、声纹、
组织架构、评测事件、作业状态或凭据加入远端仓库。

## 回归要求

- 开发中先运行与改动直接相关的测试；
- 提交 PR 前至少运行 `make check`；
- Web API、浏览器交互、Viewer、bundle schema、人物核对、进度恢复、照片生命周期、导出、
  前端构建号或 smoke 自身有变化时，本地先运行 `make smoke`；
- GitHub CI 必须完整通过 `check-and-smoke`，失败后读取日志并提交修正，不绕过门禁；
- 新增写操作时验证 revision 冲突、备份或可恢复性；
- 新增文件入口时验证扩展名、路径穿越与失败清理；
- 新增 LLM 功能时验证 dry-run、不连云、输出不能直接写文件；
- 发布涉及 GPU、模型或真实知识库的版本时，在目标机器补做 live/hardware 验证。
