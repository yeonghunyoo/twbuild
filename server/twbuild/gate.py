"""게이트 — 트리 정합성 (정적) · 빌드 (AGENT.md 6장). 리포트 · 자기신고를 판정에 쓰지 않는다 — 다시 잰다.

  static_check(root_or_worktree, platform, layout, tokens) → {"status": pass|fail, "violations": [{rule, detail}], "checked": n}
    T1 뷰 노드의 ID 가 코드에 있다 (accessibilityIdentifier / testTag 문자열)
    T2 if · list 의 상태 키가 코드에 있다
    T3 on_* 핸들러의 Action 이 코드에 있다
    T4 트리에 없는 직접값(hex 색) 이 없다 — 토큰 상수나 트리의 값만
    T5 Route 집합 iOS = Android (parity_check)
  build(worktree, platform, vars) → {"status", "detail", "log"}  — 과제 끝에 한 번. 기기 실행은 smoke.device 설정대로(뒤 단계).
규칙 ID 는 harness-rules 스킬과 같다 — 거부 · 실패 메시지가 같은 ID 를 인용한다.
"""
import os
import re
import subprocess

from . import draft, util

SRC_EXT = {"ios": (".swift",), "android": (".kt",)}
HEX_RE = re.compile(r"(?<![\w#])#([0-9a-fA-F]{6})\b|twHex:\s*0x([0-9A-Fa-f]{6})|Color\(0x[0-9A-Fa-f]{2}([0-9A-Fa-f]{6})\)")


def _sources(base, platform):
    out = {}
    skip = {"build", ".gradle", "DerivedData", ".twbuild", "Generated", "generated", ".build"}
    for d, dirs, names in os.walk(base):
        dirs[:] = [x for x in dirs if x not in skip]        # base(워크트리) 안의 경로 조각만 본다 — 워크트리 자체가 .twbuild/ 아래에 있다
        for n in names:
            if n.endswith(SRC_EXT[platform]):
                p = os.path.join(d, n)
                out[os.path.relpath(p, base)] = util.read_text(p, "")
    return out


def source_hexes(text):
    """디자인 원본(.dc.html — 로직 스크립트의 데이터 포함)에 적힌 색 리터럴. T4 는 이것도 허용한다."""
    out = {h.lower() for h in re.findall(r"#([0-9a-fA-F]{6})\b", text or "")}
    out |= {"".join(c * 2 for c in h.lower()) for h in re.findall(r"#([0-9a-fA-F]{3})\b", text or "")}
    return out


def _tree_values(lay):
    hexes = set()

    def walk(n):
        for v in (n.get("style") or {}).values():
            for h in re.findall(r"#([0-9a-fA-F]{6})\b", str(v)):
                hexes.add(h.lower())
            for h in re.findall(r"#([0-9a-fA-F]{3})\b", str(v)):
                hexes.add("".join(c * 2 for c in h.lower()))
        for c in n.get("children") or []:
            walk(c)
    if lay.get("root"):
        walk(lay["root"])
    return hexes


def static_check(base, platform, lay, token_hexes=(), extra_hexes=()):
    """base: 워크트리(또는 레포) 루트. 화면 코드 전체를 대상으로 본다 (파일 자리는 개발자 소유)."""
    src = _sources(os.path.join(base, util.APPS[platform]), platform)
    blob = "\n".join(src.values())
    violations, checked = [], 0
    an = draft.analyze(lay)

    def walk(n, scope):
        nonlocal checked
        k = n.get("kind")
        if k in draft.VIEW_KINDS or k == "screen":
            checked += 1
            if util_quote(n.get("id", "")) not in blob:
                violations.append({"rule": "T1", "detail": f"node id missing in {platform} code: {n.get('id')}"})
        if k == "if":
            checked += 1
            key = draft._flat(n["when"].split(".")[-1]) if "." in n["when"] and n["when"].split(".")[0] in scope else draft._flat(n["when"])
            if key not in blob:
                violations.append({"rule": "T2", "detail": f"state key of if missing: {n['when']} ({key})"})
        if k == "list":
            checked += 1
            key = draft._flat(n["items"])
            if key not in blob:
                violations.append({"rule": "T2", "detail": f"items key of list missing: {n['items']} ({key})"})
            scope = {**scope, n.get("as") or "item": draft._item_type(n["items"])}
        for key, v in n.items():
            if key.startswith("on_"):
                checked += 1
                head = v.split(".")[0]
                if scope and head in scope:
                    it = scope[head]
                    name = draft.camel(it[:-4] if it.endswith("Item") else it) + draft.pascal(draft._flat(v[len(head) + 1:] or "tap"))
                else:
                    name = draft.camel(draft._flat(v))
                if name not in blob and draft.pascal(name) not in blob:
                    violations.append({"rule": "T3", "detail": f"action for handler missing: {v} ({name})"})
        for c in n.get("children") or []:
            walk(c, scope)
    if lay.get("root"):
        walk(lay["root"], {})
    allowed = _tree_values(lay) | {h.lower() for h in token_hexes} | {h.lower() for h in extra_hexes}
    for rel, text in src.items():
        for m in HEX_RE.finditer(text):
            h = (m.group(1) or m.group(2) or m.group(3) or "").lower()
            if h and h not in allowed:
                violations.append({"rule": "T4", "detail": f"literal color not in tree/tokens: #{h} in {rel}"})
    return {"status": "fail" if violations else "pass", "violations": violations, "checked": checked, "files": len(src)}


