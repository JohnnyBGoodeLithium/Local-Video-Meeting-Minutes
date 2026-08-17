# HANDOFF.md — 交接笔记

> 给接手 agent：先读本文件和 `AGENTS.md`，再看 `CHANGELOG.md` 未发布段了解最近改动。
> 本文件在每次交接或大方向变化时更新；过期的进行中事项完成后删除对应段落。

更新时间：2026-08-17（当前工作树构建号 20260817p45；上一已推送功能提交 = da6b422）

## 当前基线

- 仓库：`/home/johnny-tcx_ultra/meeting-minutes`，分支 main，与 origin 同步。
- 验证基线：`make check` 全绿、`make smoke` 125/125。
- 服务：端口 8899，`systemctl --user restart meeting-minutes-web` 重启（挂起 ~45s 是已知 P2 问题，见下）。
- 隐私红线（详见 AGENTS.md）：不读真实会议正文，只看元数据/结构；上次已获用户授权诊断 Gate B 会议标题形态，新任务需重新授权。

## 已交付：最新录音的证据跳转与 Topic Map 恢复

- 事故：纯音频会议已经有 ready evidence（6/6 claims 带逐字稿引用），但纪要“依据”需要二次点击侧栏时间，用户感知为不能跳转；Topic Map 最终归并、格式修复和完整重试连续返回非 JSON，作业失败后页面只见空脉络。
- 修复：在线端与 MeetingPack 的依据 chip 显示第一条原文时间码并一键 seek；upload/regen/topic-map 完成后当前 bundle 自动刷新。Topic Map 最终 JSON 连续失败时只用已缓存局部候选及原引用确定性组装，不凭空补主题，仍走质量门槛。
- 真实任务恢复（正文未读取）：`2026-08-17_165903` 已恢复为 ready，3 个一级议题 / 3 个子节点 / 99.4% 时间覆盖，strategy=`map-reduce/local-candidates-fallback-v1`；纪要 6 条 evidence link 均 ready。
- 验证：`make check` 全绿；`make smoke` 126/126；服务已重启到 p45，health `ok` 且 active_jobs=0。

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
