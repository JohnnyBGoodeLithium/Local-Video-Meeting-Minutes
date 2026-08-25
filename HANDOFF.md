# HANDOFF.md — 交接笔记

> 给接手 agent：先读本文件和 `AGENTS.md`，再看 `CHANGELOG.md` 未发布段了解最近改动。
> 本文件在每次交接或大方向变化时更新；过期的进行中事项完成后删除对应段落。

更新时间：2026-08-25（产品版本 v0.10.0；在线工作台构建号 20260825p89；提交号以 `git log -1` 为准）

## 当前基线

- 仓库：`/home/johnny-tcx_ultra/meeting-minutes`，分支 main。
- 验证基线：发布提交前以本轮 `make check`、隔离 Web smoke 和 MeetingPack 启动测试结果为准；所有新增测试只使用虚构数据。
- 服务：端口 8899，`systemctl --user restart meeting-minutes-web` 重启。优雅退出已有界：`MEETING_WEB_GRACEFUL_SHUTDOWN` 默认 8 秒强制关闭残留连接，restart 不再挂起 45s。
- 隐私红线（详见 AGENTS.md）：不读真实会议正文，只看元数据/结构；上次已获用户授权诊断 Gate B 会议标题形态，新任务需重新授权。

## 当前批次：media 口播帧二次合并（dHash + 人脸代理）

- media 镜头签名合并对主讲人特写失效（换姿势/手势全帧均差就超阈值，16 分钟实测 112 镜头只压到 80+ 还被截断）：代表帧加 16×16 dHash（平局位掩码抗编码噪声），"中心肤色占比 + 低边缘密度"人脸代理判口播候选，仅双方都是候选且掩码汉明距 ≤8 才二次合并；合并页标 `talking_head: true`、ranges 累记出现区间。合并不设数量配额，内容帧严格全帧差分不变，同版式不同数据图表帧不进 dHash 通道。构建号 p90→p91。真实视频重跑验证等后台任务结束后再做。

## 当前批次：媒体版纪要 prompt（论证结构分析产物）

- 定位：content_type=media 的视频（评测/发布会/上手）分析目标是论证结构（铺垫→论点→证据→结论），不是决议/待办。以 `meta.json` 的 `content_type=="media"` 为总开关，生成代码自读 meta，调用方签名不变；会议行为一字不变。
- 实现：`bin/minutes_by_page.py` 新增 `MinutesProfile` + `MINUTES_PROFILES`（会议/媒体两套并列），选择集中在 `minutes_profile(mdir)`。媒体版：`MEDIA_SUM_PROMPT`/`MEDIA_GROUP_PROMPT`/`MEDIA_RETRY_PROMPT`/`MEDIA_EVIDENCE_RULES`，产出 `# 视频分析纪要`：总体摘要（主旨/核心观点，允许观点/预测/评价）→ 规格与参数（带数值事实，注明作者实测/引用官方/作者估计）→ 论证脉络（3–8 环节）→ 值得注意的质疑/保留意见；**不生成待办事项**、禁用 kind=action；prompt 明确输入是公开视频逐字稿、区分作者观点与客观规格事实。证据纪律不变（mm:evidence + 真实 T/P）。文档骨架标题换成 `## 分镜头详情` / `## 附录: 镜头详解`（`READING_DETAIL_SECTION_RE` 与 `meeting_generation.DETAIL_SECTIONS` 已同步，阅读投影与覆盖审计口径不变）。
- 护栏：`meeting_core/minutes_overview.py` 的 `generate_direct`/`generate` 增加 `required`/`validator`/`kind` 参数（默认会议口径不变）；媒体用 `MEDIA_REQUIRED=("## 总体摘要","## 论证脉络")`、validator=None（不触发待办定点修复），map/reduce 用 `MEDIA_CHUNK_PROMPT`/`MEDIA_REDUCE_PROMPT`。媒体不走会议精修 prompt（--refine-model 对 media 跳过并打日志）。
- VL：`vl_page_test.py` 新增 `MEDIA_DETAIL_PROMPT`/`MEDIA_PROMPT`；`describe_pages` 经 `vl_prompts(page)` 按 slides.json 的 `shot:true` 选媒体口径——帧按论证角色分级（evidence=规格表/对比图/跑分屏，demo=真机/操作，context=人脸特写/空镜铺垫，transition/blank），信息价值沿用 high/medium/low 但"承载论证信息=高"。`meeting_structure.py` 同步识别"论证角色"协议（`_visual_role` 媒体枚举、`_visual_value` 媒体启发式 evidence→high/demo→medium/context→low、`clean_model_text`/`visual_title`/`_display_description` 协议词表）。会议 slide 页 prompt 与启发式不变。
- 测试：`web/tests/media_minutes_test.py`（全合成：profile 分流、shot VL prompt 捕获、媒体章节结构落盘无待办、阅读投影截断、build_structure 媒体分级、会议回归、直出/map-reduce 护栏）进 `make check`；smoke 新增媒体 prompt 静态断言。构建号 p88→p89（index.html 4 处 + smoke 1 处）。`minutes_policy_test.py` 的 overview_direct 假接缝随签名加 profile 参数。
- 玄戒 O3 上手视频重跑（meta.json 已是 media；旧 slides 是 slides 模式 1 页产物，页码语义全变，page_desc.json 按页码索引必须作废）：
  ```bash
  cd /home/johnny-tcx_ultra/meeting-minutes
  M="meetings/2026-08-24_小米玄戒O3芯片前瞻上手_外星科技__"
  .venv/bin/python bin/slide_pages.py "$M/source_video.mp4" --out "$M/slides" --media
  rm -f "$M/page_desc.json" "$M"/slides/full_*.jpg
  .venv/bin/python bin/minutes_by_page.py "$M" --video "$M/source_video.mp4" --publish
  ```
  说明：重抽会自动覆盖 slides.json 并清旧 page_*.jpg；minutes.md 自动备份为 minutes.prev.md；topic map 随 --publish 重生成，关键字/翻译按 revision 自动 stale 后懒重建。不重启 8899。
