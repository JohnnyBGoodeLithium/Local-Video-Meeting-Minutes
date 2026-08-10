# 本地会议纪要管线（"钉钉闪记"的本地版）

目标：把录音笔/会议录音变成**带时间戳的逐字稿 + 结构化会议纪要**，全流程在本机完成，音频和文字不出机器。

工程文档：[系统架构](docs/ARCHITECTURE.md) · [产品与交互](docs/PRODUCT_UX.md) · [开发与验证](docs/DEVELOPMENT.md) · [工程走查](docs/ENGINEERING_REVIEW.md) · [模型矩阵](docs/MODELS.md)

## 为什么做这个

钉钉"闪记"这类功能好用，但录音和纪要都要上云。本项目的约束（来自 `~/agent-memory/PROFILE.md`）：录音、公司信息、未公开内容**优先本地处理**，云端模型需要每次显式授权。所以搭一条等价的本地管线。

## 目录结构

```text
meeting-minutes/
  recordings/                 # 录音笔原始 WAV(从 VTR5910 复制, 原件留设备上)
  meetings/                   # 每场会议一个自包含文件夹(可随便改名)
    2026-08-06_FY28-Gate-B-Pre-review-2nd-Round-Portfolio-Framework/
      audio.wav               # 16k 单声道音轨
      transcript.spk.md/json  # 具名/分说话人逐字稿
      minutes.md              # 纪要(Teams 场: 总体摘要+议题板块+逐页详情, 每页内嵌截图)
      slides/                 # 屏幕共享逻辑页截图(page_NN_t####s.jpg) + slides.json(页码时间线)
      samples/                # 声纹试听片段(voice_tool 生成)
    2026-08-06_171137/        # 录音笔会议: transcript.txt / stamps.json / transcript.ts.md
                              #   / diarization.json / transcript.spk.* / minutes*.md
  speaker_bank/               # 声纹库(个人数据, 云端不读)
    bank.json                 #   v3: 稳定人员 ID + 类型化名称 + 首选显示名；一人可挂多条声纹
    emb/v_XXXX.npy            #   声纹向量(质心, 不可还原成声音)
    orgchart.json             #   可选: BU 架构, 用户自放, 只被本地脚本读取
    orgchart.template.json    #   格式模板(假数据示例)
  bin/                        # 管线脚本
  .venv/  .cache/
```

## 用法

```bash
# 首次：建环境(已建好可跳过)
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
# 确认不会覆盖现有 ROCm torch 后，才安装管线依赖：
.venv/bin/pip install -e '.[pipeline]'
```

### Web 会议回顾工作台

```bash
.venv/bin/python web/server.py
# 或 make run
# http://127.0.0.1:8899/       打开已处理会议，阅读纪要、核对逐字稿、追问和修正
# http://127.0.0.1:8899/admin  人员身份 + 声纹试听/确认 + 图形化 org chart + 参考文件
```
左栏拖入 视频(可带同名 .vtt) 或 音频 即自动处理。详见 [web/README.md](web/README.md)。

会议详情左侧是常驻的播放证据栏：播放器、带页区间/议题标记的时间轴和逐字稿在同一列；右侧阅读纪要。底部助手可引用一轮或多轮逐字稿进行本地问答，回答带可点击时间来源。直接输入修改要求时，系统先展示可读的章节修改预览，只有用户确认后才写入，并支持立即撤销。

### 录音笔 WAV：一条命令

```bash
.venv/bin/python bin/run_all.py recordings/20260807113447.WAV --title 周会
# 转写与分离并行 → 轮次合并 → 分说话人纪要; 产出全部进 meetings/<日期>_<标题>/
```

分步：`bin/transcribe.py`(转写+字级时间戳) → `bin/diarize.py`(分离+合并) → `bin/summarize.py`(纪要, `--spk` 出分说话人版)。

### Teams 录制(带屏幕共享)

