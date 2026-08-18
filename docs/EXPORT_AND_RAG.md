# 纪要结论、证据链接、MeetingPack 与 RAG 规范

本规范定义同一份会议资料如何生成可读纪要、离线分享包和后续 RAG 记录。核心目标是：读者看到的是简洁纪要，系统保留的是可追溯证据；三种产物不能各自维护一套事实关系。

MeetingPack v5 可携带导出时已经生成且仍绑定当前 revision 的中文/英文纪要、会议脉络以及屏幕标题/短摘要。Viewer 右上角离线切换这三层阅读文本；离线端不调用 LLM，未提前生成的语言明确不可选。兼容入口保留为 `assets/minutes.md` 与 `assets/topic-map.json`，语言版本另存为 `assets/minutes.{language}.md`、`assets/topic-map.{language}.json` 和 `assets/visuals.{language}.json`。

Web bundle 和内嵌 Viewer payload 还带 `speaker_navigation[]`，每项只有 `speaker/selectable/identity_basis`。`verified_voice_binding` 才表示跨会议稳定人员；`imported_transcript_label` 表示 VTT/DOCX 在本场明确提供姓名，可按完全同名聚合；`session_voice_cluster` 表示未命名但已有 `voice_id`，可按本场声音簇跳播；只有 `insufficient_voice_sample`（片段过短、没有声音簇）不可选择。该阅读投影不写回 bank、不产生假的 `person_id`，也不改变 RAG 以 canonical evidence 为准的身份规则。

## 1. 结论策略

### 1.1 不采用“职级越高，内容权重越高”

职级不是事实准确度，也不是议题所有权。全局按职级给发言乘权重，会产生三个错误：

- 高职级的探索性提问或建议被误写为决定；
- 一线负责人给出的关键事实和执行约束被压低；
- 跨团队会议中，组织层级和本议题决策权并不等价。

系统改用“证据门槛 + 权限语境”模型：

| 内容类型 | 主判定信号 | 职级/岗位作用 |
|---|---|---|
| 已确认结论 | 明确决定/批准措辞；议题责任人作出，或多人明确确认；没有仍未解决的反对 | 只辅助判断发言者是否可能有确认权限，不能单独升级状态 |
| 方向共识 | 多人接受同一方向，但范围、权限或最终确认不完整 | 不改变 `working_alignment` 状态 |
| 提议/方案 | 建议、偏好、假设、待批准选项 | 即使由高职级人员提出，仍是 `proposal` |
| 行动项 | 整场待办章节中的明确动作、责任接受、负责人/责任团队，并带逐字稿依据 | 不参与判定；未说明的期限写“待确认”；逐页过程记录不得晋级正式待办 |
| 风险/待确认 | 影响、紧迫性、分歧和未解决程度 | 不参与判定 |

结论状态固定为：

- `confirmed`：已明确决定或批准；
- `working_alignment`：方向性共识，仍需最终确认；
- `proposal`：建议、方案或偏好；
- `open`：问题、风险或分歧未解决；
- `informational`：状态汇报、事实陈述或展示资料，不是决定。

人员信息通过已确认的 `voice_id → person_id → org node` 关系进入 Prompt。旧数据没有 `person_id` 时，只允许唯一、精确的已确认名称关联；不进行模糊匹配。传给模型的岗位字段使用 `authority_context=role_context_only`，明确禁止模型把它当成事实权重。

### 1.2 VL/PPT 内容如何进入纪要

VL 页面理解和逐字稿承担不同职责：

- 逐字稿证明“会上说了什么”；
- VL 证明“页面展示了什么”，并帮助核对标题、术语、数字和议程结构；
- 页面内容不能单独证明“会议决定了什么”。

展示分三层：

1. 常规纪要只引用与讨论、结论或行动相关的页面，不在正文底部重复逐页资料；
2. 在线会议脉络把整场内容归并为 3–8 个一级议题和类型化子节点；节点绑定逐字稿、结论和页面依据，并可跳到同一议题的多个非连续时间范围；
3. 屏幕内容以“缩略图 + 标题 + 信息价值 + 讨论状态”列出全部逻辑页面，并保留完整 VL 解释。没有对应逐字稿的页标记为“仅展示”，有对应发言的页标记为“有讨论”。

