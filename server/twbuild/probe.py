"""실측 — probe 노드와 `twbuild doctor` 가 같은 함수를 쓴다. 저장 상태보다 실측이 이긴다.

checks(): 항목마다 {id, label, ok(True|False|None=못 잼), detail, fix(사람이 칠 명령), blocks(막는 범위), weight(큰 순 정렬)}.
ready(): 사이클 그래프로 넘어갈 수 있는가 — 설정 유효 · 앱 이름 · 골격 · 생성물 재생성 일치 · rules 골격 · selfcheck 결과.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys

from . import config, contract, gen, git, tokens, util

PY_MIN = (3, 10)
JDK_MIN = 17
SDK_CANDIDATES = ("ANDROID_HOME", "ANDROID_SDK_ROOT")


def _run(cmd, timeout=20, cwd=None, env=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def android_sdk():
    for k in SDK_CANDIDATES:
        v = os.environ.get(k)
        if v and os.path.isdir(v):
            return v
    home = os.path.expanduser("~")
    for p in (os.path.join(home, "Library", "Android", "sdk"), os.path.join(home, "Android", "Sdk")):
        if os.path.isdir(p):
            return p
    return None


def toolchain():
    """플랫폼 툴체인 실측 — 값은 버전 문자열 또는 None."""
    t = {"os": platform.system(), "xcodebuild": None, "xcodegen": None, "simulators": None,
         "java": None, "android_sdk": android_sdk(), "gradle": None, "adb": None}
    if t["os"] == "Darwin" and shutil.which("xcodebuild"):
        code, out = _run(["xcodebuild", "-version"], timeout=60)
        if code == 0:
            t["xcodebuild"] = out.strip().splitlines()[0]
        if shutil.which("xcrun"):
            code, out = _run(["xcrun", "simctl", "list", "devices", "available", "-j"], timeout=60)
            if code == 0:
                try:
                    devs = json.loads(out).get("devices", {})
                    t["simulators"] = sum(len(v) for k, v in devs.items() if "iOS" in k)
                except ValueError:
                    pass
    if shutil.which("xcodegen"):
        code, out = _run(["xcodegen", "--version"])
        t["xcodegen"] = out.strip() if code == 0 else "?"
    if shutil.which("java"):
        code, out = _run(["java", "-version"])
        m = re.search(r'version "(\d+)', out)
        t["java"] = int(m.group(1)) if m else None
    if shutil.which("gradle"):
        code, out = _run(["gradle", "--version"], timeout=60)
        m = re.search(r"Gradle (\S+)", out)
        t["gradle"] = m.group(1) if m else "?"
    adb = os.path.join(t["android_sdk"], "platform-tools", "adb") if t["android_sdk"] else None
    t["adb"] = adb if adb and os.path.isfile(adb) else (shutil.which("adb") or None)
    return t


def platform_available(t):
    """툴체인만으로 빌드할 수 있는 플랫폼 — 첫 config 의 platforms 기본값. 비어 있으면 둘 다 켠다(사람 할 일로 보인다)."""
    out = []
    if t["xcodebuild"]:
        out.append("ios")
    if t["android_sdk"] and t["java"] and t["java"] >= JDK_MIN:
        out.append("android")
    return out


def _check(id_, label, ok, detail="", fix="", blocks="", weight=0):
    return {"id": id_, "label": label, "ok": ok, "detail": detail, "fix": fix, "blocks": blocks, "weight": weight}


def checks(root, cfg=None, t=None):
    """사전 점검표. weight 가 클수록 막는 범위가 크다 (3 전체 · 2 플랫폼 하나 · 1 실기기 · 배포 · 0 선택)."""
    cfg = cfg or config.load(root)
    t = t or toolchain()
    plats = cfg.get("platforms") or []
    out = []
    out.append(_check("python", "Python 3.10+", sys.version_info >= PY_MIN, platform.python_version(),
                      "python.org 에서 3.10 이상을 설치한다", "전체", 3))
    out.append(_check("git", "git 레포", git.is_repo(root), "" if git.is_repo(root) else "레포가 아니다 — wire 가 init 한다",
                      "git init -b main", "전체", 3))
    name, email = git.identity(root) if git.is_repo(root) else ("", "")
    out.append(_check("git_identity", "git user.name · user.email", bool(name and email), "",
                      'git config user.name "<이름>" && git config user.email "<id>+<login>@users.noreply.github.com"', "커밋 · 머지", 3))
    if "ios" in plats:
        darwin = t["os"] == "Darwin"
        out.append(_check("xcode", "Xcode (xcodebuild)", bool(t["xcodebuild"]) if darwin else None,
                          t["xcodebuild"] or ("macOS 가 아니다" if not darwin else "없음"),
                          "xcode-select --install 또는 App Store 에서 Xcode 설치", "iOS 빌드 · 스모크", 2))
        out.append(_check("xcodegen", "xcodegen", bool(t["xcodegen"]), t["xcodegen"] or "없음",
                          "brew install xcodegen", "iOS 프로젝트 생성 · 빌드", 2))
        out.append(_check("simulator", "iOS 시뮬레이터", (t["simulators"] or 0) > 0 if darwin and t["xcodebuild"] else None,
                          f"{t['simulators']}대" if t["simulators"] is not None else "못 잼",
                          "Xcode → Settings → Platforms 에서 iOS 런타임 설치", "iOS 실행 스모크", 1))
    if "android" in plats:
        out.append(_check("android_sdk", "Android SDK", bool(t["android_sdk"]), t["android_sdk"] or "없음",
                          "Android Studio 설치 후 SDK Manager, 또는 ANDROID_HOME 설정", "Android 빌드 · 스모크", 2))
        out.append(_check("jdk", f"JDK {JDK_MIN}+", bool(t["java"] and t["java"] >= JDK_MIN), f"java {t['java']}" if t["java"] else "없음",
                          "brew install --cask temurin@17 (또는 Android Studio 내장 JDK 를 PATH 에)", "Android 빌드", 2))
        wrapper = os.path.isfile(os.path.join(util.app_dir(root, "android"), "gradlew"))
        out.append(_check("gradle", "Gradle (wrapper 또는 gradle)", wrapper or bool(t["gradle"]),
                          "wrapper 있음" if wrapper else (t["gradle"] or "없음"),
                          "brew install gradle (wrapper 생성용 — 한 번만)", "Android 빌드", 2))
        out.append(_check("adb", "adb", bool(t["adb"]), t["adb"] or "없음", "SDK platform-tools 설치", "Android 실행 스모크", 1))
    out.append(_check("claude_design", "Claude Design 커넥터", None, "서버에서 못 잼 — lead 가 도구 목록(mcp__claude-design__*)으로 확인",
                      "Claude Code 에서 Claude Design 커넥터를 연결한다", "디자인 import", 2))
    probs = config.problems(cfg) + config.locked_problems(root, cfg)          # 첫 머지 뒤 잠긴 값(architecture · min_os · app.id · app.product)
    out.append(_check("config", "config.yaml 유효", not probs, "; ".join(probs), ".twbuild/config.yaml 을 고친다", "전체", 3))
    out.append(_check("app", "앱 이름 · 식별자", bool((cfg.get("app") or {}).get("name") and (cfg.get("app") or {}).get("id")),
                      (cfg.get("app") or {}).get("id") or "interview 에서 정한다", "", "전체", 3))
    for p in plats:
        d = util.app_dir(root, p)
        out.append(_check(f"skeleton_{p}", f"{p} 골격", os.path.isdir(d) and bool(os.listdir(d)), d if os.path.isdir(d) else "없음 — scaffold 가 만든다",
                          "", f"{p} 전체", 2))
    try:
        drift = contract.drift(root) if os.path.isfile(os.path.join(root, util.API_DIR, util.API_FILE)) else ["(계약 없음)"]
        from . import icons
        drift += tokens.drift(root, cfg) + gen.drift(root, cfg) + icons.drift(root, cfg)
        out.append(_check("contract", "계약 · 토큰 → 생성물 재생성 일치", not drift, ", ".join(drift) if drift else "", "", "계약 · 클라이언트 · 토큰", 2))
    except contract.ContractError as e:
        out.append(_check("contract", "계약 · 토큰 → 생성물 재생성 일치", False, str(e), "api/openapi.yaml · fragments 충돌을 고친다", "계약 · 클라이언트 · 토큰", 2))
    out.append(_check("rules", ".claude/rules 골격", all(os.path.isdir(os.path.join(root, util.RULES_DIR, s)) for s in util.RULE_SCOPES), "", "", "메모리", 1))
    sc = util.read_json(util.tw(root, util.SELFCHECK), None)
    failed = [f"{k} 실패 — {v.get('detail', '')}" for k, v in ((sc or {}).get("layers") or {}).items() if v.get("status") == "fail"]
    out.append(_check("selfcheck", "selfcheck 결과", bool(sc) and not failed, "; ".join(failed) if failed else ("" if sc else "없음"),
                      "로그를 보고 골격을 고친 뒤 /twbuild 를 다시 실행한다" if failed else "", "빌드", 2))
    env_local = os.path.join(root, ".env.local")
    out.append(_check("env_local", ".env.local", os.path.isfile(env_local) or None, "" if os.path.isfile(env_local) else "없음 — twbuild init 이 틀을 만든다",
                      "twbuild init 뒤 에디터로 값을 채운다 (값은 채팅을 지나지 않는다)", "실서버 · 로그인 · 푸시", 1))
    hook = git.hook_installed(root, "pre-commit", git.PRECOMMIT_MARK) if git.is_repo(root) else None
    out.append(_check("precommit", "pre-commit 시크릿 검사 훅", hook, "" if hook else "없음 — 다음 /twbuild(prepare) 가 설치한다. 다른 pre-commit 훅이 있으면 그대로 두고 설치하지 않는다",
                      "", "커밋 전 시크릿 검사", 1))
    from . import device, skills                     # 늦은 import — device 는 probe.toolchain 을 쓴다
    av = device.available(t)
    dev_ok = None if any(av.get(p) is None for p in plats) else all(av.get(p) for p in plats)
    out.append(_check("device", "기기 (시뮬레이터 · adb 기기)", dev_ok,
                      " · ".join(f"{p}: {'있음' if av.get(p) else ('없음' if av.get(p) is False else '못 잼')}" for p in plats),
                      "" if dev_ok else "iOS: Xcode 의 시뮬레이터 · Android: `emulator -avd <이름>` 을 켜 둔다", "기기 스모크 층(없으면 못 잼)", 1))
    rows = skills.status(root, cfg)
    want = [r for r in rows if r.get("source") and not r.get("human")]
    out.append(_check("skills", "공개 스킬 설치(.claude/skills)", (all(r["installed"] for r in want) if want else None), skills.summary(rows),
                      "twbuild skills install" if want and not all(r["installed"] for r in want) else "", "개발자 스킬(필요할 때 호출)", 1))
    from . import fonts
    fst = fonts.status(root, cfg)
    out.append(_check("fonts", "웹폰트(styles.css → 두 앱 등록)", (not fst["missing"]) if fst.get("families") else None, fonts.summary(fst),
                      "twbuild fonts fetch 뒤 twbuild fonts install" if fst.get("missing") else "", "타이포그래피", 1))
    trust = _trusted(root)
    out.append(_check("trust", "워크스페이스 신뢰(allow 목록 적용)", trust,
                      "" if trust else ("~/.claude.json 에 기록 없음 — 헤드리스(claude -p) 세션은 이 레포의 allow 목록을 무시한다" if trust is False else "~/.claude.json 못 읽음"),
                      "이 레포에서 claude 를 한 번 대화형으로 열어 신뢰를 확인한다", "", 1))
    return out


def _trusted(root):
    """Claude Code 가 이 레포를 신뢰했는가 — ~/.claude.json projects[<root>].hasTrustDialogAccepted. 못 읽으면 None."""
    try:
        with open(os.path.expanduser("~/.claude.json"), encoding="utf-8") as f:
            projects = (json.load(f) or {}).get("projects") or {}
    except (OSError, ValueError):
        return None
    for key in (root, os.path.realpath(root)):
        if key in projects:
            return bool(projects[key].get("hasTrustDialogAccepted"))
    return False


READY_IDS = ("python", "git", "config", "app", "contract", "rules", "selfcheck")


def ready(root, cfg=None):
    """(준비됨?, 이유 목록). 플랫폼 골격은 활성 플랫폼마다 본다."""
    if not util.is_wired(root):
        return False, ["미배선 — .twbuild/config.yaml 이 없다"]
    cfg = cfg or config.load(root)
    cs = {c["id"]: c for c in checks(root, cfg, _light_toolchain())}
    reasons = []
    for cid in READY_IDS + tuple(f"skeleton_{p}" for p in cfg.get("platforms") or []):
        c = cs.get(cid)
        if c and c["ok"] is not True:
            reasons.append(f"{c['label']}: {c['detail'] or '실패'}")
    changed = changed_keys(root, cfg)
    if changed:
        reasons.append("설정 변경: " + ", ".join(changed))
    return not reasons, reasons


def _light_toolchain():
    """ready() 는 매 진입마다 돌므로 툴체인 명령은 부르지 않는다 — 준비 판정에 툴체인은 들어가지 않는다(못 잼은 허용)."""
    return {"os": platform.system(), "xcodebuild": None, "xcodegen": None, "simulators": None, "java": None,
            "android_sdk": android_sdk(), "gradle": None, "adb": None}


def applied(root):
    return util.read_json(util.tw(root, util.APPLIED), {}) or {}


def changed_keys(root, cfg=None):
    """마지막 셋업이 적용한 설정과 지금 설정의 차이 (점 경로)."""
    a = applied(root)
    if not a.get("config"):
        return []
    base = config._merge(config.DEFAULTS, a["config"])          # 플러그인이 새 기본 키를 더해도 "설정 변경" 이 아니다 (실측: lead.edit_apps 가 셋업을 다시 돌리려 했다)
    return config.diff_keys(base, cfg or config.load(root))


def probe(root):
    """probe 노드 — 실측 묶음. 그래프 상태에 들어가므로 작게 유지한다."""
    cfg = config.load(root)
    t = toolchain()
    cs = checks(root, cfg, t)
    ok, reasons = ready(root, cfg)
    return {
        "wired": util.is_wired(root),
        "toolchain": t,
        "platforms_available": platform_available(t),
        "apps_existing": [p for p in config.PLATFORMS if os.path.isdir(util.app_dir(root, p)) and os.listdir(util.app_dir(root, p))],
        "config_problems": config.problems(cfg),
        "changed_keys": changed_keys(root, cfg),
        "ready": ok,
        "reasons": reasons,
        "todos": todos(cs),
        "checks": [{k: c[k] for k in ("id", "label", "ok", "detail")} for c in cs],
    }


def todos(cs):
    """사람 할 일 — 실패한 항목만, 막는 범위 큰 순. 못 잼(None)은 넣지 않는다."""
    rows = [c for c in cs if c["ok"] is False and c["fix"]]
    rows.sort(key=lambda c: (-c["weight"], c["id"]))
    return [{"what": c["label"], "blocks": c["blocks"], "fix": c["fix"], "detail": c["detail"]} for c in rows]


def mark(ok):
    return "✅" if ok is True else ("❌" if ok is False else "— 못 잼")


def doctor_markdown(root):
    """`twbuild doctor` 출력 (한국어)."""
    cfg = config.load(root)
    cs = checks(root, cfg, toolchain())
    ok, reasons = ready(root, cfg)
    lines = ["## twbuild doctor", "", "| 항목 | 결과 | 비고 |", "|---|---|---|"]
    for c in cs:
        lines.append(f"| {c['label']} | {mark(c['ok'])} | {c['detail']} |")
    td = todos(cs)
    if td:
        lines += ["", "### 사람 할 일 (막는 범위 큰 순)", "", "| 할 일 | 막는 범위 | 명령 |", "|---|---|---|"]
        for r in td:
            lines.append(f"| {r['what']} | {r['blocks']} | `{r['fix']}` |")
    lines += ["", f"준비: {'✅ 사이클 그래프로 갈 수 있다' if ok else '❌ ' + ' · '.join(reasons)}"]
    lines += ["", "권한: 욜로(bypass) 모드는 프로젝트 설정으로 켤 수 없다 — `claude --permission-mode bypassPermissions` 로 시작하거나 "
              "`~/.claude/settings.json` 의 permissions.defaultMode 에 둔다. 위험 동작은 훅이 차단한다."]
    return "\n".join(lines)
