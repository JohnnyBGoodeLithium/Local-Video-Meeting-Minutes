# Experimental Companion PoC

## Hypothesis

用户不必把完整桌面工作台带到每个设备。手机只承担 Connect、Send、Check、Review、Correct，X Ultra 保留媒体、canonical 数据、模型与所有重处理。

## Implemented experiment

- 手机通过 HTTPS 应用 API 发送一条经现有 SSRF 防护校验的公开媒体 URL，或流式上传一个不超过 256 MiB 的音频/视频/逐字稿文件。
- 手机读取 allowlisted `job-progress/v2`、最近项目、Meeting Map、人物片段、重要结论与 meeting-scoped evidence。
- evidence 使用受应用 session 保护的同源媒体路由，浏览器通过 HTTP Range 按需读取，不生成重复媒体。
- 人物确认先 preview，再调用既有 speaker bind/history/lock/evidence refresh 流程；模型建议不会静默升级为 confirmed。
- 5 分钟一次性 pairing token 至少 128-bit entropy，只持久化 SHA-256；设备 session 可立即撤销。

## Security and privacy boundary

同一 tailnet 不是应用授权。所有 Companion 数据 API 需要应用 session，所有写操作还需要 same-origin 与 CSRF。能力仅为 `send_url`、`upload`、`view_status`、`review`、`speaker_confirm`。管理员、删除、清理、模型设置、重转写、批量导出、release 和 shutdown 不可达。FastAPI 继续监听 `127.0.0.1`，Tailscale header 仅作为可选近似 metadata。

本原型不使用公网 Funnel，不承诺适用于所有企业会议。真实机密内容的测试须先满足公司设备、网络与第三方服务政策。

## Evidence still required

CI 能验证应用闭环和 fake Tailscale 状态，不能证明真实 tailnet transport。下一项最高价值实验是在个人测试手机和 X Ultra 上人工验证 Tailscale Serve、移动网络切换、休眠/恢复、Range seek 和 256 MiB 内的实际上传。