- 剩余：提交后回写 PRODUCT_FUNCTIONS 5.1.1.5 的 Git 号。

## 当前批次：知识库导出 profile（WeKnora 优化）+ 时间码深链

- 定位：用户将把腾讯 WeKnora 部署在本机 Docker 做知识库；本应用只做分析+导出，KB 管理归 WeKnora。WeKnora 按文档分块、支持自定义 metadata、文件夹上传保留目录树，所以 KB 导出是新 profile（每个内容收敛成一份自包含 Markdown），不改 MeetingPack/ContentPack。
- 已完成（任务 1–5 全部落地，待验证+提交）：
  1. 前端深链：`web/static/app.js` 的 `loadMeetings()` 支持 `?meeting=<slug>&t=<秒>`（小数秒；非法/超界 t 忽略），打开会议后走现有 `seek()` 定位播放器。
  2. 新 `bin/kb_document.py`：`kb_document(mdir, *, base_url, ...)` 生成自包含 kb.md（front matter：title/date/content_type/duration/keywords 带 kind/source_url（meta.json 有才带）；正文 总体摘要 → 关键结论 → 待办 → 议题脉络 → 屏幕内容 → 逐字稿；时间码全部 `[mm:ss](<base>/?meeting=<slug>&t=N)` 深链；头部 `[▶ 完整视频/音频](…/media/video|audio)` 外链；屏幕图 `…/file?path=slides/…` 外链；依据标记保留 `#mm-C00001` 纯文本；VL 描述的 `# 标题` 抹平；缺板块整节跳过；语言跟随纪要主语言）。同文件 `build_kb_pack()` 打 `.kbpack.zip`（每场 `<slug>.kb.md` + `kb-pack/v1` manifest：base_url/条目/tags 汇总；多场追加文字版 `index.md` 内容清单+贯穿关键字→涉及内容）。base 取 env `MEETING_WEB_PUBLIC_BASE`，默认 `http://127.0.0.1:8899`。evidence/待办投影与 MeetingPack 同一条 `build_evidence_document` 重建链，只读目录、不调模型。
  3. 走线：`export_meeting.py --profile kb` / `export_pack.py --profile kb`（含 CLI 打印分支）；`web/routers/export.py` 单会议与 pack 端点加 `profile` Query（full 默认 | kb）；前端导出弹窗媒体选项上方加"完整包 / 知识库版（纯文本+媒体链接）"形态选择（kb 时媒体选项灰显），预检估算 >30MB 时警告区追加"可改用知识库版"（中英文案）。
  4. 测试：`web/tests/kb_document_test.py`（全合成：front matter/深链格式含小数秒/外链/降级/英文跟随/单+多场 kbpack）已进 `make check`；`smoke_test.py` 新增深链静态断言、形态选择+30MB 提示静态断言、kb 单导出与 pack kb 结构断言。构建号 p87→p88（index.html 4 处 + smoke 1 处）。
  5. 文档：CHANGELOG 未发布段顶部、EXPORT_AND_RAG.md 新增 4.3 KB Pack 段、PRODUCT_UX.md 导出弹窗段、PRODUCT_FUNCTIONS.md 新叶 8.1.2.4（Git 号"（本批，提交后补）"）。
