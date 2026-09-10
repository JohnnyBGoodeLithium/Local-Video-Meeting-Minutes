# Local Video Meeting Minutes v0.16.0

## English

### Highlights

#### Review from more places

Companion now supports lightweight review across Phone, Tablet, and Laptop layouts while heavy
processing and canonical meeting data stay on the edge machine. Home, Library, and background jobs
remain separate so polling does not take over the user's current review route.

#### Return to source more naturally

Audio and video share source-linked replay with real Range seeking. Transcript-linked captions offer
Off, Original, Translation, and Bilingual modes, and stale translation is rejected instead of being
presented as current. User-facing actions lead back to the original words, screen, or discussion.

#### Correct people without restarting analysis

Speaker confirmation, identity binding, and display-name changes are distinct operations. Simple
binding and display-name updates refresh deterministic projections with zero model calls when the
underlying transcript facts and attribution are unchanged. MeetingPack aliases remain local to one
exported pack.

#### Get a useful first result sooner

A voice-first minutes route can produce a readable result before optional visual analysis finishes.
Later visual completion reuses the transcript, people, and safe caches already produced rather than
starting the entire workflow again.

#### Experimental Live Context

Authorized public, non-DRM native HLS sources can begin building reviewable context before an event
ends. The exit-safe Live workspace shows rolling text, capture state, and duration; stopping hands the
result to the existing finalization workflow. This capability remains **Experimental**.

### Other improvements

- Viewer audio/video layout and per-pack speaker aliases are more consistent.
- New field photos can enter local visual analysis and flow into minutes, Viewer, and knowledge
  projections without being treated as independent proof of a decision.
- Speaker correction is more conservative around confirmed identities while preserving explicit,
  reversible human corrections.
- The bilingual README and Source Fold product site now present the v0.16.0 Find → Verify → Correct →
  Reuse journey.
- GitHub Pages now requires a production HTTP smoke of the deployed page and core static assets.

### Compatibility and migration

- Existing MeetingPacks continue to open; newly exported packs can include deterministic caption cues
  and local alias support.
- Existing canonical schemas remain compatible. Display rename does not destructively rewrite legacy
  generated minutes prose.
- Distribution remains source checkout or the verified Application Release Bundle. This is not a
  PyPI package and there is no stable public Python import API.

### Known limitations

- Live Context is not production-ready. Real live events, target-host latency, browser audio capture,
  and background-capture behavior vary by source and environment and have not been validated here.
- Companion transport still requires an approved deployment policy. Hosted Chromium passes, but the
  iPhone 15 Pro + X Ultra Tailscale Serve journey is **NOT TESTED**.
- iPhone fullscreen caption behavior is **NOT TESTED**.
- Video review may use the original bitrate; an adaptive review proxy is not implemented.
- Legacy generated minutes may retain older speaker labels after a display-only rename.
- KB/RAG quality and broader cross-meeting scale remain early validation.
- This remains a controlled single-machine PoC, not a production multi-user service. The repository
  does not currently include an open-source license.

### Privacy

Meeting source files stay local by default. Remote providers and private transport require explicit
configuration. The release bundle contains no private meeting data, model weights, credentials,
tailnet hostnames, internal URLs, or real-device validation records.

### Validation

- Integrated main feature baseline: make check, 216-check smoke, hosted Chromium journeys, and
  clean Application Release Bundle verification passed before release documentation began.
- The release PR is gated again by make check, make smoke, make release-verify, privacy checks,
  hosted CI, and the production Pages smoke.
- Real-device and real-live-event gaps above remain separate from synthetic and hosted-browser proof.

---

## 中文

### 主要变化

#### 在更多设备上回顾

Companion 现在为 Phone、Tablet 与 Laptop 提供轻量回顾，同时把重处理和 canonical 会议数据留在
边缘机器。Home、Library 与后台任务彼此分离，轮询不会夺走用户当前的回顾路径。

#### 更自然地回到来源

音频与视频共享来源相连的回放和真实 Range seek。字幕支持关闭、原文、翻译和双语；过期翻译会被
拒绝，不会冒充当前内容。用户入口回到原文、画面或这段讨论。

#### 修正人物，不必重跑分析

人物确认、身份绑定和显示名修改是不同操作。逐字稿事实和发言归属未变化时，简单绑定与显示名更新
以确定性投影刷新，模型调用为零。MeetingPack alias 继续只属于单个导出包。

#### 更快获得第一份可读结果

Voice-first 路径可以先生成可读纪要，再完成可选的画面分析。后续视觉补全复用已有逐字稿、人物和
安全缓存，不从头重跑整条流程。

#### Experimental Live Context

经授权的公开、无 DRM 原生 HLS 来源可以在活动结束前开始积累可回顾上下文。可退出的 Live 工作区
展示滚动文字、采集状态与时长；停止后交给现有流程收尾。此能力仍为 **Experimental**。

### 其他改进

- Viewer 的音视频布局与单包人物 alias 更一致。
- 新现场照片可以进入本地画面分析并同步到纪要、Viewer 与知识投影，但不能独立证明一项决定。
- 人物修正更保守地保护已确认身份，同时保留明确、可撤销的人工改正。
- 双语 README 与 Source Fold 产品站更新为 v0.16.0 的 Find → Verify → Correct → Reuse 旅程。
- GitHub Pages 现在要求对已部署首页和核心静态资源执行 production HTTP smoke。

### 兼容与迁移

- 旧 MeetingPack 继续打开；新导出的包可带确定性 caption cue 与本地 alias。
- 现有 canonical schema 保持兼容。显示名修改不会破坏性重写历史生成纪要中的旧名称。
- 分发方式仍为 source checkout 或通过验证的 Application Release Bundle。当前不是 PyPI package，
  也没有稳定 Python public import API。

### 已知限制

- Live Context 尚未达到生产状态。真实直播、目标主机延迟、browser audio capture 与后台捕获行为
  取决于来源和环境，本次尚未验证。
- Companion transport 仍需要获批的部署政策。Hosted Chromium 已通过，但 iPhone 15 Pro + X Ultra
  Tailscale Serve 旅程为 **NOT TESTED**。
- iPhone 全屏字幕行为为 **NOT TESTED**。
- 视频回顾可能使用原始码率；尚无 adaptive review proxy。
- 只改显示名后，历史生成纪要可能继续保留旧人物标签。
- KB/RAG 质量与更大规模跨会议使用仍处于早期验证。
- 当前仍是受控单机 PoC，不是正式多人生产服务；仓库尚未附带开源许可证。

### 隐私

会议源文件默认留在本机。远端 provider 与私有 transport 都需要显式配置。发布包不包含私有会议
数据、模型权重、凭据、tailnet hostname、内部 URL 或真机验证记录。

### 验证

- Release 文档开始前，集成后的 main 功能基线已通过 make check、216 项 smoke、Hosted Chromium
  旅程和全新目录 Application Release Bundle 验证。
- Release PR 会再次由 make check、make smoke、make release-verify、隐私检查、Hosted CI 与
  production Pages smoke 共同门禁。
- 上述真机与真实直播缺口继续与合成和 Hosted Browser 证据分开记录。