生成阶段的 canonical `minutes.md` 目前仍可保留“分页详情”作为证据构建输入，但 Web 和 MeetingPack 使用确定性的常规纪要投影；逐页事实继续保存在 `evidence.json`、Visual 和 RAG，不会丢失整套 deck，也不会把页面上的目标、方案或数字误写成会议共识。

带录屏管线会先发布仅基于 turns/说话人的语音草稿，再用 pages/VL 生成多模态终稿。草稿 evidence 的 `generation_stage=voice_draft` 并保存独立快照；终稿为 `generation_stage=final`。MeetingPack 只允许在 `meeting-generation/v1.phase=ready` 后导出，因为离线包没有后续自动替换机制，不能把临时草稿当成可分享定稿。

## 2. Prompt 传输结构

文本模型不再接收拼接的自由文本，而是接收 `meeting-minutes-prompt/v1` JSON：

```json
{
  "schema": "meeting-minutes-prompt/v1",
  "speaker_profiles": [
    {
      "speaker": "Synthetic Director",
      "voice_ids": ["v_test"],
      "person_id": "p_test",
      "identity_basis": "verified_voice_binding",
      "title": "Director",
      "team": "Synthetic BU",
      "org_depth": 1,
      "authority_context": "role_context_only"
    }
  ],
  "pages": [
    {
      "id": "P0001",
      "number": 1,
      "first": 0.0,
      "ranges": [[0.0, 20.0]],
      "visual_summary": "页面主题摘要",
      "visual_detail": "仅在逐页生成时传输的完整 VL 解释"
    }
  ],
  "turns": [
    {
      "id": "T000001",
      "index": 0,
      "start": 1.0,
      "end": 3.0,
      "speaker": "Synthetic Director",
      "voice_id": "v_test",
      "person_id": "p_test",
      "page_id": "P0001",
      "text": "我建议先做试点，最终决定下周再确认。"
    }
  ]
}
```

总体摘要只传每页最多 500 字的视觉摘要，避免长 deck 挤占上下文；逐页生成一次最多处理 8 页，并传这些页面的完整 VL 解释。模型输出中的事实条目带隐藏标记：

```markdown
- 先做试点仍是待确认提议。 <!-- mm:evidence kind=alignment status=proposal confidence=high turns=T000001 pages=P0001 -->
```

Web 和查看器把它显示成很轻的“依据”链接；原始 Markdown 仍可自然阅读。marker 中只能使用输入提供的 ID，服务端会过滤不存在的 ID。大模型全文精修只有在页结构完整且全部 marker 逐字、顺序不变时才会被接受。

marker 是“模型手写、代码解析”的协议，模型会发明各种包装：包在反引号里（`` `<!-- mm:evidence … -->` ``）、或独占待办表格的状态列。所有消费端都必须先剥离这类包装再解析：`markdown_with_evidence_links` 用 `WRAPPED_MARKER_RE` 连带剥掉反引号，`_action_fields` 对“marker 占状态列”的三单元格行按事项/负责人/期限拆分、状态交 claim_status 兜底；修解析器时同步给存量 sidecar 留读路径重拆兜底，避免要求重跑模型。

T/P/C ID 是机器 linkage，不是员工、Teams 或组织身份。人读纪要、译文和证据抽屉只显示“依据 + 时间 + 说话人/页码”；模型偶发写出的 `（T000001, T000002）` 尾注在阅读投影与导出时确定性剥离。隐藏 marker、`evidence.json`、`transcript.json` 和 RAG 记录继续保留原 ID，因而隐藏编号不会损害跳转、审计或后续索引。正式行动只允许从 canonical 待办章节投影；如果待办写“无”而其他章节存在 action marker，生成端将其视为协议冲突并重试/定点修复，不能把明确行动静默降成九条无依据候选。

## 3. Canonical sidecar

每次生成纪要会同时写出 `minutes.evidence.json`（schema：`meeting-minutes-evidence/v1`）：

- `revisions`：逐字稿、纪要、页面时间线和 VL 缓存的内容 revision；
- `meeting_id`：同一会议的稳定 ID；`artifact_id`：由逐字稿与纪要 revision 共同决定的产物版本 ID；
- `policy`：生成时使用的结论策略版本；
- `speaker_profiles`：本次生成实际使用的身份/岗位语境；
- `sources.transcript`：稳定 T ID、时间、说话人、person、页面和原文；
- `sources.pages`：稳定 P ID、图片、完整 VL 解释、讨论轮次和 `display_status`；
- `claims`：稳定 C ID、可读文本、类别、状态、置信度、T/P 证据和时间范围；
- `actions`：从 `kind=action` claim 确定性投影的事项、负责人、期限、状态和 claim/T/P linkage；Web、Viewer 和 RAG 不需要反向解析 Markdown 表格；
- `linkage`：有多少 claim 具备逐字稿或页面关联。

