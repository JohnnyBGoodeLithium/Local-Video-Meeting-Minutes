# WeKnora 知识库集成与移交

更新时间：2026-08-28

## 1. 它为什么属于完整体验

Meeting Minutes 负责把一次音视频变成可信、可修正、带时间证据的知识源；WeKnora 负责把多份
知识源分块、索引并用于跨会议检索和问答。两者不是两个互不相关的 Demo，也不能互相覆盖职责：

```text
导入会议/媒体 → 核听身份/逐字稿 → 审计纪要证据 → 一键发布 KB 文档
                                                   │
                                                   ▼
                                 WeKnora 入库 → 跨会检索/问答
                                                   │
                                                   ▼
                              点击时间依据 → 回到 Meeting Minutes 核听
```

工作台在配置 `MEETING_KB_URL` 后显示“知识库”入口；配置服务端 API、私有 key 和目标 allowlist 后，
“更多 → 发布到知识库”可直接创建或更新文档。浏览器只看到允许发布的目标 ID，不接触 API key。
人工导出/上传仍作为跨机器移交和故障回退，不再是唯一主路径。

## 2. 推荐用户旅程

1. 在 Meeting Minutes 完成说话人确认、逐字稿核听和结论审计；未完成也可导出核听版，但不应入正式知识库。
2. 从“更多 → 发布到知识库”选择目标；“自动”按内容推荐：
   - 会议：默认轻量文字，保留结论、待办、脉络、逐字稿和时间依据；
   - 媒体：有关键画面时默认图文，并保留平台、发布者和原视频链接；
   - 含现场照片的会议：默认图文，保留白板/纸面阅读副本及其时间位置。
   用户仍可明确改成文字或图文。需要离线文件时再从“分享 / 导出”下载 `.kb.md`/`.kb.html`。
3. 导出时的 `base_url` 必须是知识库使用者可访问的 Meeting Minutes 地址。另一台电脑不能使用
   `127.0.0.1`；不可回连时，答案仍可读，但时间依据不能直接核听。
4. 在 WeKnora 为该系列会议选择一个稳定知识库；关闭 ASR，默认关闭 VLM。Meeting Minutes 已经把
   屏幕标题、详细解读和证据写进文档，只有要补读尚未文字化的截图字段时才开启 VLM。
5. 发布回执中的 `parse_status` 表示远端解析状态；先等待基础解析和索引完成。Wiki、自动问题生成、图谱和批量重解析是可选低优先级增强。
6. 用“结论、原话细节、人物/项目、截图独有字段、时间深链”五类问题验收。发现事实错误时回到
   Meeting Minutes 修正 canonical 数据，重新导出并替换旧文档；不要只在知识库答案里手工掩盖。

## 3. 数据与责任边界

| 能力 | Meeting Minutes | WeKnora |
|---|---|---|
| 音视频、ASR、说话人、身份 | canonical 责任方 | 不重复转写 |
| 共享画面理解 | 先生成标题、详情、时间和 P evidence | 只按需补读图片字段 |
| 结论/待办与证据 | canonical 责任方，T/P/C 可回跳 | 索引和引用，不反写结论 |
| 分块、embedding、reranker | 单会议问答及导出投影 | 跨文档/跨会议检索责任方 |
| 账号、知识库 ACL、保留策略 | API key 只在服务端私有环境；浏览器与回执不保存 | 自己管理 |
| 修正与版本 | 回到源内容修正，以正文 revision 重新发布 | 文本原位更新；图文新建成功后替换旧文档 |

MeetingPack 的 `viewer.html`、音视频和多份 JSON 不应整体上传知识库；它们会造成重复 chunk、体积膨胀
和来源竞争。`manifest.json` 是交接清单，不是主要检索正文。

## 4. 同机资源策略

统一内存机器可以同时保持 WeKnora 服务和两个文本模型，但“允许常驻”不等于“允许同时跑满”：

| 状态 | 默认策略 |
|---|---|
| 可用内存 ≥ 32 GiB | 最多两个文本模型常驻；交互与正式纪要可减少换模 |
| ASR / 说话人 / VL 开始 | 先收缩到一个文本模型，再进入重阶段 |
| 可用内存 < 24 GiB | 卸载空闲模型、任务显示“等待计算资源”，保留检查点 |
| 可用内存 < 8 GiB | 紧急卸载模型（包括在途请求），优先避免整机卡死 |
| 120B/122B 精修 | 独占模型驻留预算；完成后再恢复常规模型 |