- 验证：`make check` 全绿（含 kb_document_test）、隔离 `make smoke` 187/187（182 + 5 条新断言）、`git diff --check` 干净。尚未 commit（用户红线）。
- 剩余：提交后回写 PRODUCT_FUNCTIONS 8.1.2.4 的 Git 号；真实服务有活动作业时不得重启 8899；用户硬刷新后构建号 p88 生效。
- 下一步：WeKnora 本机 Docker 部署后做 API 直推（scoped key 存服务端配置不进 git）；claims→FAQ 映射为可选二期。

## 当前批次：media 画面抽取镜头检测模式

- 背景实证：一个 16 分钟动态上手视频（镜头每 2–5 秒切换）用 slides 稳定页原语 977 秒只切出 1 页，VL 无米下锅。`slide_pages.extract_pages` 新增 `mode="media"`：复用 1fps 小帧解码但用全帧差分（不做 ROI/稀疏标注抑制），局部显著峰为切点（阈值 max(8.0, p50×6)），最短镜头 1.5s 并回邻居；每镜头取中点帧代表帧，逐像素中位数签名合并重复镜头（ranges 记全部出现区间）；去重后超 80 页按总时长截断并在 slides.json 逐条标 `truncated`。
- 兼容决策：下游 `minutes_by_page`/`vl_report`/`export`/`meetings.py`/前端均按 `kind=="slide"` 过滤，故 media 页 kind 沿用 `"slide"`，只附加 `shot: true` 标记，下游零改动；会议录屏 slides 路径一字未动。
- 触发链路：`POST /api/upload` 的 `content_type=media` 且视频路由 → cmd 追加 `--media` → `video_minutes.py --media` → `extract_pages(mode="media")`；audio/teams 不受影响。CLI：`slide_pages.py --media` / `--mode media`。
- 构建号 p87；`web/tests/media_shots_test.py`（全合成视频：镜头数、重复镜头合并、1s 短镜头并入、截断重排、slides 回归）进 `make check`；smoke 新增 media 视频带 `--media`、media 音频不带两条断言。
- 后续批次：媒体版纪要 prompt 已在 p89 批次完成（见顶部"媒体版纪要 prompt"段）。

## 当前批次：内容类型 content_type 与会议/媒体列表分离

- `meta.json` 新增 `content_type`（`meeting` 默认 / `media`）：逻辑隔离、物理同库，会议与媒体共用管线、关键字索引、导出，只按类型分流语义。读取口径集中在 `deps._content_type`（缺字段/未知值一律 meeting，存量零迁移）与 `deps._meeting_identity`（列表 item、bundle、rename 响应都带 `content_type`）。
- 新端点 `POST /api/meetings/{slug}/content-type`（白名单校验，复用 MEETING_META_LOCK + 原子替换）；上传 `POST /api/upload` 接受可选 Form `content_type`，存进 upload 作业记录，由 `job_store._record_meeting_activity` 在管线成功后落 meta（侵入最小的落点；dry-run smoke 只能验证到作业记录层）。
- 前端：会议库顶部"会议 | 媒体"分段切换（`#content-type-tabs`，选择存 localStorage `contentType`），列表按类型过滤，空类型显示一行 placeholder 提示；"更多"菜单 `#content-type-btn` 重新分类，乐观更新失败回滚。中英标签集中在 app.js 的 `CONTENT_TYPE_LABELS`（ui()/isEnglishUi() 旁）；media 时列表/标题 meta 的"发言人"→"出镜"、改名提示→"修改标题"，纪要/待办等区块语义不动。
- 本批不做媒体版纪要 prompt（后续批次）；media 画面截取模式已在 p87 批次完成。构建号 p86；`web/tests/content_type_test.py` 进 `make check`，smoke 新增断言（缺省 meeting、切换后列表/bundle 同步、非法值 400、上传表单字段）。

## 当前批次：关键字索引与内容包导出

