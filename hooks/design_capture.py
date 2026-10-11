#!/usr/bin/env python3
"""PostToolUse 캡처 훅 — Claude Design read_file 의 본문을 엔티티 디코딩해 design/ 에 바이트 그대로 쓰고, 모델에게는 한 줄 요약만 넘긴다.
list_files 는 경로별 etag · size 를 run 에 남긴다 (support.js 의 etag 로 형식 변경을 감지한다) — 출력은 그대로 둔다.

5만 자를 넘어 Claude Code 가 디스크로 뺀 결과(tool_response 에 파일 경로가 있는 경우)도 그 파일을 읽어 같은 곳에 쓴다.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

TOOL = re.compile(r"^mcp__.*claude[-_]design__(read_file|list_files)$")
SAVED = re.compile(r"(?:saved to|Output has been saved to):?\s*(/\S+\.txt)")


def find_root(start):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, ".twbuild", "config.yaml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def response_text(resp):
    """tool_response 가 문자열 · {content: [{type: text, text}]} · [{text}] 어느 모양이든 본문 문자열로."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        if isinstance(resp.get("content"), list):
            return "".join(c.get("text", "") for c in resp["content"] if isinstance(c, dict))
        if isinstance(resp.get("text"), str):
            return resp["text"]
        return json.dumps(resp, ensure_ascii=False)
    if isinstance(resp, list):
        return "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in resp)
    return str(resp or "")


def main():
    data = json.load(sys.stdin)
    m = TOOL.match(data.get("tool_name", ""))
    if not m:
        return
    root = find_root(data.get("cwd")) or find_root(os.environ.get("CLAUDE_PROJECT_DIR"))
    if not root:
        return
    from twbuild import design
    if not design.active(root):
        return
    inp = data.get("tool_input") or {}
    text = response_text(data.get("tool_response"))
    saved = SAVED.search(text)
    if saved and os.path.isfile(saved.group(1)):
        with open(saved.group(1), encoding="utf-8", errors="replace") as f:
            text = f.read()
    if m.group(1) == "list_files":
        try:
            entries = json.loads(text)
        except ValueError:
            entries = []
        design.record_listing(root, entries if isinstance(entries, list) else [])
        return
    path, etag, body = design.decode_tool_text(text)
    path = path or inp.get("path")
    if not path or not body:
        return
    rec = design.capture(root, path, body, etag or "", inp.get("project_id"))
    summary = (f"captured by twbuild: {rec['dest']} ({rec['bytes']} bytes, sha256 {rec['sha256'][:12]}, etag {rec['etag'] or '-'}). "
               f"The file is in the repo now — read it from disk only if you must; the intake step derives the layout tree from it.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": summary}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
