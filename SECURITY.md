# Security Policy / 安全政策

## Project scope / 项目范围

Local Video Meeting Minutes is a local-first, controlled proof of concept. It has not completed a production security audit. LAN exposure, public Internet deployment, multi-user access, SSO, ACLs, and tenant isolation are outside the default security boundary.

Local Video Meeting Minutes 是本地优先的受控 PoC，尚未完成生产安全审计。局域网暴露、公网部署、多人访问、SSO、ACL 与租户隔离均不属于默认安全边界。

## Supported versions / 支持版本

Security fixes are assessed against the current version on the default branch and the most recent Application Release, when one exists. Historical tags are immutable references and are not all maintained.

安全修复以默认分支当前版本及最新 Application Release（如存在）为评估对象；历史 tag 是不可移动的引用，不代表全部仍受维护。

## Reporting a vulnerability / 报告安全问题

Prefer GitHub Private Vulnerability Reporting for this repository. If that feature is unavailable, open a public Issue containing no vulnerability details and request a private communication channel. The project does not publish a security email address.

优先使用本仓库的 GitHub Private Vulnerability Reporting。如果该功能不可用，请只创建一个不含漏洞细节的公开 Issue，并请求私下沟通渠道；项目当前没有公开安全邮箱。

Never paste or upload the following to a public Issue, Pull Request, discussion, or test fixture:

- real meetings, media, transcripts, minutes, names, voiceprints, or organization structures;
- internal URLs, tokens, API keys, `.env` files, credentials, or raw logs;
- private reports, internal screenshots, exports, or complete runtime directories.

不得在公开 Issue、Pull Request、讨论或测试夹具中粘贴或上传：

- 真实会议、音视频、逐字稿、纪要、人名、声纹或组织结构；
- 内部 URL、Token、API key、`.env`、凭据或原始日志；
- 私有报告、内部截图、导出物或完整运行目录。

Provide only a sanitized diagnostic ID, product version, Web build, Git commit, operating-system summary, hardware profile, processing route, affected stage, and a reproduction using synthetic data where possible. A security fix will not require uploading a real meeting sample.

只提供脱敏 diagnostic ID、产品版本、Web build、Git commit、操作系统摘要、硬件 profile、处理 route、发生阶段，以及尽可能使用虚构数据的复现方式。安全修复不会要求上传真实会议样本。
