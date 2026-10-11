#!/usr/bin/env bash
# 도구 자신을 검사한다 — venv 가 없으면 run.py 가 만든다. 인자는 이름 조각(좁히기).
set -uo pipefail
cd "$(dirname "$0")/.."
exec python3 server/run.py test "$@"
