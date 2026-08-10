# 纪要结论、证据链接、MeetingPack 与 RAG 规范

本规范定义同一份会议资料如何生成可读纪要、离线分享包和后续 RAG 记录。核心目标是：读者看到的是简洁纪要，系统保留的是可追溯证据；三种产物不能各自维护一套事实关系。

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
| 行动项 | 明确动作、责任接受、负责人、期限 | 不参与判定；未说明的负责人/期限写“不明” |
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

1. 总体摘要和正文只引用与讨论、结论或行动相关的页面；
2. 分页详情显示页面截图、一行页面主题和对应讨论；
3. `附录: 页面详解` 保留全部 VL 页面解释。没有对应逐字稿的页标记为“仅展示”，有对应发言的页标记为“有讨论”。

这样既不会丢失整套 deck 的信息，又不会把页面上的目标、方案或数字误写成会议共识。

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

## 3. Canonical sidecar

每次生成纪要会同时写出 `minutes.evidence.json`（schema：`meeting-minutes-evidence/v1`）：

- `revisions`：逐字稿、纪要、页面时间线和 VL 缓存的内容 revision；
- `meeting_id`：同一会议的稳定 ID；`artifact_id`：由逐字稿与纪要 revision 共同决定的产物版本 ID；
- `policy`：生成时使用的结论策略版本；
- `speaker_profiles`：本次生成实际使用的身份/岗位语境；
- `sources.transcript`：稳定 T ID、时间、说话人、person、页面和原文；
- `sources.pages`：稳定 P ID、图片、完整 VL 解释、讨论轮次和 `display_status`；
- `claims`：稳定 C ID、可读文本、类别、状态、置信度、T/P 证据和时间范围；
- `linkage`：有多少 claim 具备逐字稿或页面关联。

Web 只在 sidecar 的逐字稿和纪要 revision 与当前文件一致时展示“依据”，避免编辑后误指向旧内容。说话人绑定、首选显示名变更、纪要应用或撤销后，由确定性代码刷新 sidecar，不调用模型。

## 4. MeetingPack v1

分享格式是普通 ZIP，文件名后缀为 `.meetingpack.zip`。收件人解压后双击 `viewer.html`，不需要安装本项目、不需要运行服务，也不需要 LLM。查看器没有 CDN、外部字体或 `fetch` 依赖，使用 `file://` 即可。

```text
<meeting>.meetingpack.zip
├── viewer.html             # CSS/JS/数据内嵌的静态查看器
├── manifest.json           # meetingpack/v1、文件哈希、数量、媒体策略
├── README.txt
├── minutes.md              # 可继续编辑的纪要 + 隐藏 marker
├── evidence.json           # canonical 证据关系
├── rag/
│   └── records.jsonl       # meeting-minutes-rag/v1
├── slides/
│   └── ...                 # 本次会议使用的页面图
└── media/                  # 默认不存在
    ├── audio.wav           # --media audio 时
    └── source.mp4          # --media video 时
```

### 4.1 是否需要传源视频

默认不需要。纪要阅读、页面浏览、逐字稿检索和 RAG 都由 `minutes.md + evidence.json + slides + records.jsonl` 完成。源视频通常体积最大，并不会提高文本检索质量。

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

`rag/records.jsonl` 每行是独立 JSON，`record_type` 包括：

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

不建议从渲染后的 HTML 或 Markdown 脚注反向解析 RAG。`evidence.json` 和 `records.jsonl` 才是机器接口。

## 6. 隐私和版本边界

- MeetingPack 是分享副本，会包含逐字稿正文、页面解释、人员显示名和可能的岗位/团队信息；发送前应按会议保密级别判断接收范围。
- 默认不打包本机原始路径、声纹向量、声纹试听样本、完整 Org Chart 或 LLM 服务配置。
- `manifest.json` 记录包内文件 SHA-256，便于接收方验证内容是否被替换。
- 后续 schema 变更必须增加版本，不得静默改变现有字段语义。
