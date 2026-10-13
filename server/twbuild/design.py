"""디자인 import — design run 원장 · 허용 목록 · 캡처 · 트리 · 토큰 · 커밋 (AGENT.md 2장).

한 번 import 하면 로컬 design/ 이 원장이다. Claude Design 을 상시 보지 않는다 — 사용자가 원할 때만 run 을 열어 받는다.
커넥터 호출은 run 안에서만, 허용 목록 안에서만 — 훅(hooks/design_guard.py)이 allowed() 로 판정하고, 캡처 훅이 capture() 로 쓴다.
서버 코드를 훅이 import 하므로 이 모듈은 표준 라이브러리만 쓴다.

  design/index.json          원장 — 화면(<scope>/<id>)마다 현재 run · 트리 해시 · 상태 · 빌드에 쓴 것
  design/runs/R-0001.json    run 기록 — 파일별 etag · sha256 · bytes · 이전 run 대비 추가/변경/삭제 · 화면별 트리 해시
  .twbuild/intake/<scope>/run.json   진행 중인 run (허용 목록 포함)
"""
import fnmatch
import html as htmlmod
import os
import re

from . import config, git, tokens, tree, util

INDEX = os.path.join(util.DESIGN_DIR, "index.json")
RUNS_DIR = os.path.join(util.DESIGN_DIR, "runs")
INTAKE = "intake"
DENY = ("support.js", "_ds_bundle.js", "_restore_*", ".thumbnail", "*-frame.jsx.map")
DENY_DIRS = ("uploads/", "screenshots/")
BINARY = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".mp3", ".mp4", ".woff", ".woff2", ".ttf", ".otf")
DS_IN_SCREEN_PROJECT = ("_ds/*/styles.css", "_ds/*/readme.md", "_ds/*/_ds_manifest.json", "_ds/*/_adherence.oxlintrc.json", "_ds/*/theme.json")
DS_PROJECT = ("styles.css", "readme.md", "theme.json", "_adherence.oxlintrc.json", "_ds_manifest.json", "components/*.html", "foundations/*.html")
META_TOOLS = ("list_projects", "get_project", "list_design_systems")
STATUSES = ("imported", "planned", "building", "consumed", "changed", "removed")

RULES = {
    "D1": "[D1] design run 밖의 Claude Design 호출이다 — /twbuild 의 intake 에서 디자인 import 를 시작한 뒤 받는다.",
    "D2": "[D2] 이 run 의 프로젝트가 아니다 — run 은 화면 프로젝트(와 디자인 시스템 프로젝트) 하나씩만 본다.",
    "D3": "[D3] 받지 않는 파일이다 — support.js · 내보낸 standalone HTML · 번들 · 복원 파일 · 썸네일 · uploads · screenshots · 바이너리.",
    "D4": "[D4] 허용 목록 밖의 경로다 — 고른 화면 .dc.html 과 그것이 참조하는 CSS · JSX, 디자인 시스템 파일만 받는다.",
    "D5": "[D5] 크기 상한(design.fetch.max_bytes)을 넘는 파일이다 — 커넥터로 받을 수 없다.",
}


class DesignError(ValueError):
    pass


# ─────────────────────────── run ───────────────────────────

def _intake_dir(root, scope):
    return util.tw(root, INTAKE, scope)


def active(root):
    """진행 중인 run — 하나뿐이다. 없으면 None."""
    base = util.tw(root, INTAKE)
    if not os.path.isdir(base):
        return None
    for scope in sorted(os.listdir(base)):
        r = util.read_json(os.path.join(base, scope, "run.json"))
        if isinstance(r, dict) and r.get("status") == "active":
            return r
    return None


def _save_run(root, run):
    util.write_json(os.path.join(_intake_dir(root, run["scope"]), "run.json"), run)


def runs(root):
    d = os.path.join(root, RUNS_DIR)
    if not os.path.isdir(d):
        return []
    return [util.read_json(os.path.join(d, n)) for n in sorted(os.listdir(d)) if n.endswith(".json")]


def next_id(root):
    ids = [r["id"] for r in runs(root) if isinstance(r, dict) and r.get("id")]
    a = active(root)
    if a:
        ids.append(a["id"])
    n = max([int(i.split("-")[1]) for i in ids] + [0]) + 1
    return f"R-{n:04d}"