def util_quote(s):
    return '"' + s + '"'


def routes(base, platform, vars_):
    """Route 이름 집합 (소문자) — iOS enum case · Android sealed 멤버."""
    if platform == "ios":
        t = _strip_comments(util.read_text(os.path.join(base, "apps/ios/App/Core/Navigation/Route.swift"), ""))
        return {m.lower() for m in re.findall(r"^\s*case\s+(\w+)", t, re.M)}
    pkg = vars_["id"].replace(".", "/")
    t = _strip_comments(util.read_text(os.path.join(base, f"apps/android/app/src/main/kotlin/{pkg}/core/navigation/Route.kt"), ""))
    return {m.lower() for m in re.findall(r"data (?:object|class)\s+(\w+)", t)}


def _strip_comments(text):
    """// 주석과 /* */ 주석을 뺀다 — 주석 속 예시 코드가 라우트로 잡히지 않게."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(l.split("//", 1)[0] for l in text.splitlines())


def parity_check(ios_base, android_base, vars_):
    a, b = routes(ios_base, "ios", vars_), routes(android_base, "android", vars_)
    if a == b:
        return {"status": "pass", "violations": []}
    return {"status": "fail", "violations": [{"rule": "T5", "detail": f"routes differ — ios only: {sorted(a - b)}, android only: {sorted(b - a)}"}]}


def build(base, platform, vars_, log_path, timeout=1800):
    """워크트리의 앱을 빌드한다. 툴체인이 없으면 unmeasured."""
    from . import probe
    t = probe.toolchain()
    app = os.path.join(base, util.APPS[platform])
    if os.environ.get("TWBUILD_NO_BUILD"):
        return {"status": "unmeasured", "detail": "TWBUILD_NO_BUILD"}
    if platform == "ios":
        if not t["xcodebuild"] or not t["xcodegen"]:
            return {"status": "unmeasured", "detail": "Xcode · xcodegen 없음"}
        steps = [["xcodegen", "generate", "--quiet"],
                 ["xcodebuild", "-project", f"{vars_['product']}.xcodeproj", "-scheme", vars_["product"], "-destination", "generic/platform=iOS Simulator",
                  "-derivedDataPath", os.path.join(base, ".twbuild", "derived", "ios"), "CODE_SIGNING_ALLOWED=NO", "-quiet", "build"]]
    else:
        if not t["android_sdk"] or not t["java"]:
            return {"status": "unmeasured", "detail": "Android SDK · JDK 없음"}
        gradlew = os.path.join(app, "gradlew")
        if not os.path.isfile(gradlew):
            return {"status": "unmeasured", "detail": "gradlew 없음 — 셋업 selfcheck 가 만든다"}
        steps = [[gradlew, "assembleDebug", "-q"]]
        sdk_props = os.path.join(app, "local.properties")
        if not os.path.isfile(sdk_props):
            util.write_text(sdk_props, f"sdk.dir={t['android_sdk']}\n")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as lf:
        for cmd in steps:
            lf.write(f"$ {' '.join(cmd)}\n")
            lf.flush()
            try:
                r = subprocess.run(cmd, cwd=app, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=timeout,
                                   env={**os.environ, "ANDROID_HOME": t["android_sdk"] or os.environ.get("ANDROID_HOME", "")})
            except subprocess.TimeoutExpired:
                return {"status": "fail", "detail": f"시간 초과 {timeout}s", "log": log_path}
            if r.returncode != 0:
                return {"status": "fail", "detail": f"exit {r.returncode}: {' '.join(cmd[:2])}", "log": log_path}
    return {"status": "pass", "detail": f"{len(steps)}단계 통과", "log": log_path}


def tail(log_path, n=40):
    """빌드 로그 꼬리 — 재작업 과제에 싣는다 (경로가 아니라 내용을, 마스킹은 호출자가)."""
    text = util.read_text(log_path, "")
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines[-n:])
