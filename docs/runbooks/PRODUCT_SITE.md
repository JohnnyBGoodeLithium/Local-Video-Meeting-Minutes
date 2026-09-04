# 产品介绍站部署

公开产品站只发布 `web/static/product.html` 及其五个前端资源，不连接会议、作业、人物库或私有报告。

- 线上地址：<https://johnnybgoodlithium.github.io/Local-Video-Meeting-Minutes/>
- 本地构建：`make product-site-build`
- 默认输出：`dist/product-site/`
- 构建器：`scripts/build_product_pages.py`
- 部署 workflow：`.github/workflows/pages.yml`

## 发布流程

1. PR 必须通过 `make check`、完整 Headless Chromium smoke，以及中文、英文、桌面和移动端截图检查。
2. PR 合入 `main` 后，主干 CI 再次验证准确的合并提交。
3. 只有主干 CI 成功，`Product site` workflow 才构建无数据静态制品并部署到 GitHub Pages。
4. deploy job 使用 GitHub 返回的 production URL 做有限重试，要求首页、`static/product.css` 和
   `static/product.js` 全部返回成功，并在首页找到 Source Fold 与当前内容版本标记。
5. production smoke 通过才算 Pages 发布成功。workflow 失败时不得手工上传未验证目录；修复
   构建、缓存或 Pages 设置后重跑准确提交。

GitHub 仓库只需一次性将 Pages 的 Source 设为 **GitHub Actions**。站点不需要自定义域名、服务器密钥或手工复制文件。

## 隐私边界

构建器使用固定资源清单，并将工作台入口替换为公开仓库安装入口。静态页面使用 `VERSION`
显示版本，不调用 `/api/health`。构建测试必须在临时目录运行，并检查资源集合、相对路径和
公开链接。Production smoke 只读取公开静态响应，不接触 backend 或真实会议数据。
