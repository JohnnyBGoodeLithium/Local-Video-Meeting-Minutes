# Fluent 2 设计基础、令牌与组件定制

本项目采用 Fluent 2 的设计原则、语义 token、焦点模型和官方图标语言，但不直接引入
`@fluentui/react-components`。在线端是无构建的原生 JavaScript，MeetingPack 又必须保持
单文件、无 CDN、离线可运行；强行引入 React 会增加两套运行时、构建链和导出体积。
因此当前路线是：**Fluent 语义合同 + 原生 HTML/JS 组件层 + 产品专有可视化**。

参考规范：

- [Design principles](https://fluent2.microsoft.design/design-principles)
- [Design tokens](https://fluent2.microsoft.design/design-tokens)
- [Accessibility](https://fluent2.microsoft.design/accessibility)
- [Iconography](https://fluent2.microsoft.design/iconography)
- [Fluent System Icons](https://github.com/microsoft/fluentui-system-icons)

适配判断：设计语言适配度高，React 组件库直装适配度低。采用 Fluent 的自然、聚焦、包容和
跨平台一致性；不复制 Teams 壳层或微软品牌身份。会议时间轴、说话人车道、证据 Focus、
会议脉络和 Org Chart 仍是产品专有组件，不应被通用控件替换。

全套界面常量收敛到 CSS 自定义属性，改字体 / 配色 / 间距 / 圆角只改 token，页面结构不变。
现在是四层合同（上层引用下层，越上层越贴近产品）：

```
1) Fluent 语义层  --colorNeutral* / --colorBrand* / --fontSizeBase*
                   --spacing* / --borderRadius* / --shadow* / --duration*
2) 兼容别名层      --bg / --panel / --accent / --fs-* / --sp-* / --r-*
3) 原生组件层      .fluent-button / .fluent-field / .fluent-tab / .fluent-dialog
4) 产品组件层      timeline / speaker lanes / evidence / topic map / org graph
```

## 换主题

基础合同在 `web/static/fluent-foundation.css`。定制项目主题时编辑 `web/static/theme.css`，
不要在业务选择器里散落新色值。兼容别名仍可覆盖，但新代码优先使用 Fluent 语义名：

```css
:root{
  --fontFamilyBase: "PingFang SC", sans-serif;
  --colorBrandBackground: #7c3aed;
  --colorBrandBackgroundHover: #6d28d9;
  --topic-1: #8b5cf6;                       /* 脉络八色逐条换 */
  --speaker-1: #8b5cf6;                     /* 说话人八色逐条换 */
}
button{ --btn-radius: 99px; }               /* 兼容组件级覆盖 */
.chip{ --chip-radius: 3px; }                /* 方形姓名标签 */
```

`theme.css` 里有完整的可覆盖清单 + 浅色主题示例（取消注释即可预览）。

## 共享到 Viewer 的方式

`bin/export_meeting.py` 在导出时把同一份 `fluent-foundation.css` 和
`fluent-icons.svg` 内联到 `viewer.html`。Viewer 根节点使用
`data-fluent-theme="light"`，在线工作台默认使用深色角色映射。因此：

- 两端共享 token 名称、焦点环、减弱动效和公共组件行为；
- Viewer 不依赖 CDN、字体下载或外部 SVG；
- 现有包被冻结，不会自动变化；需要重新导出才能获得新的设计基础；
- 颜色主题不同，但信息层级、交互状态和无障碍合同相同。

## 产品介绍页

`/product` 同样加载 `fluent-foundation.css`，并在其上只增加一层产品叙事角色：
`--productInk`、`--productCanvas`、`--productBrand`、`--productIdentity`、
`--productEvidence`、`--productKnowledge` 和对应的暗色表面角色。页面组件只能引用这些
角色或 Fluent 基础 token；具体品牌色变化不应要求逐个改卡片、按钮和数据流图。

中英文不是两套主题或两份 HTML。中文 DOM 是无 JavaScript 时也可阅读的基线，
`product-copy.js` 用相同 key 集合投影英文，并与工作台共享语言偏好。`product_intro_test.py`
同时检查中英键一一对应、页面内容版本、Fluent 基础加载、必需产品角色和 `var()` 引用可解析，
避免文案与设计 token 在后续版本中悄悄漂移。

## 各层细节

- **Fluent 语义层**（`fluent-foundation.css`）：颜色角色、4px 间距、字号、圆角、阴影和动效。
  `[data-fluent-theme="light"]` 是 Viewer 的浅色映射，默认映射为在线工作台深色主题。
- **兼容层**（`style.css :root`）：历史 `--bg/--panel/--accent/--fs-*/--sp-*/--r-*` 继续可用，
  并由 Fluent 语义层提供默认值，迁移不要求一次重写数千行 CSS。
- **阶梯层**：
  - 字号 `--fs-8 … --fs-22`（变量名 = 像素值，如 `--fs-12` = 12px）；全站 `font-size` 已零字面值。
  - 字重 `--fw-400/500/600`；字族 `--font-sans`（正文）/`--font-mono`（时间码、代码）。
  - 间距 `--sp-4…24` 连续阶梯，另有 `--sp-27/28/30/38/41/42/45/48/50/54/55/56/60/70/90` 大值（变量名=像素值）；新增引用必须有定义或回退值，由 `web/tests/design_tokens_test.py` 在 `make check` 中强制。圆角 `--r-2/3/4/6/7/8/9/10/12/18`。
  - 调色板 `--topic-1…8`（议题）、`--speaker-1…8`（说话人，轮转取模 8）。
- **组件层**：首批包含 Button、Field、Tablist/Tab、Dialog/Drawer、Message bar 和 Icon button。
  它们是 CSS/HTML 行为合同，不是 React 封装；业务 JS 仍负责状态。新增公共控件优先复用
  `.fluent-*`，不要再建立另一套按钮或焦点视觉。
- **无障碍层**：键盘 `:focus-visible` 使用双层焦点环；Tab 同步 `role="tab"` 与
  `aria-selected`；系统启用“减少动态效果”时关闭平滑滚动和非必要动画。
- **图标层**：只从 Fluent System Icons 选择小型本地子集，源文件为
  `web/static/fluent-icons.svg`。图标为辅助视觉，按钮仍必须有文字或 `aria-label`。

## JS 调色板同步

说话人/议题颜色 CSS 与 JS 双轨使用（填色靠 JS），两边都读同一组 token：

- `app.js`：`palettes()` 用 `getComputedStyle` 读 `--speaker-N/--topic-N`，读不到回退内置默认值。
- Viewer `bin/meetingpack_viewer.html`：`_palRead()` 同理，回退到 viewer 自有配色。

所以换 `--speaker-1…8` / `--topic-1…8` 后，时间轴、逐字稿 chip、密度条、Viewer 全部自动跟随，
无需动 JS。

## 边界（诚实声明）

- token 覆盖**外观**（颜色/字体/字号/字重/间距/圆角/调色板）；**结构**（栏宽比例、栅格列数、
  DOM 顺序）仍需改 `style.css` 布局段和模板 HTML。
- Viewer 的历史 CSS 仍有大量字面间距与局部色值；第一批已经建立共享基础，不等于一次完成视觉
  重写。后续应按 Button/Tab/Field → Dialog/Drawer → Toast/Message bar 的顺序迁移。
- 在线端仍是单体 `app.js`；设计系统不能替代模块拆分。组件行为稳定后，再把会议库、播放器、
  逐字稿、纪要、助手和导出拆成独立模块。
- Fluent 规范不能决定产品信息架构。会议纪要优先级、核听流程、证据边界和说话人身份逻辑继续
  由产品场景决定。

## 相关文档

- 交互与视觉规范：`docs/PRODUCT_UX.md`
- 技术债与组件化路线：`docs/ENGINEERING_REVIEW.md`（P3）
