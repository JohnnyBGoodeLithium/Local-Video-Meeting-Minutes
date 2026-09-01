# Local Video Meeting Minutes

English | [简体中文](README.zh-CN.md)

[Product site](https://johnnybgoodlithium.github.io/Local-Video-Meeting-Minutes/)

<!-- maturity: controlled-single-machine-poc -->
<!-- product-version: v0.15.3 -->

## Overview

Local Video Meeting Minutes is a local-first workflow that turns meetings and first-party videos into evidence-linked, reusable context. It connects configurable speech recognition, speaker separation, visual understanding, and text generation while keeping transcripts, confirmed identities, revisions, and source links independent from any one model.

The application can deliver an offline MeetingPack, portable AI Context, and knowledge-base (KB) projection for downstream RAG. It is model-agnostic: providers may run locally or through explicitly approved endpoints, and the system does not silently cross the configured privacy boundary.

## Why it exists

Meeting summaries are useful only when people can check where a statement came from and correct the source when it is wrong. This project keeps review close to the original audio, transcript, speaker identity, screen evidence, and first-party material. Model output assists interpretation; it is not the source of truth.

The project also explores how one controlled local machine can compile trusted context for humans, general-purpose AI tools, and knowledge systems without requiring private meetings to become cloud training or troubleshooting material.

## Core capabilities

- **Identity correction:** review who said what, confirm or correct identities, and preserve reversible history.
- **Source-linked review:** move from a conclusion back to the relevant transcript, audio, screen, or supplied material.
- **Progressive meeting processing:** make transcript and voice draft outputs available before optional visual enrichment finishes.
- **MeetingPack:** export an offline, reviewable meeting package.
- **AI Context:** produce portable context for explicitly chosen AI tools without binding the meeting to one model.
- **KB projection and RAG:** project validated material into a knowledge-base-friendly form and retrieve evidence-linked context.
- **Meeting and first-party video routes:** support controlled meeting review and videos supplied or authorized by the operator.

## How it works

The workflow imports local or explicitly authorized media, builds transcript and speaker context, adds visual and supplied material when available, and projects the result into review and export views. Canonical meeting artifacts stay separate from model-specific outputs. Human corrections create new revisions instead of silently rewriting the evidence history.

The default Web workflow runs on one controlled host. Local providers are preferred; any remote provider must be configured deliberately. The application never treats a page description, generated summary, or model answer as independent proof of a meeting decision.

## Current maturity

Current product version: **v0.15.3**.

| Area | Maturity | Current boundary |
|---|---|---|
| Meeting import, transcript and identity correction, evidence navigation, MeetingPack | Validated | Used in controlled real workflows with synthetic CI coverage |
| First-party video understanding, AI Context, KB projection, local RAG | Implemented, under validation | Functional, but quality and scale baselines are still developing |
| Cross-content comparison and experimental retrieval routes | Experimental | Not a stable product commitment |
| SSO, ACLs, tenant isolation, and multi-user production service | Out of scope | A local port must not be treated as production deployment |

This is a controlled single-machine proof of concept, not a production multi-user service. Meeting review is validated more deeply than video understanding and cross-content RAG. See [current status](docs/STATUS.md) for the maintained validation state.

## Quick start

Linux, Python 3.11+, and `ffmpeg/ffprobe` are required. Full model execution also requires hardware-compatible PyTorch, model services, and model files; consult the [deployment runbook](docs/runbooks/DEPLOYMENT.md) before changing a working CUDA or ROCm environment.

```bash
git clone <repository-url> meeting-minutes
cd meeting-minutes
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

make doctor
make check
make run
```

Open `http://127.0.0.1:8899/`. `make smoke` uses an isolated temporary data root and synthetic fixtures; it must not read real meetings.

## Privacy and trust boundary

The public repository contains code, synthetic fixtures, templates, and sanitized documentation only. Do not commit real meetings, transcripts, minutes, names, voiceprints, organization structures, credentials, internal URLs, raw logs, exports, or private reports.

Local-first does not mean every configured provider is local. Remote endpoints are allowed only when the operator explicitly approves and configures them. The application must fail clearly rather than silently changing the privacy boundary. See [SECURITY.md](SECURITY.md) and [open risks](docs/RISKS.md).

## Documentation

| Question | Authoritative document |
|---|---|
| Where should I start? | [Documentation index](docs/INDEX.md) |
| What is validated now? | [Current status](docs/STATUS.md) |
| What is the product boundary? | [Product definition](docs/PRODUCT.md) |
| Which capabilities exist? | [Product functions](docs/PRODUCT_FUNCTIONS.md) |
| How do canonical data, revisions, and providers work? | [Architecture](docs/ARCHITECTURE.md) |
| What interaction contracts are stable? | [UX](docs/UX.md) |
| How is the application operated and recovered? | [Operations](docs/OPERATIONS.md) |
| How do MeetingPack, AI Context, KB projection, and RAG relate? | [Knowledge and RAG](docs/KNOWLEDGE_RAG.md) |
| What remains risky or unresolved? | [Risks](docs/RISKS.md) |
| What changed by version? | [Changelog](CHANGELOG.md) |

## Release and installation status

The current distribution models are a source checkout and a verified **Application Release Bundle** containing the application scripts, Web assets, prompts, deployment examples, locked lightweight dependencies, and required documentation.

This is not a PyPI package. `pip install -e .` currently installs base dependencies and project metadata while the application continues to run from the repository or bundle directory. There is no stable public Python import API and no promise that a pip installation can be launched from an arbitrary directory.

## License status

This repository currently does not include an open-source license.
Review ownership and company policy before redistribution or commercial use.
