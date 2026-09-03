# Current task

Experimental Companion: Phone ↔ X Ultra via private Tailscale tailnet.

# Product goal

Heavy work on X Ultra. Light actions on endpoint.

# User journeys implemented

- Pair：完成；5 分钟一次性 token、二维码/短码、X Ultra Allow/Deny、可撤销设备 session。
- Send URL / Send file：完成；复用既有导入与队列，小文件上限 256 MiB、流式上传。
- Check status / Review：完成；安全 job、library、Meeting Map、人物、结论和 evidence 投影。
- Speaker confirmation：完成；代表片段、现有候选、preview、human confirmation 和 undo。
- 真实手机 tailnet transport：未完成；需要 X Ultra 人工安装/登录 Tailscale 并执行 Serve 建议命令。

# Network architecture

Phone → tailnet HTTPS → Tailscale Serve → localhost FastAPI. NO Funnel, NO public exposure, NO `0.0.0.0` requirement.

# Security contracts

应用 pairing 必须存在；token 一次性且只保存 hash；session 可 revoke；能力仅限 Companion 五项；写操作 same-origin + CSRF；没有 admin/destructive capability；backend 只监听 localhost；Tailscale identity header 不能授权。

# Important files

- `web/companion_security.py`, `web/companion_projection.py`
- `web/routers/companion.py`, `web/routers/jobs.py`, `web/routers/pages.py`
- `web/static/companion.html`, `companion.css`, `companion.js`, `companion-setup.html`
- `bin/companion_doctor.py`
- `docs/runbooks/COMPANION_TAILSCALE.md`, `docs/research/COMPANION.md`
- `web/tests/companion_*`, `web/tests/chromium_companion_test.py`

# Reused contracts

Jobs 与 `job-progress/v2`、meeting canonical truth、Topic Map、evidence/media Range serving、speaker correction transaction/history/locks 全部复用；Companion 只做 projection + controller。

# Tests

11 个 Companion Python 安全/业务测试与 frontend contract 已通过；每个功能提交后的 `make check` 已通过。最终本地 `make check` 通过，隔离 `make smoke` 为 214 passed / 0 failed。GitHub CI run `33733294284` 的 `check-and-smoke` 与全新解包 `release-candidate` 均通过；Hosted Chromium 完成 390px 双语旅程并上传 synthetic screenshots。本机与 CI 均没有真实 Tailscale transport，仍需 X Ultra 人工验证。

# Current branch / commits

- Branch: `feat/companion-tailscale-poc`
- Base main: `ca40902ba97b783aded3136610a3bbf2cd6e6646`
- Functional tip before final documentation: `c365981`
- PR: #16 (`feat(companion): add private edge companion prototype`)

# Known limitations

No native app, BLE, Wi-Fi Direct, live audio streaming or remote wake. No enterprise approval. Tailscale installation/login/Serve execution are manual. Large resumable upload is not implemented. Pairing admin entry is a localhost-only setup page rather than a full desktop Settings panel.

# Next recommended experiments

1. Real phone + X Ultra Tailscale Serve test.
2. Large resumable upload.
3. Mobile meeting recording → X Ultra.
4. Nearby direct transport (BLE pairing + Wi-Fi P2P).
5. Approved enterprise relay / identity integration.

# Do not do next

Do not make Funnel public, duplicate canonical state, build a native mobile app before validating the web prototype, or mix Companion with Live Context prematurely.
