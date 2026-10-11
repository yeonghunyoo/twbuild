#!/usr/bin/env python3
"""twbuild 런처 + CLI.

  python3 run.py                       # MCP 서버 (stdio) — .mcp.json 이 이것을 부른다
  python3 run.py doctor  [--root R]    # 사전 점검 ✅/❌ (한국어)
  python3 run.py status  [--root R]
  python3 run.py advance [--root R]    # 그래프를 다음 멈춤까지 — 과제가 나오면 화면에 찍고 멈춘다
  python3 run.py submit <json|@file> [--root R]
  python3 run.py init    [--root R]    # .env.local 틀 (값은 묻지 않는다 — 에디터로 채운다)
  python3 run.py stats   [--root R]    # 측정 표
  python3 run.py test    [이름 조각]    # 자기 검사 (tests/cases.py)

의존성(requirements.txt)이 없으면 데이터 디렉터리(~/.claude/plugins/data/twbuild/venv)에 venv 를 만들어 갈아탄다 —
플러그인 캐시 디렉터리는 업데이트마다 바뀌지만 데이터 디렉터리는 남는다. 안내는 stderr 로 (stdout 은 JSON-RPC 통로).
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REQUIREMENTS = os.path.join(HERE, "requirements.txt")


def _have_deps():
    try:
        import langgraph  # noqa: F401
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def bootstrap_venv():
    from twbuild import util
    if _have_deps():
        return
    venv = os.path.join(util.data_dir(), "venv")
    py = os.path.join(venv, "bin", "python3")
    if os.environ.get("TWBUILD_BOOTSTRAPPED"):
        print("venv 에 빠진 의존성이 있다 — requirements.txt 를 설치한다.", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", REQUIREMENTS], check=False, stdout=sys.stderr.fileno())
        if _have_deps():
            return
        print(f"의존성을 못 찾았다 — {venv} 를 지우고 다시 띄운다.", file=sys.stderr)
        raise SystemExit(1)
    if sys.version_info < (3, 10):
        print("Python 3.10 이상이 필요하다.", file=sys.stderr)
        raise SystemExit(1)
    if not os.path.isfile(py):
        print(f"의존성이 없다 — {venv} 를 만든다 (최초 1회, 네트워크).", file=sys.stderr)
        try:
            os.makedirs(os.path.dirname(venv), exist_ok=True)
            subprocess.run([sys.executable, "-m", "venv", venv], check=True, stdout=sys.stderr.fileno())
            subprocess.run([py, "-m", "pip", "install", "-q", "-r", REQUIREMENTS], check=True, stdout=sys.stderr.fileno())
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"venv 생성 실패: {e}", file=sys.stderr)
            raise SystemExit(1)
    os.environ["TWBUILD_BOOTSTRAPPED"] = "1"
    os.execv(py, [py, os.path.abspath(__file__), *sys.argv[1:]])


def _print_task(out):
    p = out.get("pending")
    if p:
        print(out.get("message", ""))
        for k in ("questions", "defaults"):
            if p.get(k):
                print(f"\n{k}: " + json.dumps(p[k], ensure_ascii=False, indent=2))
        print(f"\n다음: python3 {os.path.abspath(__file__)} submit '<json>' --root <레포>")
        return
    if out.get("report"):
        print(out["report"])
    print(out.get("message") or json.dumps(out, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="twbuild MCP 서버 · CLI")
    ap.add_argument("cmd", nargs="?", default="serve",
                    choices=["serve", "doctor", "status", "advance", "submit", "init", "stats", "test", "decide", "version"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--root", default=None)
    a = ap.parse_args()
    root = os.path.abspath(a.root or os.environ.get("TWBUILD_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

    if a.cmd == "serve":
        os.environ.setdefault("TWBUILD_ROOT", root)
        bootstrap_venv()
        from twbuild import server
        server.main()
        return 0
    if a.cmd == "version":
        from twbuild import util
        print(json.dumps(util.plugin_version()))
        return 0
    if a.cmd == "test":
        bootstrap_venv()
        return subprocess.call([sys.executable, os.path.join(HERE, "..", "tests", "cases.py"), *a.args])

    from twbuild import leaks, metrics, probe, setup
    if a.cmd == "doctor":
        print(leaks.mask_all(probe.doctor_markdown(root)))
        return 0
    if a.cmd == "init":
        added = setup.env_local_init(root)
        print(f".env.local 에 키 {len(added)}개를 더했다: {', '.join(added) or '(없음)'}\n에디터로 값을 채운 뒤 `twbuild doctor` 로 확인한다. 값은 채팅으로 보내지 않는다.")
        return 0
    if a.cmd == "stats":
        print(metrics.stats_table(root))
        return 0
    if a.cmd == "decide":
        print("twbuild decide 는 사이클 그래프와 함께 붙는다 (다음 단계).", file=sys.stderr)
        return 2
    bootstrap_venv()
    from twbuild import router
    if a.cmd == "status":
        out = router.status(root)
    elif a.cmd == "advance":
        out = router.advance(root)
    else:
        if len(a.args) != 1:
            print("submit '<json>' 또는 submit @payload.json", file=sys.stderr)
            return 2
        raw = a.args[0]
        if raw.startswith("@"):
            with open(raw[1:], encoding="utf-8") as f:
                raw = f.read()
        out = router.submit(root, json.loads(raw))
    out = leaks.mask_all_deep(out)
    _print_task(out)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