```bash
.venv/bin/python bin/teams_minutes.py meeting.mp4 meeting.vtt
# VTT 自带姓名: 远程参会者直接具名; 会议室设备通道按声纹拆成"声音K"
# 自动抽幻灯片逻辑页(屏蔽摄像头条→逐秒画面差→自适应阈值 max(2.0,p90×5) 切段,
#   build 小变化也能抓到→回翻认页→medoid 截图(与段签名最接近的帧,
#   动画播完且免疫并入段尾的 1-2s 闪断/黑帧杂质)
#   →段内运动中位>0.5 的摄像头画面(人坐一起)自动过滤不截图)
# 纪要是"按页"结构(bin/minutes_by_page.py): 逐字稿按"说话时显示哪页"切片 →
#   VL 层: 本地 Miloco-7B 视觉模型逐页详细解读(原生分辨率帧, 缓存 page_desc.json;
#   服务不在时自动拉起, 端口 11436; --no-vl 可关) →
#   总体摘要+议题板块(VL 读出的 agenda/章节标题锚定) → 逐页讨论要点/结论;
#   正文每页 = 截图+一行页面主题+讨论块, VL 详解全文收在文末"附录: 页面详解";
#   可选 122B 大模型整体精修(--refine-model, 或网页"大模型精修"按钮); 声纹自动入库

# 只重抽截图/换参数, 不动纪要文字(会删掉旧图片行再按时间线重贴):
.venv/bin/python bin/slide_pages.py meeting.mp4 --out meetings/<某会议>/slides \
    --update-minutes meetings/<某会议>/minutes.md

# 只重生成纪要(逐字稿/slides.json 已在, 旧纪要备份为 minutes.prev.md):
.venv/bin/python bin/minutes_by_page.py meetings/<某会议>/ --video 原视频.mp4   # 不带 --video 则用 slides/ 里 1280px 图给 VL

# VL 读页单独测试/评审(对照模型用):
.venv/bin/python bin/vl_page_test.py meetings/<某会议>/ --tag xxx --detail --video 原视频.mp4 [--pages 2,9,11]
.venv/bin/python bin/vl_report.py meetings/<某会议>/vl_test_xxx.json   # 生成图文对照 .md
```

### 无 VTT 的普通录屏

```bash
.venv/bin/python bin/video_minutes.py meeting.mp4 --slug 标题
# 转写走 Qwen3-ASR; 说话人是匿名"说话人K"(声纹入库但不建 person), 之后在网页/CLI 绑定
```

### 维护/修复

```bash
# 老会议逐字稿修复(空格回填+分离段平滑+重放合并+voice回填, 不重跑模型):
.venv/bin/python bin/repair_transcript.py meetings/<某会议>/

# 工程自检与隔离回归（不会读真实会议目录）
make doctor
make check
make smoke
```

### 声纹绑定(谁是谁)

```bash
.venv/bin/python bin/voice_tool.py sample meetings/<某会议>/   # 1) 每个声音切 ≤20s 试听片段
.venv/bin/python bin/voice_tool.py list                       # 2) 看库里的人和声纹
.venv/bin/python bin/voice_tool.py bind v_0003 "Peter Yuan"   # 3) 绑定（只接受唯一精确已确认名称）
.venv/bin/python bin/voice_tool.py alias "Peter Yuan" 彼得 Peter   # 加别名(多标签)
.venv/bin/python bin/voice_tool.py merge v_0003 v_0007        # 多条声纹并给同一人(拆过头时)
.venv/bin/python bin/voice_tool.py unbind v_0003              # 绑错了撤销
```

绑定一次，之后所有会议可通过声纹自动认人（余弦相似度 ≥0.70，`teams_minutes.py --match-threshold` 可调）。姓名绑定只接受唯一、精确的已确认名称；包含或近似匹配只展示候选，必须由用户选择或显式新建，不能自动归到相似人员。每个人可保存 Org Chart 原名、中文名、全拼、英文名加姓氏等类型化名称，并独立选择首选显示名。

