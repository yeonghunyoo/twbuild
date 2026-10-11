"""셋업 — 결정적 노드들의 구현. wire(배선) · brief(앱 개요) · scaffold(골격) · selfcheck(빈 골격 점검) · report(보고서).

전부 멱등이다. 사람이 고친 파일은 덮지 않는다 — 템플릿에서 낸 파일은 .twbuild/scaffold.json 에 해시를 적어 두고,
그 해시와 같을 때(사람이 안 건드렸을 때)만 다시 낸다. 생성물(api/generated)은 항상 덮는다.
"""
import json
import os
import re
import shutil
import subprocess

from . import config, contract, git, probe, util

SCAFFOLD_LOG = "scaffold.json"
GITIGNORE_MARK = "# twbuild ("
CLAUDE_MARK = "## twbuild"
QUESTIONS = ("topic", "name", "requirements")
DEFAULT_PLACEHOLDER_HINT = "값은 .env.local 에만 둔다 (gitignore). 채팅으로 보내지 않는다."


# ─────────────────────────── wire ───────────────────────────

def wire(root, pr):
    """git · config 기본값 · .gitignore 블록 · CLAUDE.md 절 · .claude/rules 골격 · .claude/settings.json 허용 · 거부 목록. 멱등."""
    done = []
    if not git.is_repo(root):
        git.init(root)
        done.append("git init")
    if not util.is_wired(root):
        avail = pr.get("platforms_available") or []
        plats = avail if avail else list(config.PLATFORMS)
        config.write_template(root, {"platforms": "[" + ", ".join(plats) + "]"})
        done.append("config.yaml")
    ig = os.path.join(root, ".gitignore")
    cur = util.read_text(ig)
    if GITIGNORE_MARK not in cur:
        block = util.read_text(os.path.join(util.TEMPLATES, "gitignore.block"))
        util.write_text(ig, (cur.rstrip("\n") + "\n\n" if cur.strip() else "") + block)
        done.append(".gitignore")
    md = os.path.join(root, "CLAUDE.md")
    cur = util.read_text(md)
    if CLAUDE_MARK not in cur:
        section = util.read_text(os.path.join(util.TEMPLATES, "claude.section.md"))
        util.write_text(md, (cur.rstrip("\n") + "\n\n" if cur.strip() else "") + section)
        done.append("CLAUDE.md")
    for scope in util.RULE_SCOPES:
        d = os.path.join(root, util.RULES_DIR, scope)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            util.write_text(os.path.join(d, ".gitkeep"), "")
            done.append(f"rules/{scope}")
    if _merge_settings(root):
        done.append(".claude/settings.json")
    return done


def _merge_settings(root):
    """프로젝트 settings.json 에 하네스 허용 · 거부 목록을 더한다 — 있는 항목은 건드리지 않는다. bypass 는 여기서 켤 수 없다(사용자 설정)."""
    want = util.read_json(os.path.join(util.TEMPLATES, "settings.json"), {}) or {}
    path = os.path.join(root, ".claude", "settings.json")
    cur = util.read_json(path, {}) or {}
    perms = cur.setdefault("permissions", {})
    changed = False
    for key in ("allow", "deny"):
        have = perms.setdefault(key, [])
        for rule in (want.get("permissions") or {}).get(key, []):
            if rule not in have:
                have.append(rule)
                changed = True
    if changed:
        util.write_json(path, cur)
    return changed


# ─────────────────────────── interview · brief ───────────────────────────

def brief_path(root):
    return os.path.join(root, util.APP_BRIEF)


def read_brief(root):
    """features/app.md → {topic, name, requirements} (없는 칸은 빈 문자열)."""
    text = util.read_text(brief_path(root), "")
    out = {"topic": "", "name": "", "requirements": ""}
    if not text.strip():
        return out
    m = re.search(r"^# (.+)$", text, re.M)
    if m:
        out["name"] = m.group(1).strip()
    m = re.search(r"^- 주제: (.+)$", text, re.M)
    if m:
        out["topic"] = m.group(1).strip()
    m = re.search(r"^## 요구사항\n(.*)", text, re.S | re.M)
    if m:
        out["requirements"] = m.group(1).strip()
    return out


def write_brief(root, answers, cfg):
    app = cfg.get("app") or {}
    text = (f"# {answers['name']}\n\n"
            f"- 주제: {answers['topic']}\n"
            f"- 식별자: {app.get('id', '')}\n"
            f"- 플랫폼: {', '.join(cfg.get('platforms') or [])}\n\n"
            f"## 요구사항\n{answers['requirements'].strip()}\n")
    util.write_text(brief_path(root), text)


