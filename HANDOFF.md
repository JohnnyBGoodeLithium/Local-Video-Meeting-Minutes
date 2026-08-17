# HANDOFF.md — 交接笔记

> 给接手 agent：先读本文件和 `AGENTS.md`，再看 `CHANGELOG.md` 未发布段了解最近改动。
> 本文件在每次交接或大方向变化时更新；过期的进行中事项完成后删除对应段落。

更新时间：2026-08-17（构建号 20260814p43，HEAD = b2356fc 已推送）

## 当前基线

- 仓库：`/home/johnny-tcx_ultra/meeting-minutes`，分支 main，与 origin 同步。
- 验证基线：`make check` 全绿、`make smoke` 123/123。
- 服务：端口 8899，`systemctl --user restart meeting-minutes-web` 重启（挂起 ~45s 是已知 P2 问题，见下）。
- 隐私红线（详见 AGENTS.md）：不读真实会议正文，只看元数据/结构；上次已获用户授权诊断 Gate B 会议标题形态，新任务需重新授权。

## 进行中：会议终稿就绪后自动翻译（方案已定，勿重开讨论）

**已与用户确认的范围**：纪要 + 会议脉络 + 屏幕标题/摘要 在终稿 ready 后自动生成另一种语言的译文；**逐字稿保持手动触发**；**VL 详情正文不翻**（只翻标题和摘要）。

动机：现在英文纪要要手动点语言切换才触发；用户希望跑完纪要/脉络后自动翻译。原文（主语言）不做冗余 sidecar 的既有逻辑保留。

### 已探明的集成点（关键事实，勿重复探查）

- `web/translation_service.py`：已有三类 sidecar——`transcript.translation.{target}.json`（SCHEMA）、`minutes.translation.{target}.json`（MINUTES_SCHEMA）、`meeting.topic-map.translation.{target}.json`（TOPIC_MAP_SCHEMA）。target 只支持 `zh-CN`/`en`；TARGETS 字典含 label/source_language。`detect_document_language()` 判主语言；`needs_translation(source, target)`。payload 状态机：missing/stale/context_stale/ready/partial/failed/cancelled；纪要原文=目标语言时 `is_source: True` 直接 ready 不建 sidecar。`_write()` 原子落盘。`translate_topic_map` 是单发 JSON 同构校验（`_topic_translation_shape`），`_dry_translate_topic_map` 做 dry-run；`translate_minutes` 分块逐块原子落盘。模型调用统一走 `assistant._chat(messages, max_tokens=, json_mode=)`，`assistant.revision(path)` 算文件 revision。
- `web/routers/translations.py`：GET/POST `/api/meetings/{slug}/translations/minutes|topic-map`。POST 模式：payload state==ready 且非 force 直接返回 cached；已有同 artifact+target 的 queued/running 作业则复用；否则 `_new_job("translation", ...)` + `EXEC.submit(_run_X_translation, ...)`。runner `_run_minutes_translation` 在 91 行附近，内部调 `translation.translate_minutes(..., dry_run=DRY_RUN)`。
- `web/job_store.py`：`KIND_PRIORITIES` 在 `bin/job_scheduler.py`，translation=30 已是最低优先级，无需改。自动触发钩子位置：`_run_pipeline` 尾部 rc==0 分支（约 135-148 行）。kind 为 upload/regen（regen 在 routers/meetings.py:210 也走 `_run_pipeline`）；topic_map 也走同一 runner。**注意循环 import**：routers.translations 已从 job_store import EXEC/_new_job，所以 job_store 里必须函数内 lazy import（`from routers.translations import auto_translate_after_ready`）。DRY_RUN 时跳过自动触发。
- 屏幕标题/摘要来源：`page_desc.json` 的 `desc` 字典（页号 str→文本）；标题用 `meeting_structure.visual_title(clean_model_text(v), page)`；摘要取 `" ".join(cleaned.split())[:240]`（会议 prompt 用的 visual_summary 是 500 字截断，`bin/meeting_artifact.py:194`）。与 `routers/meetings.py:122-133` bundle 组装处保持一致。
- 前端 `web/static/app.js`：minutes 翻译接线在 2055-2107（`loadMinutesTranslation`/`startMinutesTranslation`），topic-map 在 2109-2171，`setUiLanguage` 在 2173。屏幕列表渲染函数 `renderVisuals()` 在 2531（列表卡 `visual.title`、详情头 `selected.title`，列表/详情都没有显示 summary 字段——接线时决定摘要展示位置或只替换标题）。`state.uiLanguage`、`isEnglishUi()` 现成。

### 实施计划（按序）

