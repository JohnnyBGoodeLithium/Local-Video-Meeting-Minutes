# 运维入口

本文回答非开发维护者和技术人员如何安装、启动、检查、升级与恢复，以及哪些数据可以清理。它是入口，不复制所有命令。完整安装看 [部署 runbook](runbooks/DEPLOYMENT.md)，处理恢复看 [处理与恢复 runbook](runbooks/PROCESSING_AND_RECOVERY.md)，开发测试看 [开发 runbook](runbooks/DEVELOPMENT.md)。

## 最短运行路径

```bash
make doctor
make check
make run
```

浏览器默认打开 `http://127.0.0.1:8899/`。首次部署前应先按目标 NVIDIA、AMD 或 CPU 环境安装正确 PyTorch 与 llama.cpp 产物，不能让通用依赖安装覆盖已工作的 GPU runtime。

## 日常检查

1. 访问 `/api/health`，确认产品版本、数据目录、Python 和集成配置。
2. 在工作台确认是否有 `queued / running / waiting_resource / paused / recovering` 作业。
3. 使用 `make doctor` 检查媒体工具、provider、硬件和受保护目录。
4. 模型或知识库问题先检查对应 loopback 健康端点，不读取或打印会议正文。
5. UI 变更后确认 Web build；若浏览器仍显示旧资源，先硬刷新而不是重复改代码。

## Live Context（实验）

Live Context 默认关闭。只在了解来源权限、音频路由和数据保留责任后设置：

```bash
MEETING_LIVE_CONTEXT=1 make run
```

启动前运行 `make doctor`，并单独检查 `ffmpeg`、`tesseract`与 PipeWire/Pulse 命令是否存在。当前主机只检测到 `ffmpeg` 和 `tesseract`，未检测到 `pactl`/`pw-cli`/`wpctl`，因此不能声称 browser 可在该主机静音捕获音频。原生 HLS 可以由 `ffmpeg` 直接 ingest，不打开浏览器也不输出到扬声器。

Live 运行数据位于会议目录下 `.live/`。不要手工把它复制进发布包、MeetingPack 或 KB。正常停止应在 UI 选“停止并整理”；服务重启时会扫描 checkpoint 恢复未完成 session。如发现 DRM、需绕过权限、音频丢块或只能无提示捕获全系统音频，立即停止对应路径。详见 [Live Context 研究与验证边界](research/LIVE_CONTEXT.md)。

## 安全启动和停止

- 开发运行：`make run`。
- 用户服务：按 [DEPLOYMENT.md](runbooks/DEPLOYMENT.md) 的 systemd 模板安装和管理。
- 停止或重启前必须确认零活动作业和无处理子进程；不要仅依赖页面是否打开。
- 有活动作业时优先让任务到达安全检查点、使用产品暂停/取消，或等待完成。强制停止可能保留检查点，但仍会中断当前生成。
- 服务异常退出后，先读取持久化 job 状态，再决定恢复；不要删除 job JSON 来“清空页面”。

## 安全升级

1. 阅读 [STATUS.md](STATUS.md)、[CHANGELOG.md](../CHANGELOG.md) 和 [发布规范](runbooks/RELEASES.md)。
2. 确认工作树只包含预期代码，私有会议目录没有进入 Git。
3. 运行与改动范围匹配的测试；正式发布至少运行 `make check`，Web/API/Viewer 改动再运行 `make smoke`。
4. 确认零活动作业，再切换代码和重启服务。
5. 访问 `/api/health`，核对产品版本与 active jobs；核对首页 asset build。
6. 不因升级删除 canonical 或受保护母版。旧会议至少保持可读。

## 失败恢复入口

用户优先在工作台打开失败详情：系统说明业务阶段、保留输出、阻塞结果和具体恢复动作。维护者只有在 UI 无法提供足够信息时才查看技术详情。

推荐顺序：

1. 从最近安全检查点继续；
2. 只重跑失败阶段；
3. 释放资源或使用管理员配置的低资源模式；
4. 跳过非必要增强，生成明确降级结果；
5. 高质量模型或从头重跑；
6. 更换损坏来源。

逐字稿人工修正后优先使用“快速同步纪要”，但只在全部视觉页面缓存完整时成立；缺页应走标准重生成，不能手工绕过完整性检查。

## 资源问题

### 内存与显存

- 统一 `resource_policy` 负责重阶段准入；不要在单个脚本再写一套卸载规则。
- `waiting_resource` 不是失败。先停止无关 GPU/LLM 工作，等待资源恢复后让有限自动重试继续。
- 120B 量级精修必须独占；健康时也只允许少量文本模型同时驻留。
- 系统整机卡死不应先假定为 OOM。应同时核对内核 OOM、GPU reset、温度、I/O、BTRFS/磁盘和电源/固件证据。

### 磁盘

- 先使用存储接口或白名单清理工具估算可再生缓存。
- 不对数据根、HOME 或不明目录执行递归删除。
- 磁盘不足时保留母版、canonical 逐字稿、人工身份、正式纪要和证据；优先回收可再生 PCM、VL full frame 和 RAG index。

### 模型服务

- 检查 provider 是否启动、模型身份是否与配置一致、端口是否只绑定 loopback。
- 能力不足与服务不可用要区分：没有时间戳的 ASR 不能通过反复重试变成可对齐结果。
- 不静默切换云端或更大模型。高质量恢复必须是用户或管理员明确操作。

## 数据保护等级

### 不能作为缓存删除

- 原始媒体或固化母版；
- `transcript.spk.json` 及人工修正历史；
- 人工确认的 identity / org 数据；
- `minutes.md`、`minutes.evidence.json` 与正式历史；
- 现场照片原图、canonical sidecar；
- 发布回执和 revision 记录。

### 可按白名单重建

- ASR 中间 PCM（来源和时间戳完整时）；
- VL 临时 full frame；
- `.rag/`、embedding 和关键词索引；
- 可从母版恢复的阅读缩略图；
- 不承担恢复职责的临时下载文件。

任何清理必须先解析为会议目录内的受控路径，并保持 sidecar 不悬空。

## 知识库

- 配置、健康检查、发布、revision 替换和资源策略见 [WEKNORA.md](runbooks/WEKNORA.md)。
- 凭据只存在本机 mode-restricted 环境文件，不进入浏览器、Git 或共享记忆。
- 删除本地会议前，应根据产品策略处理远端知识文档；远端内容不能反写 canonical。
- KB 服务长时间优化或 VLM 重分析可能占用统一内存，应纳入单并发资源管理。

## 网络边界

默认 Web 和模型端点只监听 loopback。受控 LAN 试点也必须先增加反向代理、TLS、企业身份、会议级 ACL、上传配额、审计和生命周期；端口转发或公开 tunnel 不是生产化方案。

## 继续阅读

- 跨机器和 GPU：[runbooks/DEPLOYMENT.md](runbooks/DEPLOYMENT.md)
- 处理状态与恢复：[runbooks/PROCESSING_AND_RECOVERY.md](runbooks/PROCESSING_AND_RECOVERY.md)
- 开发和测试：[runbooks/DEVELOPMENT.md](runbooks/DEVELOPMENT.md)
- 发布与版本：[runbooks/RELEASES.md](runbooks/RELEASES.md)
- 模型角色：[reference/MODELS.md](reference/MODELS.md)
- 成本模型：[reference/COST_MODEL.md](reference/COST_MODEL.md)
- 开放风险：[RISKS.md](RISKS.md)