行动项在可读 `minutes.md` 中仍保留 Markdown 表格，便于复制和分享；生成端会固定表头，渲染端会修复旧纪要中“列表项紧贴表格”等确定可判定的语法问题。结构化 `actions` 才是后续 Viewer、RAG 和任务系统集成的机器接口。

Web 只在 sidecar 的逐字稿和纪要 revision 与当前文件一致时展示“依据”，避免编辑后误指向旧内容。说话人绑定、首选显示名变更、纪要应用或撤销后，由确定性代码刷新 sidecar，不调用模型。

## 4. MeetingPack v5

分享格式是普通 ZIP，文件名后缀为 `.meetingpack.zip`。收件人解压后双击 `viewer.html`，不需要安装本项目、不需要运行服务，也不需要 LLM。查看器没有 CDN、外部字体或 `fetch` 依赖，使用 `file://` 即可。

```text
<meeting>_<meeting-date>_v<product-version>_<export-time>.meetingpack.zip
├── viewer.html             # CSS/JS/数据内嵌的静态查看器
├── README.txt
├── AGENTS.md               # 给 AI agent 的使用指引：文件地图 + 引用规则 + 任务菜谱
│                            # （单场深读 / 同系列多场对比 / 会后产出 / 建索引 / 事实核对）
└── assets/                 # 所有依赖统一收纳；顶层不再散落机器文件
    ├── manifest.json       # meetingpack/v5、文件哈希、证据与媒体策略
    ├── minutes.md          # 常规阅读版纪要 + 隐藏 marker
    ├── transcript.md       # 带可读时间码的完整逐字稿
    ├── transcript.json     # 结构化完整逐字稿
    ├── evidence.json       # canonical 证据关系
    ├── topic-map.json      # meeting-topic-map/v3 整场语义脉络（v1/v2 旧图仍可消费）
    ├── minutes.{language}.md
    ├── topic-map.{language}.json
    ├── visuals.{language}.json # 屏幕页号、标题和短摘要；不复制完整 VL
    ├── rag/
    │   └── records.jsonl   # meeting-minutes-rag/v1
    ├── slides/
    │   └── ...             # 长边 1600px WebP 阅读图（按放大预览窗设计），不包含 VL full_* 工作帧
    └── media/              # 默认不存在
        ├── audio.m4a       # --media audio：AAC 40kbps 分享版
        └── video.mp4       # --media video：H.264 720p/10fps 分享版
```

例如 `Project_review_2026-08-18_v0.8.2_20260818-153000.meetingpack.zip`。文件名中的产品版本来自根目录 `VERSION`，导出时间保证同一会议多次导出可并存。`README.txt` 和 `assets/manifest.json.generator.version` 同时记录生成器版本；Viewer 顶栏也显示该版本。

Viewer 提供四个任务入口：“会议脉络 / 会议纪要 / 逐字稿 / 屏幕内容”，右侧证据以抽屉按需打开。脉络、纪要和屏幕属于全宽浏览态；进入逐字稿才切成左侧媒体/截图内容舞台与时间轴、右侧完整逐字稿和发言级核听控制。浏览期间如果媒体仍在播放，只保留紧凑悬浮播放器。顶部搜索按当前入口限定到脉络节点、结论、逐字稿轮次或屏幕资料，并分别保留关键词。冻结的 `meeting-topic-map/v3`（兼容 v1/v2 旧图）通过质量门槛（`ready` 且 3–8 个一级议题）时默认打开会议脉络，否则安全回退会议纪要。v3 中 `turn_ids` / `evidence_ranges` 是代表论据，供审计和 RAG 回溯；`navigation_turn_ids` / `ranges` 是完整浏览范围，供时间轴、Focus 和播放器定位；顶层 `navigation_segments` 显式保留 `topic`、`transition`、`unclassified` 三类整场序列。`stats.coverage` 是归入业务议题的轮次比例，静音不再拉低该值，实际发言时间比例另见 `time_coverage`。Viewer 与在线端都以灰色斜纹显示过渡/等待、以琥珀色显示尚未分类，绝不把未知内容延长到最近议题。脉络首屏只展示一级议题，选择分支才展开子节点和节点说明；选择节点只建立横跨时间范围、逐字稿、结论和屏幕的 Focus，不自动播放，只有显式时间入口才进入核听并 seek。Viewer 时间轴与在线端同为“Topic 车道 + 说话人像素桶节奏条 + 人物图例 + 可展开逐人车道”，未绑定说话人灰斜纹沉底（离线不可绑定），逐字稿长发言拆成带独立近似起止时间的核听段落，后续段重复说话人并标注“同一发言 · N/M”；上一段、重播、下一段及个人跳播都按可见段落工作。无视频时，截图内容舞台会随音频播放或时间选择切换。“屏幕内容”按缩略图、标题、状态和完整 VL 解读浏览。必须解压整个 ZIP 后再打开，不能只在压缩软件里预览单个 HTML。

