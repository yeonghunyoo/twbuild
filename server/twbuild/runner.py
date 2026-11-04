"""빌드 머신 — 원격 러너 (AGENT.md 15장).

조종 기기(플러그인이 도는 곳)에 그 플랫폼 툴체인이 없으면 빌드 · 계약 디코딩 · 기기 층을 그 플랫폼 머신의
GitHub Actions 자체 호스팅 러너에서 돌리고 결과를 git 으로 돌려받는다.

  조종 기기: 워크트리 스냅샷 → commit-tree(메시지 = 요청 JSON) → push <prefix>/run/<플랫폼>/<id>
  러너:      twbuild run-job → result.json · 로그 · 스크린샷을 부모 없는 커밋으로 push <prefix>/result/<플랫폼>/<id>
  조종 기기: ls-remote 대기 → fetch → 로컬 경로에 풀기 → 두 브랜치 삭제

표준 라이브러리만 쓴다 — 러너 머신에는 venv 가 없다.
"""
import json
import os
import platform as _platform
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from . import config, leaks, util

MODES = ("auto", "local", "remote")
JOBS = ("ping", "build", "decode", "device")
STATE = "runner.json"                       # .twbuild/runner.json — 자격 캐시 · 마지막 ping
VIS_CACHE_S = 86400
WORKFLOW = os.path.join(".github", "workflows", "twbuild-runner.yml")
TEMPLATE = os.path.join("github", "twbuild-runner.yml")
LABELS = {"ios": "twbuild-ios", "android": "twbuild-android"}
RESULT = "result.json"
REQ_MARK = "twbuild-run"


class RunnerError(RuntimeError):
    pass


# ─────────────────────────── 설정 · 방식 ───────────────────────────

def settings(cfg):
    b = (cfg or {}).get("build") or {}
    r = b.get("remote") or {}
    return {"runner": b.get("runner", "auto"), "prefix": str(r.get("prefix") or "twbuild").strip("/"),
            "timeout": int(r.get("timeout") or 2400), "poll": float(r.get("poll") or 5),
            "plugin_ref": str(r.get("plugin_ref") or "main"), "plugin_repo": str(r.get("plugin_repo") or "yeonghunyoo/twbuild")}


def configured(cfg, platform):
    v = settings(cfg)["runner"]
    if isinstance(v, dict):
        v = v.get(platform, "auto")
    return v if v in MODES else "auto"


def problems(cfg):
    """config.problems 가 부른다 — 사람이 고칠 설정 오류."""
    v = settings(cfg)["runner"]
    vals = list(v.values()) if isinstance(v, dict) else [v]
    if any(x not in MODES for x in vals) or (isinstance(v, dict) and any(k not in config.PLATFORMS for k in v)):
        return [f"build.runner 는 {list(MODES)} 중 하나 또는 플랫폼별 {{ios: …, android: …}} 다: {v!r}"]
    return []


def local_capable(platform, t):
    if platform == "ios":
        return bool(t.get("xcodebuild") and t.get("xcodegen"))
    return bool(t.get("android_sdk") and t.get("java"))


def installed(root):
    return os.path.isfile(os.path.join(root, WORKFLOW))


def mode(root, cfg, platform, t=None):
    """local | remote. auto: 툴체인이 있으면 local, 없고 러너 워크플로가 깔려 있으면 remote, 그 밖은 local(= 지금처럼 못 잼)."""
    v = configured(cfg, platform)
    if v != "auto":
        return v
    if os.environ.get("TWBUILD_NO_BUILD"):
        return "local"
    if t is None:
        from . import probe
        t = probe.toolchain()
    if local_capable(platform, t):
        return "local"
    from . import git
    return "remote" if installed(git.main_root(root) or root) else "local"


# ─────────────────────────── 자격 (private 레포만) ───────────────────────────