WeKnora 的 Web、数据库和索引服务可以常驻；模型增强队列限制为一条。会议任务是用户正在等待的主旅程，
优先级高于 Wiki、自动问题、图谱和批量优化。资源护栏只看内存和模型槽位，不读取提示词或会议正文。

阈值位于 `deploy/meeting-minutes.env.example`，WeKnora 并发参考
`deploy/weknora/resource-profile.env.example`。不同内存容量应通过 soak test 调整，不能把 32/24/8
当作所有机器的固定常数。

## 5. 部署与健康检查

1. WeKnora 源码/容器栈放在独立目录，使用固定 release；它自己的真实 `.env` 不进入本仓库。
2. 参考 `deploy/weknora/weknora-compose.service.example` 设置用户级开机启动。
3. 参考 `deploy/meeting-resource-guard.service.example` 启动共享资源守护。
4. 在 Meeting Minutes 私有环境文件配置：

```bash
MEETING_KB_PROVIDER=weknora
MEETING_KB_URL=http://127.0.0.1:8088
MEETING_KB_HEALTH_URL=http://127.0.0.1:8080/health
MEETING_KB_API_URL=http://127.0.0.1:8080
MEETING_KB_API_KEY=<只写入私有环境文件>
MEETING_KB_DEFAULT_ID=<WeKnora knowledge base ID>
MEETING_KB_DEFAULT_NAME=Meeting Knowledge
```

多个目标使用 `MEETING_KB_TARGETS_JSON`，每项只能声明 `id`、显示名、接受的
`meeting`/`media` 类型和可选 tag；不要把 token 放进 JSON。服务重启后浏览器才会看到新 allowlist。

5. 只读健康检查：

```bash
.venv/bin/python bin/weknora_health.py
.venv/bin/python bin/meeting_core/resource_policy.py status
```

前一个命令只请求健康端点并报告可用内存/已加载模型，不读取知识库文档；后一个命令的 `status` 在越过
安全线时会执行既定卸载策略，因此生产监控若只想采集指标，应读取 systemd 日志而不是高频调用它。

## 6. 移交清单

- [ ] 固定并记录 Meeting Minutes、WeKnora 和模型服务版本；
- [ ] WeKnora 真实 `.env`、数据库密码和用户数据只保留在部署机；
- [ ] 两个 systemd 用户服务开机可恢复，`loginctl enable-linger` 已按管理员策略配置；
- [ ] `MEETING_KB_URL` 从实际使用者电脑可访问，顶栏“知识库”可打开；
- [ ] 一份脱敏 `.kb.md` 与 `.kb.html` 均能解析，默认 ASR/VLM 关闭；
- [ ] 时间依据能回到对应会议和非 00:00 位置；
- [ ] 会议处理期间 WeKnora 增强并发为 1，低内存时任务进入等待而不是 OOM；
- [ ] 首次发布返回 created，同一 revision 再次发布返回 already_current；
- [ ] 修正源内容后重新发布为 updated，旧图文文档只有新版本创建成功后才清理；
- [ ] `meeting.knowledge-publications.json` 不含会议正文、API key 或响应 body；
- [ ] 备份与清理分别覆盖会议 canonical 数据和 WeKnora 数据库/文件存储。

## 7. 已实现的一键同步合同

`meeting_core.knowledge_sink` 已提供显式 `KnowledgeSink` 合同，WeKnora 是首个 adapter；导出器仍只负责
可下载文件，不包含 provider API：

- 输入：`meeting_id`、artifact revision、`kb`/`kb-html` 文档、公开时间基址；
- 输出：provider、knowledge_base_id、document_id、source revision、同步状态和时间；
- 幂等键：`provider + target_id + artifact revision + profile`；
- 更新：新 revision 成功后替换旧 revision，失败保持旧文档可用；
- 删除：profile 替换时只在新文档成功后删除上一份；隐藏/删除会议不会隐式删除远端知识；
- 权限：API token 只在部署密钥存储中，绝不返回浏览器或写入作业日志。

发布失败时旧文档和上次成功回执保持可用，错误信息不包含响应正文。若 WeKnora API 版本不兼容或权限
未开放，继续用导出的 KB 文件人工上传即可；该回退不改变 canonical 数据。
