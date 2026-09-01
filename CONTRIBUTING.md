# Contributing / 参与贡献

## Project state

This repository is a controlled, local-first single-machine PoC. Contributions should improve a clear user problem without presenting experimental model output as canonical truth or silently expanding the privacy boundary.

本仓库处于本地优先的受控单机 PoC 阶段。贡献应解决明确的用户问题，不能把实验性模型输出变成 canonical 真源，也不能静默扩大隐私边界。

## Before starting

Read, in order:

1. [AGENTS.md](AGENTS.md)
2. [docs/STATUS.md](docs/STATUS.md)
3. [docs/INDEX.md](docs/INDEX.md)
4. one task-specific document selected from the index

Do not read `docs/archive/` by default. Use Git history for implementation detail and open archived material only when the task specifically requires it.

## Branches and Pull Requests

- Create a feature branch; do not develop directly on `main`.
- Explain the user problem, scope, data/API/schema impact, privacy boundary, failure behavior, rollback, and validation.
- Keep changes reviewable and avoid unrelated modernization.
- CI must pass `make check`, `make smoke`, Headless Chromium journeys, and whitespace checks before merge.
- Never force-push protected branches or move an existing tag.

## Data and privacy

Use only synthetic, fictional, public-domain, or explicitly authorized data. Never commit real meetings, transcripts, minutes, identities, voiceprints, organization relationships, credentials, internal URLs, raw logs, exports, private reports, or model weights. Do not add a silent cloud fallback.

## Product and engineering contracts

- New features must identify the user problem they solve.
- Do not create a second canonical source of truth.
- API or schema changes require an architecture update.
- User interaction changes require a UX update.
- Important release-facing changes belong in [CHANGELOG.md](CHANGELOG.md).
- Model and RAG experiments enter [docs/research/EXPERIMENT_LOG.md](docs/research/EXPERIMENT_LOG.md) before becoming product commitments.
- Framework rewrites are not accepted merely to appear modern; they require measurable migration value and an explicit plan.

## Local validation

```bash
make check
make smoke
git diff --check
```

Run focused tests while developing. Hardware/model changes also require the relevant Lenovo-host validation described in the runbooks.

## Dependency locks

The project uses pip and pip-tools for lightweight runtime and CI locks:

```bash
make lock
make lock-check
```

Do not generate a universal pipeline lock across CUDA, ROCm, PyTorch, and model runtimes. Follow the hardware-specific model and deployment references.

## Release candidates

```bash
make release-bundle
make release-verify
```

These commands build and verify an Application Release Bundle; they do not create a tag, GitHub Release, wheel, or PyPI publication.
