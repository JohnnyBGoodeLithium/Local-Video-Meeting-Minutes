# 跨机器与 GPU 部署

## 结论

项目业务代码不依赖 AMD。当前机器使用 ROCm，但 PyTorch 的 ROCm 构建同样暴露 `torch.cuda` 设备 API；项目现在会把实际 backend 诊断为 `rocm` 或 `cuda`，并按显卡能力选择 BF16/FP16。迁移到 NVIDIA 的关键不是改业务流程，而是安装 CUDA 版 PyTorch、CUDA 版 `llama.cpp`，并配置模型路径。

| 层 | NVIDIA | AMD | CPU |
|---|---|---|---|
| ASR / pyannote | PyTorch CUDA | PyTorch ROCm | 可运行，明显更慢 |
| 文本/VL GGUF | llama.cpp CUDA backend | llama.cpp HIP/ROCm backend | llama.cpp CPU backend |
| Python 业务代码 | 相同 | 相同 | 相同 |
| 默认 dtype | 支持 BF16 则 BF16，否则 FP16 | 支持 BF16 则 BF16，否则 FP16 | FP32 |

PyTorch 官方也明确说明 ROCm 构建沿用 `torch.cuda.is_available()` 语义；安装时应在官方选择器中选择与机器匹配的 CUDA、ROCm 或 CPU 构建：[PyTorch Start Locally](https://docs.pytorch.org/get-started/locally/)。`llama.cpp` 官方构建文档分别提供 CUDA 与 HIP backend：[Build llama.cpp locally](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)。

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
git clone <private-repository-url> meeting-minutes
cd meeting-minutes
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
```

先从 PyTorch 官方选择器安装目标机器对应的构建，再安装项目。顺序很重要：`pyannote.audio` 会依赖 PyTorch，提前安装正确构建可避免被通用 wheel 替换。

```bash
# 这里执行 pytorch.org 为目标 CUDA/ROCm 给出的命令
.venv/bin/python -c 'import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda, torch.version.hip)'

.venv/bin/pip install -e .
.venv/bin/pip install -e '.[pipeline]'
```

不建议把某个 CUDA 或 ROCm wheel 固定进 `pyproject.toml`：那会使另一类显卡无法安装。

## 3. 安装 llama.cpp

目标是让 `llama-server` 位于 `PATH`。按照官方构建文档选择 backend：

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

复制 [环境变量示例](../deploy/meeting-minutes.env.example)，把路径改成目标机器实际位置。关键变量：

| 变量 | 默认 | 作用 |
|---|---|---|
| `MEETING_DEVICE` | `auto` | `auto/cpu/cuda/cuda:0`；ROCm 也写 `cuda` |
| `MEETING_TORCH_DTYPE` | `auto` | `auto/fp32/fp16/bf16` |
| `MEETING_ASR_MODEL` | 用户模型缓存 | Qwen3-ASR 路径 |
| `MEETING_ALIGNER_MODEL` | 用户模型缓存 | ForcedAligner 路径 |
| `MEETING_PYANNOTE_MODEL` | 用户模型缓存 | pyannote pipeline 路径 |
| `MEETING_LLM_API` | `http://127.0.0.1:11435/v1` | OpenAI-compatible 文本端点 |
| `MEETING_LLM_MODEL` | `qwen3.6-35b-a3b-operator` | AI 对话、翻译与通用文本模型 ID |
| `MEETING_DRAFT_MODEL` | 跟随 `MEETING_LLM_MODEL` | 视频会议早期语音草稿模型 ID |
| `MEETING_MINUTES_MODEL` | `qwen3.8-27b-minutes` | 纯音频正式纪要与多模态终稿模型 ID |
| `MEETING_RECOVERY_REFINE_MODEL` | 未设置 | 高质量恢复/精修模型 ID；大模型机器可设 `gpt-oss-120b` |
| `MEETING_TERMINOLOGY_MODEL` | 跟随 `MEETING_LLM_MODEL` | 从已完成屏幕说明提取下一场 ASR 候选的本地模型 ID |
| `MEETING_LLM_CONTEXT_SIZE` | `65536` | 长会切分预算依据 |
| `MEETING_VL_MODEL` | 当前用户 Miloco 路径 | VL GGUF |
| `MEETING_VL_MMPROJ` | 当前用户 mmproj 路径 | VL projector |
| `MEETING_VL_PORT` | `11436` | VL loopback 端口 |
| `MEETING_VL_WORKERS` | `2` | VL 逐页解读的并发请求数；需与 VL 服务 `--parallel` 槽位匹配 |
| `MEETING_VL_GPU_LAYERS` | `999` | llama.cpp GPU offload；显存不足可降低 |
| `MEETING_DATA_ROOT` | 仓库根 | 私有会议数据根 |
| `MEETING_BANK_DIR` | `<MEETING_DATA_ROOT>/speaker_bank` | 可选的独立声纹/身份/术语私有目录；兼容旧 `MEETING_WEB_BANK` |
| `MEETING_PYTHON` | 当前解释器/Web venv | 作业子进程解释器 |

文本服务示例：

```bash
llama-server --model /models/text-model.gguf \
  --host 127.0.0.1 --port 11435 --ctx-size 65536 \
  --gpu-layers 999 --flash-attn auto --jinja --no-webui
```

本机需要同时提供快速草稿、27B 正式纪要和可选 120B 精修时，使用 llama.cpp router preset；
仓库提供不含机器路径的 [预设模板](../deploy/llama-models.ini.example)。模板中的 section 名就是 API
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

术语私有数据位于数据根的 `speaker_bank/terminology.json`（人工确认）和 `terminology.candidates.json`（自动候选），两者都不得进入 Git。仓库只提供不含人员信息的 `speaker_bank/terminology.template.json` 示例。历史会议回填会调用本机文本服务且只输出数量：

```bash
.venv/bin/python bin/meeting_terminology.py backfill meetings
```

回填不是批量纠错：它不读取或改写 canonical 逐字稿，只从已有 `page_desc.json` 建候选。部署验收应对同一段脱敏音频分别运行默认 context 与 `--no-context`，记录目标术语召回、普通词误识别和 ASR 阶段耗时。

## 5. 首次验收

```bash
make doctor
.venv/bin/python bin/doctor.py --profile all --json
make check
make smoke
```

`doctor` 应显示：

- NVIDIA：`backend=cuda`、`torch.version.cuda` 非空、`torch.version.hip` 为空；
- AMD：`backend=rocm`、`torch.version.hip` 非空；
- 模型路径存在，`llama-router` 可达；
- `hardware_test.py` 验证 NVIDIA FP16 回退、AMD BF16 和 CPU FP32 选择。

之后只用一段经过脱敏、约 3 分钟的测试媒体跑端到端。不要把真实会议复制到第三方测试机。通过后再做 30–60 分钟 soak test。

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
