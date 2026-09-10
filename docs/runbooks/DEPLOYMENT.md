# 跨机器与 GPU 部署

首次安装按第 1–5 节顺序进行；OEM 预装 GPU 软件栈先读第 0 节。命令以 Linux/Bash 为准，
不能直接作为 Windows/macOS 的安装承诺。先跑通“本地录音 → 逐字稿 → 说话人确认 → 纪要”；
VL、知识库、Companion、精修大模型后续按需启用。仅查看 Web 界面可以使用 README 的轻量启动步骤。

## 结论

项目业务代码不依赖 AMD。当前机器使用 ROCm，但 PyTorch 的 ROCm 构建同样暴露 `torch.cuda` 设备 API；项目现在会把实际 backend 诊断为 `rocm` 或 `cuda`，并按显卡能力选择 BF16/FP16。迁移到 NVIDIA 的关键不是改业务流程，而是安装 CUDA 版 PyTorch、CUDA 版 `llama.cpp`，并配置模型路径。

本地文件导入不要求外网。只有用户选择“媒体 → 粘贴公开链接”时，服务端才需要外网 DNS/HTTPS，并使用项目依赖中的 `yt-dlp` 获取单条公开视频。该能力不依赖 AMD/NVIDIA，但站点兼容性会随平台变化；部署在受控 LAN 前应为下载 worker 配置独立出口、磁盘/时长配额和审计，不能把应用端口当作开放下载代理。

| 层 | NVIDIA | AMD | CPU |
|---|---|---|---|
| ASR / pyannote | PyTorch CUDA | PyTorch ROCm | 可运行，明显更慢 |
| 文本/VL GGUF | llama.cpp CUDA backend | llama.cpp HIP/ROCm backend | llama.cpp CPU backend |
| Python 业务代码 | 相同 | 相同 | 相同 |
| 默认 dtype | 支持 BF16 则 BF16，否则 FP16 | 支持 BF16 则 BF16，否则 FP16 | FP32 |

