# 产品版本与发布规范

## 四种版本不要混用

| 标识 | 例子 | 作用 | 何时变化 |
| --- | --- | --- | --- |
| 产品版本 | `v0.8.1` | 对用户沟通、交付和回溯 | 形成一个可验收的发布点 |
| 前端构建号 | `20260818p51` | 缓存刷新与排障 | 每批用户可见前端改动 |
| Git commit | `abcdef1` | 完整工程历史 | 每个可审查的工程变更 |
| 数据 schema | `meetingpack/v5` | 机器可读格式兼容 | 字段或语义不兼容变化 |

产品版本的单一真源是仓库根目录 `VERSION`。Web 健康端点、在线工作台、
产品介绍页、MeetingPack Viewer、发布 manifest 和默认导出文件名从它读取或由测试约束投影；
`pyproject.toml`、README、`docs/STATUS.md` 与 CHANGELOG 不得形成独立版本事实。

当前发布基线为 `v0.15.3`（2026-09-01，Web p109）：保留 v0.15.2 的产品能力和运行合同，
修正正式 Application Release Bundle 的授权标记收录与全新目录验证，并消除 Headless Chromium
启动端口文件的瞬时读取竞态。本次是发布可靠性 patch，不改变产品 UI、canonical schema、模型管线或 RAG 行为。

## 版本节奏

- 普通 Git 提交不自动升级产品版本。一个产品版本可以包含多个完整、可审计的提交。
- `PATCH`（如 `0.8.1 → 0.8.2`）：用户可感知的修复或小改进，不改主任务。
- `MINOR`（如 `0.8.x → 0.9.0`）：一组可独立介绍和验收的新能力或新用户旅程。
- `MINOR` 或 `MAJOR` 发布必须复核 `/product` 的定位、能力边界、用户旅程和架构，并把页面的
  `data-product-content-version` 更新为 `VERSION` 的 `major.minor`。`make check` 会阻止两者不一致；
  `PATCH` 不改变产品叙事时无需机械重写介绍页。
- `0.9.0` 之后是 `0.10.0`，不是小数比较；SemVer 按点分隔的整数段比较。
- `1.0.0`：只在核心用户旅程稳定、有可重复部署方式和明确验收标准后使用。

## 发布流程

当前正式分发对象是 [Application Release Bundle](DISTRIBUTION.md)，不是 PyPI wheel。

1. 开发期间把重要交付变化记到 `CHANGELOG.md` 的“Unreleased”。
2. 获得发布授权后，一次性修改 `VERSION` 及其受约束投影，把 Unreleased 收敛为带日期的正式版本段。
3. 从 [Release Notes 模板](../releases/TEMPLATE.md) 建立 `docs/releases/vX.Y.Z.md`，英文在前、中文在后。
4. 通过 Pull Request 合入发布准备提交，并确认 `make check`、`make smoke` 和
   `make release-verify` 全部通过。
5. 在该准确提交上创建不可移动的 annotated tag `vX.Y.Z` 并推送。不要复用或移动历史 tag。
6. `.github/workflows/release.yml` 会重新校验 tag、`VERSION`、`pyproject.toml`、
   CHANGELOG 和 Release Notes；随后在干净 runner 上运行检查、smoke、正式 bundle 构建与全新目录 smoke。
7. 只有全部验证通过后，workflow 才使用 `gh release create` 发布 ZIP、tar.gz、
   `release-manifest.json` 和 `SHA256SUMS`。主版本为 `0` 时自动标记 pre-release。

`workflow_dispatch` 只接受已经存在的 tag，并 checkout 该 tag 的准确 commit。普通分支或 Pull Request
只生成短期 dev 候选制品，不创建 GitHub Release。Make target 不会隐式创建 tag 或发布。

旧 MeetingPack 不会自动变更。同一会议重新导出时，文件名带当前产品版本和导出时间，
因此可以并存、比较和回溯。
