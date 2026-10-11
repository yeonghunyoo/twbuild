## twbuild

This repo is built by the twbuild harness (plugin `twbuild`). Before any development work, run `/twbuild` and follow the
graph — the MCP server `twbuild` owns the order and the gates; the lead (main session) only fills in tasks.

- Sources of truth: `design/` (Claude Design snapshot + layout trees), `api/openapi.yaml` (+ `api/fragments/`), `.twbuild/config.yaml`.
  Generated files (`api/generated/`, tokens, layout trees) are never edited by hand.
- Screens are implemented 1:1 from the layout tree, in pairs (iOS ∥ Android), inside `.twbuild/worktrees/`. Merge is automatic after smoke.
- Interpretations are recorded only with `twbuild decide`. Secrets live in `.env.local` only and never pass through chat.
- Talk to the user in Korean. Texts for agents (prompts, skills, rules) are English imperatives.