def start(root, scope, project_id, screens, ds_project_id=None, trigger="user", bootstrap=False):
    """run 을 연다. screens: 받을 화면 파일 경로들(.dc.html). bootstrap: 디자인 시스템 프로젝트의 컴포넌트까지 받는다(첫 사이클)."""
    if active(root):
        raise DesignError(f"진행 중인 run 이 있다: {active(root)['id']} — finish 하거나 abort 한 뒤 다시 시작한다")
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", scope or ""):
        raise DesignError("scope(기능 이름)는 소문자 영숫자와 - 만 쓴다")
    bad = [s for s in screens if not s.endswith(".dc.html")]
    if bad:
        raise DesignError(f"화면은 .dc.html 이어야 한다: {bad}")
    run = {"id": next_id(root), "scope": scope, "project_id": project_id, "ds_project_id": ds_project_id, "trigger": trigger,
           "bootstrap": bool(bootstrap), "started": util.now(), "status": "active", "screens": list(screens),
           "allow": list(screens), "files": [], "listing": {}}
    _save_run(root, run)
    return run


def abort(root):
    run = active(root)
    if not run:
        return None
    run["status"] = "aborted"
    run["finished"] = util.now()
    _save_run(root, run)
    return run


# ─────────────────────────── 허용 판정 ───────────────────────────

def _denied_name(path):
    name = path.rsplit("/", 1)[-1]
    if any(path.startswith(d) or f"/{d}" in path for d in DENY_DIRS):
        return True
    if any(fnmatch.fnmatch(name, g) for g in DENY):
        return True
    if name.lower().endswith(BINARY):
        return True
    in_catalog = bool(re.search(r"(^|/)(components|foundations)/[^/]+$", path))
    if name.endswith(".html") and not name.endswith(".dc.html") and not in_catalog:
        return True       # 내보낸 standalone HTML (에셋 묶음 1 MB 한 줄). 디자인 시스템 카탈로그(components/ · foundations/)의 .html 은 받는다
    return False


def allowed(root, tool, project_id, path, run=None, cfg=None):
    """(허용?, 규칙 ID, 메시지). tool 은 커넥터 도구 이름의 꼬리(read_file · list_files …)."""
    if tool in META_TOOLS:
        return True, "", ""
    run = run if run is not None else active(root)
    if not run:
        return False, "D1", RULES["D1"]
    if project_id and project_id not in (run.get("project_id"), run.get("ds_project_id")):
        return False, "D2", RULES["D2"]
    if tool == "list_files":
        return True, "", ""
    if tool != "read_file":
        return False, "D4", RULES["D4"] + f" ({tool})"
    path = (path or "").lstrip("./")
    cfg = cfg or config.load(root)
    fetch = (cfg.get("design") or {}).get("fetch") or {}
    if any(fnmatch.fnmatch(path, g) for g in fetch.get("exclude") or []):
        return False, "D4", RULES["D4"] + f" ({path} — config exclude)"
    if _denied_name(path):
        return False, "D3", RULES["D3"] + f" ({path})"
    size = (run.get("listing") or {}).get(path, {}).get("size")
    if size and size > int(fetch.get("max_bytes") or 262144):
        return False, "D5", RULES["D5"] + f" ({path}, {size} bytes)"
    if any(fnmatch.fnmatch(path, g) for g in fetch.get("include") or []):
        return True, "", ""
    if project_id and project_id == run.get("ds_project_id") and run.get("ds_project_id") != run.get("project_id"):
        ok = any(fnmatch.fnmatch(path, g) for g in DS_PROJECT)
        return (True, "", "") if ok else (False, "D4", RULES["D4"] + f" ({path})")
    if path in run.get("allow") or []:
        return True, "", ""
    if any(fnmatch.fnmatch(path, g) for g in DS_IN_SCREEN_PROJECT):
        return True, "", ""
    if run.get("bootstrap") and any(fnmatch.fnmatch(path, g) for g in ("_ds/*/components/*.html", "_ds/*/foundations/*.html")):
        return True, "", ""
    return False, "D4", RULES["D4"] + f" ({path})"


# ─────────────────────────── 캡처 ───────────────────────────

def dest_of(run, path):
    """커넥터 경로 → design/ 안의 자리. _ds/<ds>/x → design/ds/x (디자인 시스템), 화면 · JSX → design/<scope>/<basename>."""
    path = path.lstrip("./")
    m = re.match(r"^_ds/[^/]+/(.+)$", path)
    if m:
        return os.path.join(util.DESIGN_DIR, "ds", m.group(1))
    if run.get("ds_project_id") and run.get("ds_project_id") != run.get("project_id") and run.get("_ds_mode"):
        return os.path.join(util.DESIGN_DIR, "ds", path)
    return os.path.join(util.DESIGN_DIR, run["scope"], path.rsplit("/", 1)[-1])


