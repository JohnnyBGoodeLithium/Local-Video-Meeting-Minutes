# v0.15 工作台 UX / 技术实施方案

> 范围：处理进度、失败恢复、现场资料和工作台层级。保持播放器、逐字稿、会议脉络、人物核对、导出、知识发布及 canonical 会议格式不变。

## 1. 问题与成功标准

当前作业状态由后端解析 stdout、前端再解析最后一行日志，刷新虽不丢任务，却无法稳定回答“正在做什么、什么可用、还需多久、失败后怎么办”。恢复 successor 与原失败作业分裂成多张卡；照片在看到内容前先询问定位，只显示文件名，错误离开弹窗，且缺少改名/删除生命周期。工作台同时强调过多 chip、边框和入口。

成功标准：五秒内看懂当前阶段、可用结果和下一步；进度与失败使用持久化 `job-progress/v2`；历史作业明确标为估算；照片先预览再逐张定位；所有新增文案中英同步；不泄露正文、姓名、路径、URL 或凭据。

## 2. 状态图

```text
queued → running ↔ waiting_resource → done
             │              │
             ├→ paused ─────┤→ recovering → running
             ├→ degraded ───┴→ done（主结果可用）
             ├→ recoverable_failure → 恢复预览 → recovering
             ├→ blocked_failure → 用户解决输入/环境 → 恢复
             └→ cancelled
```

阶段状态：`pending → running/waiting_resource → done|degraded|failed|skipped|cancelled`。结构化事件是新任务真源；`[meta]` 只做维护日志；旧任务由 legacy adapter 投影并显示“进度来自历史日志估算”。

## 3. 按真实 route 生成 phase plan

| route / kind | 用户阶段 |
|---|---|
| `teams` | 准备资料 → 区分发言人并对齐 Teams 文稿 → 生成语音草稿 → 提取共享画面 → 理解共享画面 → 生成正式纪要 → 构建会议脉络 |
| `video` meeting | 准备资料 → 处理语音（ASR 与发言人并行）→ 生成语音草稿 → 提取共享画面 → 理解共享画面 → 生成正式纪要 → 构建会议脉络 |
| `audio` | 准备音频 → 处理语音（ASR 与发言人并行）→ 生成正式纪要 |
| `media_url` | 获取并保存媒体 → 准备资料 → 处理语音 → 生成语音草稿 → 检测镜头 → 理解关键画面 → 生成分析纪要 → 构建论证脉络 |
| `retranscribe` | 检查已有母版 → 按母版类型复用 video/audio 的后续真实阶段 |
| `regen` | 检查当前资料 → 视频资料按需复用画面理解 → 生成正式纪要 → 更新会议脉络；纯音频只重新生成纪要 |
| `topic_map` | 检查当前资料 → 更新会议脉络 |

`--no-vl`、纯音频、独立翻译等不适用阶段从计划移除；当前 ASR 与发言人分离并行执行，因此聚合为一个真实用户阶段，不伪造先后关系。现有主处理脚本不会在该作业内建立知识库索引，因此不展示不存在的检索阶段。

## 4. 可用结果与 ETA

`available_outputs` 分别记录 transcript、speaker_navigation、voice_draft、visuals、final_minutes、topic_map、retrieval。`first usable` 是逐字稿或语音草稿首次可读；`full ready` 是当前 route 必要阶段完成。ETA 只在有可靠依据时显示范围：单位阶段完成至少 2 个单位后使用近期吞吐；否则使用同 route 最近少量成功阶段耗时中位数并放宽区间；样本不足显示“正在估算”。等待、暂停和失败不递减；恢复只估算剩余范围；不生成均匀假百分比。

## 5. Failure 与恢复

```text
事件/受控退出 → failure code + category → 判断可恢复性
  ├─ 临时资源：waiting_resource，退避和有限自动检查
  ├─ 可续跑：recoverable_failure，最近检查点为主操作
  ├─ 可降级：degraded_continue，明确缺失能力
  └─ 输入/能力阻塞：blocked_failure，先解决外部问题
```

分类覆盖 input_invalid、resource_insufficient、service_unavailable、capability_missing、stage_processing_failed、revision_conflict、download_or_network_failed、cancelled_or_paused、unknown_internal。恢复排序固定为：最近检查点 → 失败阶段 → 低资源模式 → 降级完成 → 高质量模型 → 从头处理 → 更换输入。原任务和 `retry_of/recovered_by` successor 聚合为一个 attempt history；重复恢复沿用现有 409 防重。

## 6. 信息层级与 DOM 边界

- 标题下方唯一 banner：当前动作、可用结果、ETA、一个主操作；完成后收起。
- 左侧：紧凑任务卡只显示阶段/单位/ETA或保留结果；原失败与 successor 合并。
- 右侧统一 sheet shell：处理详情、恢复预览沿用同一标题栏、关闭、滚动区和底部动作，但各自保持独立状态。
- `job-progress.js` 只规范化数据、ETA和动作；`job-progress-view.js` 只生成 DOM；`app.js` 负责 API、全局状态、播放器/滚动保存和写入。

## 7. 现场资料旅程

```text
画面与资料 / 当前时间入口 → 选择文件 → 缩略图与逐项校验
→ 默认建议（资料页=未定位；当前时间入口=当前时间）
→ 可逐张移除/更改定位 → 导入 → 查看大图/改名/定位/取消定位/删除
```

EXIF 只生成建议，确认后才是已定位；行内显示无效图片和重复项；关闭/移除/完成均释放 object URL。删除使用产品内确认 sheet，原子移除 sidecar、受保护原图和阅读副本。未分析照片显示“未分析，仅作为现场资料保存”，不制造后台分析预期。

## 8. API、模块、迁移与停止边界

- 新增安全事件 helper、`web/job_progress.py` 及作业 JSON 内 `progress`；API 继续兼容旧字段。
- 新增 `PATCH /photos/{id}`（显示标题）和 `DELETE /photos/{id}`；对齐 PATCH 保持兼容。批量导入先以未定位安全固化，再逐张 PATCH，不改照片 schema 版本。
- 新前端模块不读取全局 state、不调用 API；现有人物核对模块不改。
- 历史作业无 `progress` 时即时生成 legacy 投影，不批量改写私有 job JSON；新事件只含枚举、数字和安全 key。
- 明确不做：新模型/Agent/RAG、框架或构建系统、播放器/逐字稿/脉络/人物核对重写、canonical schema 改造、照片自动分析、时间轴拖动、云端回退、完整 tracing 平台。
