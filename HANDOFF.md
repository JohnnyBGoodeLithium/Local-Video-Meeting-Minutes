# v0.16.0 Release Handoff
- Current release target: `v0.16.0`
- Previous release: `v0.15.3`
- Release branch: `release/v0.16.0`
- Base SHA: `e93d22cc7cc9a1ff0992d266717d516476bbd67e`
- Feature freeze: **yes**
- State: release-preparation PR; no tag or GitHub Release

## Capabilities
- Voice-first minutes with later visual completion; person-focused review, source return, conservative speaker correction, field-photo analysis, and MeetingPack.
- Adaptive Companion Phone/Tablet/Laptop review: jobs, Library, URL/file/video send, playback, captions, identity binding, display rename, and undo.
- Viewer local speaker alias, aligned audio/video layout, transcript-linked captions, and old-pack compatibility.
- Experimental Live Context for authorized public, non-DRM native HLS. Full evidence: [reality matrix](docs/releases/v0.16.0-reality-matrix.md).

## Boundaries and validation
- Live is **Experimental**: synthetic/replay and Hosted Chromium pass; real live event, target-host latency, and browser audio capture are **NOT TESTED**.
- Companion hosted layouts/journeys pass; iPhone 15 Pro + X Ultra Tailscale Serve and iPhone fullscreen captions are **NOT TESTED**.
- Companion transport is not enterprise approval; backend remains localhost-only, Funnel disabled. No adaptive video proxy; broader KB/RAG scale remains early.
- Integrated main `e93d22c`: hosted check/smoke, 216 checks, Chromium/screenshots, and clean-bundle verification passed.
- Release branch local `make check` and 216-check smoke pass; bundle structure/checksums pass. Local full bundle smoke is blocked only by absent Chromium and remains a Hosted CI gate. Pages HTTP result is pending merge.

## Blockers and publish
- Release PR/hosted CI, final local checks, clean bundle, privacy scan, and post-merge production Pages smoke must pass.
- `release/authorized-tag.txt` remains `v0.15.3` until the user explicitly says **Publish v0.16.0**.
- Then: verify clean green `main` and device record; set authorization to `v0.16.0`; run `RELEASE_TAG=v0.16.0 make release-verify`; merge authorization.
- Tag exactly that commit with `git tag -a v0.16.0 -m "Meeting Context v0.16.0"`; run `git push origin v0.16.0`.
- Let `.github/workflows/release.yml` create the pre-release/assets; verify ZIP, tar.gz, manifest, checksums, and public product page.

TAG CREATED: **NO**
