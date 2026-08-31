# WeKnora 部署交接模板

这里保存的是 Meeting Minutes 与 WeKnora 的**集成配置**，不是 WeKnora 源码副本，也不包含账号、
数据库密码、JWT、模型密钥或知识库数据。

1. 按 WeKnora 官方说明在独立目录部署固定版本；复制其 `.env.example` 为私有 `.env`。
2. 将 `resource-profile.env.example` 中的资源项合并进私有 `.env`，再填写官方要求的密码。
3. 将 `weknora-compose.service.example` 复制到 `~/.config/systemd/user/`；若目录或 Compose
   命令不同，修改 `WorkingDirectory`/`ExecStart` 后执行 `systemctl --user daemon-reload` 和
   `systemctl --user enable --now weknora-compose.service`。
4. 在 Meeting Minutes 的私有环境文件设置 `MEETING_KB_URL` 和 `MEETING_KB_HEALTH_URL`。
5. 运行 `bin/weknora_health.py`，再按 [WeKnora runbook](../../docs/runbooks/WEKNORA.md) 完成一份脱敏 KB 文档验收。

默认不要为 Meeting Minutes 导出的 Markdown/HTML 开启 ASR；图片 VLM 也默认关闭。后台 Wiki、
问题生成和批量重解析属于低优先级增强，不应与急件会议的 ASR/说话人/VL 阶段并行跑满。
