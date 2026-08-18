# HANDOFF.md — 交接笔记

> 给接手 agent：先读本文件和 `AGENTS.md`，再看 `CHANGELOG.md` 未发布段了解最近改动。
> 本文件在每次交接或大方向变化时更新；过期的进行中事项完成后删除对应段落。

更新时间：2026-08-18（产品版本 v0.8.2；在线工作台构建号 20260818p55；提交号以 `git log -1` 为准）

## 当前基线

- 仓库：`/home/johnny-tcx_ultra/meeting-minutes`，分支 main。
- 验证基线：`make check` 全绿、隔离 Web smoke 137/137；真实 Teams DOCX 样本结构验证得到 259 条有效 cue、时间单调且正文/姓名非空，未把内容写入仓库或测试夹具。
- 服务：端口 8899，`systemctl --user restart meeting-minutes-web` 重启（挂起 ~45s 是已知 P2 问题，见下）。
- 隐私红线（详见 AGENTS.md）：不读真实会议正文，只看元数据/结构；上次已获用户授权诊断 Gate B 会议标题形态，新任务需重新授权。

## 当前批次：会议排序与错误逐字稿纠错

- 列表默认按最近导入，可切换会议时间/最近更新并持久化。`meta.json` 增量保存 `imported_at/updated_at`；旧会议有明确估算回退。
- 新导入可忽略附带 VTT/DOCX 改用本地 ASR；存量外部逐字稿视频会议从「更多」发起本地重转写。`source.json.transcript_source` 是当前来源真源，原文件保留，快照失败恢复，屏幕与 VL 缓存复用。

## 当前批次：Topic Map 章节级时间线

- v3 导航直接把同一议题之间不超过 60 秒的短回应、过渡和未分类轮次归回该议题，时间线展示章节，不再暴露逐轮分类噪声。
- Teams DOCX 中连续发言共用时间戳时，导航投影在重叠区中点按顺序切分，不改 canonical 逐字稿时间。
- 存量 v3 在读取时确定性收敛，翻译层重用 canonical 时间/linkage，不需重跑 LLM。当前产品版本 `v0.8.2`。

## 当前批次：MeetingPack 浏览 / 核听两态阅读

- 仅离线 MeetingPack 使用四入口与两态布局：会议脉络、会议纪要和屏幕内容使用全宽浏览布局；逐字稿进入左侧播放器/章节与说话人时间轴、右侧大面积逐字稿的核听态。在线工作台保持原有常驻播放器/逐字稿布局，不同步 Viewer 的窗口尺寸。
- 浏览状态播放继续时仅显示紧凑悬浮播放器；点击脉络显式时间或屏幕出现区间会进入逐字稿核听，不把普通节点选择误作 seek。搜索框按当前入口独立保存关键词与命中位置。
- 修复节点详情在读取相关屏幕变量前发生 TDZ 的运行时错误；点击脉络节点恢复展开说明且不播放，只有时间按钮进入核听。
- 在线端与 Viewer 的长发言分段共享核听索引：控制条与播放高亮按可见分段前进，后续段重复说话人并显示“同一发言 · N/M”。Viewer 核听列扩大至接近半屏；在线端布局尺寸不变。在线构建为 `20260818p54`。

## 已交付：产品版本与可回溯导出

- 产品版本从根目录 `VERSION` 单一读取。在线工作台、产品页、Viewer、README 和 manifest 共享该版本。
- MeetingPack 默认文件名为`会议_会议日期_产品版本_导出时间.meetingpack.zip`，同一会议可多次导出并存。
- 产品版本、前端构建号、Git commit 和数据 schema 独立；普通提交不升版，只在可验收发布点升级。见 `docs/RELEASES.md`。
- 该批前端构建号 `20260818p51`。

## 已交付：发言级回听与个人连续播放

- 在线端和 MeetingPack Viewer 均在说话人/时间轴下提供上一段、重播本段、下一段；没有选中人物时按整场逐字稿轮次导航。
- 点击说话人图例、逐人车道姓名或发言块会选中人物，并可切换“顺次播放 / 仅当前说话人”；个人模式在当前轮结束后确定性 seek 到该人的下一轮，不修改媒体和逐字稿数据。
- 当前轮同步高亮逐字稿与逐人车道。Viewer 删除了人物区域与搜索之间重复的 `focusbar` DOM；议题 Focus、屏幕舞台、结论关联和数据仍保留，在线端摘要继续用于审计工作台。
- 人物选择只负责高亮和预备过滤条件：只要“顺次播放”仍高亮，逐段按钮就按自然时间线；只有“仅听此人”高亮时才按人物过滤。未选人直接点“仅听此人”会取当前位置的说话人，不倒回当前句首。
- 回听身份分四态：`verified_voice_binding` 代表跨会身份；`imported_transcript_label` 来自 VTT/DOCX 明确姓名，按本场完全同名聚合；`session_voice_cluster` 是未命名但有 `voice_id` 的“说话人 K”，可在本场跳播并保留绑定入口；`insufficient_voice_sample` 才是声音过短、图例/车道禁选。该投影不写回声纹库。
- 构建号 `20260818p50`；合成静态断言和 Viewer 无头启动回归覆盖新增控制、摘要条移除以及顺次/个人/当前位置自动选人三种契约。

## 已交付：Teams DOCX 逐字稿输入

