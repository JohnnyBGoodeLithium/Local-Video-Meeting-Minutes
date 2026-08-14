# 设计令牌（Design Tokens）— 主题与组件定制

P3 原子化：全套界面常量收敛到 CSS 自定义属性，改字体 / 配色 / 间距 / 圆角只改 token，
页面结构不变。三层合同（上层引用下层，越上层越贴近组件）：

```
1) 语义层   --bg / --ink / --accent / --danger …           颜色含义
2) 阶梯层   --font-sans --font-mono / --fs-8…22 / --fw-4..6
            --sp-4…24 / --r-2…18 / --topic-1…8 / --speaker-1…8   通用刻度
3) 组件层   --btn-* / --input-* / --chip-* / --tab-* / --dialog-*  控件外壳
```

## 换主题

不要直接改 `style.css`——新建（或编辑）`web/static/theme.css`（已用注释模板建好），
它在两个页面里都排在 `style.css` 之后，所有覆盖在这里生效：

```css
:root{
  --font-sans: "PingFang SC", sans-serif;   /* 全局字体 */
  --fs-12: 13px;                            /* 基础字号上调一档 */
  --accent: #7c3aed;                        /* 品牌主色 */
  --topic-1: #8b5cf6;                       /* 脉络八色逐条换 */
  --speaker-1: #8b5cf6;                     /* 说话人八色逐条换 */
}
button{ --btn-radius: 99px; }               /* 胶囊按钮（组件级覆盖） */
.chip{ --chip-radius: 3px; }                /* 方形姓名标签 */
```

`theme.css` 里有完整的可覆盖清单 + 浅色主题示例（取消注释即可预览）。

## 各层细节

- **语义层**（`style.css :root`）：`--bg/--panel/--line/--ink/--ink-2/--ink-3/--accent/--danger/--good/--mask-bg` 等。
  深色/浅色互换只改这一层即可整体翻色。
- **阶梯层**：
  - 字号 `--fs-8 … --fs-22`（变量名 = 像素值，如 `--fs-12` = 12px）；全站 `font-size` 已零字面值。
  - 字重 `--fw-400/500/600`；字族 `--font-sans`（正文）/`--font-mono`（时间码、代码）。
  - 间距 `--sp-4/6/8/10/12/14/16/20/24`；圆角 `--r-2/3/4/6/7/8/9/10/12/18`。
  - 调色板 `--topic-1…8`（议题）、`--speaker-1…8`（说话人，轮转取模 8）。
- **组件层**：`button`、`input,textarea,select`、`.chip`（说话人标签）、`.mode-tab`（视图切换）、
  `.dialog`（弹窗）都有 `--x-*` 变量 + 回退值，可在 `:root` 全局改，也可在某一容器内局部改。

## JS 调色板同步

说话人/议题颜色 CSS 与 JS 双轨使用（填色靠 JS），两边都读同一组 token：

- `app.js`：`palettes()` 用 `getComputedStyle` 读 `--speaker-N/--topic-N`，读不到回退内置默认值。
- Viewer `bin/meetingpack_viewer.html`：`_palRead()` 同理，回退到 viewer 自有配色。

所以换 `--speaker-1…8` / `--topic-1…8` 后，时间轴、逐字稿 chip、密度条、Viewer 全部自动跟随，
无需动 JS。

## 边界（诚实声明）

- token 覆盖**外观**（颜色/字体/字号/字重/间距/圆角/调色板）；**结构**（栏宽比例、栅格列数、
  DOM 顺序）仍需改 `style.css` 布局段和模板 HTML。
- Viewer 是单文件，token 只覆盖调色板；其内部其余样式随导出物冻结，不追主题。
- 组件级重构（模板化 partials / Vue 组件库）在 P3 路线，届时 token 层直接沿用。

## 相关文档

- 交互与视觉规范：`docs/PRODUCT_UX.md`
- 技术债与组件化路线：`docs/ENGINEERING_REVIEW.md`（P3）