- `keyword_service.py` 追加纯读盘全局索引：`normalize_keyword`（NFKC + casefold + 去空白，"玄戒 O3"="玄戒O3"）、`global_index`（`keyword-index/v1`，按涉及会议数降序，title 取 meta.json 的 title、缺省回退 slug，坏 sidecar 跳过不 500）、`related`（共享关键字加权 product/project=3、organization/topic=2、other=1，shared 即推荐理由）。路由：`GET /api/keywords/index`、`GET /api/meetings/{slug}/keywords/related`，请求时重建不做缓存。
- 新 `bin/export_pack.py`：复用 `export_meeting` 逐场导出到暂存再解压进 `meetings/<slug>/`，顶层叠加 README、AGENTS.md、`content-pack/v1` manifest、`content-pack-index/v1`（≥2 个内容共享的关键字 → slug 列表，来源为实际打进包的 keywords.json）。命名沿用导出约定，默认名取最高频共享关键字；服务端 `GET /api/export/pack?slugs=a,b,c&media=none`（2–12 场，校验存在）同步返回 zip。
- 导出弹窗预检下方按需出现"相关内容"（最多 5 条，checkbox + 标题 + 灰色共享理由）；默认不勾选、无相关整块不出现，勾选后确认按钮变为"导出内容包（N 个内容）"。中英文案走现有 isEnglishUi() 机制，样式约 5 条新规则。
- 边界：全局索引是服务端内部件，只服务导出建议与 pack 索引两个出口，不做知识库管理 UI；导出全程不调用模型、不写回会议目录。
- 构建号 p85；`web/tests/keyword_index_test.py` 进 `make check`，smoke 新增 6 条断言（索引聚合、related 双向、pack 校验/404、contentpack 结构），`make check` 与 smoke 172/172 通过。
- 部署注意：与上批相同——真实服务有活动作业时不得重启；旧会议关键字懒生成后才参与索引。

## 当前批次：会议关键字

- 新 sidecar `meeting-keywords/v1`（`meeting.keywords.json`）：纪要（及事实层）就绪后自动提炼至多 12 个关键字，事实层 claims 按 decision/action 优先取前 40，无 facts 退回 evidence claims + Topic Map 一级标题；单次 `assistant._chat` json_mode 输出，`_validate_keywords` 做 kind 白名单、≤20 字符、去重、claim_ids 存在性过滤。状态机 missing/stale/ready/failed，绑定 minutes + facts revision。
- 路由 `web/routers/keywords.py`：GET/POST `/api/meetings/{slug}/keywords`；`auto_keywords_after_ready` 挂在管线成功分支（auto_translate 之后），ready 且无活动作业才排队（job priority 30）；bundle 懒触发兜底。
- 前端零新增视觉元素：列表 meta 最多 3 个、工作台标题 meta 最多 5 个 `.keyword-token` 纯文本词，悬停下划线，点击 = 填逐字稿搜索框并过滤；不翻译、不提供人工编辑。
- 导出与 RAG：`bin/export_meeting.py` 产出 `assets/keywords.json`（校验 source_revision=sha256(minutes)[:16]），进 manifest counts、README 与 Viewer meta；`meeting_artifact.py` 的 records 与 `web/rag_service.py` 每条 record 带 `keywords`。
- 构建号 p84；`web/tests/keyword_service_test.py` + smoke 关键字与 pack 断言，`make check` 与 smoke 166/166 通过。
- 部署注意：真实服务有活动作业时不得重启；旧会议首次打开时懒生成关键字。

## 当前批次：Web 优雅退出有界超时

- `web/server.py` 给 `uvicorn.run` 加 `timeout_graceful_shutdown`（env `MEETING_WEB_GRACEFUL_SHUTDOWN`，默认 8）；deploy 示例 unit 加 `TimeoutStopSec=15`。挂起连接实测退出 8.2s；`make check` 全绿。
- 本机 user unit `~/.config/systemd/user/meeting-minutes-web.service` 未改：应用层 8s 已够，systemd 默认 90s 兜底足够。

## 当前批次：处理中核听快照与检查点强制调度

