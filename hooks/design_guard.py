#!/usr/bin/env python3
"""PreToolUse 검문 훅 — Claude Design 커넥터(mcp__*claude-design__*) 읽기를 design run 의 허용 목록 안에서만 통과시킨다 (AGENT.md 2장).

쓰기 · 공유 · 미리보기는 guard.py(H7)가 항상 막는다. 여기서는 읽기 도구만 본다:
  list_projects · get_project · list_design_systems  항상 통과 (메타데이터)
  list_files                                        run 안 · 그 run 의 프로젝트만
  read_file                                         run 안 · 허용 목록(고른 화면 · 참조 CSS/JSX · 디자인 시스템 파일) · 거부 목록 밖 · 크기 상한 안
판정 코드는 서버의 twbuild.design.allowed() 하나다 — 테스트 · doctor 가 같은 것을 쓴다. 표준 라이브러리만 쓰는 모듈이라 venv 가 없어도 돈다.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

TOOL = re.compile(r"^mcp__.*claude[-_]design__(\w+)$")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)


def find_root(start):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, ".twbuild", "config.yaml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def main():
    data = json.load(sys.stdin)
    m = TOOL.match(data.get("tool_name", ""))
    if not m:
        return
    tool = m.group(1)
    root = find_root(data.get("cwd")) or find_root(os.environ.get("CLAUDE_PROJECT_DIR"))
    if not root:
        return
    from twbuild import design
    inp = data.get("tool_input") or {}
    ok, rule, msg = design.allowed(root, tool, inp.get("project_id"), inp.get("path"))
    if not ok:
        deny(msg)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