导出不再生成 `views.json`；受众/深度重排并未产生新事实，却会让收件人在阅读前先理解模式。如后续需要“管理层版”，应当在导出时明确生成一份独立成品，而不是在离线 Viewer 中平铺四个重排入口。RAG 的 `minutes_section` 只取 Viewer 同款常规纪要，逐页事实由独立的 claim/slide 记录保留，避免重复收录旧纪要中的逐页生成过程或 reasoning 污染。旧会议没有有效 evidence marker 时，包仍包含完整逐字稿、媒体与纪要，但 `manifest.evidence.state=partial`，Viewer 显式提醒“结论不可逐条核验”，不会把 `claims=0` 伪装成完整导出。导出过程只读会议目录，不会为方便打包而重写 `minutes.evidence.json`。

`page_desc.json` 保持 canonical 原始输出；导出投影使用与在线端相同的 `clean_model_text()` 和 `visual_title()`。清洗后的文本才进入 `evidence.json`、Viewer 内嵌数据和 RAG。如果去掉未闭合 reasoning 后没有可靠答案，标题回退为“第 N 页屏幕内容”，不从推理过程猜标题。

### 4.1 是否需要传源视频

默认不需要。纪要阅读、页面浏览、逐字稿检索和 RAG 都由 `assets/minutes.md + assets/evidence.json + assets/topic-map.json + assets/slides + assets/rag/records.jsonl` 完成。源视频通常体积最大，并不会提高文本检索质量。

应用中的原始媒体是项目母版；MeetingPack 中的音视频只是面向分享的派生副本。导出不会覆盖或重新编码项目母版：音频统一生成 AAC 40kbps，视频生成 H.264 720p/10fps，屏幕图生成长边 1600px、quality 80 的 WebP（按 Viewer 放大预览窗尺寸设计，支持 125–300% 缩放阅读）。以 78 分钟会议估算，AAC 约 24–27MB；视频大小依画面变化量而异。需要逐像素、原码流审计时应访问项目母版，而不是把 MeetingPack 当作原始档案。

当前 Gate B 实测：无媒体包 2.52MB；AAC 包 23.60MB，相比 149.55MB PCM 工作音轨减少约 84%；视频包 40.27MB，其中分享视频 37.74MB，相比 206.92MB 母版减少约 82%。这些是实际内容的参考值，导出预检仍按每场会议时长和源媒体单独估算。

只有以下情况建议包含媒体：

- 同事需要直接试听语气或处理说话人争议：包含音频；
- 需要审计动态演示、动画过程或非幻灯片画面：包含视频；
- 包作为正式留档，需要在离线环境复核原始证据：包含视频。

Web“更多”菜单提供三种导出；命令行等价用法：

```bash
.venv/bin/python bin/export_meeting.py meetings/<会议>/ --media none
.venv/bin/python bin/export_meeting.py meetings/<会议>/ --media audio
.venv/bin/python bin/export_meeting.py meetings/<会议>/ --media video
```

## 5. RAG 使用方式

`assets/rag/records.jsonl` 每行是独立 JSON，`record_type` 包括：

- `claim`：结论、共识、行动、风险等可读归纳，带 `evidence_ids`；
- `transcript`：单轮原文，带时间、说话人、person 和页面；
- `slide`：完整页面理解，带 `display_status` 与讨论轮次；
- `minutes_section`：适合宽泛主题检索的可读章节。

推荐索引与检索流程：

