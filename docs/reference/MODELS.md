# 机型 Portfolio × 可用模型 × 可提供服务

验证矩阵：每档机型回答三件事——**什么模型验证可跑 → 能开哪些服务 → 慢多少/缺什么**，以及升降级路径。
验证状态：✅=本机实测；📐=按参数量/量化体积推算（未实测）。

Python 管线不绑定 AMD：NVIDIA 使用 PyTorch CUDA，AMD 使用 PyTorch ROCm，两者在代码中
都遵循 `torch.cuda` 设备语义。`meeting_core.hardware` 会诊断真实 backend，并在 NVIDIA
不支持 BF16 时回退 FP16。GGUF 文本/VL 层依赖目标机器对应的 llama.cpp 构建：NVIDIA
使用 CUDA backend，AMD 使用 HIP backend。模型路径与 dtype 不应写死，配置和验收见
[跨机器与 GPU 部署](../runbooks/DEPLOYMENT.md)。

## 1. 模型池（按管线角色）

| 角色 | 模型 | 体积 | 备注 |
|---|---|---|---|
| 语音转写 | Qwen3-ASR-1.7B | 4.4G | ROCm GPU ✅；原生 context 注入已确认/跨会重复术语；CPU 可跑约 3–6× 实时 📐 |
| 字级对齐 | Qwen3-ForcedAligner-0.6B | 1.8G | 随转写加载 ✅ |
| 说话人分离+声纹 | pyannote community-1 | 33M | GPU/CPU 均可 ✅ |
| 语音草稿/AI 交互 | Qwen3.6-35B-A3B Q4_K_M（MoE 3B 激活） | 22G | 低激活量，优先保证草稿和交互速度 ✅ |
| 正式纪要（标准） | Qwen3.8-27B Q6_K（dense） | 22.9G | 本机 llama.cpp 路由加载与非 thinking 输出已验证 ✅ |
| 纪要文本（中杯替代） | Qwen3-14B / GLM-Flash 级 Q4 | 9–18G | 16G 档的现实选择 📐 |
| 纪要文本（小杯替代） | Qwen3-8B 级 Q4 | ~5G | 8G 档选择 📐 |
| 纪要精修（重写） | Qwen3.5-122B-A10B Q4_K_M / gpt-oss-120b Q4 | 72G / 59G | 仅 A 档；路由器按模型名自动加载 ✅ |
| VL 画面解读 | MiMo-VL-Miloco-7B Q4_0 + mmproj | 5.5G | ✅ |
| VL 备选 | Qwen3-VL-8B Q8_0 | 8.9G | ✅ 质量略高、更慢更贵 |
| 会议检索 | Qwen3-Embedding-0.6B Q8_0 + Qwen3-Reranker-0.6B Q8_0 | GGUF 各 0.64G | 多语言混合召回与重排 ✅ |

pyannote 路径统一按以下顺序解析：`MEETING_PYANNOTE_MODEL` → 应用目录内
`models/pyannote/speaker-diarization-community-1` →
`~/.local/share/models/hf/pyannote/speaker-diarization-community-1`。全部不存在时直接返回“Speaker model is not installed locally”，不触发 Hugging Face 下载或隐式登录。

应用发布包永远不含模型权重。单独的 Diarization Runtime Pack 构建器要求锁定 upstream ID/revision，列举所有 submodel，并为每项提供已核实的 license、attribution 与 redistribution terms；任一项不明确就拒绝生成。`community-1` 页面标注 CC BY 4.0 且支持离线克隆，但真实 pack 的子模型和分发条件尚未逐项核实，因此本仓库未构建或发布 official model pack。这是工程门禁记录，不是法律意见。

## 2. 档位矩阵

### A 档：统一内存大盒（本机 Strix Halo 96G VRAM / 124G RAM）✅ 已验证
- **可用模型**：池内全部，含 Qwen3.8-27B 正式纪要与 120B/122B 精修。
- **可提供服务**：全量——转写+分离+逻辑页+VL 逐页解读+27B 正式纪要+Web 界面+声纹库+**120B/122B 精修重写**。
- **速度实测**：录音笔 24m35s 旧流程全链路 322s；51m20s Teams 会（复用 VTT 免转写）抽页 ~40s + VL 39页 ~19min + 旧 35B 纪要 ~2min。Qwen3.8-27B 已验证加载和输出，完整长会基准仍待补测；120B/122B 首次加载为分钟级，之后重写一遍纪要约 2–5min。
- **取舍**：无。

### B 档：M90t + RTX 5060Ti 16G 📐
- **可用模型**：ASR/Aligner/pyannote/Miloco VL 全上 GPU；文本二选一：
  - Qwen3-14B Q4（~9G，纯 GPU 全速）——**推荐**；
  - 35B-A3B Q4_K_M 内存卸载（需 64G 系统内存，估 5–10 t/s，纪要 2min→10-20min）。
