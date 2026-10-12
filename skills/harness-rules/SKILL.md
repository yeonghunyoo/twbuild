---
name: harness-rules
description: Rule IDs of the twbuild harness that gates and hooks cite — tree parity rules (T1–T6), hook blocks (H1–H7), design-import rules (D1–D5). Preloaded into developers so a rejection message is understood without asking.
user-invocable: false
---

# harness-rules

What the developers know is exactly what the gate measures. A failure or rejection message cites one of these IDs.

## Tree parity (static gate, both platforms)
| ID | Rule | How it is measured |
|---|---|---|
| T1 | Every view node of the layout tree exists in code with its id | the id string appears as `accessibilityIdentifier("…")` / `testTag("…")` |
| T2 | Every `if` state key and `list` items key of the tree exists in code | the camelCased key appears in the platform's source |
| T3 | Every `on_*` handler has an Action | `<handler>` (top level) or `<items><Handler>(item)` (inside a list) appears as an Action case |
| T4 | No literal color that is not in the tree or the tokens | hex literals in source ⊆ tree values ∪ token colors |
| T5 | Route set iOS = Android | enum cases of `Route.swift` vs sealed members of `Route.kt` |
| T6 | Data-layer type names iOS = Android | type names under `App/Core/Data` vs `core/data` (Repository · Store · Draft · models) — same names, same method names |
| T7 | Design-system component names iOS = Android | types + capitalized functions (Composables) under `App/Core/DesignSystem` vs `core/designsystem` |
| T10 | UiState fields · Actions iOS = Android | field names + types of `<Screen>UiState` (Bool≡Boolean, [T]≡List<T>) and Action names + parameter types — the generator made them equal; keep them equal when you change one |
| T9 | Font registration iOS = Android | fonts in `App/Resources/Fonts` + `UIAppFonts` vs `res/font/` (family · weight · style) — the harness registers them; do not add or remove fonts yourself |
| T8 | A class node uses its catalog component | for a tree node whose `class` is an implemented catalog component `<Name>`, the screen code calls `<Name>(` / `<Name> {` (the draft already wraps it) |

Also binding: the structure (nesting · order · containers) is the tree's; UiState field names, Action names and data object names/methods are the
same on both platforms (the generator names them; keep them).

## Builds · device · commits
- Build layer: the app compiles (`xcodebuild` / `gradlew assembleDebug`) — measured again by the gate, not taken from your report.
- Device layer (config `smoke.device`, default `merge` = once, right before the merge): the gate installs the built app on a booted simulator / connected device, launches it and checks it is still alive after 5 s. A crash fails the smoke (log tail comes back in the rework task). No device → "unmeasured": never pass, never fail.
- Contract decoding is measured by the harness when enabled; "unmeasured" never counts as pass.
- S1 commits: a pre-commit hook scans staged files for secrets and sensitive files (`.env*`, keys, certificates) and rejects the commit with the rule name. The merge re-scans every file your branch changed; a hit blocks the merge until a human removes it. Values go to `.env.local`, examples to `.example` files. A false positive: `git commit --no-verify` and say so in your task note.

## Hooks (yolo mode safety)
| ID | Blocked |
|---|---|
| H1 | `git push` |
| H2 | git history rewrite (reset --hard · rebase · amend · filter) |
| H3 | writes outside the repo (temp dirs are fine) |
| H4 | protected areas: `design/` · `api/generated/` · `api/fragments/` · `.twbuild/` (except `.twbuild/tasks/`) |
| H5 | secrets: `.env*`, keys, certificates, `~/.ssh`; `env`/`printenv` dumps |
| H6 | installs and privilege: sudo · brew install · pip/npm global installs · `curl | sh` |
| H7 | any write to Claude Design |

## Design import (lead only)
D1 call outside a design run · D2 other project · D3 denied file (support.js, standalone HTML, bundles, uploads, binaries) · D4 outside the allow list · D5 over the size cap.
