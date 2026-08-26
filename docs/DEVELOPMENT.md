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

## 在线前端模块

`web/static/app.js` 是无构建原生 ES module 装配入口；可复用、无 DOM 的领域规则放在 `web/static/modules/`。当前边界为媒体来源、导入、任务面板、内容库、核听导航、逐字稿搜索/分段和导出选择/体积/URL；DOM、滚动、媒体 `play()`、下载点击与跨域状态协调留在入口，新增纯规则不要再直接堆回去。模块须能被 `web/tests/frontend_modules_test.mjs` 独立导入；入口或加载顺序变化还须通过 `make smoke` 的 Headless Chromium 在线启动检查。静态契约测试检索整个模块图，不得假设实现仍位于 `app.js` 单文件。

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
跨 NVIDIA/AMD/CPU 的安装顺序、环境模板和验收矩阵见 `docs/DEPLOYMENT.md`。

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

首次发布到 GitHub 时应创建空的私有仓库，再添加远端并推送当前分支；正常 push 会上传
当前分支可达的全部历史提交，而不只是最终快照。发布前必须再次执行私有路径检查：

```bash
git status --short
git ls-files meetings recordings speaker_bank evaluations web/jobs
git check-ignore -v meetings/example/transcript.spk.json recordings/example.wav
```

第二条命令只允许出现明确公开的模板或 `.gitkeep`。不得把真实会议、录音、人员、声纹、
组织架构、评测事件、作业状态或凭据加入远端仓库。

## 回归要求

任何 Web API 或交互改动至少需要：

- `make check`；
- `make smoke`；
- 新增写操作时验证 revision 冲突、备份或可恢复性；
- 新增文件入口时验证扩展名、路径穿越与失败清理；
- 新增 LLM 功能时验证 dry-run、不连云、输出不能直接写文件。