- Web 导入支持“一个录像 + 一个 `.vtt`/`.docx`”；文件名无需相同，同时给两份逐字稿会 400 拒绝。裸 DOCX 不处理，因为缺少音频、声纹和可播放证据。
- `bin/teams_transcript.py` 以标准库读取 Teams OOXML run 结构，输出与既有 VTT 完全相同的 cue schema；真实样本只做本机结构确认，正文、人名与路径不进仓库或测试。
- `source.docx` 和 `source.vtt` 同属受保护母版；`source.json` 新增 `transcript/original_transcript/transcript_format`，同时保留格式专用键供旧消费点兼容。
- 解析器测试使用虚构 DOCX；Web smoke 覆盖双文件路由和 VTT+DOCX 冲突拒绝。服务部署与提交号见本批 Git 提交。

## 已交付：Topic Map v3 导航/证据拆分

- 根因：v2 的 `turn_ids/ranges` 同时承担代表事实证据和全量播放器导航；reduce 只保留代表 turn 时，页面诚实但大面积无覆盖，按邻近填满又会制造错误语义。
- v3：局部候选使用稳定 `candidate_id`，reduce 必须列出吸收的 `candidate_ids`。`turn_ids/evidence_ranges` 只保存代表依据，`navigation_turn_ids/ranges` 保存 Topic 的完整浏览范围，顶层 `navigation_segments` 逐段标记 `topic/transition/unclassified`。
- 指标：`coverage/turn_coverage` 是业务议题轮次比例，`time_coverage` 是实际发言秒数比例，`navigation_coverage` 包含明确过渡；另记录证据覆盖、过渡/未知轮次和候选映射异常。
- UI：在线端与 MeetingPack 时间轴区分普通空白、过渡斜纹和未分类琥珀块；脉络根节点显示已归入议题比例。v1/v2 旧图继续可读，但只有重生成后才获得 v3 导航字段。
- 网络：临时静态健康页在本机所有地址可访问，但同一企业无线网络上的另一台设备请求没有到达本机，说明点对点入站被网络或终端策略阻断。不要把正式服务改成 `0.0.0.0` 来绕过；受限环境优先走 SharePoint/Teams 异步分发或经过批准的企业入口。

## 已交付：纯音频纪要协议与旧 Topic Map 数据边界修复

- 纪要：语音草稿与多模态终稿共用待办合规护栏；明确行动只能存在于 canonical 待办章节，其他章节的错误 action marker 在修复后降为 discussion。人读纪要、翻译和证据抽屉隐藏 T 机器主键，sidecar/RAG 保留 linkage。
- Topic Map：结构化 JSON 不再经过会删除独占花括号的 VL 人读清洗器；map/reduce 增加 `response_format=json_object` grammar、紧凑文案上限与独立 reasoning 清洗。一级议题互斥持有 turn/claim，跨段 claim 不得吞掉后一议题的显式锚点；长未知区间如实留空。
- 获准的私有样本只在本机数据目录验证，不把目录名、正文、姓名或关系写进 Git。此前暴露的“每轮导航分类”与“代表事实证据”共用字段问题已由 v3 解决；存量会议需要重新生成 Topic Map 才会迁移。
- 已生成无媒体轻量包和带压缩音频包供本机验收；路径与标题不进入项目文档。验证：虚构 grammar 实测、`make check` 全绿、`make smoke` 126/126、ZIP 完整性通过。

## 已交付：会议终稿就绪后自动补齐双语阅读层

- 范围：纪要 + 会议脉络 + 屏幕标题/短摘要；逐字稿仍手动触发，完整 VL 详情正文不翻译。
- 触发：upload/regen/topic_map 成功后自动排队；旧的 ready 会议在首次 bundle 阅读时懒补齐。翻译保持最低优先级，失败不改坏主管线的 done 状态。
- 语言边界：每类资产独立判断原文语言，中/英阅读层分别补齐；解决“英文会议但 VL 输出中文”时屏幕层仍残留中文的问题。原文已是目标语言时不建冗余 sidecar。
- 数据/API：新增 revision-bound `visuals.translation.{target}.json` 与 `/translations/visuals` GET/POST；每 12 页一批，只保留 `{number,title,summary}` 并校验页号集合。
- Web/MeetingPack：界面语言同步切换屏幕列表、Focus 舞台和相关页卡片；离线包新增 `assets/visuals.{language}.json`，Viewer 在无网络/LLM 时同步切换纪要、脉络和屏幕阅读文本。
- 验证：`make check` 全绿；`make smoke` 125 passed / 0 failed；离线 Viewer headless boot 通过。
- 提交：`da6b422 feat(i18n): auto-generate bilingual meeting views`（Codex <codex@local>），详细 commit body 已记录产品边界、技术实现和验证结果。

## 其他遗留（不主动做，等用户发起）

- 速度：VL 双槽/语音草稿/SSE 流式已上线；文本路由单槽刻意不动（避免争抢）；Web 优雅退出有界超时（P2）仍欠，表现为 restart 挂起 ~45s。
- 已讨论未做：会议关键字/标签（用户说过"先作第一项"但一直未启动）、术语替换预览（人名批量纠错）、补充事实强制带依据、跨会议检索。
- 大屏滚动链修复（b8c2d4e）探针验证过收敛，用户未回复确认。

## 最近一批已推送（详见 CHANGELOG 未发布段）

- `6120b27` 直出路径护栏（`minutes_overview.generate_direct` 共用退化/待办合规护栏）。
- `b2356fc` 屏幕标题乱码修复（`\boxed{}`、`\#` 转义、JSON 键形态）。