def capture(root, path, text, etag="", project_id=None):
    """받은 본문을 design/ 에 바이트 그대로 쓴다. 본문은 이미 엔티티 디코딩된 원문이어야 한다 (훅이 decode 한다)."""
    run = active(root)
    if not run:
        raise DesignError(RULES["D1"])
    path = path.lstrip("./")
    if project_id and project_id == run.get("ds_project_id") and project_id != run.get("project_id"):
        run["_ds_mode"] = True
    dest = dest_of(run, path)
    run.pop("_ds_mode", None)
    util.write_text(os.path.join(root, dest), text)
    rec = {"path": path, "dest": dest, "etag": etag or "", "sha256": util.sha_text(text), "bytes": len(text.encode("utf-8")),
           "project_id": project_id or run.get("project_id")}
    run["files"] = [f for f in run["files"] if f["path"] != path] + [rec]
    if path.endswith(".dc.html"):
        for ref in tree.refs(text):
            if ref not in run["allow"]:
                run["allow"].append(ref)
    _save_run(root, run)
    return rec


def record_listing(root, entries):
    """list_files 결과 — 경로별 etag · size. support.js 의 etag 가 여기서 남는다(형식 변경 감지)."""
    run = active(root)
    if not run:
        return 0
    n = 0
    for e in entries or []:
        if isinstance(e, dict) and e.get("path"):
            run["listing"][e["path"]] = {"etag": e.get("etag", ""), "size": e.get("size", 0)}
            n += 1
    _save_run(root, run)
    return n


def decode_tool_text(text):
    """커넥터 read_file 응답(<untrusted-project-content path= etag=>엔티티 본문</…>) → (path, etag, 원문). 래퍼가 없으면 (None, None, 디코딩 본문)."""
    m = re.search(r'<untrusted-project-content\b([^>]*)>(.*?)</untrusted-project-content>', text or "", re.S)
    if not m:
        return None, None, text or ""          # 래퍼가 없으면 이미 원문이다 (CLI 로 파일을 넘긴 경우)
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
    body = m.group(2)
    if body.startswith("\n"):          # 래퍼가 본문 앞뒤에 개행 하나씩을 더한다 — 원본 바이트를 되살린다 (실측: 크기가 목록의 size 와 같아야 한다)
        body = body[1:]
    if body.endswith("\n"):
        body = body[:-1]
    return attrs.get("path"), attrs.get("etag"), htmlmod.unescape(body)


# ─────────────────────────── 원장 · 완료 ───────────────────────────

def index(root):
    return util.read_json(os.path.join(root, INDEX), {"screens": {}, "ds": None}) or {"screens": {}, "ds": None}


def _write_index(root, idx):
    util.write_json(os.path.join(root, INDEX), idx)


DEMO_CLASSES = {"demo", "demo-head", "row", "stack", "grid-2", "grid-3", "note"}      # 카탈로그 페이지의 데모 골격 — 컴포넌트가 아니다
_BASE_CLASS = re.compile(r"^[a-z][a-z0-9]*$")


