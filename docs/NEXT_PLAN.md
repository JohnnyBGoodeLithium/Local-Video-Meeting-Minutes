# 下一阶段计划：从个人工具到可自助使用的本地 POC

更新时间：2026-08-26

## 0. 先降低当前前端变更成本

在扩展多人服务之前，先把 `web/static/app.js` 从全域脚本收敛为装配入口。保持现有无构建部署，按 import/library/jobs/player/transcript/minutes/media-source/export 逐个抽取原生 ES module，每一步都用现有 API smoke 和无头浏览器回归锁定行为。Meeting 与 Media 继续共享 Media Analysis Core，只在输入策略、prompt 和阅读投影上分流；不创建两份仓库或两套 ASR/VL/证据逻辑。

公开媒体链接目前适合本机主动提交，不等于可安全暴露的通用下载代理。LAN 试点前需将下载器放入限制出口、CPU/磁盘/时长的 worker 沙箱，覆盖重定向、DNS rebinding、站点条款与失败清理，再纳入用户配额和审计。

## 1. 下一阶段不是再加一种纪要视图

当前内核已经能把说话人身份、逐字稿、共享画面和结论依据组织成可阅读结果。下一阶段的
产品验收目标改为：**一名没有开发环境的同事，可以自己提交会议、看到真实进度、收到结果，
并在权限范围内阅读和追问，不需要开发者手工下载、拷贝、启动脚本或转发文件。**

面向试点用户和管理者的最小演示旅程：

1. 用户打开一个受控入口，选择或拖入 Teams 录制、音频或视频；
2. 大文件上传可恢复，关闭/刷新浏览器不会从零重传；
3. 用户看到排队位置、处理阶段和失败后的可操作重试；
4. 语音草稿先出现，多模态终稿随后在同一会议内升级；
5. 用户通过结果链接阅读会议脉络、纪要、屏幕内容和原文依据；
6. 用户可在本机服务上追问，模型端口和私有文件路径不暴露给浏览器；
7. 全程不需要开发者介入，管理员仍能插队、审计和清理存储。

跨会议知识消费已经纳入同一条旅程：Meeting Minutes 先产出可信 KB 文档，WeKnora 完成跨文档检索，
答案再通过时间深链回到原会议核听。当前支持可审计的人工上传和顶栏跳转；一键同步放在多人 ACL、
revision 幂等和 token 托管之后实现，接口边界采用 `KnowledgeSink`，详见 `WEKNORA_INTEGRATION.md`。

## 2. 建议架构：单机服务化，不先做分布式系统

```text
同事浏览器
    │ HTTPS + 身份/配额
    ▼
入口层（反向代理）
    ├── Web/API ────────► Meeting Catalog / ACL / Audit
    ├── 可恢复上传 ─────► 隔离暂存区 ──原子发布──► Source Vault
    └── SSE 状态/结果链接
                              │
                              ▼
                     持久化优先队列
                              │
                              ▼
                单 GPU Worker / Pipeline Orchestrator
                    ├── ASR / diarization / identity
                    ├── voice draft / VL / final minutes
                    └── evidence / Topic Map / translation / RAG
                              │
                              ▼
                    Meeting Store + Viewer API
                              │
                       loopback-only LLM/VL
```

保留现有“同一时间只运行一个重型会议任务”的资源策略。Web 请求、上传和阅读可以并发；GPU
模型执行仍由单 worker 串行调度。这样解决普通用户交付问题，不会引入多任务争抢显存的新事故。
同机 WeKnora 的控制面与索引服务可以常驻，但后台模型增强属于低优先级；统一内存护栏按阈值把两个
文本模型收缩到一个或零，并让会议作业进入可恢复等待，而不是把 OOM 当作正常重试机制。

## 3. 工程研究结论

### 3.1 大文件上传