- `4d28155` 解除“必须等纪要终稿才可导出”的整阶段门：只要 canonical `transcript.spk.json` 已有发言，就能导出 MeetingPack v5 核听快照。缺失纪要时使用确定性处理中说明，不调用 LLM、不写回会议目录；Viewer、README、预检与 manifest 的 `document.snapshot` 都明确标注非终稿。快照保证说话人、完整逐字稿、时间跳转和所选媒体，终稿完成后需重新导出正式分享版。
- 同一提交新增安全“立即处理”：普通“优先”仍只重排等待项；只有运行中的 upload/regen 已进入后半程并同时存在 canonical 逐字稿与页面检查点时，才允许终止当前进程组。系统先构造白名单续跑命令，再按“急件 → 自动续跑原任务”排队；ASR、说话人分离、重转写和页面清单未完成阶段拒绝抢占。
- 前端构建号为 p83。`make check` 与隔离 smoke 163/163 通过。真实服务有活动任务时不得为部署重启；静态核听包可由 CLI 立即生成，新后端能力待队列安全清空后重启生效。

## 当前批次：终稿收尾与极短轮次人工改派

- 待办证据修复会合并多次模型调用的 token usage。兼容服务可能附带嵌套 `*_tokens_details`；只累加 `int/float` 计数，嵌套诊断对象不参与统计，避免正文已生成却在收尾抛 `TypeError`。
- `/split/preview` 接受可选姓名。手选轮次具名为已有人员且未选择相似扩散时，后台直接复用该人员现存声纹，只改手选轮次并写人工锁；0 时长和极短边界轮次不再被 embedding 可用性卡住。没有现存目标声纹或用户明确选择扩散时，继续走原声学拆分路径。
- 翻译仍是独立 revision-bound 派生任务；若源文档仍是渐进式语音草稿，作业卡明确显示“语音草稿译文”，不冒充多模态终稿。

## 当前批次：同场匿名声纹隔离

- 声纹入库不再让本场刚创建的匿名 voice 参与同一轮后续匹配；一条未绑定 voice 在一场会议最多认领一个原始聚类，已绑定 person 仍可承载同场多簇。`source_clusters` 保存会议+原始聚类的唯一幂等映射，会议删除和碎片清理同步清除。
- 该规则可在受控说话人重跑中拆开旧的同场匿名多对一，不重跑 ASR 文字；真正重叠说话时单流 ASR 漏掉的第二路文字仍不在本修复范围。实现提交 `6b52345`，合成 `make check` 与隔离 smoke 161/161 通过。

## 当前批次：ASR 断点恢复与 VL JPEG 导出

- v0.10.0 的 `transcribe.py` 在正常 ASR/aligner 完成并写出 `stamps.json` 后，生成 `transcript.ts.md` 时仍访问重构前变量 `r.language`，真实长视频因此在“区分发言人”卡片报 `NameError`。实现提交 `5796d2d` 改用单一确定性落盘函数，并增加 `--reuse-stamps` / `--reuse-asr`：受控恢复要求视频母版、音频与完整 stamps，同一 ASR 不再重复计算；pyannote 说话人分离仍需重跑。
- 失败恢复计划新增 `speaker_resume`，工作台 p81 显示“从说话人识别继续”；不会重放 job JSON 旧命令，不会自动跨 provider 或上云。后续兼容提交 `0d18688` 修复 p80 前普通视频上传中 Web 预测 slug 与实际 `-Meeting_Recording` 目录不一致的问题：新上传统一清理空格/下划线形态，历史任务只接受固定精确后缀，不做模糊目录匹配。可恢复失败卡不会在一小时后消失，普通不可恢复失败仍限时展示。目标真实失败任务已经保留约 20 分钟 ASR 结果，部署后由用户点击续跑，不自动占用 GPU。
- MeetingPack `assets/slides/` 改为 `pNNNN.jpg`：优先逐字节复用 `full_XX.jpg` VL 分析帧；缓存清理后按同一 `captured` 时间和 `ffmpeg -q:v 2` 从母版恢复；无视频/旧格式才回退逻辑页并统一 JPEG。manifest 记录 `slides.format/source/included_bytes`，README 提示可直接取图且保留 P 证据编号。
- 合成验证：`make check` 通过；隔离 smoke 159/159；Viewer 启动回归通过。三场 151 页实测中，分析 JPEG 为 36.78MiB，旧 WebP 为 8.66MiB，包体绝对增加 28.12MiB；这是换取原分析分辨率与办公软件直接使用的明确取舍。

## 当前批次：v0.10.0 原语言逐字稿修正与可移植 ASR

