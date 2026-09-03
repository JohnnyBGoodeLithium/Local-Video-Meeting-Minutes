# Companion：Tailscale Serve 实验接入

Companion 是私有 tailnet 内的实验原型，不代表公司批准的部署方式。真实 EVP、SVP、Finance 或其他机密会议，必须先满足公司的设备、网络与第三方服务政策。

网络边界固定为：手机浏览器 → tailnet HTTPS → X Ultra 上的 Tailscale Serve → `http://127.0.0.1:8899`。FastAPI 不监听 `0.0.0.0`，不要求企业 LAN 允许客户端互访，也不使用 Tailscale Funnel。

## 准备

1. 在 X Ultra 和测试手机安装 Tailscale，并由用户自行登录同一个获准的 tailnet。应用不会登录 Tailscale、保存 auth key、修改 ACL 或注册设备。
2. 启动本机服务并打开 Companion：

   ```bash
   MEETING_COMPANION=1 \
   MEETING_COMPANION_PUBLIC_BASE=https://x-ultra.example.ts.net \
   make run
   ```

3. 另开终端运行 `make companion-doctor`。只有本机已安装的 CLI help 明确支持当前 target 语法时，doctor 才打印建议命令。人工检查后再执行；脚本本身不会修改网络状态。
4. 不要运行 `tailscale funnel`。如果 doctor 报告 Public Funnel，先人工关闭并复核 Serve 状态。
5. 本机打开 `http://127.0.0.1:8899/companion/setup`，生成 5 分钟配对信息；手机通过 HTTPS 地址申请，X Ultra 上明确 Allow。

## 人工验证

手机关闭公司 Wi-Fi、仅保留可用的移动网络和 Tailscale，验证配对、发送合成 URL/小文件、状态、轻量 review、Range evidence 播放、人物确认和撤销。只使用虚构素材。休眠或断网时页面应保留已提交状态并显示重试。

CI 使用 fake Tailscale JSON、fake identity header 和临时合成数据；没有真实账号、tailnet 名称或 auth key。当前环境没有 Tailscale CLI，因此 transport 必须在 X Ultra 上人工验证。
