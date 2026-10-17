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


def _design(a, root):
    """design start|capture|listing|trial|finish|shots|abort|status — 훅이 없는 자리(테스트 · 수동 import)에서 같은 코드를 부른다."""
    from twbuild import design, leaks
    sub = a.args[0] if a.args else "status"
    try:
        if sub == "start":
            run = design.start(root, a.scope, a.project, a.screen, ds_project_id=a.ds_project, bootstrap=a.bootstrap)
            print(f"{run['id']} 시작 — scope {run['scope']} · 화면 {run['screens']}")
        elif sub == "capture":
            with open(a.file, encoding="utf-8") as f:
                text = f.read()
            path, etag, body = design.decode_tool_text(text)
            rec = design.capture(root, a.path or path, body, a.etag or etag or "", a.project)
            print(f"캡처: {rec['dest']} ({rec['bytes']} bytes, sha256 {rec['sha256'][:12]})")
        elif sub == "listing":
            with open(a.file, encoding="utf-8") as f:
                n = design.record_listing(root, json.load(f))
            print(f"목록 {n}개 기록")
        elif sub == "trial":
            with open(a.file, encoding="utf-8") as f:
                text = f.read()
            spec = json.load(open(a.spec, encoding="utf-8")) if a.spec else None
            out = design.trial(root, text, spec)
            print(json.dumps(leaks.mask_all_deep(out), ensure_ascii=False, indent=2))
        elif sub == "finish":
            spec = json.load(open(a.spec, encoding="utf-8")) if a.spec else None
            out = design.finish(root, spec, preview_url=a.url)
            print(json.dumps(leaks.mask_all_deep(out), ensure_ascii=False, indent=2))
        elif sub == "shots":
            from twbuild import vis
            scope = a.scope or (design.active(root) or {}).get("scope")
            if not a.url or not scope:
                print("twbuild design shots --url <render_preview serve_url> [--scope <기능>]", file=sys.stderr)
                return 2
            r = vis.design_shots(root, scope, a.url)
            print(f"기준 이미지 {len(r['shots'])}개: {', '.join(sorted(r['shots']))}" + (f" · 못 간 화면: {', '.join(r['unreached'])}" if r["unreached"] else ""))
        elif sub == "abort":
            run = design.abort(root)
            print(f"{run['id']} 중단" if run else "진행 중인 run 이 없다")
        else:
            print(json.dumps(leaks.mask_all_deep({"active": design.active(root), "summary": design.summary(root)}), ensure_ascii=False, indent=2))
    except design.DesignError as e:
        print(str(e), file=sys.stderr)
        return 1
    except RuntimeError as e:                     # vis.VisError — 기준 이미지
        print(str(e), file=sys.stderr)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="twbuild MCP 서버 · CLI")
    ap.add_argument("cmd", nargs="?", default="serve",
                    choices=["serve", "doctor", "status", "advance", "submit", "init", "stats", "test", "decide", "version", "design", "tokens", "scan", "device", "skills", "gen", "mock", "check", "fonts", "tour", "icons"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--root", default=None)
    ap.add_argument("--scope", default=None, help="design start: 기능 이름")
    ap.add_argument("--project", default=None, help="design start: Claude Design 프로젝트 id")
    ap.add_argument("--ds-project", default=None, help="design start: 디자인 시스템 프로젝트 id")
    ap.add_argument("--screen", action="append", default=[], help="design start: 받을 화면 .dc.html (여러 번)")
    ap.add_argument("--bootstrap", action="store_true", help="design start: 디자인 시스템 컴포넌트까지 받는다(첫 사이클)")
    ap.add_argument("--path", default=None, help="design capture: 커넥터 경로")
    ap.add_argument("--etag", default="", help="design capture: etag")
    ap.add_argument("--file", default=None, help="design capture/listing/trial: 본문 파일")
    ap.add_argument("--spec", default=None, help="design finish/trial: 화면 spec JSON 파일")
    ap.add_argument("--url", default=None, help="design finish/shots: render_preview 의 serve_url (기준 이미지, 남기지 않는다)")
    ap.add_argument("--by", default=None, help="decide: ios | android | lead")
    ap.add_argument("--staged", action="store_true", help="scan: 스테이지된 파일만 (pre-commit 훅)")
    ap.add_argument("--port", type=int, default=8787, help="mock: 포트")
    ap.add_argument("--platform", default=None, help="check: ios | android (기본: 워크트리에서 추론)")
    ap.add_argument("--build", action="store_true", help="check: 플랫폼 빌드까지")
    ap.add_argument("--compare", action="store_true", help="stats: 기능별 비교 표")
    ap.add_argument("--feature", default=None, help="stats: 기능 하나의 요약")
    ap.add_argument("--retro", default=None, help="stats: 기능의 회고 보고서")
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
        print(metrics.retro_markdown(root, a.retro) if a.retro else metrics.compare_table(root) if a.compare else metrics.feature_table(root, a.feature) if a.feature else metrics.stats_table(root))
        return 0
    if a.cmd == "scan":
        from twbuild import git as g, leaks
        if a.staged:
            rels = g.staged_files(root)
            hits = leaks.scan_files(root, rels, reader=lambda rel: g.staged_text(root, rel))
        else:
            rels = list(a.args)
            hits = leaks.scan_files(root, rels)
        if hits:
            print("커밋 거부 — 시크릿 · 민감 파일 의심 (AGENT.md 11장):")
            for rel, kind, peek in hits:
                print(f"  {rel}: {kind} {peek}")
            print("값은 .env.local(gitignore)에, 예시는 .example 로. 거짓 양성이면 `git commit --no-verify` 로 넘기고 lead 에게 알린다.")
            return 1
        print(f"깨끗함 — {len(rels)}개 파일")
        return 0
    if a.cmd == "decide":
        from twbuild import decide
        try:
            code, msg = decide.cli(a.args + (["--by", a.by] if a.by else []), os.getcwd() if a.root is None else root)
        except decide.DecideError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(msg)
        return code
    if a.cmd == "tokens":
        from twbuild import tokens
        files = tokens.write(root)
        print("토큰 생성: " + (", ".join(files) if files else "design/ds/styles.css 가 없다"))
        return 0
    if a.cmd == "design":
        return _design(a, root)
    if a.cmd == "gen":
        from twbuild import gen
        files = gen.write(root)
        print("계약 코드 생성: " + (", ".join(files) if files else "api/openapi.yaml 이 없다"))
        return 0
    if a.cmd == "mock":
        from twbuild import mock
        mock.serve(root, a.port)
        return 0
    if a.cmd in ("device", "skills", "fonts", "icons", "tour"):
        from twbuild import device, fonts, icons, skills, tour
        code, msg = {"device": device, "skills": skills, "fonts": fonts, "icons": icons, "tour": tour}[a.cmd].cli(list(a.args), root)
        print(msg)
        return code
    bootstrap_venv()
    if a.cmd == "check":
        from twbuild import cycle
        code, msg = cycle.check_cli(os.getcwd() if a.root is None else root, a.platform, a.build)
        print(msg)
        return code
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