- `meeting_core.asr` 提供 native Qwen 和 OpenAI-compatible `/audio/transcriptions` 两个适配器。默认 native；兼容端点只在显式配置后使用，必须返回 word timestamps。`MEETING_ASR_CONTEXT_MODE=auto` 只在同一端点去掉不受支持的 prompt 重试，`MEETING_ASR_FALLBACK_PROVIDER` 为空时不会跨端点或上云。
- `meeting_core.transcript_review` v1 只检查人工确认术语的已知混淆写法，每场最多重听 12 个短片段；二次音频结果明确支持标准术语才自动修正。异常被隔离，第一遍逐字稿继续进入说话人/纪要流程；后置 LLM 永不重写 canonical 原语言文本。
- 在线工作台 p79 在逐轮 hover 提供“修正”，支持播放、revision 乐观锁、私有快照和最近一次撤销。保存后 `.rag` 删除，evidence/事实层/Topic Map/翻译因 revision 变化进入待同步；用户点“更新纪要”才重建下游。静态 Viewer 保持只读，修正后需重新导出。
- `retranscribe_local.py` 现在覆盖已有纯音频和视频会议，使用当前 provider/Context，保留母版并在失败时恢复 `.versions/before-local-asr-*`。合成回归为 `make check` 通过、Web smoke 158/158；实现提交 `9d25c13`。

## 当前批次：Qwen3.8 正式纪要与终稿覆盖门

- `qwen3.8-27b-minutes` 已加入本机 llama router；Q6_K 文件约 22.9GB，2026-08-19 用纯虚构请求完成实际加载/非 thinking 输出验收。视频早期语音草稿仍走 35B MoE，纯音频正式纪要与多模态终稿走 27B；Topic Map、翻译和 AI 对话仍走通用 35B。`MEETING_RECOVERY_REFINE_MODEL` 在本机计划配置为 `gpt-oss-120b`。
- 终稿提示接收受限的语音草稿 checklist，但清单不是证据；模型必须回到原始 T 轮次。发布时按材料事项的类型和 T 交集做覆盖审计，`meeting.generation.json` 只记统计。缺项标 `review_needed`，Web p78 显示“终稿待复核”，不阻断阅读/导出。
- 新增 `docs/PROCESSING_GUIDE.md` 面向非技术读者解释处理阶段、模型分工、状态和 ASR 术语边界。领域化选词仍是建议方案；已上线的定点复核 v1 只覆盖确认词表中的已知混淆，不等价于通用声学低置信检测。Context Pack 仍在 ASR 开始前构建一次，跨会候选池尚未按 Portfolio/GEO、Business Mgmt/Finance 分域。
- 新增 `docs/PRODUCT_FUNCTIONS.md` 作为四级编号产品功能表，固定记录功能短名、说明、上线版本、关键 Git 与 P0–P3 重要度；AGENTS.md 要求今后功能与重要增强在同批提交中更新。Bug 台账暂未建立，等待产品负责人确认独立字段。

## 当前批次：ASR 术语 Context Pack

- `meeting_core.terminology` 把会议标题、人工确认词表和至少跨两场重复的高置信屏幕候选压缩为 ≤2400 字符，传给 Qwen3-ASR 原生 `context`；`asr.context.json` 只保留 term ID/状态和 context 哈希，不复制历史正文。
- 普通录屏与 Teams 会议在终稿/Topic Map 完成后从 `page_desc.json` 提取候选到私有 `speaker_bank/terminology.candidates.json`。单场候选不复用、不改写逐字稿；后处理失败不影响正式纪要。历史回填入口为 `bin/meeting_terminology.py backfill <meetings-root>`。
- 仓库只跟踪无人员信息的 `terminology.template.json`；真实确认词表和候选继续由 `speaker_bank/*` ignore。合成回归在 `web/tests/terminology_test.py`，并已加入 `make check`。

## 当前批次：短插话与声纹抖动

- 根因不是声纹绑定，而是旧 `smooth_dia` 在 ASR/分离合并前无条件把所有不足 1 秒的说话人段并给前一人，真实插话与标签抖动一起被删除。
- 新平滑在字级时间戳可用后运行：已有稳定发言簇的单字插话保留；一次性短标签要有至少两个可读字符；无文字或 ABA 中仅孤立单字的新标签仍过滤。普通视频只把最终逐字稿使用到的声音簇送入声纹库。
- 能力边界：该修复只覆盖前后相继的短发言。两人真正同时说话时，单流 Qwen3-ASR 若没有输出第二路文字，pyannote 声纹区间无法恢复不存在的文本。虚构回归同时覆盖稳定说话人插话、孤立抖动、一次性多字短发言和无声短段。

## 当前批次：VL 与说话人修正的身份一致性