def remaining(root, answers):
    """아직 답이 없는 질문 — app.md 에 있는 것은 답한 것으로 친다. ASCII 이름이 안 나오면 ascii_name 을 더 묻는다."""
    have = {**read_brief(root), **{k: v for k, v in (answers or {}).items() if v}}
    rest = [q for q in QUESTIONS if not str(have.get(q) or "").strip()]
    decided = bool((config.load(root).get("app") or {}).get("id"))      # 식별자가 이미 정해졌으면 영문 이름은 다시 묻지 않는다
    if have.get("name") and not util.slug(have["name"]) and not have.get("ascii_name") and not decided:
        rest.append("ascii_name")
    return rest


def defaults(root):
    base = os.path.basename(os.path.abspath(root))
    return {"name": base, "product": util.pascal(base) or "App", "id": f"com.example.{util.slug(base) or 'app'}"}


def identifiers(answers):
    """이름 → product(PascalCase) · id(com.example.<slug>). ASCII 글자가 없으면 ascii_name 을 쓴다."""
    src = answers.get("ascii_name") or answers.get("name") or ""
    s = util.slug(src)
    return {"product": util.pascal(src) or "App", "id": f"com.example.{s or 'app'}"}


# ─────────────────────────── scaffold ───────────────────────────

def _log(root):
    return util.read_json(util.tw(root, SCAFFOLD_LOG), {}) or {}


def _emit(root, rel, text, log, out):
    """템플릿 파일 하나 — 없으면 쓰고, 전에 낸 그대로면 다시 내고, 사람이 고쳤으면 둔다."""
    path = os.path.join(root, rel)
    prev = log.get(rel)
    cur = util.read_text(path, None)
    if cur is None:
        util.write_text(path, text)
        out["written"].append(rel)
    elif prev and util.sha_text(cur) == prev:
        if cur != text:
            util.write_text(path, text)
            out["updated"].append(rel)
    elif cur != text:
        out["kept"].append(rel)
        return
    log[rel] = util.sha_text(text)


def _walk_templates(sub):
    base = os.path.join(util.TEMPLATES, sub)
    for d, _, names in os.walk(base):
        for n in sorted(names):
            p = os.path.join(d, n)
            yield os.path.relpath(p, base), util.read_text(p)


def scaffold(root, answers=None):
    """features/app.md · config.app · 플랫폼 골격 · 계약 조각 · 생성물 · placeholders → .env.example · SETUP.md."""
    cfg = config.load(root)
    out = {"written": [], "updated": [], "kept": [], "generated": []}
    answers = {**read_brief(root), **{k: v for k, v in (answers or {}).items() if v}}
    if answers.get("name"):
        ids = identifiers(answers)
        app = cfg.get("app") or {}
        if not app.get("id"):     # 식별자는 한 번 정하면 유지한다(첫 머지 뒤 잠김)
            config.update(root, **{"app.name": answers["name"], "app.product": ids["product"], "app.id": ids["id"]})
        elif app.get("name") != answers["name"]:
            config.update(root, **{"app.name": answers["name"]})
        cfg = config.load(root)
        write_brief(root, answers, cfg)
    vars_ = config.app_vars(cfg)
    log = _log(root)
    if "_existing" not in log:      # 첫 scaffold 전에 있던 앱 — 보고서의 "신규/기존" 은 이것으로 본다 (뒤 실측은 늘 "기존")
        log["_existing"] = [p for p in config.PLATFORMS if os.path.isdir(util.app_dir(root, p)) and os.listdir(util.app_dir(root, p))]
    for p in cfg.get("platforms") or []:
        for rel, text in _walk_templates(os.path.join("monorepo", p)):
            rel = rel.replace("__pkg__", vars_["pkg_path"]).replace("__product__", vars_["product"])
            _emit(root, os.path.join(util.APPS[p], rel), util.render(text, vars_), log, out)
    log = {k: v for k, v in log.items() if k.startswith("_") or os.path.isfile(os.path.join(root, k))}
    # 계약 — 본문은 없을 때만, 조각은 셋업 소유(항상 최신)
    body = contract.body_path(root)
    if not os.path.isfile(body):
        util.write_text(body, util.render(util.read_text(os.path.join(util.TEMPLATES, "api", "openapi.yaml")), vars_))
        out["written"].append(os.path.relpath(body, root))
    frag_dir = os.path.join(root, util.FRAGMENTS_DIR)
    os.makedirs(frag_dir, exist_ok=True)
    providers = (cfg.get("auth") or {}).get("providers") or []
    for rel, text in _walk_templates(os.path.join("api", "fragments")):
        text = _filter_auth(text, providers) if rel.startswith("auth") else text
        _emit(root, os.path.join(util.FRAGMENTS_DIR, rel), util.render(text, vars_), log, out)
    out["generated"] = contract.write_generated(root)
    # placeholders → .env.example · SETUP.md (사람용 문서는 손으로 쓰지 않는다)
    ph = util.read_json(os.path.join(util.TEMPLATES, "placeholders.json"), {}) or {}
    rows = [r for r in ph.get("placeholders", []) if _placeholder_applies(r, cfg)]
    util.write_json(os.path.join(root, "config", "placeholders.json"), {"placeholders": rows})
    util.write_text(os.path.join(root, ".env.example"), _env_example(rows))
    util.write_text(os.path.join(root, "SETUP.md"), _setup_md(rows, cfg))
    sdk = probe.android_sdk()
    if "android" in (cfg.get("platforms") or []) and sdk:
        util.write_text(os.path.join(util.app_dir(root, "android"), "local.properties"), f"sdk.dir={sdk}\n")
    util.write_json(util.tw(root, SCAFFOLD_LOG), log)
    return out