1. 对所有记录的 `text` 建全文或向量索引，并把其余字段作为 metadata；
2. 用户问决定/行动时优先检索 `claim`，问“谁在何时说了什么”时优先检索 `transcript`，问 deck 内容时检索 `slide`；
3. 命中 claim 后，按 `evidence_ids` 精确读取对应 T/P source，而不是再次用向量猜来源；
4. 回答展示 claim，同时给出发言时间、说话人和页面；`display_only` 页面必须标成“材料展示”，不能表述为会议决定；
5. `retrieval_priority` 只用于召回排序，不代表真实性。`confidence` 是纪要归纳置信度，也不能覆盖原始证据；
6. `meeting_id` 用于把同一会议的不同版本归组；每条记录 ID 以 `artifact_id` 为前缀。逐字稿或纪要变化会产生新的 `artifact_id`，旧包与旧索引记录保持不可变，便于审计或显式清理旧版本。

不建议从渲染后的 HTML 或 Markdown 脚注反向解析 RAG。`assets/evidence.json` 和 `assets/rag/records.jsonl` 才是机器接口。

### 5.1 当前本机 RAG 服务

Web 的会议助手使用 `meeting-rag/evidence-hybrid-v1`：在一场会议内统一召回 claim、逐字稿、VL 页面和纪要章节，再把受控上下文交给本机 LLM。命中 claim 或讨论过的页面时会补入少量原始逐字稿，避免回答只引用二次归纳。显式选择的逐字稿及其相邻语境始终优先。

`POST /api/meetings/{slug}/rag/search` 只返回召回来源，不调用 LLM，可用于检查为什么命中这些证据；`assistant/chat` 在其上完成生成式回答。旧会议没有 `mm:evidence` marker 时标记为 `partial`，仍能检索逐字稿和纪要章节，但不能伪装成已建立 claim linkage。

当前本机检索顺序为：

1. 对 claim、逐字稿、页面和分块后的纪要章节同时执行词法 BM25 风格检索与 Qwen3-Embedding-0.6B 稠密检索；
2. 用 Reciprocal Rank Fusion 合并两路结果，避免某一路分数尺度支配排序；
3. 把前 36 个候选交给 Qwen3-Reranker-0.6B，保留前 28 个进入类型配额和证据扩展；
4. 命中 claim 或页面后按稳定 T/P ID 精确补回原始逐字稿，而不是再用向量猜证据；
5. embedding 或 reranker 服务不可用时自动降级，最差仍保留词法检索和显式引用。

每场会议的向量索引保存在私有会议目录 `.rag/`：JSON manifest 只含模型名、记录 ID、revision 和维度，`.f32` 文件只含向量，不复制逐字稿正文。逐字稿或纪要变化会让 `record_revision` 改变并自动重建该会议。部署后可以主动预热：

```bash
make rag-index
```

两个 0.6B 模型分别由 loopback systemd user service 常驻在 `127.0.0.1:11437` 和 `127.0.0.1:11438`。服务使用单并发、4K context、关闭额外 prompt cache，并设置 `MemoryHigh=3G`、`MemoryMax=5G`；Web 健康接口公开模型状态但不公开会议正文。测试中 `retrieval_mode` 会明确返回 `hybrid_reranked`、`hybrid` 或 `lexical`，便于排查是否发生降级。

MeetingPack 中的 `assets/rag/records.jsonl` 是可移植的索引原料，不等于一个可运行的 RAG 服务。纯 `file://` Viewer 可以离线全文搜索，但若要生成回答，必须满足以下之一：

- 连接部署在有算力机器上的受控 RAG/LLM 服务；
- 接收方本机运行模型；
- 在导出时预生成固定阅读视图，不提供自由问答。

默认产品同时保留第三种完全离线路径。中心智能版需要额外的网络可达、鉴权、会议级权限和撤销访问机制；当前只部署在 `127.0.0.1`，不得把无鉴权接口直接暴露到 LAN 或公网。

## 6. 隐私和版本边界

- MeetingPack 是分享副本，会包含逐字稿正文、页面解释、人员显示名和可能的岗位/团队信息；发送前应按会议保密级别判断接收范围。
- 默认不打包本机原始路径、声纹向量、声纹试听样本、完整 Org Chart 或 LLM 服务配置。
- `assets/manifest.json` 记录包内文件 SHA-256，便于接收方验证内容是否被替换。
- 后续 schema 变更必须增加版本，不得静默改变现有字段语义。
