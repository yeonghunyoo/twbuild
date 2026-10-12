#!/bin/sh
# twbuild pre-commit — 스테이지된 파일의 시크릿 · 민감 파일 검사 (AGENT.md 11장). twbuild wire 가 설치한다(멱등).
# 플러그인이 없으면 조용히 통과한다. 워크트리에서도 같은 훅이 돈다(.git/hooks 는 공용).
RUN="__RUN__"
[ -f "$RUN" ] || exit 0
exec python3 "$RUN" scan --staged --root "$(git rev-parse --show-toplevel)"