会议文件通常是数百 MB，普通 multipart 上传遇到网络中断会整段重传。建议在受控 LAN 试点
采用 [tus 1.0 协议](https://tus.io/protocols/resumable-upload)：客户端用 `HEAD` 查询已接收偏移，
再用 `PATCH` 续传。优先评估官方参考实现
[tusd](https://tus.github.io/tusd/) 作为 loopback sidecar；它是单二进制、支持本地磁盘、任意大
文件和完成 hook。FastAPI 只负责鉴权、元数据校验、创建任务与接收完成事件，不自己重写一套
续传协议。

安全边界：上传 ID 必须随机生成；原始文件名只作显示元数据；完成前只存在隔离暂存区；服务端
重新探测 MIME/媒体流、校验大小与扩展名；成功后在同一文件系统内原子移动到 source vault；
失败/放弃上传按 TTL 清理。tus 协议本身不定义鉴权，因此认证和会议 ACL 必须由入口层与 hook
共同执行，不能直接把 tusd 端口暴露到网络。

### 3.2 Catalog 与队列持久化

当前 JSON 作业记录适合单人本机，但服务重启会把 queued/running 标失败。下一步增加
`MeetingCatalog` 和 `JobRepository` 接口，先把 API 与目录扫描解耦，再迁移：

- meetings：meeting_id、owner、标题、输入 revision、当前 artifact、权限与保留策略；
- uploads：upload_id、owner、大小、校验、状态、暂存路径 token（不回传真实路径）；
- jobs：priority、owner、pipeline、attempt、heartbeat、cancel/retry 原因；
- shares：受控结果链接、接收范围、到期时间；
- audit_events：上传、查看、导出、插队、重试、删除和权限变化。

SQLite 适合单机 catalog，但当前项目 Python 运行时链接的 SQLite 是 **3.46.1**。SQLite 官方在
2026-03 公布了多连接 WAL reset 竞态，修复版本为 3.51.3，另有少数维护分支回移。因此本机
运行时升级/确认修复前，**不得直接启用多进程 WAL**。第一阶段采用单 catalog writer + 默认
rollback journal，或继续原子 JSON event log；升级到受修复版本并完成崩溃/并发测试后，再评估
WAL。即使启用 WAL，数据库也必须留在本机文件系统，不能放网络盘。

### 3.3 Web 进程与模型 worker 分离

FastAPI 只承担短请求、SSE 和结果读取，不在请求进程内持有重模型或执行长管线：

- `web`：鉴权、ACL、上传会话、bundle/read API、SSE；
- `scheduler`：持久化状态机、优先级、公平性、恢复和心跳；
- `worker`：领取一个 job，执行现有 pipeline，阶段性原子发布 artifact；
- `model services`：继续只监听 loopback，由 worker/API 代理调用。

当前不通过增加多个 Uvicorn worker 提升吞吐。多个 Web 进程会放大内存内队列、全局锁和写入者
不一致问题；先完成持久 catalog/worker 边界，再决定 Web worker 数。

### 3.4 网络入口和身份

不能把现有 `127.0.0.1:8899` 直接改为 `0.0.0.0`。试点入口建议由反向代理终止 HTTPS，应用
仍监听 loopback。Caddy 可以为内网主机签发本地证书，但其他同事电脑必须信任对应内部 CA；
公司已有网关/PKI 时优先复用公司能力。身份模型先在代码中固定
`RequestContext(user_id, roles, meeting_ids)`，具体接 Entra/SSO、公司反向代理身份头还是受控
试点账号，在获得 IT 约束后决定。

不接受的捷径：共享一个无密码 URL、浏览器直连 LLM、把绝对文件路径作为 API 参数、用静态
MeetingPack 伪装成在线权限系统。

## 4. 实施顺序

### P0 — 当前结果可信（本轮）

- 人读纪要与证据抽屉隐藏 T/P 机器主键，sidecar/RAG 保留稳定 linkage；
- 语音草稿和多模态纪要统一待办协议，漏投影触发重试与定点修复；
- Topic Map 一级议题取得互斥主归属，长未知区间不再硬塞给最近标题；
- 增加合成回归，并用一场获准的纯音频会议做真实回归。

### P1 — 先拆边界，不改变使用方式

1. 定义 `MeetingCatalog`、`JobRepository`、`ArtifactPublisher`、`RequestContext`；
2. 把进程内 scheduler 与 `web/job_store.py` 的持久状态拆开；
3. worker 增加 lease/heartbeat，重启后将 `running` 变为 `interrupted`，允许安全续跑或重试；
4. 所有写入继续使用 revision + 临时文件 + 原子替换；
5. 用虚构数据做断电、重复提交、重复完成 hook 和同一会议双写测试。

完成标志：重启 Web 不影响正在上传的文件；重启 scheduler 后排队任务仍在；同一 upload finalize
重复调用只产生一个 meeting/job。

### P2 — 自助上传试点

1. 受控入口页：文件、会议标题、语言提示、是否保留原媒体；
2. tusd loopback sidecar + pre-create/post-finish hook；
3. 上传配额、媒体探测、校验和、TTL、磁盘余量预检；
4. 上传完成自动创建会议并进入现有优先队列；
5. 浏览器展示上传/排队/ASR/身份/VL/终稿的统一进度。

完成标志：500MB 虚构媒体上传中断后续传；非法类型和超配额在进入 pipeline 前拒绝；上传目录
不出现用户控制的路径穿越；浏览器刷新后仍能恢复上传与任务状态。

### P3 — 结果交付与多人边界

1. 完成通知和“打开结果”链接；
2. owner/viewer/admin 三种最小角色，会议列表按 ACL 过滤；
3. 在线结果默认走中心 Viewer；MeetingPack 仍是明确的离线副本；
4. 导出/分享记录到 audit，链接可过期/撤销；
5. 对话按 user + meeting + artifact revision 保存，不再只存在单浏览器 localStorage。

### P4 — POC 验收

- 让非开发用户独立完成三次端到端任务：纯音频、Teams 录屏、长会议；
- 至少一次在上传、处理和 Web 重启三个阶段分别注入中断；
- 核对说话人绑定、正式待办、脉络、证据跳转、双语和导出；
- 记录人工介入次数、首份可读时间、终稿时间、失败恢复时间、误权限访问数；
- 达标后再决定是否同步推进“发布会解读”第二场景。

### 阶段汇报与项目所有权（与 P1–P4 同步）

这轮 POC 不只汇报“又增加了哪些功能”，而要明确记录产品假设、技术决策与验收责任。阶段材料
统一标注 **POC Owner / Product Lead: `<负责人姓名>`**，并用一页决策简报回答：

1. 用户原来在哪一步浪费时间、需要谁人工介入；
2. 说话人身份绑定、画面理解、证据可追溯和纯本地处理为何构成差异化内核；
3. 本阶段验证了什么假设，由谁独立验收，什么情况算失败；
4. 人工介入次数、上传成功率、首份可读时间、终稿时间、依据可达率和用户节省时间；
5. 下一阶段需要管理者作出的资源、试点范围或停止决定。

演示不再由开发者代操作。试点用户和管理者使用合成数据或获准会议，从提交到打开结果独立完成任务，
POC 负责人只观察、记录阻塞点并解释产品原则。这样验收的是“用户能否完成任务”，也能把个人贡献从
临时帮忙转化为可归属、可复盘的产品验证。

## 5. 暂不做

- 不先做 Kubernetes、分布式 GPU 队列或云对象存储；
- 不开放公网，不让浏览器直接访问 ASR/LLM/VL 端口；
- 不把发布会、博客监控和竞品爬取混进这轮 POC 验收；
- 不用更多纪要模板掩盖上传、交付、权限和失败恢复问题；
- 不在未确认公司身份/PKI方案前承诺正式企业部署。

## 6. 下一次代码批次

建议下一批只做 P1 的前三项：catalog/repository 接口、持久任务状态机、独立 worker lease。
它们是上传、多人权限和通知的共同地基，也能直接解决当前“Web 重启后任务只能标失败”的工程债。

内容内核另立一个小批次，不与多人服务化混改：把 Topic Map 的“导航覆盖”与“事实证据”拆成
两个字段。前者要求每个逐字稿轮次被分类到议题或明确标记为过渡/未分类；后者只保存真正支持
标题、结论和行动的代表 T/C 引用。局部窗口缺分类时只对缺失轮次做定点补全，不再让整场 reduce
同时承担分类与证据筛选。时间轴使用导航覆盖，结论审计使用代表证据；这样既能连续浏览，也不会
为了提高 coverage 把没有语义依据的长区间硬塞给最近议题。