- `minutes_by_page.generate` 在 VL 完成后重新读取逐字稿，再开始总体纪要与逐页文本生成；发布前用 transcript revision 做第二道栅栏。文本阶段身份再次变化时，第一次文本结果不落盘，复用 `page_desc.json` 自动重跑一次。
- 合成测试覆盖两种真实时序：VL 期间改名，以及文本生成期间再次改名；最终 evidence 只包含最后一次身份，视觉函数只调用一次。用户授权的 POR 会议时间元数据显示逐字稿在 19:29 更新、终稿在 19:47 写入，符合原实现“VL 前旧快照覆盖修正”的竞态。
- 原负责人可信度策略保持不变；本修复不把原有负责人批量降为“待确认”。存量受影响会议需要点一次重新生成纪要，过程复用 VL 缓存。
- MeetingPack Viewer 四个内容 Tab 已移除永久高亮的 `primary-tab`，统一为相同尺寸的 Fluent 下划线选中态；无头浏览器回归检查唯一选中、宽度稳定和导航位置稳定。现有包需重新导出。

## 当前批次：v0.9.2 Fluent 2 基础与安全说话人修正

- 工作台与 MeetingPack Viewer 共用 `fluent-foundation.css` 的语义 token、焦点、动效和原生控件合同；Viewer 导出时把 CSS 和本地图标子集内联，不新增 CDN 或运行时。在线保持深色、Viewer 保持浅色，产品专有时间轴/声纹/证据/脉络不套通用组件。
- 人工说话人修改写入 `speaker.corrections.json` 逐轮保护；只存时间指纹和内部 ID，不存逐字稿正文。拆分前 `/split/preview` 返回手选、建议、保护和存疑四类，用户明确选择后才扩散。
- bind/split 以 `.history/speakers` 快照事务覆盖 bank、embedding、逐字稿和保护锁；失败回滚，成功可从“更多”撤销。跨会议或已绑定到其他人的声纹不会被目标姓名强制覆盖。
- 在线旧服务仍有一个 VL 作业运行，静态 p75 已上线但新 Python 路由需等作业结束后重启。旧后台下前端会阻止 split，不会再次发生静默扩散；整条声纹绑定仍可用。重启后必须跑一次真实 UI 的预览→只手选/接受建议→撤销验收。

## 当前批次：v0.9.0 事实层与自然语言重组纪要

- `meeting.facts.json`（`meeting-facts/v1`）保存终稿生成时的完整 claim 库，只绑定逐字稿、slides 和 VL 描述 revision；改变 `minutes.md` 的栏目或取舍不会让它过期。
- 会议纪要标题栏提供“重组纪要”。用户在 AI 栏输入任意结构要求，服务端从事实层生成整篇 Markdown 预览；marker 白名单、逐行依据、正式待办语义和 revision 由代码校验，之后复用既有应用/撤销历史链路。
- 重组只改变会议纪要，不修改时间线性的 Topic Map。当前纪要的 `minutes.evidence.json` 会刷新，但明确以 `update_facts=False` 防止窄阅读视图覆盖完整库存。
- 在线 RAG 和 MeetingPack RAG 将当前纪要省略的库存项投影为 `fact` 记录；MeetingPack 新增 `assets/facts.json`，schema 保持兼容的 v5。旧会议首次点击重组时会从仍有效的 evidence 无模型迁移事实层。

## 当前批次：会议排序与错误逐字稿纠错

- 列表默认按最近导入，可切换会议时间/最近更新并持久化。`meta.json` 增量保存 `imported_at/updated_at`；旧会议有明确估算回退。
- p55 初次上线遗漏列表渲染函数内的排序状态声明，导致浏览器停止绘制但会议数据未丢失；p56 已修复并增加静态回归断言。
- 新导入可忽略附带 VTT/DOCX 改用本地 ASR；存量外部逐字稿视频会议从「更多」发起本地重转写。`source.json.transcript_source` 是当前来源真源，原文件保留，快照失败恢复，屏幕与 VL 缓存复用。
- 真实服务已在队列清空后安全重启；18/18 场会议现均返回 `imported_at/updated_at`，接口默认按导入时间倒序。旧会议中 11 场没有可验证上传作业，`imported_at_estimated=true`，使用派生资产最早时间作为保守估算。

## 当前批次：VL 标题与草稿失败可诊断性