def _filter_auth(text, providers):
    """auth 조각에서 쓰지 않는 로그인 수단의 경로를 뺀다 — 마커 `# provider: apple` 블록 단위."""
    out, skip = [], False
    for line in text.splitlines():
        m = re.match(r"\s*# provider: (\w+)\s*$", line)
        if m:
            skip = m.group(1) not in providers
            continue
        if re.match(r"\s*# provider-end\s*$", line):
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out) + "\n"


def _placeholder_applies(row, cfg):
    need = row.get("when") or {}
    plats = set(cfg.get("platforms") or [])
    providers = set((cfg.get("auth") or {}).get("providers") or [])
    if need.get("platform") and need["platform"] not in plats:
        return False
    if need.get("provider") and need["provider"] not in providers:
        return False
    return True


def _env_example(rows):
    lines = ["# twbuild 가 config/placeholders.json 에서 생성한다 — 손으로 고치지 않는다.", "# 실제 값은 .env.local 에 (gitignore).", ""]
    for r in rows:
        if r.get("kind", "env") != "env":
            continue
        lines.append(f"# {r['desc']} — 발급: {r['where']} ({'필수' if r.get('required') else '선택'})")
        lines.append(f"{r['key']}={r.get('default', '')}")
        lines.append("")
    return "\n".join(lines)


def _setup_md(rows, cfg):
    app = cfg.get("app") or {}
    lines = [f"# {app.get('name') or '앱'} — 셋업", "",
             "twbuild 가 `config/placeholders.json` 에서 생성한 문서다. 손으로 고치지 않는다.", "",
             "## 환경 변수 (.env.local)", "", "`twbuild init` 이 `.env.local` 틀을 만든다. 에디터로 값을 채운 뒤 `twbuild doctor` 로 확인한다. " + DEFAULT_PLACEHOLDER_HINT, "",
             "| 키 | 설명 | 발급처 | 필수 | 막는 범위 |", "|---|---|---|---|---|"]
    for r in rows:
        if r.get("kind", "env") == "env":
            lines.append(f"| `{r['key']}` | {r['desc']} | {r['where']} | {'예' if r.get('required') else '아니오'} | {r.get('blocks', '')} |")
    files = [r for r in rows if r.get("kind") == "file"]
    if files:
        lines += ["", "## 사람이 넣는 파일", "", "| 파일 | 자리 | 설명 | 발급처 | 막는 범위 |", "|---|---|---|---|---|"]
        for r in files:
            lines.append(f"| `{r['key']}` | `{r['path']}` | {r['desc']} | {r['where']} | {r.get('blocks', '')} |")
    lines += ["", "## 실서버 전환", "", "`API_BASE_URL` 하나만 바꾼다. 앱은 mock 서버로 끝까지 간다."]
    return "\n".join(lines) + "\n"


def env_local_init(root):
    """`twbuild init` — .env.local 틀(키만, 값 비움). 있으면 빠진 키만 더한다. 값은 묻지 않는다."""
    rows = (util.read_json(os.path.join(root, "config", "placeholders.json"), {}) or {}).get("placeholders", [])
    path = os.path.join(root, ".env.local")
    cur = util.read_text(path, "")
    have = {l.split("=", 1)[0].strip() for l in cur.splitlines() if "=" in l and not l.strip().startswith("#")}
    add = [r for r in rows if r.get("kind", "env") == "env" and r["key"] not in have]
    if add or not cur:
        text = cur.rstrip("\n") + ("\n" if cur.strip() else "")
        for r in add:
            text += f"{r['key']}={r.get('default', '')}\n"
        util.write_text(path, text)
    return [r["key"] for r in add]