org chart 也可以走 `/admin` 网页：上传架构 PDF → “提取草稿”（VL 逐页读姓名/岗位/汇报关系，不翻译、不补全拼音、不合并跨语言变体）→ 将草稿增量合并到图形画布 → 拖动节点确认上级 → 保存。未确认上级、重名与冲突保留为待人工处理项，不创建虚假上级。人员身份与岗位节点分离，新建人员会先进入“待放置人员”区。提取规范见 `prompts/orgchart_extract.md`；`bin/orgchart_mermaid.py` 可导出 Mermaid 层级图。

注意：所有脚本的 stdout 只打印元数据(耗时/数量/时长)，不打印转写、纪要或人名，防止内容进入云端 agent 上下文。

已知事项：

- pyannote 开源版无遥测，分离推理完全在本机；唯一接触 HuggingFace 的环节是最初下载 gated 模型(需账号授权，已完成)。若要无 HF 血统的替代，可走 ModelScope 的 FunASR/CAM++/3D-Speaker 组合。
- pyannote 配置 `min_duration_off=0.0` 会把静音段吸收进说话人段，所以分离报告的"说话总时长"含噪声段，偏高；分说话人逐字稿不受影响(只挂接真实转写文字)。
- 若说话人标签切换过频/人数偏多，说明聚类过度，可调高 `config.yaml` 的 `clustering.threshold`(默认 0.6)或用 `--num-speakers N` 指定人数。

实测(gfx1151 ROCm)：24m35s 录音笔文件全链路 **322s**(0.22× 实时)；51m20s Teams 会议 **286s**。首次跑会慢一倍左右(MIOpen 内核库冷启动)。

## 模型路径（已就位）

**模型清单、激活策略（内存×速度）、不同机型（如 M90t+5060Ti 16G/8G）的功能取舍见 [docs/MODELS.md](docs/MODELS.md)。**

- Qwen3-ASR：`~/.local/share/models/hf/Qwen/Qwen3-ASR-1.7B/`
- ForcedAligner：`~/.local/share/models/hf/Qwen/Qwen3-ForcedAligner-0.6B/`
- Whisper（对照，未跑）：`~/.local/share/models/hf/openai/whisper-large-v3-turbo/`
- 说话人分离：`~/.local/share/models/hf/pyannote/speaker-diarization-community-1/`
- VL 读页：`视频/joyai-test/models/MiMo-VL-Miloco-7B_Q4_0.gguf`（+ 同目录 mmproj；:11436 按需拉起）
- 备选 VL：`~/.local/share/models/hf/Qwen/Qwen3-VL-8B-Instruct-GGUF/`（Q8_0）

## 隐私红线

- `recordings/`、`meetings/`、`speaker_bank/`（含 org chart 与声纹）**不进任何云端服务**；这些目录的内容不发给云模型，云端 agent（含 Kimi Code）不读取其中数据文件——脚本 stdout 只出元数据。
- 需要云端能力时必须单独、显式授权，且只针对当前那次请求。

## 状态

- [x] 录音笔管线（转写/时间戳/分离/纪要，一条命令 `bin/run_all.py`）
- [x] Teams 管线（VTT 姓名对齐 + 房间声纹拆分 + 截图纪要，见 `bin/teams_minutes.py`）
- [x] 声纹库 v3 + 人员身份管理（国际化类型名称、独立首选显示名、精确绑定、后台试听与跨会议认人）
- [x] 本地会议助手（逐字稿引用问答 + 来源跳转 + 纪要预览/确认/撤销/版本备份）
- [x] 隔离测试数据根、环境 doctor、Git 私有数据边界与工程文档
- [ ] 与 Whisper 的对照评估
- [ ] 房间声音完成命名后的首轮跨会议验证
