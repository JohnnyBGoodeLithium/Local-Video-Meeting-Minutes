# Experimental Live Context

本文记录 Live Context 的工程假设、已实现路径和必须继续验证的限制。它不把实验原型描述为成熟产品。稳定架构边界见 [ARCHITECTURE.md](../ARCHITECTURE.md)，用户交互见 [UX.md](../UX.md)，运维开关见 [OPERATIONS.md](../OPERATIONS.md)。

## 任务和非目标

在 session 进行时持续建立 timed text、speaker/topic context、source timestamp 和经选 visual evidence；session 结束后是 finalize 已有上下文，不是从零重跑全流程。Live Draft 不是正式纪要，proposal 不是 decision，screen 不是 approval，模型输出不是 fact source。

## 已实现

- `TimedTextSignal` 记录文本与人物 provenance、时间、语言、暂定和待复核状态。Teams VTT/DOCX 复用现有 parser，普通 WebVTT 使用 native subtitle 语义。
- Replay-as-Live 可以 1×/10×/100× 速率重放本地媒体与时间文本，media timestamp 不随墙钟倍速改变。
- Generic HLS 支持 master/media playlist、`EXT-X-MEDIA` 字幕、media sequence checkpoint、新分片去重、暂时网络失败恢复、target-duration 轮询和 `ENDLIST` 结束。URL 日志不保留 query。
- Native HLS worker 通过 `ffmpeg` 直接解调音频，有原生字幕时不运行主 ASR；无字幕时可使用 rolling chunk ASR。不创建可听播放元素。
- Visual Caption Capture 只读 0–1 相对坐标手工区域，1–5 fps（默认 2）变化检测后才运行本地 Tesseract；前缀扩展、后缀重叠、重复和闪烁经时序合并。没有 cloud OCR fallback。
- 近实时 ASR 是明确的 rolling chunk + overlap，不声称 native streaming。人物使用 stable anonymous ID，display label 可在会后 reconcile；platform/human identity 不会被本地 cluster 降级。
- 资源优先级固定为 audio → text/ASR + speaker → topic → OCR → VL → final heavy analysis。压力增加时先降 VL 频率、暂停 VL、降 OCR、暂停 live topic；丢 audio 块是硬失败。
- VL 只由场景/议题变化、数字、百分比、价格、规格、用户书签或周期安全样本触发，可落后 5–30 秒，不逐帧运行。
- Finalizer 冻结输入、融合文字和人物 provenance、物化已选画面，然后复用 PR #12 的 later visual path 与现有纪要/evidence pipeline。

## 能力与安全边界

Source probe 只接受用户提供的公开或明确授权来源，拒绝 loopback/private address、凭据、过大响应、不安全 redirect 和 DRM。不绕过登录、cookie、下载限制或保护流。

Browser adapter 定义 foreground、background-headful 和 headless-verified，但只有当 media/audio/caption 持续且无后台节流的 capability test 全部通过才能启用 headless。当前主机没有 `pactl`/`pw-cli`/`wpctl`，尚未建立 Chromium → dedicated virtual sink → monitor 的稳定实证。因此 browser source 只返回明确的 background unavailable，绝不自动播放或切换到 system-wide loopback。后者必须告知可能捕获其他应用并获得单独确认。

## 结束、恢复和投影

`ENDLIST` 是最强结束信号。媒体序列、音视频进展和字幕都停止时先进入 `ENDING`，等待可配 30–60 秒 grace；恢复时回到 `LIVE`。同页从 Live 变 VOD 时结束当前 session，不从 00:00 重复分析 replay。

`.live/` 不进入 Git、MeetingPack、AI Context、KB 或 Application Release Bundle。只有 finalizer 校验后才写 `transcript.spk.json`、视觉页和现有正式结果。关闭 UI 不停 worker；用户显式 Stop 会 finalize 已捕获内容，不丢弃。

## 测量与当前结果

CI 只使用 synthetic/public-safe fixture，验证信号、HLS sequence/checkpoint、字幕合并、资源降级、finalization、模型分发门禁和 Chromium UI 合同。Metrics 只写 backlog/lag/RTF/churn/drop 等数字，不记录正文、真名、会议标题、URL query 或 token。

ASR 已提供 5/8/12/15 秒 replay benchmark 工具，但本次没有用未授权的真实会议或未安装模型伪造数字。因此 ASR p50/p95、speaker lag/churn、VL lag、peak memory 和会后收尾时间尚为“未在目标主机实测”。下一步是在本机使用授权素材运行 benchmark，没有达到无丢块和持续 RTF < 1 之前不声称可实时运行。

## Diarization Runtime Pack

resolver 支持环境变量、应用本地和用户本地三级路径，且不联网下载。Pack builder 会检查 upstream ID/revision、license、attribution、redistribution terms、所有 submodel、文件 hash、路径、软链接和凭据。

`community-1` 官方页标注 CC BY 4.0 且提供离线克隆步骤，但文件访问仍需接受用户条件，真实 pack 所含子模型与再分发条件尚未逐项核实。当前状态是：安全 builder/verifier 已实现；official model pack 没有生成；终端用户无需 HF 登录的公开分发路径尚未成立。