_GH = re.compile(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
_PROXY = re.compile(r"/git/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def origin_repo(root):
    """origin 이 GitHub 이면 'owner/repo' (클라우드 세션의 git 프록시 주소도), 아니면 None."""
    r = _git(root, "remote", "get-url", "origin", check=False)
    url = r.stdout.strip()
    m = _GH.search(url) or (_PROXY.search(url) if "github" in url or "/git/" in url else None)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _api_visibility(repo):
    """토큰 없이 — 200 이면 public/private, 404 면 None(private 이거나 없음), 그 밖은 'unknown'."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers={"User-Agent": "twbuild", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
            return "private" if d.get("private") else "public"
    except urllib.error.HTTPError as e:
        return None if e.code == 404 else "unknown"
    except (urllib.error.URLError, OSError, ValueError):
        return "unknown"


def visibility(root, refresh=False):
    """→ {"repo", "value": private|public|unknown|not-github, "t"}. 하루 캐시."""
    st = _state(root)
    repo = origin_repo(root)
    cached = st.get("visibility") or {}
    if not refresh and cached.get("repo") == repo and time.time() - cached.get("ts", 0) < VIS_CACHE_S:
        return cached
    if os.environ.get("TWBUILD_VISIBILITY"):              # 테스트 · 수동 지정
        value = os.environ["TWBUILD_VISIBILITY"]
    elif not repo:
        value = "not-github"
    else:
        value = _api_visibility(repo)
        if value is None:
            value = "private" if _git(root, "ls-remote", "origin", "HEAD", check=False, timeout=30).returncode == 0 else "unknown"
    out = {"repo": repo, "value": value, "t": util.now(), "ts": time.time()}
    if not os.environ.get("TWBUILD_VISIBILITY"):
        _save_state(root, visibility=out)
    return out


def eligible(root):
    """(True | False | None, 사유). False 면 원격 러너를 쓰지 않는다 — public 거부는 설정으로 못 푼다."""
    v = visibility(root)
    if v["value"] == "private":
        return True, f"{v['repo']} · private"
    if v["value"] == "public":
        return False, f"{v['repo']} 는 public 레포다 — 자체 호스팅 러너는 private 레포에서만 쓴다(포크 PR 이 러너 머신에서 코드를 돌릴 수 있다)"
    if v["value"] == "not-github":
        return False, "origin 이 GitHub 이 아니다 — 원격 러너는 GitHub Actions 로 돈다"
    return None, f"{v.get('repo') or '?'} 공개 여부 못 잼(네트워크) — 막지 않는다"


# ─────────────────────────── 상태 ───────────────────────────

def _state(root):
    from . import git
    return util.read_json(util.tw(git.main_root(root) or root, STATE), {}) or {}


def _save_state(root, **kv):
    from . import git
    base = git.main_root(root) or root
    if not util.is_wired(base):
        return
    st = _state(base)
    st.update(kv)
    util.write_json(util.tw(base, STATE), st)


# ─────────────────────────── git ───────────────────────────

def _git(cwd, *args, env=None, check=True, timeout=120, input_=None):
    try:
        r = subprocess.run(["git", "-C", cwd, "-c", "core.quotePath=false", *args], capture_output=True, text=True,
                           env={**os.environ, **(env or {})}, timeout=timeout, input=input_)
    except subprocess.TimeoutExpired:
        if check:
            raise RunnerError(f"git {args[0]} 시간 초과 {timeout}s")
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    if check and r.returncode != 0:
        raise RunnerError(f"git {' '.join(args[:2])}: {leaks.mask_all((r.stderr or r.stdout).strip())[:400]}")
    return r


_BOT = {"GIT_AUTHOR_NAME": "twbuild", "GIT_AUTHOR_EMAIL": "twbuild@localhost", "GIT_COMMITTER_NAME": "twbuild", "GIT_COMMITTER_EMAIL": "twbuild@localhost"}


def snapshot(wt):
    """작업 트리 전체(커밋 안 된 변경 포함, gitignore 제외)의 tree 해시 — 임시 인덱스로, 워크트리 인덱스 · HEAD 는 그대로."""
    fd, idx = tempfile.mkstemp(prefix="twbuild-index-")
    os.close(fd)
    os.unlink(idx)
    env = {"GIT_INDEX_FILE": idx}
    try:
        if _git(wt, "rev-parse", "--verify", "HEAD", check=False).returncode == 0:
            _git(wt, "read-tree", "HEAD", env=env)
        _git(wt, "add", "-A", env=env, timeout=600)
        return _git(wt, "write-tree", env=env).stdout.strip()
    finally:
        if os.path.exists(idx):
            os.unlink(idx)


def _refs(cfg, platform, rid):
    p = settings(cfg)["prefix"]
    return f"refs/heads/{p}/run/{platform}/{rid}", f"refs/heads/{p}/result/{platform}/{rid}"


def make_request(wt, platform, jobs, vars_, cfg, rid=None):
    """요청 커밋을 만든다(push 는 안 한다) → (commit, run_ref, result_ref, req)."""
    bad = [j for j in jobs if j not in JOBS]
    if bad:
        raise RunnerError(f"모르는 잡: {bad}")
    rid = rid or time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
    run_ref, result_ref = _refs(cfg, platform, rid)
    req = {"v": 1, "id": rid, "platform": platform, "jobs": list(jobs), "vars": vars_,
           "cfg": {k: cfg.get(k) for k in ("platforms", "app", "min_os", "auth") if k in cfg},
           "result_ref": result_ref, "plugin": util.plugin_version()}
    tree = snapshot(wt)
    parent = ["-p", "HEAD"] if _git(wt, "rev-parse", "--verify", "HEAD", check=False).returncode == 0 else []
    msg = f"{REQ_MARK} {platform} {rid}\n\n{json.dumps(req, ensure_ascii=False)}\n"
    commit = _git(wt, "commit-tree", tree, *parent, input_=msg, env=_BOT).stdout.strip()
    return commit, run_ref, result_ref, req


def parse_request(message):
    """커밋 메시지 → 요청 dict. 형식이 아니면 RunnerError."""
    head, _, body = (message or "").partition("\n\n")
    if not head.startswith(REQ_MARK):
        raise RunnerError("twbuild 요청 커밋이 아니다")
    try:
        req = json.loads(body.strip())
    except ValueError as e:
        raise RunnerError(f"요청 JSON 오류: {e}")
    if req.get("platform") not in config.PLATFORMS or any(j not in JOBS for j in req.get("jobs") or []):
        raise RunnerError("요청의 platform · jobs 가 열거형 밖이다")
    if not re.fullmatch(r"refs/heads/[\w./-]+/result/(ios|android)/[\w.-]+", req.get("result_ref") or ""):
        raise RunnerError("요청의 result_ref 형식 오류")
    return req


def _remote_has(cwd, ref):
    r = _git(cwd, "ls-remote", "origin", ref, check=False, timeout=60)
    return r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None


def roundtrip(root, wt, platform, jobs, vars_, cfg, dest):
    """요청 push → 결과 대기 → dest 디렉터리에 결과 파일을 푼다 → result dict. 실패는 RunnerError."""
    st = settings(cfg)
    commit, run_ref, result_ref, req = make_request(wt, platform, jobs, vars_, cfg)
    t0 = time.monotonic()
    _git(wt, "push", "--quiet", "origin", f"{commit}:{run_ref}", timeout=300)
    try:
        sha = None
        deadline = t0 + st["timeout"]
        while time.monotonic() < deadline:
            sha = _remote_has(wt, result_ref)
            if sha:
                break
            time.sleep(st["poll"])
        if not sha:
            raise RunnerError(f"러너 응답 없음 {st['timeout']}s — {platform} 러너가 켜져 있는지 `twbuild runner ping {platform}`")
        _git(wt, "fetch", "--quiet", "--no-tags", "origin", result_ref, timeout=300)
        sha = _git(wt, "rev-parse", "FETCH_HEAD").stdout.strip()
        _extract(wt, sha, dest)
        res = util.read_json(os.path.join(dest, RESULT), None)
        if not isinstance(res, dict):
            raise RunnerError("결과 커밋에 result.json 이 없다")
        res["roundtrip_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return res
    finally:
        for ref in (run_ref, result_ref):                 # 남기지 않는다 — 실패해도 다음 왕복을 막지 않는다
            _git(wt, "push", "--quiet", "origin", f":{ref}", check=False, timeout=120)


def _extract(cwd, sha, dest):
    os.makedirs(dest, exist_ok=True)
    names = _git(cwd, "ls-tree", "-r", "--name-only", sha).stdout.splitlines()
    for n in names:
        if n.startswith("/") or ".." in n.split("/"):
            continue
        r = subprocess.run(["git", "-C", cwd, "cat-file", "blob", f"{sha}:{n}"], capture_output=True)
        if r.returncode == 0:
            p = os.path.join(dest, *n.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(r.stdout)


# ─────────────────────────── 조종 기기: 층 ───────────────────────────

def _err_layers(platform, msg, jobs):
    out = {"build": {"status": "fail", "detail": f"원격 러너: {msg}", "runner_error": True}}
    if "decode" in jobs:
        out["contract_decode"] = {"status": "unmeasured", "detail": "빌드 층이 통과하지 않아 건너뜀"}
    if "device" in jobs:
        out["device"] = {"status": "unmeasured", "detail": "빌드 층이 통과하지 않아 건너뜀"}
    return out


def remote_layers(root, wt, platform, vars_, cfg, jobs, logs, screenshot=None):
    """원격으로 jobs(build · decode · device)를 돌려 로컬과 같은 모양의 층 결과를 돌려준다.
    logs = {"build": 경로, "decode": 경로, "device": 경로}. 실패는 build 층 fail + runner_error (fix 분류가 blocked(harness) 로)."""
    ok, why = eligible(root)
    if ok is False:
        return _err_layers(platform, why, jobs)
    dest = tempfile.mkdtemp(prefix=f"twbuild-result-{platform}-")
    try:
        try:
            res = roundtrip(root, wt, platform, jobs, vars_, cfg, dest)
        except RunnerError as e:
            return _err_layers(platform, str(e), jobs)
        layers = res.get("layers") or {}
        tag = f"{res.get('host') or '?'} · 왕복 {round(res.get('roundtrip_ms', 0) / 1000)}s"
        out = {}
        for key, job in (("build", "build"), ("contract_decode", "decode"), ("device", "device")):
            if job not in jobs:
                continue
            r = dict(layers.get(key) or {"status": "unmeasured", "detail": "러너가 이 층을 돌리지 않았다"})
            if r.get("log_file") and logs.get(job):
                src = os.path.join(dest, r.pop("log_file"))
                if os.path.isfile(src):
                    os.makedirs(os.path.dirname(logs[job]), exist_ok=True)
                    shutil.copyfile(src, logs[job])
                    r["log"] = logs[job]
            if r.get("screenshot_file"):
                src = os.path.join(dest, r.pop("screenshot_file"))
                if screenshot and os.path.isfile(src):
                    os.makedirs(os.path.dirname(screenshot), exist_ok=True)
                    shutil.copyfile(src, screenshot)
                    r["screenshot"] = screenshot
            r["runner"] = tag
            out[key] = r
        if "build" in out and out["build"].get("status") == "fail" and out["build"].get("log"):
            from . import gate
            out["build"]["tail"] = gate.tail(out["build"]["log"])
        return out
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def ping(root, platform, cfg=None):
    """main 의 작업 트리로 ping 잡 하나 — 러너가 살아 있는지 · 툴체인 · 왕복 초. .twbuild/runner.json 에 남긴다."""
    from . import git
    base = git.main_root(root) or root
    cfg = cfg or config.load(base)
    ok, why = eligible(base)
    if ok is False:
        rec = {"ok": False, "t": util.now(), "detail": why}
    elif not installed(base):
        rec = {"ok": False, "t": util.now(), "detail": f"{WORKFLOW} 없음 — `twbuild runner install` 뒤 main 을 push 한다"}
    else:
        dest = tempfile.mkdtemp(prefix="twbuild-ping-")
        try:
            res = roundtrip(base, base, platform, ["ping"], config.app_vars(cfg), cfg, dest)
            tc = res.get("toolchain") or {}
            rec = {"ok": local_capable(platform, tc), "t": util.now(), "host": res.get("host"), "seconds": round(res["roundtrip_ms"] / 1000, 1),
                   "toolchain": tc, "plugin": res.get("plugin"),
                   "detail": "" if local_capable(platform, tc) else f"러너 {res.get('host')} 에 {platform} 툴체인이 없다"}
        except RunnerError as e:
            rec = {"ok": False, "t": util.now(), "detail": str(e)}
        finally:
            shutil.rmtree(dest, ignore_errors=True)
    pings = _state(base).get("ping") or {}
    pings[platform] = rec
    _save_state(base, ping=pings)
    return rec


def last_ping(root, platform):
    return (_state(root).get("ping") or {}).get(platform)


# ─────────────────────────── 러너 머신: run-job ───────────────────────────

def _mask_file(path):
    if os.path.isfile(path):
        util.write_text(path, leaks.mask_all(util.read_text(path, "")))


def run_job(src, out, request=None):
    """러너 쪽 — src(체크아웃된 요청 커밋)의 요청대로 층을 돌리고 out 에 result.json · 로그 · 스크린샷을 쓴다 → result dict."""
    from . import device, gate, gen, probe
    req = request or parse_request(_git(src, "log", "-1", "--format=%B").stdout)
    p, jobs, vars_ = req["platform"], req.get("jobs") or [], req.get("vars") or {}
    cfg = config._merge(config.DEFAULTS, req.get("cfg") or {})
    os.makedirs(out, exist_ok=True)
    t = probe.toolchain()
    tc = {k: t.get(k) for k in ("os", "xcodebuild", "xcodegen", "simulators", "java", "android_sdk", "adb")}
    res = {"v": 1, "id": req.get("id"), "platform": p, "host": _platform.node(), "plugin": util.plugin_version(),
           "request_plugin": req.get("plugin"), "toolchain": tc, "t": util.now(), "layers": {}}
    L = res["layers"]
    if any(j != "ping" for j in jobs):
        if not local_capable(p, t):
            L["build"] = {"status": "fail", "detail": f"러너 {res['host']} 에 {p} 툴체인이 없다", "runner_error": True}
        else:
            b = gate.build(src, p, vars_, os.path.join(out, "build.log"))
            if b.get("status") == "pass":
                b["bytes"] = device.artifact_bytes(src, p, vars_)
            L["build"] = b
            if "decode" in jobs:
                L["contract_decode"] = (gen.decode_check(src, p, os.path.join(out, "decode.log"), cfg=cfg) if b.get("status") == "pass"
                                        else {"status": "unmeasured", "detail": "빌드 층이 통과하지 않아 건너뜀"})
            if "device" in jobs:
                L["device"] = (device.run(src, p, vars_, os.path.join(out, "device.log"), screenshot=os.path.join(out, "device.png"))
                               if b.get("status") == "pass" else {"status": "unmeasured", "detail": "빌드 층이 통과하지 않아 건너뜀"})
    for key, name in (("build", "build.log"), ("contract_decode", "decode.log"), ("device", "device.log")):
        r = L.get(key)
        if not r:
            continue
        _mask_file(os.path.join(out, name))
        if isinstance(r.get("log"), str) and os.path.isabs(r["log"]):
            r.pop("log")
            if os.path.isfile(os.path.join(out, name)):
                r["log_file"] = name
        elif key == "device":
            r["log"] = leaks.mask_all(r.get("log") or "")
        if r.get("screenshot"):
            r.pop("screenshot")
            r["screenshot_file"] = "device.png"
        r["detail"] = leaks.mask_all(r.get("detail") or "")
    util.write_json(os.path.join(out, RESULT), res)
    return res


def push_result(src, out, ref):
    """out 디렉터리를 부모 없는 커밋으로 origin 의 ref 에 push 한다 (러너 쪽)."""
    fd, idx = tempfile.mkstemp(prefix="twbuild-result-index-")
    os.close(fd)
    os.unlink(idx)
    env = {"GIT_INDEX_FILE": idx, "GIT_WORK_TREE": os.path.abspath(out), **_BOT}
    try:
        _git(src, "add", "-A", "--force", ".", env=env)
        tree = _git(src, "write-tree", env=env).stdout.strip()
    finally:
        if os.path.exists(idx):
            os.unlink(idx)
    commit = _git(src, "commit-tree", tree, input_="twbuild result\n", env=_BOT).stdout.strip()
    _git(src, "push", "--quiet", "origin", f"{commit}:{ref}", timeout=300)
    return commit


def run_job_cli(src, out, push=True, clean=False):
    """`twbuild run-job --dir <src> --out <dir>` — 워크플로가 부른다."""
    src = os.path.abspath(src)
    shutil.rmtree(out, ignore_errors=True)
    try:
        req = parse_request(_git(src, "log", "-1", "--format=%B").stdout)
    except RunnerError as e:
        return 2, f"run-job: {e}"
    if clean:
        _git(src, "clean", "-ffdq", check=False)          # ignored(DerivedData · build/) 는 남긴다 — 증분 빌드
    res = run_job(src, out, req)
    summary = " · ".join(f"{k} {v.get('status')}" for k, v in res["layers"].items()) or "ping"
    if push:
        try:
            push_result(src, out, req["result_ref"])
        except RunnerError as e:
            return 1, f"run-job: 결과 push 실패 — {e}"
    return 0, f"run-job {req['platform']} {req['id']}: {summary}"


# ─────────────────────────── 워크플로 설치 · CLI ───────────────────────────

def workflow_text(cfg):
    st = settings(cfg)
    text = util.read_text(os.path.join(util.TEMPLATES, TEMPLATE))
    for k, v in {"__PREFIX__": st["prefix"], "__PLUGIN_REPO__": st["plugin_repo"], "__PLUGIN_REF__": st["plugin_ref"],
                 "__LABEL_IOS__": LABELS["ios"], "__LABEL_ANDROID__": LABELS["android"]}.items():
        text = text.replace(k, v)
    return text


def install(root, cfg=None, commit=True):
    """대상 레포에 러너 워크플로를 쓰고 main 에 커밋한다 → (경로, 바뀜?)."""
    from . import git
    cfg = cfg or config.load(root)
    path = os.path.join(root, WORKFLOW)
    text = workflow_text(cfg)
    changed = util.read_text(path, None) != text
    if changed:
        util.write_text(path, text)
        if commit and git.is_repo(root):
            git.commit_paths(root, "chore(twbuild): build runner workflow", WORKFLOW)
    return path, changed


def status_markdown(root, cfg=None):
    from . import git, probe
    base = git.main_root(root) or root
    cfg = cfg or config.load(base)
    t = probe.toolchain()
    ok, why = eligible(base)
    L = ["## 빌드 머신 (15장)", "", f"- 레포: {why}", f"- 워크플로: {'있음' if installed(base) else f'없음 — `twbuild runner install`'} (`{WORKFLOW}`)", "",
         "| 플랫폼 | 설정 | 이 머신 툴체인 | 방식 | 마지막 ping |", "|---|---|---|---|---|"]
    for p in cfg.get("platforms") or []:
        lp = last_ping(base, p)
        lp_s = "—" if not lp else (f"✅ {lp.get('host')} · {lp.get('seconds')}s · {lp.get('t')}" if lp.get("ok") else f"❌ {lp.get('detail')} · {lp.get('t')}")
        L.append(f"| {p} | {configured(cfg, p)} | {'있음' if local_capable(p, t) else '없음'} | {mode(base, cfg, p, t)} | {leaks.mask_all(lp_s)} |")
    return "\n".join(L) + "\n"


def cli(argv, root):
    sub = argv[0] if argv else "status"
    if sub == "status":
        return 0, status_markdown(root)
    if sub == "install":
        path, changed = install(root)
        return 0, (f"{os.path.relpath(path, root)} {'를 쓰고 커밋했다' if changed else '는 이미 최신이다'} — main 을 origin 에 push 해야 러너가 받는다.\n"
                   f"러너 머신: 레포 Settings → Actions → Runners → New self-hosted runner, 라벨 {LABELS['ios']}(Mac) · {LABELS['android']}(Windows/Linux). 전용 저권한 계정으로 돌린다.")
    if sub == "ping":
        cfg = config.load(root)
        plats = argv[1:] or list(cfg.get("platforms") or [])
        lines, code = [], 0
        for p in plats:
            if p not in config.PLATFORMS:
                return 2, f"모르는 플랫폼: {p}"
            r = ping(root, p, cfg)
            code = code or (0 if r["ok"] else 1)
            lines.append(f"{p}: " + (f"✅ {r.get('host')} · 왕복 {r.get('seconds')}s" if r["ok"] else f"❌ {r.get('detail')}"))
        return code, "\n".join(lines)
    if sub == "visibility":
        v = visibility(root, refresh=True)
        return 0, f"{v.get('repo')}: {v['value']}"
    return 2, "twbuild runner [status|install|ping [ios|android]|visibility]"