1. `translation_service.py` 新增：`VISUALS_SCHEMA = "meeting-visuals-translation/v1"`；`visuals_sidecar_path(mdir, target)` → `visuals.translation.{target}.json`；`visuals_source(mdir)` 从 page_desc.json 提取 `{number: {title, summary}}`；`visuals_translation_payload(mdir, target)`（source_revision=`assistant.revision(mdir/"page_desc.json")`，source_language 由标题拼接 `detect_document_language`，is_source 短路同 topic map）；`translate_visuals(mdir, target, dry_run=, should_cancel=)`：按 ~12 页一批调 `_chat`（json_mode），返回 `{"pages":[{"number":n,"title":"","summary":""}]}`，校验页号集合完整、逐批原子落盘，状态机照抄 translate_minutes 的 partial/failed 语义。dry-run 分支仿 `_dry_translate_topic_map` 加前缀。
2. `routers/translations.py`：GET/POST `/translations/visuals` + `_run_visuals_translation` runner，照抄 topic-map 的模式。新增 `auto_translate_after_ready(slug, mdir)`：无 minutes 或非 ready 不动作；目标语言=另一种（`en` if 纪要主语言 zh else `zh-CN`）；对 minutes/topic_map/visuals 三个 artifact 各查 payload，state ∈ {missing, stale, context_stale, failed, cancelled} 且无同名活动作业才建作业（job 加 `auto: True` 标记）。topic-map 翻译前置要求 topic map ready，否则跳过该 artifact。
3. `job_store._run_pipeline` rc==0 且 kind ∈ {upload, regen, topic_map} 且非 DRY_RUN：lazy import 调 `auto_translate_after_ready(job["meeting"], mdir)`，try/except 包住只记 log，**绝不能让翻译触发失败搞挂主作业状态**。
4. 旧会议补翻触发点（已定边界）：**首次 bundle 请求时**若会议 ready 且无活动作业则触发（比服务启动时全量扫安全），做进 `auto_translate_after_ready` 的调用点。
5. 前端 app.js：语言切换/会议加载时拉 visuals payload（target=uiLanguage），ready 则存 `state.visualsTranslation`，`renderVisuals()` 标题/摘要替换显示；未 ready 显示原文（不自动创建作业——自动触发在服务端做；手动兜底复用 POST）。minutes/topic-map 现有手动逻辑保留作兜底，不动。
6. 导出（`bin/export_meeting.py`）：sidecar ready 时加 `assets/visuals.{lang}.json`；Viewer 合并标题参考现有 `_minutes_languages`/`_topic_map_languages` 模式（约 169/198 行，调用点 448-476）。若 Viewer 模板改动变复杂，可只做 assets 携带 + 文档注明，Viewer 内合并后续再做。
7. 测试：`web/tests/translation_service_test.py` 补 visuals payload/translate/dry-run/revision 绑定用例（仿现有 minutes 用例）；smoke 翻译断言区补 visuals sidecar 与自动触发断言（dry-run 管线下 upload 作业 done 后应自动生成三个翻译 sidecar——dry-run 下 `translate_visuals` 也要能跑）。
8. 文档：PRODUCT_UX.md（自动翻译行为+屏幕双语）、ARCHITECTURE.md（上下文感知翻译节加 visuals sidecar + 自动触发时机）、EXPORT_AND_RAG.md（包内新文件）、CHANGELOG.md 未发布段、ENGINEERING_REVIEW.md 已处理段（如有事故）。构建号 bump（有前端改动）：`sed -i 's/20260814p43/20260814p44/g' web/static/index.html web/tests/smoke_test.py`（index.html 3 处 + smoke 1 处）。
9. `make check && make smoke`，提交推送，重启服务。
10. 回复用户：功能上线说明 + 提醒旧会议在首次打开时补翻。

## 其他遗留（不主动做，等用户发起）

- 速度：VL 双槽/语音草稿/SSE 流式已上线；文本路由单槽刻意不动（避免争抢）；Web 优雅退出有界超时（P2）仍欠，表现为 restart 挂起 ~45s。
- 已讨论未做：会议关键字/标签（用户说过"先作第一项"但一直未启动）、术语替换预览（人名批量纠错）、补充事实强制带依据、跨会议检索。
- 大屏滚动链修复（b8c2d4e）探针验证过收敛，用户未回复确认。

## 最近一批已推送（详见 CHANGELOG 未发布段）

- `6120b27` 直出路径护栏（`minutes_overview.generate_direct` 共用退化/待办合规护栏）。
- `b2356fc` 屏幕标题乱码修复（`\boxed{}`、`\#` 转义、JSON 键形态）。
