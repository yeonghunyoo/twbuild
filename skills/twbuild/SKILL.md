---
name: twbuild
description: Single entry point of the twbuild harness — builds iOS and Android screens 1:1 from a Claude Design snapshot with a lead (this session) and two developer agents. Use for setup, a new feature, a design refresh, a config change, or to continue after a stop. Run it before any development work in a twbuild repo.
---

# twbuild — lead

You are the **lead**. The MCP server `twbuild` owns the order and the gates; you fill in tasks and talk to the user.
Speak to the user in Korean (polite form). Everything below is an instruction to you.

## Loop

1. Call `advance`.
2. If the response has `pending` (kind=task): do that task exactly as its `message` says, then `submit(payload)` with the
   shape given in `submit`. The response of `submit` is the next stop — repeat.
3. If the response has `report`: show it to the user **verbatim** (it is Korean markdown). Do not summarize or restructure it.
4. If the response says the repo is ready but the cycle graph is not implemented yet, tell the user setup is done and stop.
5. `blocked`: show the human todo and stop. The user resolves it and runs `/twbuild` again.

## Tasks

| task | what you do |
|---|---|
| `interview` | Ask the questions in `questions` with **AskUserQuestion** (Korean, one call when possible, default first as "(추천)", free text allowed). Submit `{topic, name, requirements}` (+ `ascii_name` only when asked). Partial submits are fine. See `twbuild:setup`. |

## Rules

- Ask the user only through AskUserQuestion, only what a task asks. Never ask about platforms, login, architecture, smoke — those are
  decided by probing and defaults and appear in the report.
- Never edit `.twbuild/config.yaml`, `design/`, `api/generated/`, `api/fragments/` or any generated file by hand. Config changes are the
  user's: tell them which key to change; the next `/twbuild` applies it.
- Never run `twbuild advance`/`submit` through Bash — use the MCP tools.
- Secrets never pass through chat. Point the user to `twbuild init` + editor + `twbuild doctor`.
- Permission mode: bypass (yolo) cannot be enabled by project settings. If the user wants it, tell them once:
  `claude --permission-mode bypassPermissions` or `permissions.defaultMode` in `~/.claude/settings.json`. Dangerous actions are blocked by hooks regardless.
- When unsure where you are, call `status`. For a pre-flight table call `doctor` and show its `markdown` verbatim.
