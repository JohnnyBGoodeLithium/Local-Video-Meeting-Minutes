# Local Video Meeting Minutes v0.16.3

## English

### Highlights

- One appearance system across the workspace, settings, Companion, product introduction, and offline Viewer: follow system, light or dark, with four highlight colors.
- Fixed light-theme surfaces and narrow-screen controls. Restrained motion respects reduced-motion preferences; changing appearance keeps the player in place.
- Video images use content titles or time-based key-frame labels, including older default slide titles and translations. Reading coverage and frame classification are separate; deferred frames are not labeled as still processing. Source IDs remain unchanged.
- Device pairing has bilingual approve/decline controls, explicit revoke confirmation, and recoverable error feedback.
- Live is explained through user tasks, with compatibility details separated. New first-use and UX review guides cover setup through export.

### Compatibility and migration

This patch requires no data migration or model changes. Appearance stays in each browser; preferences do not automatically sync between devices. Export a new MeetingPack to receive the new Viewer; existing packages remain unchanged. See the [first-use guide](https://github.com/JohnnyBGoodeLithium/Local-Video-Meeting-Minutes/blob/v0.16.3/docs/runbooks/FIRST_USE.md).

### Validation and limits

Release gates require repository checks, isolated smoke, clean-bundle verification, and hosted CI. Synthetic Chromium journeys cover six surfaces, desktop/mobile viewports, both themes, highlight/text contrast, keyboard dismissal, persistence, reduced motion, pairing confirmation and offline Viewer portability. Actual mobile full-screen behavior, all operating-system inference installations, sustained Live capture and complex-chart accuracy are not claimed by this UI update.

---

## 中文

### 主要变化

- 工作台、人员设置、Companion、产品介绍和离线 Viewer 共用外观：跟随系统、浅色、深色和四种高亮色。
- 修正浅色背景与小屏按钮；动效遵循系统减少动态效果设置，切主题保留播放器。
- 视频图片显示内容标题或带时间的关键画面名称，兼容旧默认页标题及译文；读取覆盖与画面分类分别展示，延后画面不再称仍在分析；证据编号不变。
- 配对页提供中英批准/拒绝操作、明确的撤销确认和可恢复错误反馈。
- Live 以用户任务说明，兼容性按需展开；补齐从部署到导出的首次使用指南与走查记录。

### 兼容与迁移

补丁无需数据迁移或更换模型。外观保存在各浏览器，不自动跨设备同步。重新导出 MeetingPack 才会获得新版 Viewer，旧包不被修改。详见[首次使用指南](https://github.com/JohnnyBGoodeLithium/Local-Video-Meeting-Minutes/blob/v0.16.3/docs/runbooks/FIRST_USE.md)。

### 验证与边界

发布门禁包含完整检查、隔离 smoke、全新解压包验证和托管 CI。虚构 Chromium 旅程覆盖六个页面、桌面/手机视口、明暗主题、文字与高亮色对比度、键盘关闭、偏好保存、减少动态效果、配对确认及离线 Viewer。此次 UI 更新不声称已验证所有真机全屏、各操作系统本地推理安装、持续直播与复杂图表准确性。
