# Local Video Meeting Minutes

English | [简体中文](README.zh-CN.md)

[Product site](https://johnnybgoodelithium.github.io/Local-Video-Meeting-Minutes/)

<!-- maturity: controlled-single-machine-poc -->
<!-- product-version: v0.16.1 -->

Find what matters.
Verify it against the source.
Correct what is wrong.
Reuse trusted context anywhere.

Local Video Meeting Minutes is a local-first context compiler for meetings and videos. It keeps transcripts,
identity, topics, facts, source-linked evidence, and visuals independent from any one model, then
projects them into review and reuse surfaces.

## What it does

- **Meetings:** follow who said what, review decisions and follow-ups, return to the exact audio,
  transcript, or screen, and correct identity or transcript mistakes with revision history.
- **Videos:** start with a fast minutes path or run full visual analysis, browse the argument and
  important shots, and return to the original source when a claim needs checking.

## Review anywhere

- **Workbench** is the deep local review surface for transcript, identity, visual context, recovery,
  and exports.
- **Companion** is an adaptive Phone / Tablet / Laptop endpoint for sending inputs, checking jobs,
  reviewing source-linked context, captions, and small identity decisions. Hosted Chromium coverage
  passes; real iPhone and Tailscale transport validation is still pending.
- **MeetingPack** is a portable offline review package that needs no server, model, or CDN.

Minutes and knowledge bases are continuation layers, not additional review surfaces. Minutes make
this session clear and retain the path back to the original words, audio, or screen. A knowledge
base such as WeKnora makes verified results searchable and reusable later without becoming a new
source of meeting truth.

**Minutes make this session clear. The knowledge base carries it into the next task.**

## Core journey

1. Import a meeting, recording, first-party video, or explicitly authorized public video URL.
2. Find important topics, decisions, people, transcript moments, and visual material.
3. Verify a conclusion against the original audio, transcript, screen, or supplied photo.
4. Correct names, identity attribution, or transcript facts at the appropriate data layer.
5. Reuse the trusted result as MeetingPack, AI Context, KB projection, or evidence-linked RAG input.

## v0.16.1 highlights

- Structured local visual observations with stable tables, chart data, explicit unread regions, and independent review.
- Revision-aware image caching and budgeted audio/visual evidence comparison.
- Live visual reads run separately from audio with short deadlines; unfinished screenshots remain available.

### Existing review workflows

- Adaptive Companion review across Phone, Tablet, and Laptop layouts.
- One audio/video playback model with Off, Original, Translation, and Bilingual captions.
- Separate canonical identity binding, display-name editing, and per-pack local aliases.
- Fast minutes first, with later visual enrichment that reuses existing transcript and identity work.
- Experimental Live Context workspace for authorized public, non-DRM native HLS sources.
- Clearer source-return language: original text, screen, and “back to this discussion.”

## Current maturity

| Area | Maturity | Current boundary |
|---|---|---|
| Meeting review, identity correction, source return, MeetingPack | Validated | Controlled real workflows plus synthetic and browser regression coverage |
| Video analysis, Companion adaptive review, captions, AI Context, KB projection | Implemented / validating | Functional; target-device, quality, and scale baselines are incomplete |
| Live Context and private Companion transport | Experimental | Synthetic/replay and hosted-browser evidence only; no real live event or iPhone + Tailscale validation |
| SSO, ACLs, tenant isolation, multi-user production service | Planned / out of scope | A local port or tailnet prototype is not production approval |

This is a controlled single-machine PoC. The release-candidate evidence table is in the
[validation boundaries](docs/STATUS.md).

## Local-first boundary

The default backend listens on localhost. Providers may run locally or through endpoints explicitly
approved and configured by the operator; the application does not silently cross that boundary.
Companion is transport-independent, with Tailscale Serve as the first private prototype and Funnel
disabled by default. Public repository fixtures and documentation are synthetic and sanitized.

## Quick start

The speaker diarization model is included in both source downloads and application bundles.
It loads automatically without a Hugging Face account, token, or additional model download.
See the [distribution notes](docs/runbooks/DISTRIBUTION.md) for attribution and deployment scope.

Requires Linux, Python 3.11+, and `ffmpeg` / `ffprobe`. Full model execution also needs compatible
model services and hardware; read the [deployment runbook](docs/runbooks/DEPLOYMENT.md) before
changing a working CUDA or ROCm environment.

```bash
git clone https://github.com/JohnnyBGoodeLithium/Local-Video-Meeting-Minutes.git meeting-minutes
cd meeting-minutes
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
.venv/bin/python bin/doctor.py --profile web
make run
```

This starts the Web interface only. To process new recordings, follow the
[first-install deployment steps](docs/runbooks/DEPLOYMENT.md): install the hardware-specific
pipeline dependencies, configure ASR and a text model, load the environment file, and validate a short recording.
On OEM systems with a validated PyTorch stack, use the venv instructions there before installing dependencies.
Open `http://127.0.0.1:8899/`. `make smoke` uses a temporary data root and synthetic fixtures; it
must not read real meetings.

## Documentation

| Need | Source |
|---|---|
| All documentation | [Documentation index](docs/INDEX.md) |
| Product story | [Product site](https://johnnybgoodelithium.github.io/Local-Video-Meeting-Minutes/) |
| Latest release candidate | [v0.16.1 release notes](docs/releases/v0.16.1.md) |
| Capability inventory | [Product functions](docs/PRODUCT_FUNCTIONS.md) |
| Current validation state | [Status](docs/STATUS.md) |
| Canonical data and projections | [Architecture](docs/ARCHITECTURE.md) |
| Deployment and recovery | [Operations](docs/OPERATIONS.md) |
| Security boundary | [Security](SECURITY.md) |

The supported distributions are source checkout and the verified Application Release Bundle. This
is not a PyPI package and does not expose a stable public Python API.

## License status

This repository currently does not include an open-source license.
Review ownership and company policy before redistribution or commercial use.
