# WeKnora 知识库集成与移交

更新时间：2026-08-27

## 1. 它为什么属于完整体验

Meeting Minutes 负责把一次音视频变成可信、可修正、带时间证据的知识源；WeKnora 负责把多份
知识源分块、索引并用于跨会议检索和问答。两者不是两个互不相关的 Demo，也不能互相覆盖职责：

```text
导入会议 → 核听身份/逐字稿 → 审计纪要证据 → 导出 KB 文档
                                                   │
                                                   ▼
                                 WeKnora 入库 → 跨会检索/问答
                                                   │
                                                   ▼
                              点击时间依据 → 回到 Meeting Minutes 核听
```

工作台在配置 `MEETING_KB_URL` 后显示“知识库”入口。当前稳定交接仍是**导出后人工上传**：它可审计、
可撤回，也不会把 WeKnora 的账号或 API key 放进会议服务。后续一键同步必须先补知识库 ID 映射、
幂等 revision、ACL 和删除/替换语义，不能用一个无状态上传按钮跳过治理。

## 2. 推荐用户旅程

1. 在 Meeting Minutes 完成说话人确认、逐字稿核听和结论审计；未完成也可导出核听版，但不应入正式知识库。
2. “分享 / 导出”选择：
   - 只检索文字、追求体积：`知识库轻量版`，上传单份 `.kb.md`；
   - 需要保留关键图表：`知识库图文版`，上传单份 `.kb.html`。
3. 导出时的 `base_url` 必须是知识库使用者可访问的 Meeting Minutes 地址。另一台电脑不能使用
   `127.0.0.1`；不可回连时，答案仍可读，但时间依据不能直接核听。
4. 在 WeKnora 为该系列会议选择一个稳定知识库；关闭 ASR，默认关闭 VLM。Meeting Minutes 已经把
   屏幕标题、详细解读和证据写进文档，只有要补读尚未文字化的截图字段时才开启 VLM。
5. 上传后先等待基础解析和索引完成；Wiki、自动问题生成、图谱和批量重解析是可选低优先级增强。
6. 用“结论、原话细节、人物/项目、截图独有字段、时间深链”五类问题验收。发现事实错误时回到
   Meeting Minutes 修正 canonical 数据，重新导出并替换旧文档；不要只在知识库答案里手工掩盖。

## 3. 数据与责任边界

| 能力 | Meeting Minutes | WeKnora |
|---|---|---|
| 音视频、ASR、说话人、身份 | canonical 责任方 | 不重复转写 |
| 共享画面理解 | 先生成标题、详情、时间和 P evidence | 只按需补读图片字段 |
| 结论/待办与证据 | canonical 责任方，T/P/C 可回跳 | 索引和引用，不反写结论 |
| 分块、embedding、reranker | 单会议问答及导出投影 | 跨文档/跨会议检索责任方 |
| 账号、知识库 ACL、保留策略 | 不保存 WeKnora 凭据 | 自己管理 |
| 修正与版本 | 回到源会议修正、重新导出 | 替换对应 revision 文档 |

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
```

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
- [ ] 修正源会议后按 revision 替换旧知识库文档，不保留两个无标识的重复版本；
- [ ] 备份与清理分别覆盖会议 canonical 数据和 WeKnora 数据库/文件存储。

## 7. 下一步的一键同步合同

在具备知识库 API 权限后，优先实现一个显式 `KnowledgeSink` adapter，而不是在导出器里写死 WeKnora：

- 输入：`meeting_id`、artifact revision、`kb`/`kb-html` 文档、公开时间基址；
- 输出：provider、knowledge_base_id、document_id、source revision、同步状态和时间；
- 幂等键：`meeting_id + artifact revision + profile`；
- 更新：新 revision 成功后替换旧 revision，失败保持旧文档可用；
- 删除：必须由用户明确确认，不能因会议列表隐藏而删除知识库文档；
- 权限：API token 只在部署密钥存储中，绝不返回浏览器或写入作业日志。

在这个合同完成前，人工上传不是“临时凑合”，而是当前最安全、可解释的正式交接方式。
