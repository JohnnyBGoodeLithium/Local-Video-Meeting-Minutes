# v0.15 工作台合成截图

这些截图只使用 `web/tests/make_smoke.py` 生成的虚构会议，不包含真实会议、人员、文件路径或组织信息。

- `before-v0.14.2-workspace.png`：从 Git tag `v0.14.2` 的隔离工作树、一次性数据根和 Headless Chromium 获取。
- `after-processing-detail.png`：v0.15 的语音草稿已可读、画面处理 12/36 和结构化阶段详情。
- `after-workspace-materials.png`：v0.15 的 “Visuals & Materials” 资料浏览、未定位状态和资料操作。

截图用于产品回归与版本对比，不是视觉 golden；布局断言由 Headless Chromium 旅程和 DOM 合同测试承担。
