#!/usr/bin/env python3
"""결정 주입 훅 — `twbuild decide` 로 생긴 팀 결정을 개발자 서브에이전트에게 넣는다 (AGENT.md 5장 · PoC 2 · 3).

워크트리의 .claude/rules 는 브랜치 시점 사본이라 빌드 중 생긴 결정이 안 보인다. 그래서:
  SubagentStart (agent_type *-dev)        현재 과제의 기능에 속한 결정 전부를 additionalContext 로
  PreToolUse (Read|Edit|Write|MultiEdit)   이 agent_id 에 마지막으로 넣은 뒤 새로 생긴 결정만 — 상대 플랫폼의 잠정 결정이 여기로 온다
중복 제거는 agent_id 기준 (.twbuild/tmp/inject-<agent_id>.json). 표준 라이브러리만, 서버 모듈(decide · util)은 stdlib 이라 import 한다.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))


def find_root(start):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, ".twbuild", "config.yaml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def out(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, ensure_ascii=False))


def main():
    data = json.load(sys.stdin)
    event = data.get("hook_event_name", "")
    agent_id = data.get("agent_id") or ""
    agent_type = data.get("agent_type") or ""
    if event == "PreToolUse" and not agent_id:
        return                                   # 메인 세션(lead)에는 넣지 않는다 — lead 는 파일을 직접 본다
    root = find_root(data.get("cwd")) or find_root(os.environ.get("CLAUDE_PROJECT_DIR"))
    if not root:
        return
    from twbuild import decide, util
    cur = util.read_json(util.tw(root, "tasks", "_current.json"), {}) or {}
    feature = cur.get("feature")
    if not feature:
        return
    mark_path = util.tw(root, "tmp", f"inject-{agent_id or 'main'}.json")
    mark = util.read_json(mark_path, {}) or {}
    if event == "SubagentStart":
        if not re.search(r"(^|:)(ios|android)-dev$", agent_type):
            return
        decs = decide.since(root, feature, "")
        util.write_json(mark_path, {"t": util.now(), "feature": feature})
        if not decs:
            return
        lines = [f"Team decisions for feature `{feature}` (binding; recorded with `twbuild decide`):"]
        lines += [f"- {d['id']} [{d['status']}] `{d['topic']}` — {d['text']} (by {d['by']})" for d in decs]
        out("SubagentStart", "\n".join(lines))
        return
    if event == "PreToolUse":
        since = mark.get("t", "")
        decs = decide.since(root, feature, since)
        if not decs:
            return
        util.write_json(mark_path, {"t": util.now(), "feature": feature})
        lines = ["New team decisions since you started (follow them; if one contradicts your work, adapt or report blocked):"]
        lines += [f"- {d['id']} [{d['status']}] `{d['topic']}` — {d['text']} (by {d['by']})" for d in decs]
        out("PreToolUse", "\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