PyTorch 官方也明确说明 ROCm 构建沿用 `torch.cuda.is_available()` 语义；安装时应在官方选择器中选择与机器匹配的 CUDA、ROCm 或 CPU 构建：[PyTorch Start Locally](https://docs.pytorch.org/get-started/locally/)。`llama.cpp` 官方构建文档分别提供 CUDA 与 HIP backend：[Build llama.cpp locally](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)。

## 0. 平台验证栈优先（OEM AI 工作站）

在 Lenovo/AMD rex 等 OEM 验证平台（如 gfx1151 统一内存机型）上，**不要**用 pytorch.org 通用 ROCm wheel 覆盖系统预装的 PyTorch。通用 wheel 的典型故障模式是：`import torch`、`torch.cuda.is_available()` 全部正常，但任何 GPU 计算立即段错误，无 Python 报错，极易误判为项目代码问题。

正确做法：

- PyTorch 优先使用平台验证渠道：系统 deb（如 `python3-torch-rocm`）或 AMD TheRock 对应 gfx 目标的构建；
- 项目 venv 用 `python3 -m venv --system-site-packages` 继承系统验证版 torch/torchaudio/torchvision，再安装项目依赖；
- torch、torchaudio、torchvision 必须属于相互兼容的平台版本组合和构建渠道；三个包的版本号不必相同。不要混装 CUDA 和 ROCm 构建；
- 安装项目依赖前先做 10 秒 GPU 冒烟，确认实际计算可用而不只是枚举可用：

```bash
python3 -c 'import torch; x=torch.randn(1024,1024,device="cuda"); print("GPU OK", (x@x).sum().item())'
```

自装 ROCm 的通用（非 OEM 验证）机器仍按第 2 节从 PyTorch 官方选择器安装。

## 1. 系统准备

建议 Linux、Python 3.11 或 3.12。系统工具至少包括：

```bash
ffmpeg -version
ffprobe -version
python3 --version
```

组织架构 PDF 上传另需 `pdftoppm`。驱动层先用 `nvidia-smi` 或 `rocm-smi` 验证，之后再创建 Python 环境。

## 2. 安装 Python 环境

```bash
git clone https://github.com/JohnnyBGoodeLithium/Local-Video-Meeting-Minutes.git meeting-minutes
cd meeting-minutes
# 普通机器；OEM 预装验证栈改用 python3 -m venv --system-site-packages .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
```

普通机器先从 PyTorch 官方选择器安装对应构建，命令中的 pip 应使用 `.venv/bin/python -m pip`。
OEM 机器先验证 venv 能导入平台提供的 torch。提前安装并不能保证依赖解析时不被替换，
因此先记录已验证的版本作为本机约束，再安装管线；发生依赖冲突时应解决平台组合，不删除约束硬装。

```bash
.venv/bin/python -c 'import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda, torch.version.hip)'
.venv/bin/python - <<'PY' > .env.torch-constraints.txt
from importlib.metadata import version
for name in ("torch", "torchaudio", "torchvision"):
    print(f"{name}=={version(name)}")
PY
.venv/bin/python -m pip install -c .env.torch-constraints.txt -e '.[pipeline]'
.venv/bin/python -m pip check
```

约束文件只保留在本机。安装前后都要用该 venv 做实际计算：GPU 机器运行
`.venv/bin/python -c 'import torch; x=torch.randn(1024,1024,device="cuda"); print((x@x).sum().item())'`；
CPU 安装把 `device="cuda"` 改为 `device="cpu"`。仅 import 成功不代表 GPU 可用。

不建议把某个 CUDA 或 ROCm wheel 固定进 `pyproject.toml`：那会使另一类显卡无法安装。

## 3. 安装 llama.cpp

已有可用的 OpenAI-compatible 文本服务可跳过编译，直接配置第 4 节的端点和模型 ID。
自行构建时，先获取 llama.cpp 源码并进入其目录，再按官方构建文档选择 backend。
以下不是在 meeting-minutes 仓库内执行的命令；构建后把 `build/bin/llama-server` 加入 PATH：

```bash
# NVIDIA 示例
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j

# AMD 示例
cmake -B build -DGGML_HIP=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j
```

不要把 AMD 编译出的 `llama-server` 复制到 NVIDIA 机器，反之亦然。CLI 参数可以相同，但动态库与 GPU kernel 不同。

## 4. 配置模型与服务

从 meeting-minutes 仓库根执行；已有 `.env` 时直接编辑，不覆盖：

```bash
test -e .env || (umask 077; cp deploy/meeting-minutes.env.example .env)
```

编辑 `.env`，所有路径使用本机实际的绝对路径。首次只需要：

1. `MEETING_DATA_ROOT` 指向可写的私有数据目录，`MEETING_WEB_JOBS` 指向其中的 `jobs`。
2. **同时设置 `MEETING_WEB_BANK` 和 `MEETING_BANK_DIR` 为同一个绝对路径**，通常是数据根下的 `speaker_bank`。目前各模块读取变量仍有差异，仅设置数据根或仅设置 `MEETING_BANK_DIR` 不足以让所有入口一致。
3. `MEETING_PYTHON` 指向当前仓库 `.venv/bin/python`，不要沿用另一台机器的解释器路径。
4. native ASR 需要准备完整的 ASR、ForcedAligner 模型目录并填写路径；包内只附带说话人区分模型，不包含这两个模型或文本/VL 权重。也可使用下文满足时间戳合同的兼容 ASR 服务。
5. 先让 `MEETING_LLM_MODEL`、`MEETING_DRAFT_MODEL`、`MEETING_MINUTES_MODEL` 使用同一个已部署文本模型 ID。精修、VL、知识库暂时保留为注释；首次视频导入选择“快速纪要”。

native ASR 权重可按 [Qwen 官方模型说明](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)获取，
对齐模型见 [ForcedAligner](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)。离线部署可从获准联网设备
复制完整模型目录；不能只复制 config.json 或缓存软链接。文本 GGUF 也需自行准备，下面的 `/models/text-model.gguf` 是待替换路径。

项目不会自动加载 `.env`。每次新终端启动 Web、doctor 或 CLI 管线前，在仓库根加载自己编辑的文件：

```bash
set -a
. ./.env
set +a
mkdir -p "$MEETING_DATA_ROOT/meetings" "$MEETING_DATA_ROOT/recordings" "$MEETING_WEB_BANK" "$MEETING_WEB_JOBS"
test "$MEETING_WEB_BANK" = "$MEETING_BANK_DIR"
test -x "$MEETING_PYTHON"
curl --fail --silent --show-error "${MEETING_LLM_API%/}/models"
```

确认返回列表包含三个文本角色配置的 ID；服务健康不代表请求的模型存在。环境文件若也用于 systemd，
使用 `KEY=value` 和必要的引号，不能依赖 shell 的 `$HOME`、`~` 展开或命令替换。

关键变量参考：

| 变量 | 默认 | 作用 |
|---|---|---|
| `MEETING_DEVICE` | `auto` | `auto/cpu/cuda/cuda:0`；ROCm 也写 `cuda` |
| `MEETING_TORCH_DTYPE` | `auto` | `auto/fp32/fp16/bf16` |
| `MEETING_ASR_PROVIDER` | `native` | `native` 进程内适配器，或显式 `openai-compatible` HTTP 端点 |
| `MEETING_ASR_MODEL` | 用户模型缓存 | native provider 的 Qwen3-ASR 路径 |
| `MEETING_ALIGNER_MODEL` | 用户模型缓存 | ForcedAligner 路径 |
| `MEETING_ASR_API` | `http://127.0.0.1:11439/v1` | 兼容 provider 的 `/audio/transcriptions` 基址；可为本机、局域网或获批云端 |
| `MEETING_ASR_API_MODEL` | `whisper-1` | 兼容端点的模型 ID |
| `MEETING_ASR_CONTEXT_MODE` | `auto` | `auto` 拒绝 prompt 后同端点无 context 重试；`required` 硬失败；`off` 不发送 |
| `MEETING_ASR_FALLBACK_PROVIDER` | 空 | 只有显式设置才允许跨 provider 故障切换；默认绝不切云端 |
| `MEETING_ASR_REVIEW` | `1` | 已知术语混淆的短音频定点复核；失败保留第一遍结果 |
| `MEETING_PYANNOTE_MODEL` | 包内 community-1，其次用户模型缓存 | 可选覆盖；内置说话人模型无需 HF 授权或另行下载 |
| `MEETING_LLM_API` | `http://127.0.0.1:11435/v1` | OpenAI-compatible 文本端点 |
| `MEETING_LLM_MODEL` | `qwen3.6-35b-a3b-operator` | AI 对话、翻译与通用文本模型 ID |
| `MEETING_DRAFT_MODEL` | 跟随 `MEETING_LLM_MODEL` | 视频会议早期语音草稿模型 ID |
| `MEETING_MINUTES_MODEL` | `qwen3.8-27b-minutes` | 纯音频正式纪要与多模态终稿模型 ID |
| `MEETING_RECOVERY_REFINE_MODEL` | 未设置 | 高质量恢复/精修模型 ID；大模型机器可设 `gpt-oss-120b` |
| `MEETING_TERMINOLOGY_MODEL` | 跟随 `MEETING_LLM_MODEL` | 从已完成屏幕说明提取下一场 ASR 候选的本地模型 ID |
| `MEETING_LLM_CONTEXT_SIZE` | `65536` | 长会切分预算依据 |
| `MEETING_MEMORY_RESERVE_GIB` | `32` | 双文本模型允许常驻的健康线 |
| `MEETING_MEMORY_STOP_GIB` | `24` | 低于此值卸载空闲模型并暂停新重阶段 |
| `MEETING_MEMORY_EMERGENCY_GIB` | `8` | 低于此值可中断在途模型，优先保护整机 |
| `MEETING_KB_URL` | 未设置 | 可选知识库浏览入口；配置后显示在工作台顶栏 |
| `MEETING_VL_MODEL` | 当前用户 Miloco 路径 | VL GGUF |
| `MEETING_VL_MMPROJ` | 当前用户 mmproj 路径 | VL projector |
| `MEETING_VL_PORT` | `11436` | VL loopback 端口 |
| `MEETING_VL_WORKERS` | `2` | VL 逐页解读的并发请求数；需与 VL 服务 `--parallel` 槽位匹配 |
| `MEETING_VL_GPU_LAYERS` | `999` | llama.cpp GPU offload；显存不足可降低 |
| `MEETING_DATA_ROOT` | 仓库根 | 私有会议数据根 |
| `MEETING_WEB_BANK` | Web 默认 `<MEETING_DATA_ROOT>/speaker_bank`；部分 CLI 默认仓库内 | 当前 Web、视频和 Teams 管线读取的声纹库路径；部署时必须显式设置 |
| `MEETING_BANK_DIR` | 术语模块回退到 `MEETING_WEB_BANK` / 数据根 | 不能替代所有模块的 `MEETING_WEB_BANK`；两者设置相同路径 |
| `MEETING_PYTHON` | 当前解释器/Web venv | 作业子进程解释器 |

文本服务示例：

```bash
llama-server --model /models/text-model.gguf \
  --alias local-text \
  --host 127.0.0.1 --port 11435 --ctx-size 65536 \
  --gpu-layers 999 --flash-attn auto --jinja --no-webui
```

此单模型示例对应环境模板的 `local-text`；改用其他服务时以其 `/v1/models` 返回值为准。

ASR 兼容端点必须支持 `multipart/form-data` 的 `/audio/transcriptions`，并在
`response_format=verbose_json`、`timestamp_granularities[]=word` 下返回 `text`、`language` 与
`words[{word,start,end}]`。这是说话人对齐的数据合同，不满足时系统会明确报告 capability error。
Context 使用标准 `prompt` 字段；端点不支持时建议保留 `MEETING_ASR_CONTEXT_MODE=auto`。例如：

```bash
MEETING_ASR_PROVIDER=openai-compatible
MEETING_ASR_API=http://127.0.0.1:11439/v1
MEETING_ASR_API_MODEL=local-asr
MEETING_ASR_CONTEXT_MODE=auto
MEETING_ASR_FALLBACK_PROVIDER=
```

远程端点不会被自动发现或自动启用。只有管理员明确设置上述地址，音频才会发送到它；API key 只放在
机器私有环境文件的 `MEETING_ASR_API_KEY`，不得写进仓库。若确实需要 native 作为备用，再显式设置
`MEETING_ASR_FALLBACK_PROVIDER=native`。部署验收必须分别测试端点正常、拒绝 prompt、缺 word timestamps
和完全不可达四种情况，确认不会出现未授权跨端点传输。

本机需要同时提供快速草稿、27B 正式纪要和可选 120B 精修时，使用 llama.cpp router preset；
仓库提供不含机器路径的 [预设模板](../../deploy/llama-models.ini.example)。模板中的 section 名就是 API
请求里的模型 ID，必须与 `MEETING_DRAFT_MODEL`、`MEETING_MINUTES_MODEL` 和
`MEETING_RECOVERY_REFINE_MODEL` 一致。模型不存在时不要保留对应环境变量，否则高质量按钮会显示
但首次请求会失败。

VL 服务示例（逐页解读默认 2 路并发，槽位数要配得上）：

```bash
llama-server --model /models/vl-model.gguf --mmproj /models/mmproj.gguf \
  --host 127.0.0.1 --port 11436 --ctx-size 32768 --parallel 2 \
  --gpu-layers 999 --flash-attn auto --jinja --no-webui
```

如果显存/统一内存不允许文本模型与 7B VL 双槽同时驻留，应退回 `--parallel 1` 并设 `MEETING_VL_WORKERS=1`（串行解读）；不要为了常驻而让系统交换或 OOM。

统一内存机器还应安装 `deploy/meeting-resource-guard.service.example`。它与管线内准入使用同一策略：
健康状态允许两个文本模型驻留，音频/视觉阶段压到一个，120B 精修独占；低内存作业会显示等待并
保留检查点。若同机部署 WeKnora，合并 `deploy/weknora/resource-profile.env.example` 的低并发项，
并阅读 [WEKNORA.md](WEKNORA.md)，不要让 Wiki/图谱/自动问题生成与急件会议同时跑满。

术语私有数据位于数据根的 `speaker_bank/terminology.json`（人工确认）和 `terminology.candidates.json`（自动候选），两者都不得进入 Git。仓库只提供不含人员信息的 `speaker_bank/terminology.template.json` 示例。历史会议回填会调用本机文本服务且只输出数量：

```bash
.venv/bin/python bin/meeting_terminology.py backfill meetings
```

回填不是批量纠错：它不读取或改写 canonical 逐字稿，只从已有 `page_desc.json` 建候选。部署验收应对同一段脱敏音频分别运行默认 context 与 `--no-context`，记录目标术语召回、普通词误识别和 ASR 阶段耗时；再构造一条确认术语混淆，验证短片复核失败时仍保留第一遍逐字稿。

## 5. 首次验收与启动

```bash
.venv/bin/python bin/doctor.py --profile web
.venv/bin/python bin/doctor.py --profile all --json
make run
```

打开 `http://127.0.0.1:8899/`。`doctor` 应显示：

- NVIDIA：`backend=cuda`、`torch.version.cuda` 非空、`torch.version.hip` 为空；
- AMD：`backend=rocm`、`torch.version.hip` 非空；
- 模型路径存在，`llama-router` 可达；
- 实际计算另按第 2 节验证；doctor 的设备枚举不是 GPU 运算测试。

不启用 VL 时，VL 模型缺失的 warn 可以预期；文本服务不可达的 warn 会阻止纪要生成，不能忽略。
目前 `--profile all` 仍检查 native ASR 依赖和路径，即使配置了兼容 ASR 服务；应结合实际 provider 单独验收，不能靠重复下载模型消除所有提示。

用一段虚构内容、约 3 分钟且至少两人发言的测试录音或快速模式视频跑端到端：

1. 导入后逐字稿可读、音频可跳播，纪要最终完成。
2. 新建一个测试人员并确认声音组，再将另一组绑定到已有测试人员；刷新后仍保留，并验证撤销。
3. 图例和泳道中已绑定人员在前，两组内部各按发言时长降序；这不是按编号或全局首次出现排序。
4. 检查声纹文件确实写入配置的库，且服务和 CLI 使用同一路径。通过后再处理长会议。

`make check` / `make smoke` 是开发回归，不替代以上安装验收；修改代码准备 PR 时按 AGENTS 要求运行。

## 迁移已有数据与常见故障

迁移时同时保留原始媒体、会议目录、人工修改历史和完整声纹库（含 bank.json、向量及组织/术语资料）。
内置模型是通用权重，不能恢复个人声纹库。复制前后比对文件数量、大小和校验和；不能用“目录存在”判定成功。
发现关键 JSON 或向量是零字节时先从有效备份恢复。外部媒体路径和软链接需要在新机重新核对，不能仅复制链接本身。

| 现象 | 先检查 | 处理方向 |
|---|---|---|
| 确认身份报“找不到这个声音组”/404 | 会议 voice ID 是否存在于 Web 实际读取的库，管线是否写到另一目录 | 备份两边后核对来源；不能直接覆盖或拼接两个库，重复 ID 可能指向不同声音 |
| 绑定返回“没有精确命中”/409 | 是否选择了已有人员，还是输入新名字 | 新名字用“新建人员并确认”，不需要重装模型 |
| PR 已合并但排序未变化 | 服务工作目录、提交、实际返回的 app.js | 按运维入口安全升级；确认服务资源更新后再硬刷新 |
| import torch 正常但 GPU 计算崩溃 | 平台构建与安装前后版本 | 回到第 0–2 节验证平台栈 |
| 能打开网页但处理失败 | 是否仅安装 Web 依赖、环境是否加载、模型 ID 是否存在 | 完成第 2–5 节，不把网页打开当作安装完成 |

## NVIDIA 测试矩阵

每张卡至少记录下表，便于判断是代码、驱动、显存还是模型量化问题：

| 项目 | 记录内容 |
|---|---|
| 机器 | OS、内核、CPU、RAM、GPU、VRAM |
| 运行时 | NVIDIA driver、CUDA runtime、PyTorch、llama.cpp commit |
| 模型 | ASR/aligner/pyannote/text/VL 名称、量化、context |
| 正确性 | ASR 可读性、speaker 数、逻辑页数、纪要/Topic Map 是否 ready |
| 性能 | ASR、diarization、VL、minutes、Topic Map 各阶段秒数 |
| 资源 | 各阶段峰值 VRAM、系统 RAM、是否发生 OOM/交换 |
| 降级 | BF16→FP16、降低 GPU layers、关闭 VL 后的结果 |

建议优先测试 16 GB、24 GB 和 32 GB+ 三档 NVIDIA 显存。16 GB 卡通常不能同时完整承载当前 35B 文本模型与 VL，需要更小量化、分层 offload 或按需换模；这属于部署容量规划，不是 AMD 代码依赖。

## Web 常驻

`deploy/meeting-minutes-web.service.example` 是 systemd 示例。复制前必须修改 `User`、`WorkingDirectory`、环境文件和数据目录；服务仍只监听 `127.0.0.1`。未来给同事开放上传/阅读时，应在外层增加企业身份、会议级 ACL、TLS、配额、审计和生命周期，不能直接把 8899 或模型端口暴露到局域网。

优雅退出：收到 SIGTERM 后应用最多等待 `MEETING_WEB_GRACEFUL_SHUTDOWN` 秒（默认 8）让在途连接排空，超时由 uvicorn 强制关闭剩余连接；systemd 侧 `TimeoutStopSec=15` 作为兜底。浏览器长连接不再把部署重启挂住；正在执行的后台作业在下次启动时仍按既有规则标记为中断并走恢复流程。
