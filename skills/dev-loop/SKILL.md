---
name: dev-loop
description: Inner loop of a twbuild developer (iOS or Android) — order of work on a task, incremental build cadence, error handling, commit rhythm, when to decide alone vs record a decision vs report blocked, and the task-note format. Preloaded into ios-dev and android-dev.
user-invocable: false
---

# dev-loop

Procedure for one task (a screen or the data layer). Platform specifics (build commands, project layout) are in your playbook;
CSS → native translation is in your translate skill; rule IDs are in harness-rules.

## Order of work
1. Read, in this order: the task prompt → the layout tree JSON → the plan YAML → the brief → the structure draft files → team decisions.
2. Build once before changing anything (the draft compiles; if it does not, that is the first thing to fix and to mention in the note).
3. Work top-down through the tree: for each node, translate its `// style:` comment, keep its identifier, keep the nesting.
   Then the ViewModel (Action → UiState), then data wiring, then navigation. Icons and assets last.
4. Build incrementally after each coherent step (a component, a section, the ViewModel). Full build + no errors before you finish.

## Errors
- Fix compile errors first, then gate rule violations (IDs in harness-rules), then warnings that affect behavior.
- The same error twice → change approach (read the API doc, simplify, split). Three times → stop and report `blocked` with the error text.
- Long builds run once; wait for them (one wait, not repeated polling). Never run several builds at the same time.

## Commits
- Small commits: after each component/section, before each long build, and at the end. Messages: `<screen>: <what>` in English.
- Never commit secrets, build outputs or `.twbuild/` (except your task note).

## Decide alone · record · blocked
| Situation | Do |
|---|---|
| CSS maps cleanly to a platform idiom | Decide alone, implement. |
| Ambiguous translation for a node (blur, gradient center, gesture) | `twbuild decide <node id> "<interpretation>" --by <platform>` — then implement it. If a decision already exists for the node, follow it. |
| Needs a change outside your boundary (contract, shared component, design system, different structure than the tree, the other platform) | Do not change it. Report `blocked` with the exact need. |
| The design itself seems wrong | Not yours to fix. Implement as designed, mention it in the note. |

## Task note (`.twbuild/tasks/<task>-<platform>.md`)
```
# <task> — <platform>
- status: done | blocked
- did: …
- decisions: D-xx …
- uncertain: …
- build: pass | fail (<how it was built>)
```
End with a one-paragraph summary in your final message: status, commits, note path, open questions.