# ─────────────────────────── selfcheck ───────────────────────────

def _scaffold_hash(root, cfg):
    """골격 입력의 지문 — 바뀌지 않았으면 selfcheck 의 빌드를 건너뛴다."""
    parts = [config.digest(cfg)]
    for p in cfg.get("platforms") or []:
        parts.append(util.tree_hash(util.app_dir(root, p)))
    parts.append(util.tree_hash(os.path.join(root, util.API_DIR)))
    return util.sha_text("\n".join(parts))[:12]


def selfcheck(root):
    """빈 골격 점검 → .twbuild/selfcheck.json. 층: static · contract_decode(못 잼, 뒤 단계) · build_<플랫폼>(툴체인 있을 때)."""
    cfg = config.load(root)
    t = probe.toolchain()
    prev = util.read_json(util.tw(root, util.SELFCHECK), {}) or {}
    h = _scaffold_hash(root, cfg)
    layers = {}
    problems = config.problems(cfg)
    try:
        drift = contract.drift(root)
    except contract.ContractError as e:
        drift = [str(e)]
    missing = [p for p in cfg.get("platforms") or [] if not os.path.isdir(util.app_dir(root, p))]
    static_ok = not problems and not drift and not missing
    layers["static"] = {"status": "pass" if static_ok else "fail",
                        "detail": "; ".join(problems + [f"생성물 불일치: {d}" for d in drift] + [f"골격 없음: {p}" for p in missing])}
    layers["contract_decode"] = {"status": "unmeasured", "detail": "생성 모델 디코딩 검사는 게이트 단계에서 붙는다"}
    for p in cfg.get("platforms") or []:
        key = f"build_{p}"
        if not cfg.get("setup", {}).get("build", True) or os.environ.get("TWBUILD_NO_BUILD"):
            layers[key] = {"status": "unmeasured", "detail": "setup.build: false" if not os.environ.get("TWBUILD_NO_BUILD") else "TWBUILD_NO_BUILD"}
        elif prev.get("scaffold_hash") == h and (prev.get("layers") or {}).get(key, {}).get("status") == "pass":
            layers[key] = {**prev["layers"][key], "detail": "변경 없음 — 이전 결과 유지"}
        else:
            layers[key] = _build(root, p, cfg, t)
    rec = {"t": util.now(), "scaffold_hash": h, "layers": layers}
    util.write_json(util.tw(root, util.SELFCHECK), rec)
    return rec


def _build(root, p, cfg, t):
    vars_ = config.app_vars(cfg)
    logs = util.tw(root, util.LOGS_DIR)
    os.makedirs(logs, exist_ok=True)
    log = os.path.join(logs, f"selfcheck-{p}.log")
    app = util.app_dir(root, p)
    if p == "ios":
        if not t["xcodebuild"]:
            return {"status": "unmeasured", "detail": "Xcode 없음"}
        if not t["xcodegen"]:
            return {"status": "unmeasured", "detail": "xcodegen 없음 — brew install xcodegen"}
        steps = [["xcodegen", "generate", "--quiet"],
                 ["xcodebuild", "-project", f"{vars_['product']}.xcodeproj", "-scheme", vars_["product"],
                  "-destination", "generic/platform=iOS Simulator", "-derivedDataPath", util.tw(root, "derived", "ios"),
                  "CODE_SIGNING_ALLOWED=NO", "-quiet", "build"]]
        timeout = 1500
    else:
        if not t["android_sdk"] or not t["java"]:
            return {"status": "unmeasured", "detail": "Android SDK · JDK 없음"}
        gradlew = os.path.join(app, "gradlew")
        steps = []
        if not os.path.isfile(gradlew):
            if not t["gradle"]:
                return {"status": "unmeasured", "detail": "gradle wrapper 도 gradle 도 없음 — brew install gradle"}
            steps.append(["gradle", "wrapper", "--gradle-version", "8.11.1", "-q"])
        steps.append([gradlew if os.path.isfile(gradlew) else "./gradlew", "assembleDebug", "-q"])
        timeout = 1800
    with open(log, "w", encoding="utf-8") as lf:
        for cmd in steps:
            lf.write(f"$ {' '.join(cmd)}\n")
            lf.flush()
            try:
                r = subprocess.run(cmd, cwd=app, stdout=lf, stderr=subprocess.STDOUT, text=True, timeout=timeout,
                                   env={**os.environ, "ANDROID_HOME": t["android_sdk"] or os.environ.get("ANDROID_HOME", "")})
            except subprocess.TimeoutExpired:
                return {"status": "fail", "detail": f"시간 초과 {timeout}s: {' '.join(cmd)}", "log": os.path.relpath(log, root)}
            except OSError as e:
                return {"status": "fail", "detail": str(e), "log": os.path.relpath(log, root)}
            if r.returncode != 0:
                return {"status": "fail", "detail": f"exit {r.returncode}: {' '.join(cmd)} — 로그 {os.path.relpath(log, root)}",
                        "log": os.path.relpath(log, root)}
    return {"status": "pass", "detail": f"{len(steps)}단계 통과", "log": os.path.relpath(log, root)}


