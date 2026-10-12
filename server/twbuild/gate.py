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
import time

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


def static_check(base, platform, lay, token_hexes=(), extra_hexes=(), catalog=()):
    """base: 워크트리(또는 레포) 루트. 화면 코드 전체를 대상으로 본다 (파일 자리는 개발자 소유). catalog: 이 플랫폼에 구현된 카탈로그 컴포넌트 이름(T8)."""
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
        comp = draft.catalog_component(n, catalog)
        if comp:
            checked += 1
            if f"{comp}(" not in blob and f"{comp} {{" not in blob:
                violations.append({"rule": "T8", "detail": f"class node {n.get('id')} must use the catalog component {comp} (call {comp}(...) / {comp} {{ }})"})
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


_SWIFT_TYPES = re.compile(r"^\s*(?:public\s+|internal\s+)?(?:final\s+)?(?:protocol|class|struct|actor|enum)\s+(\w+)", re.M)
_KT_TYPES = re.compile(r"^\s*(?:public\s+|internal\s+)?(?:data\s+|sealed\s+|open\s+|abstract\s+)?(?:interface|class|object)\s+(\w+)", re.M)


_SWIFT_FUNCS = re.compile(r"^\s*(?:public\s+|internal\s+)?(?:static\s+)?func\s+([A-Z]\w*)\s*[<(]", re.M)
_KT_FUNCS = re.compile(r"^\s*(?:@Composable\s+)?(?:public\s+|internal\s+)?fun\s+([A-Z]\w*)\s*[<(]", re.M)
DATA_DIRS = ("App/Core/Data", "core/data")
DS_DIRS = ("App/Core/DesignSystem", "core/designsystem")


def types_in(base, platform, vars_, dirs, funcs=False):
    """한 계층 디렉터리의 타입 이름 집합 — iOS apps/ios/<dirs[0]> · Android <패키지>/<dirs[1]>. funcs 면 대문자 함수(Composable)도 센다."""
    if platform == "ios":
        d = os.path.join(base, "apps/ios", dirs[0])
        rxs = [_SWIFT_TYPES] + ([_SWIFT_FUNCS] if funcs else [])
    else:
        d = os.path.join(base, "apps/android/app/src/main/kotlin", vars_["id"].replace(".", "/"), dirs[1])
        rxs = [_KT_TYPES] + ([_KT_FUNCS] if funcs else [])
    names = set()
    if not os.path.isdir(d):
        return names
    for base_dir, _, files in os.walk(d):
        for n in files:
            if n.endswith((".swift", ".kt")):
                t = _strip_comments(util.read_text(os.path.join(base_dir, n), ""))
                for rx in rxs:
                    names |= set(rx.findall(t))
    return names


def data_types(base, platform, vars_):
    """데이터 계층의 타입 이름 — iOS App/Core/Data · Android core/data. 두 플랫폼이 같아야 한다 (AGENT.md 14장)."""
    return types_in(base, platform, vars_, DATA_DIRS)


def ds_types(base, platform, vars_):
    """디자인 시스템(카탈로그 컴포넌트) 이름 — 타입과 Composable 함수. 두 플랫폼이 같아야 한다 (T7)."""
    return types_in(base, platform, vars_, DS_DIRS, funcs=True)


def ds_parity_check(ios_base, android_base, vars_):
    """T7 — 디자인 시스템 컴포넌트 이름 집합 iOS = Android. 둘 다 없으면 못 잼."""
    a, b = ds_types(ios_base, "ios", vars_), ds_types(android_base, "android", vars_)
    if a == b:
        return {"status": "pass" if a else "unmeasured", "violations": []}
    return {"status": "fail", "violations": [{"rule": "T7", "detail": f"design-system components differ — ios only: {sorted(a - b)}, android only: {sorted(b - a)}"}]}


def data_parity_check(ios_base, android_base, vars_):
    """T6 — 데이터 객체(Repository · Store · Draft · 모델) 이름 집합 iOS = Android."""
    a, b = data_types(ios_base, "ios", vars_), data_types(android_base, "android", vars_)
    if a == b:
        return {"status": "pass" if a else "unmeasured", "violations": []}
    return {"status": "fail", "violations": [{"rule": "T6", "detail": f"data types differ — ios only: {sorted(a - b)}, android only: {sorted(b - a)}"}]}


def _block(text, head_rx, open_ch, close_ch):
    """head_rx 가 가리키는 선언의 본문(괄호 안) — 없으면 None."""
    m = re.search(head_rx, text, re.M)
    if not m:
        return None
    i = text.find(open_ch, m.end())
    if i < 0:
        return None
    depth, j = 0, i
    while j < len(text):
        if text[j] == open_ch:
            depth += 1
        elif text[j] == close_ch:
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
        j += 1
    return None


_TYPE_MAP = {"bool": "bool", "boolean": "bool", "int": "int", "long": "int", "double": "double", "float": "float", "cgfloat": "double",
             "string": "string", "color": "color", "uuid": "string"}


def norm_type(t):
    """플랫폼 타입 → 비교용 — Bool·Boolean, [X]·List<X>, X?·X? 를 같게."""
    t = re.sub(r"\s+", "", t or "")
    opt = t.endswith("?")
    t = t.rstrip("?")
    m = re.match(r"^\[(.+)\]$", t) or re.match(r"^(?:List|Array|MutableList)<(.+)>$", t)
    if m:
        return f"list<{norm_type(m.group(1))}>" + ("?" if opt else "")
    return _TYPE_MAP.get(t.lower(), t.lower()) + ("?" if opt else "")