- **可提供服务**：全管线但**严格串行**（转写/分离 → 抽页 → VL → 文本纪要错峰用卡）；无 122B 精修。
- **预计速度**：单会全链路约为 A 档的 1.5–3 倍。
- **取舍**：纪要质量（14B vs 35B）换速度；精修服务下线。

### C 档：M90t + RTX 5060Ti 8G 📐
- **可用模型**：文本降 Qwen3-8B Q4（~5G）；VL 与 ASR 不能同驻（5.5G+4.4G 超 8G）→ 严格串行或关 VL。
- **可提供服务**：转写+分离+抽页+8B 按页纪要+Web；VL 可选但慢（1280px 图，`--no-vl` 一键降级）；无精修。
- **取舍**：VL 画面层是首个可裁项；文本上限 8B。

### D 档：纯 CPU（M90t 无独显）📐
- **可用模型**：ASR CPU、pyannote CPU、8B Q4 文本（3–5 t/s）。
- **可提供服务**：转写+分离+基础纪要（无 VL、无精修）；Web 可用。
- **取舍**：只剩"文字主线"。

### 服务 × 档位速查

| 服务 | A 96G | B 16G | C 8G | D CPU |
|---|---|---|---|---|
| 转写+时间戳 | ✅ 全速 | ✅ | ✅ | 📐 慢 3-6× |
| 说话人分离+声纹 | ✅ | ✅ | ✅ | 📐 慢 |
| 逻辑页抽取 | ✅ | ✅ | ✅ | ✅ |
| VL 画面解读 | ✅ 全尺寸 | ✅ 串行 | 可选/1280px | ✘ |
| 按页纪要 | ✅ 27B Q6 | 📐 14B 或卸载 27B | 📐 8B | 📐 8B 慢 |
| 122B 精修重写 | ✅ | ✘ | ✘ | ✘ |
| Web 界面 | ✅ | ✅ | ✅ | ✅ |
| 本地 embedding + reranker | ✅ 常驻 | ✅ 可常驻/按需 | 建议按需或仅 embedding | 可用但应评估时延 |

### 升降级路径
- D→C（加 8G 卡）：GPU 转写/分离，纪要上 8B GPU，体验从"能用"到"顺手"。
- C→B（16G 卡）：解锁 14B 中杯全速、VL 稳定可用。
- B→A（统一内存 96G+ 大盒）：解锁 35B 全速并发、VL 全尺寸、122B 精修重写。

## 3. 精度与加载备注

- ASR context 不是转写后全文替换规则：标题和术语作为 provider 可选 context 参与声学/语言判断，最多 2400 字符；单场屏幕模型候选不会进入下一次转写，跨两场重复的高置信候选才允许复用。可用 `transcribe.py --no-context` 做基线 A/B。兼容端点不支持 context 时可在同一端点无 context 重试；跨 provider 回退必须显式配置。
- 第一遍完整 ASR 后，已确认术语的已知混淆写法最多触发 12 个短音频片段复核；二次声学结果明确支持标准术语才自动修正，否则留给人工核听。该增强失败不阻断第一遍结果，也不允许纪要/翻译 LLM 反向改写原语言逐字稿。
- 声纹识别不能独自解决插话切分：pyannote 只提供谁在何时发声，Qwen3-ASR 仍输出单路文字。当前合并器会保留有字级时间戳支持的短说话人段，同时过滤孤立标签抖动；两人真正同时发声且 ASR 没有输出第二路文字时，仍不能从声纹结果凭空恢复内容。
- 量化选择：文本 Q4_K_M 为甜点；VL 读小字建议不低于 Q4_0/Q8_0（Miloco Q4_0 与 Qwen3-VL Q8_0 实测均可，后者略准）。
- 122B/120B 由 llama-router 按请求里的模型名自动加载；资源护栏会把这类精修视为独占负载，先释放常规文本模型。首次加载通常明显慢于常规模型，结束后再按请求恢复。
- MoE 模型的"内存卸载"只在大统一内存或宽裕系统内存时有意义；8/16G 独显直放 dense 中小杯体验更好。
- 本机检索模型不进入大模型 router 的两模型 LRU，而是分别监听 `127.0.0.1:11437/11438`。两者均为单并发、4K context、`--cache-ram 0`，systemd cgroup 使用 3G soft / 5G hard 内存限制；预热 2545 条真实记录后的常驻占用约 1.6G + 1.0G。小内存机器可只常驻 embedding、让 reranker 按需启动，或把 `MEETING_RAG_MODE=lexical` 作为确定性降级。

双文本模型常驻是健康状态的上限，不是并发许可。默认可用内存 ≥32 GiB 时保留草稿/交互与正式纪要
两个模型；ASR、说话人、VL 或 WeKnora 后台增强开始前收缩为一个；低于 24 GiB 等待，低于 8 GiB
紧急卸载。阈值按机器通过环境变量调整，策略与部署见 `WEKNORA_INTEGRATION.md`。