# ─────────────────────────── report ───────────────────────────

def mark_applied(root):
    cfg = config.load(root)
    util.write_json(util.tw(root, util.APPLIED), {"t": util.now(), "config": cfg, "digest": config.digest(cfg)})


def decisions(root, pr):
    """결정 표 — 항목 · 값 · 출처. interview 가 묻지 않은 것은 여기서 보인다."""
    cfg = config.load(root)
    app = cfg.get("app") or {}
    t = pr.get("toolchain") or {}
    avail = pr.get("platforms_available") or []
    plats = cfg.get("platforms") or []
    existing = _log(root).get("_existing", pr.get("apps_existing") or [])
    rows = [
        ("앱 이름", app.get("name") or "(미정)", "interview"),
        ("식별자", app.get("id") or "(미정)", "이름에서 생성 (com.example.<slug>)"),
        ("플랫폼", " · ".join(plats), "툴체인 실측" if plats == avail else "config"),
        ("신규/기존", " · ".join(f"{p}: {'기존' if p in existing else '신규'}" for p in plats) or "-", "레포 실측"),
        ("아키텍처", cfg.get("architecture", ""), "기본값 (첫 머지 뒤 잠김)"),
        ("최소 OS", f"iOS {cfg['min_os']['ios']} · Android {cfg['min_os']['android']}", "기본값 (첫 머지 뒤 잠김)"),
        ("로그인", " · ".join((cfg.get("auth") or {}).get("providers") or []), "기본값"),
        ("기기 스모크", cfg.get("smoke", {}).get("device", ""), "기본값"),
        ("화면당 재시도", str(cfg.get("budget", {}).get("attempts_per_screen", "")), "기본값"),
        ("Xcode", t.get("xcodebuild") or "없음", "실측"),
        ("Android SDK", t.get("android_sdk") or "없음", "실측"),
    ]
    return rows


def report(root, pr, sc, scaffold_out=None):
    """셋업 보고서 (한국어 markdown) — lead 가 그대로 보인다."""
    lines = ["## twbuild 셋업 결과", "", "### 결정", "", "| 항목 | 값 | 출처 |", "|---|---|---|"]
    for k, v, src in decisions(root, pr):
        lines.append(f"| {k} | {v} | {src} |")
    lines += ["", "바꾸려면 `.twbuild/config.yaml` 을 고치고 `/twbuild` 를 다시 실행한다 (바뀐 부분만 다시 돈다).", "",
              "### 점검", "", "| 층 | 결과 | 비고 |", "|---|---|---|"]
    for name, layer in (sc.get("layers") or {}).items():
        st = layer.get("status")
        m = "✅" if st == "pass" else ("❌" if st == "fail" else "— 못 잼")
        lines.append(f"| {name} | {m} | {layer.get('detail', '')} |")
    todos = pr.get("todos") or []
    if todos:
        lines += ["", "### 사람 할 일 (막는 범위 큰 순)", "", "| 할 일 | 막는 범위 | 명령 |", "|---|---|---|"]
        for r in todos:
            lines.append(f"| {r['what']} | {r['blocks']} | `{r['fix']}` |")
    if scaffold_out:
        kept = scaffold_out.get("kept") or []
        if kept:
            lines += ["", "유지(사람이 고친 파일, 덮지 않음): " + ", ".join(kept)]
    ok, reasons = probe.ready(root)
    lines += ["", "### 다음", ""]
    if ok:
        lines.append("준비됨 ✅ — `/twbuild` 를 다시 실행하면 첫 기능 사이클(디자인 import → 플랜 → 구현)이 시작된다.")
    else:
        lines.append("아직 준비되지 않음 ❌ — " + " · ".join(reasons))
    lines.append("시크릿 값은 `twbuild init` 으로 `.env.local` 틀을 만들고 에디터로 채운다. `twbuild doctor` 가 ✅/❌ 로 확인한다.")
    return "\n".join(lines) + "\n"