def catalog(root):
    """디자인 시스템 카탈로그 — design/ds/components/*.html 의 클래스에서 컴포넌트를 뽑는다(실측: Organic 의 cards.html 은 `.card` + 부품 `.card-kicker` + 변형 `.elev-sm` 가 한 페이지에 여럿).
    → [{"name": Pascal, "class": "card", "file": rel, "parts": [...], "modifiers": [...]}]. 기본 클래스(한 단어, 요소의 첫 클래스)가 컴포넌트,
    같은 요소의 나머지 클래스가 변형, `<기본>-x` 가 첫 클래스인 요소가 부품. 클래스가 없는 페이지는 파일 이름이 컴포넌트다."""
    d = os.path.join(root, util.DESIGN_DIR, "ds", "components")
    found = {}
    if not os.path.isdir(d):
        return []
    for n in sorted(os.listdir(d)):
        if not n.endswith(".html"):
            continue
        rel = os.path.join(util.DESIGN_DIR, "ds", "components", n)
        text = util.read_text(os.path.join(d, n), "")
        elements = [m.group(1).split() for m in re.finditer(r'class="([^"]+)"', text)]
        bases = {}
        for classes in elements:
            base = classes[0]
            if base in DEMO_CLASSES or not _BASE_CLASS.match(base):
                continue
            e = bases.setdefault(base, {"modifiers": set(), "parts": set()})
            e["modifiers"].update(c for c in classes[1:] if c not in DEMO_CLASSES)
        for classes in elements:
            for base in bases:
                if classes[0].startswith(base + "-"):
                    bases[base]["parts"].add(classes[0])
        if not bases:
            bases[n[:-5]] = {"modifiers": set(), "parts": set()}
        for base, e in bases.items():
            cur = found.setdefault(base, {"name": util.pascal(base), "class": base, "file": rel, "parts": set(), "modifiers": set()})
            cur["parts"] |= e["parts"]
            cur["modifiers"] |= e["modifiers"]
    return [{**e, "parts": sorted(e["parts"]), "modifiers": sorted(e["modifiers"])} for _, e in sorted(found.items())]


def catalog_names(root):
    return {c["name"] for c in catalog(root)}


def set_ds_built(root, built):
    """디자인 시스템 과제가 머지됐다 — 원장 ds.built (해시 · 커밋 · 컴포넌트)."""
    idx = index(root)
    idx["ds"] = {**(idx.get("ds") or {}), "built": built}
    _write_index(root, idx)
    return idx["ds"]


def set_status(root, key, status, **fields):
    """원장 상태 전이 — 결정적 단계만 부른다 (plan → planned · 초안 생성 → building · merge → consumed)."""
    if status not in STATUSES:
        raise DesignError(f"상태가 아니다: {status}")
    idx = index(root)
    if key not in idx["screens"]:
        raise DesignError(f"원장에 없는 화면: {key}")
    idx["screens"][key]["status"] = status
    idx["screens"][key].update(fields)
    _write_index(root, idx)
    return idx["screens"][key]


def trial(root, text, spec=None):
    """시험 실행 — 파일을 쓰지 않고 화면 후보와 트리 상태만. intake 가 lead 에게 보인다."""
    markup, script, frame = tree.split(text)
    specs = spec or tree.detect_screens(markup, script)
    tm = tree.TokenMap(tokens.load(root) or {})
    out = []
    for sc in specs:
        lay = tree.layout(markup, sc, specs, tm, frame=frame)
        out.append(tree.status(lay))
    return {"screens": specs, "status": out, "frame": frame}


def _sig(sc):
    return (sc.get("kind"), tuple(sc.get("when") or []), tuple(sc.get("style") or []))


def last_spec(root, scope, dest):
    """같은 scope · 같은 화면 파일의 마지막 run 이 쓴 화면 spec — 없으면 None."""
    d = os.path.join(root, util.DESIGN_DIR, "runs")
    if not os.path.isdir(d):
        return None
    for n in sorted(os.listdir(d), reverse=True):
        r = util.read_json(os.path.join(d, n), {}) or {}
        if r.get("scope") == scope and r.get("status") in ("done", "finished") and (r.get("spec") or {}).get(dest):
            return r["spec"][dest]
    return None


def reconcile_spec(detected, stored):
    """자동 감지 결과에 이전 run 의 화면 이름을 입힌다 — 같은 분기(kind · when · style)면 이전 id. 새 분기는 감지된 id 그대로."""
    if not stored:
        return detected
    by_sig = {_sig(s): s for s in stored}
    return [{**d, "id": by_sig[_sig(d)]["id"]} if _sig(d) in by_sig else d for d in detected]


