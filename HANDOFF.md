# Product Site Handoff
- Current task: Product site clarity and wide-screen stabilization
- Branch: `fix/product-site-surfaces-and-reuse`
- Base main: `cc7ea75cc7830cee462e27d1d3aac0dbcf6c0d6e`
- Version: `0.16.0` unchanged
- Remote `v0.16.0` tag / Release at task start: **absent**

## Commits
- `feat(site): separate review surfaces from knowledge reuse`
- `fix(site): stabilize wide-screen review and closing sections`
- `test(site): lock bilingual responsive product story`

## Information architecture
- Review surfaces: Workbench, Companion, MeetingPack
- Continuation layers: Minutes, Knowledge Base / WeKnora
- Locked line: 纪要讲清这一次，知识库连接下一次。

## Wide-screen bug and fix
- Root cause: `.final-cta::before` used viewport-derived horizontal positioning and `top: 0; bottom: 0`, so a decorative rail spanned the full CTA and detached visually from its fixed-width content on wide screens.
- Fix: a short clamped accent now belongs to the positioned `.final-cta-content`; section height is padding plus content, and balanced headline wrapping is constrained by readable inline size.

## Validation
- Targeted copy / DOM / Pages tests: passed
- `make check`: passed; `make smoke`: 216 passed, 0 failed (local Chromium journeys skipped because the binary is unavailable)
- Screenshot matrix: 393, 820, 1440, 1920, 2560 plus English 1440 / 1920; local Chromium unavailable, so the Hosted CI artifact is the visual acceptance source
- Existing main Pages build/deploy/production HTTP smoke: passed in run `33865462469`

## Release impact
- No VERSION change, tag action, Release action, or automatic `0.16.1`
- Main has no automatic tag publisher; open PR #26 would add one if separately merged
