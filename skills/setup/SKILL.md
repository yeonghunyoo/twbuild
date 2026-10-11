---
name: setup
description: How the lead runs the twbuild setup interview — three questions (app topic, name, requirements) via AskUserQuestion, then the report. Not a user entry point; the `interview` task of the setup graph names it.
user-invocable: false
---

# twbuild setup — interview

The setup graph asks you (the lead) for exactly three things. Everything else is probed or defaulted and listed in the report.

## Ask

Use **AskUserQuestion** once with all remaining `questions` (max 4 per call). Korean, polite. For each question:

| id | header | how |
|---|---|---|
| `topic` | 앱 주제 | One option "직접 입력" is not needed — users type via "Other". Offer 2–3 plausible topics only if the repo name hints at one; otherwise a single option "아직 정하지 않았어요 — 간단히 설명" plus free text. |
| `name` | 앱 이름 | First option = `defaults.name` labelled "(추천)"; second option = a Korean/English variant if obvious. Free text via "Other". |
| `requirements` | 요구사항 | Options: "핵심 기능 몇 가지만 적을게요" / "아직 없음 — 디자인대로". Free text via "Other" for the real list. |
| `ascii_name` | 영문 이름 | Only when present in `questions` (the name has no ASCII letters). First option = your transliteration "(추천)". |

Do not add questions. Do not explain the harness. If the user answers a question with nothing useful, submit what you have — the task
returns with what is still missing.

## Submit

`submit({"topic": "...", "name": "...", "requirements": "..."})` (+ `"ascii_name"` when asked). Keep the user's words; do not rewrite them.

## Report

When the response carries `report`, print it verbatim. Then say one line: what the user should do next (from the report's "다음").