def _swift_state(text, S):
    body = _block(text, rf"^\s*(?:public\s+|internal\s+)?struct\s+{re.escape(S)}UiState\b", "{", "}")
    if body is None:
        return None
    return {m.group(1): norm_type(m.group(2)) for m in re.finditer(r"^\s*(?:var|let)\s+(\w+)\s*:\s*([^=\n{]+?)\s*(?:=|$)", _strip_comments(body), re.M)}


def _kt_state(text, S):
    body = _block(text, rf"^\s*(?:data\s+)?class\s+{re.escape(S)}UiState\b", "(", ")")
    if body is None:
        return None
    out = {m.group(1): norm_type(m.group(2)) for m in re.finditer(r"\bva[lr]\s+(\w+)\s*:\s*([^=,\n]+)", _strip_comments(body))}
    if list(out) == ["placeholder"]:
        return {}                                        # 필드가 없을 때의 자리표시
    return out


def _swift_actions(text, S):
    body = _block(text, rf"^\s*(?:public\s+|internal\s+)?enum\s+{re.escape(S)}Action\b", "{", "}")
    if body is None:
        return None
    out = {}
    for m in re.finditer(r"^\s*case\s+([^\n]+)", _strip_comments(body), re.M):
        for part in re.split(r",\s*(?![^()]*\))", m.group(1)):         # case a, b(T) 를 나눈다
            pm = re.match(r"\s*(\w+)(?:\(([^)]*)\))?", part)
            if pm:
                out[pm.group(1).lower()] = [norm_type(p.split(":")[-1]) for p in pm.group(2).split(",")] if pm.group(2) else []
    return out


def _kt_actions(text, S):
    body = _block(text, rf"^\s*sealed\s+(?:interface|class)\s+{re.escape(S)}Action\b", "{", "}")
    if body is None:
        return None
    out = {}
    for m in re.finditer(r"\b(?:data\s+)?(?:class|object)\s+(\w+)(?:\(([^)]*)\))?", _strip_comments(body)):
        params = [norm_type(p.split(":")[-1]) for p in m.group(2).split(",") if p.strip()] if m.group(2) else []
        out[m.group(1).lower()] = params
    return out


def _screen_sources(base, platform, vars_, feature, screen):
    F, S = util.pascal(feature), util.pascal(screen)
    if platform == "ios":
        d = os.path.join(base, "apps/ios/App/Features", F, S)
    else:
        feat = re.sub(r"[^a-z0-9]", "", feature.lower())
        d = os.path.join(base, "apps/android/app/src/main/kotlin", vars_["id"].replace(".", "/"), "features", feat, screen.lower())
    texts = []
    if os.path.isdir(d):
        for bd, _, files in os.walk(d):
            for n in files:
                if n.endswith((".swift", ".kt")):
                    texts.append(util.read_text(os.path.join(bd, n), ""))
    return "\n".join(texts)


def state_parity_check(ios_base, android_base, vars_, feature, screen):
    """T10 — 화면의 UiState 필드(이름 · 타입)와 Action(이름 · 매개변수 타입)이 iOS = Android. 한쪽에 없으면 못 잼."""
    S = util.pascal(screen)
    a, b = _screen_sources(ios_base, "ios", vars_, feature, screen), _screen_sources(android_base, "android", vars_, feature, screen)
    sa, sb = _swift_state(a, S), _kt_state(b, S)
    aa, ab = _swift_actions(a, S), _kt_actions(b, S)
    if sa is None or sb is None or aa is None or ab is None:
        return {"status": "unmeasured", "violations": [], "detail": "UiState · Action 선언을 양쪽에서 못 찾았다"}
    v = []
    for name in sorted(set(sa) ^ set(sb)):
        v.append({"rule": "T10", "detail": f"UiState field only on {'ios' if name in sa else 'android'}: {name}"})
    for name in sorted(set(sa) & set(sb)):
        if sa[name] != sb[name]:
            v.append({"rule": "T10", "detail": f"UiState field type differs: {name} — ios {sa[name]} · android {sb[name]}"})
    for name in sorted(set(aa) ^ set(ab)):
        v.append({"rule": "T10", "detail": f"Action only on {'ios' if name in aa else 'android'}: {name}"})
    for name in sorted(set(aa) & set(ab)):
        if aa[name] != ab[name]:
            v.append({"rule": "T10", "detail": f"Action parameter types differ: {name} — ios {aa[name]} · android {ab[name]}"})
    return {"status": "fail" if v else "pass", "violations": v}


def parity_check(ios_base, android_base, vars_):
    a, b = routes(ios_base, "ios", vars_), routes(android_base, "android", vars_)
    if a == b:
        return {"status": "pass", "violations": []}
    return {"status": "fail", "violations": [{"rule": "T5", "detail": f"routes differ — ios only: {sorted(a - b)}, android only: {sorted(b - a)}"}]}


def ensure_android_props(base, t=None):
    """apps/android/local.properties(gitignore) — SDK 경로. 워크트리마다 없으면 쓴다(개발자 · 게이트 빌드 공용)."""
    from . import probe
    t = t or probe.toolchain()
    app = os.path.join(base, util.APPS["android"])
    p = os.path.join(app, "local.properties")
    if t.get("android_sdk") and os.path.isdir(app) and not os.path.isfile(p):
        util.write_text(p, f"sdk.dir={t['android_sdk']}\n")


def build(base, platform, vars_, log_path, timeout=1800):
    """워크트리의 앱을 빌드한다 — 걸린 시간 ms 를 함께 돌려준다(13장 층별 시간). 툴체인이 없으면 unmeasured."""
    t0 = time.time()
    r = _build(base, platform, vars_, log_path, timeout)
    r["ms"] = round((time.time() - t0) * 1000, 1)
    return r


def _build(base, platform, vars_, log_path, timeout):
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
        ensure_android_props(base, t)
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
