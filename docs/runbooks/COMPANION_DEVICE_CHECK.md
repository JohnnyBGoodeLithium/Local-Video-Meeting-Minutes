# Companion 真机与截图验收

## 前置条件

使用纯合成会议，在 X Ultra 仅通过 localhost 启动 FastAPI，并按 `COMPANION_TAILSCALE.md` 配置私有 Tailscale Serve。禁止 Funnel；不要把一次性 pairing URL 放入日志或截图。

## iPhone 15 Pro Safari

- [ ] Pair 后地址栏不再含 token，刷新仍可连接，revoke 立即失效。
- [ ] Home recent 不超过 5 条；只有一个 Send 入口。
- [ ] Send URL 后仍停留 Home，处理中卡片自行更新，点击卡片才进入 Job。
- [ ] 从 Photos 选择并发送合成视频；上传进度可见，返回仍在 Home。
- [ ] 详情有概览、章节、人物、逐字稿四个 Tab，横向无溢出。
- [ ] Video 可播放并 seek；跳到 42:18 后时间正确，切 Tab 不重置。
- [ ] 原文、翻译、双语、关闭四种 caption 可切换；stale 翻译不会显示旧文本。
- [ ] 进入原生 fullscreen 后 caption 可见；退出后时间不跳回。
- [ ] 匿名人物确认已有人员和新建人员均先预览，确认／撤销保持时间、Tab、人物上下文。
- [ ] 已确认人物显示名改名先展示会议数与发言数，撤销恢复。
- [ ] portrait ↔ landscape 旋转后无横向溢出，player 与当前 Tab 保持。

## Tablet 与 Laptop

- [ ] 820px portrait 为内容＋sticky player 双列。
- [ ] 1180px landscape 保持双列、键盘焦点可见。
- [ ] 1440×900 为 persistent Library＋正文＋sticky player 三列。
- [ ] Tab 左右方向键切换，任一时刻只有一个 `aria-selected=true` 与一个可见 tabpanel。

## Hosted synthetic screenshots

PR 的 `companion-ux-<sha>` artifact 必须包含：

| 截图 | 走查重点 |
|---|---|
| `phone-home-393.png` | recent 密度、单一 Send、处理中区域 |
| `phone-send-sheet-393.png` | URL／Photos video／file 入口和安全关闭 |
| `phone-processing-393.png` | 两张以内任务卡、状态不夺取导航 |
| `phone-overview-393.png` | 标题、摘要、结论与 mini-player |
| `phone-chapters-393.png` | 章节编号、时间范围和可点目标 |
| `phone-people-393.png` | 人物密度、确认提示不暴露工程术语 |
| `phone-transcript-player-393.png` | 50-turn 页边界、播放按钮、sticky player |
| `phone-speaker-confirm-393.png` | 影响预览、确认与撤销层级 |
| `phone-video-caption-393.png` | 真实 video、caption selector 与原生 track |
| `tablet-review-820.png` | portrait 双列、无遮挡 |
| `tablet-landscape-1180.png` | landscape 双列与 sticky player |
| `laptop-review-1440.png` | Library／正文／player 三列 |
| `viewer-caption-1440.png` | video caption 控件与布局稳定 |
| `viewer-local-rename-1440.png` | local alias、reset 与 canonical 区分 |

逐张记录 overflow、遮挡、截断、焦点、对比度或文案问题；修复后重新跑同一 SHA 对应的新 workflow。自动化只保证状态和文件生成，不得把未打开 artifact 写成“已视觉通过”。