- 读路径还原 VL 字面量 `\\n` 和同一行协议标题；在线前端兼容旧后端，存量页面不用重跑，MeetingPack 新导出同步清洗。
- 草稿失败不再统一误报为“模型没有返回正文”：`rc=2` 为模型请求失败、`rc=3` 为空正文，其他值显示内部异常。`summarize.safe_main` 只保留异常类型，不把请求、正文或私有路径写进作业日志。
- 全局作业 runner 识别 Python traceback 末行时也只保留异常类名，非协议输出继续丢弃。一个失败的多模态任务已确认逐字稿、逻辑页和 VL 缓存完整，正通过 `regen_minutes` 复用缓存恢复终稿；不要重新上传或重跑 ASR。

## 当前批次：失败作业恢复

- `web/job_recovery.py` 根据作业种类、受控阶段名、返回码/异常类和资产是否存在生成 `job-recovery/v1`；不读取会议正文，也不把日志消息或文件路径投影到恢复说明。
- Web 最近失败卡显示“为什么失败 / 已保留什么 / 下一步”。翻译、Topic Map、本地重转写与具备逐字稿+页面缓存的纪要后半程可点一次按阶段恢复；成功排队后旧红卡隐藏，旧任务不能重复提交。
- ASR/说话人前段失败以及视频尚未形成 `slides.json` 的抽帧失败没有安全断点，明确要求重新导入。恢复 API 绝不直接执行旧 job JSON 的 `cmd`。标准恢复不切换模型；只有设置 `MEETING_RECOVERY_REFINE_MODEL` 后，视觉纪要卡才显示“高质量重试”。
- 隔离 smoke 预置合成失败作业，覆盖计划、单阶段入队、successor 关联与重复恢复 409。在线构建为 `20260818p60`。

## 当前批次：Topic Map 章节级时间线

- v3 导航直接把同一议题之间不超过 60 秒的短回应、过渡和未分类轮次归回该议题，时间线展示章节，不再暴露逐轮分类噪声。
- Teams DOCX 中连续发言共用时间戳时，导航投影在重叠区中点按顺序切分，不改 canonical 逐字稿时间。
- 存量 v3 在读取时确定性收敛，翻译层重用 canonical 时间/linkage，不需重跑 LLM。该批发布于 `v0.8.2`。

## 当前批次：MeetingPack 响应式核听工作台

- 仅离线 MeetingPack 使用“全局播放证据 + 当前内容”两栏：播放器、双时间轴、人物图例/车道及逐段回听控制在所有 Tab 常驻左侧；右侧只显示当前脉络、纪要、逐字稿或屏幕内容。在线工作台保持既有窗口比例。
- 导航与搜索固定在顶部。进入逐字稿后再切回内容 Tab 会立即收起逐字稿，不保留隐藏的 review-workbench 状态；显式时间仍可切到逐字稿核听。右侧内容区扩大到约 60–68%，Topic Map 按可用宽度自然多列。
- Viewer 人物车道保持 16px、姓名区加宽。普通逐字稿行使用中性背景，只有姓名标签带人物色；当前核听句才出现很浅的人物色，避免整页彩色底纹。议题与人物继续使用不重叠的调色板。
- 在线端与 Viewer 的自动跟随只在核听段落变化时居中当前段，避免停在底部和每帧滚动。长发言核听索引与播放规则保持不变。在线构建为 `20260818p60`（该构建号对应同工作区内的 Web 失败恢复功能；Viewer 本身随重新导出更新）。

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

- 速度：VL 双槽/语音草稿/SSE 流式已上线；文本路由单槽刻意不动（避免争抢）。
- 已讨论未做：会议关键字/标签（本轮已立项，见下）、术语替换预览（人名批量纠错）、补充事实强制带依据、跨会议检索。
- 大屏滚动链修复（b8c2d4e）探针验证过收敛，用户未回复确认。

## 进行中：会议关键字/标签（2026-08-24 立项，用户选定）

- 用户诉求（原话整理）：导出数据既方便人类浏览纪要，也方便进知识库检索与结论查找；参考其他产品的会议关键字功能，展示位置待定（会议脉络？库列表？），并让 RAG 更好找。
- 本批同时做：Web 优雅退出超时（已完成，见上）。

## 最近一批已推送（详见 CHANGELOG 未发布段）

- `6120b27` 直出路径护栏（`minutes_overview.generate_direct` 共用退化/待办合规护栏）。
- `b2356fc` 屏幕标题乱码修复（`\boxed{}`、`\#` 转义、JSON 键形态）。