def finish(root, spec=None, commit=True):
    """run 을 닫는다 — 트리 · 토큰 생성, 원장 갱신, run 기록, 커밋 + 태그. spec: lead 가 확인한 화면 목록(없으면 자동 감지)."""
    run = active(root)
    if not run:
        raise DesignError("진행 중인 run 이 없다")
    cfg = config.load(root)
    idx = index(root)
    prev_hashes = {k: v.get("tree") for k, v in idx["screens"].items()}
    screens_out, statuses = {}, []
    tk = tokens.load(root)
    tm = tree.TokenMap(tk or {})
    for f in run["files"]:
        if not f["path"].endswith(".dc.html"):
            continue
        text = util.read_text(os.path.join(root, f["dest"]), "")
        markup, script, frame = tree.split(text)
        specs = spec or reconcile_spec(tree.detect_screens(markup, script), last_spec(root, run["scope"], f["dest"]))
        run.setdefault("spec", {})[f["dest"]] = specs        # lead 가 고친 화면 이름은 다음 run 이 이어받는다 (실측: 자동 감지가 mixer 를 sheet 로 되돌렸다)
        for sc in specs:
            lay = tree.layout(markup, sc, specs, tm, source=f["dest"], frame=frame)
            rel = os.path.join(util.DESIGN_DIR, run["scope"], "layout", f"{sc['id']}.json")
            util.write_text(os.path.join(root, rel), util.stable_json(lay))
            screens_out[f"{run['scope']}/{sc['id']}"] = {"tree": lay["hash"], "layout": rel, "source": f["dest"], "ok": lay["root"] is not None}
            statuses.append(tree.status(lay))
    token_files = tokens.write(root, cfg) if tk is not None else []
    from . import fonts                              # styles.css 의 웹폰트 → design/ds/fonts(스냅샷) → 두 앱 등록 · Fonts.swift/kt (2장)
    fonts_out = fonts.fetch(root) if (tk is not None and not os.environ.get("TWBUILD_OFFLINE")) else {"files": [], "skipped": [], "errors": []}
    fonts_inst = fonts.install(root, cfg) if fonts.index(root) else {"ios": [], "android": [], "errors": []}
    diff = {"added": [], "changed": [], "removed": []}
    for key, info in screens_out.items():
        cur = idx["screens"].get(key)
        if not cur:
            idx["screens"][key] = {"run": run["id"], "tree": info["tree"], "status": "imported", "layout": info["layout"], "built": None}
            diff["added"].append(key)
        elif cur.get("tree") != info["tree"]:
            new_status = "changed" if cur.get("status") in ("building", "consumed", "changed") else "imported"
            idx["screens"][key].update({"run": run["id"], "tree": info["tree"], "status": new_status, "layout": info["layout"]})
            diff["changed"].append(key)
        else:
            idx["screens"][key]["run"] = run["id"]
    if run["files"] and any(f["path"].endswith(".dc.html") for f in run["files"]):
        for key, cur in idx["screens"].items():
            if key.startswith(run["scope"] + "/") and key not in screens_out and cur.get("status") != "removed":
                cur["status"] = "removed"
                diff["removed"].append(key)
    if tk is not None:
        idx["ds"] = {"run": run["id"], "hash": tk.get("source_sha"), "unresolved": tk.get("unresolved", [])}
    _write_index(root, idx)
    run.update({"status": "done", "finished": util.now(), "screens": screens_out, "diff": diff, "token_files": token_files,
                "support_js_etag": (run.get("listing") or {}).get("support.js", {}).get("etag", ""),
                "prev_hashes": {k: v for k, v in prev_hashes.items() if k in screens_out}})
    util.write_json(os.path.join(root, RUNS_DIR, f"{run['id']}.json"), run)
    _save_run(root, run)
    committed = None
    if commit and git.is_repo(root):
        paths = [util.DESIGN_DIR] + token_files
        pkg = (cfg.get("app") or {}).get("id", "com.example.app").replace(".", "/")
    paths = list(paths) + [fonts.FONTS_DIR, "apps/ios/App/Resources/Fonts", "apps/ios/project.yml", "apps/ios/App/Core/DesignSystem",
                           "apps/android/app/src/main/res/font", f"apps/android/app/src/main/kotlin/{pkg}/core/designsystem"]
    if git.commit_paths(root, f"design-run: {run['id']} ({run['scope']})", *paths):
            git.tag(root, f"design-run/{run['id']}", f"design run {run['id']} {run['scope']}")
            committed = git.head(root)
    return {"run": run["id"], "scope": run["scope"], "screens": screens_out, "status": statuses, "diff": diff,
            "tokens": {"files": token_files, "unresolved": (tk or {}).get("unresolved", [])} if tk is not None else None,
            "commit": committed}


def summary(root):
    """`/twbuild` 진입마다 보이는 원장 요약 — 상태별 화면 수."""
    idx = index(root)
    counts = {}
    for v in idx["screens"].values():
        counts[v.get("status", "?")] = counts.get(v.get("status", "?"), 0) + 1
    return {"screens": len(idx["screens"]), "by_status": counts, "ds": idx.get("ds"), "active_run": (active(root) or {}).get("id")}
