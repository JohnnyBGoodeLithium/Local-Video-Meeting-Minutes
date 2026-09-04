# Handoff
- 产品版本保持 `v0.15.3`；禁止改 `VERSION`、tag 或 Release。
- baseline：`f98719c2037ed6d6d33bcceb510556184c86be44`；分支：`feat/companion-adaptive-review`。
- 目标 PR：`feat(companion): add adaptive review, captions, and identity UX`。
- 状态：[docs/STATUS.md](docs/STATUS.md)；真机步骤：[docs/runbooks/COMPANION_DEVICE_CHECK.md](docs/runbooks/COMPANION_DEVICE_CHECK.md)。

## 已完成
九个提交依次分离导航与后台任务、精简 Home/分页 Library、自适应详情、身份语义、caption projection、视频回放、人物命名、跨尺寸旅程和文档。PR 同时含已过 CI 的 Viewer alias/layout；alias 是 local-only。

## 必守合同
- Home recent=5；提交后保持 Home，poll 不跳 Job；Phone 四 Tab，Tablet 双列，Laptop 三列。
- media Range 返回真实 206；caption=关闭／原文／翻译／双语；stale translation 返回 409。
- bind/display rename 的 ASR、diarization、VL、minutes、topic、translation calls 均为 0。
- display rename 更新 bank、逐字稿、people/evidence/caption，可跨会议撤销；不全局替换旧 minutes prose。
- attribution split 继续走桌面高级 correction；old MeetingPack 继续启动；Viewer alias 按 pack 隔离。

## 下一位 Agent
1. 最终再跑 `make check`、`make smoke`；本机无 Chromium时需以 hosted CI 为浏览器证据。
2. 推送九个提交、创建 PR，等 `check-and-smoke` 与 `release-candidate` 成功。
3. 下载 `companion-ux-<sha>`，确认 14 张图齐全并逐张视觉走查；未打开不能声称通过。
4. 按真机 runbook 验证 iPhone 15 Pro Safari；未执行必须报告“未验证”。
5. 若成功 check 仍显示 expected，记录 repository rule/status association 问题，不绕过。

已知限制：无 adaptive bitrate/review proxy；iOS fullscreen captions 待真机；旧 minutes 人名不破坏性改写；手机不提供缩水 split；无大屏 presentation mode。
