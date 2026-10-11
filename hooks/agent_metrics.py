#!/usr/bin/env python3
"""개발자 과제 측정 훅 — SubagentStart → SubagentStop 시간과 토큰 (AGENT.md 13장 "개발자 과제" 구간).

SubagentStop 입력의 agent_transcript_path(서브에이전트 자신의 JSONL)에서 usage 를 합산한다 — 자기신고가 아니라 트랜스크립트가 근거다.
기록은 twbuild.metrics.record 로 events.jsonl 에 (key agent:<agent_id>, 한 번만). 표준 라이브러리만.
"""
import json
import os
import re
import sys
import time

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


def usage_of(path):
    """트랜스크립트 JSONL → {input, output, cache_read, cache_create, turns, tool_uses}."""
    u = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "turns": 0, "tool_uses": 0}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message") if isinstance(rec, dict) else None
                if not isinstance(msg, dict):
                    continue
                us = msg.get("usage") or {}
                if us:
                    u["turns"] += 1
                    u["input"] += int(us.get("input_tokens") or 0)
                    u["output"] += int(us.get("output_tokens") or 0)
                    u["cache_read"] += int(us.get("cache_read_input_tokens") or 0)
                    u["cache_create"] += int(us.get("cache_creation_input_tokens") or 0)
                for c in msg.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        u["tool_uses"] += 1
    except OSError:
        return None
    return u


def main():
    data = json.load(sys.stdin)
    event = data.get("hook_event_name", "")
    agent_id = data.get("agent_id") or ""
    agent_type = data.get("agent_type") or ""
    if not agent_id or not re.search(r"(^|:)(ios|android)-dev$", agent_type):
        return
    root = find_root(data.get("cwd")) or find_root(os.environ.get("CLAUDE_PROJECT_DIR"))
    if not root:
        return
    from twbuild import metrics, util
    cur = util.read_json(util.tw(root, "tasks", "_current.json"), {}) or {}
    p = util.tw(root, "tmp", f"agent-{agent_id}.json")
    if event == "SubagentStart":
        util.write_json(p, {"t0": time.time(), "agent_type": agent_type, "task": cur.get("task"), "feature": cur.get("feature")})
        return
    if event == "SubagentStop":
        st = util.read_json(p, {}) or {}
        ms = round((time.time() - st["t0"]) * 1000, 1) if st.get("t0") else None
        us = usage_of(data.get("agent_transcript_path") or "")
        platform = "ios" if agent_type.endswith("ios-dev") else "android"
        metrics.record(root, "agent", key=f"agent:{agent_id}", agent_type=agent_type, platform=platform, task=(cur.get("task") or {}).get("id"),
                       feature=cur.get("feature"), ms=ms, usage=us)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
