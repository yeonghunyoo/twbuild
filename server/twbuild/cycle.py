"""사이클 그래프 — 기능 하나가 한 사이클 (AGENT.md 4장). langgraph 를 import 하는 둘째 파일 (graph.py 가 컴파일 · 구동한다).

  START → intake → plan → prepare → dispatch → smoke ─┬─ merge ─┬─ prepare (다음 과제)
                                        ▲             │         └─ done → END
                                        └── blocked ◀─┘ (예산 소진 · 개발자 blocked)
  smoke 실패 → prepare (재작업, 화면당 예산 안)

멈춤: task(intake · plan · build → submit) · blocked(사람이 풀면 submit 으로 재개).
묻는 노드(intake · plan · dispatch · blocked)는 interrupt 만 하고, 실행 노드(prepare · smoke · merge)는 부작용만 한다.
"""
import operator
import os
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import config, contract, decide, design, device, draft, fonts, gate, gen, git, leaks, metrics, setup, tokens, tree, util, yaml_lite

PLANS = os.path.join(".twbuild", "plans")
RESULTS = os.path.join(".twbuild", "results")
REPORTS = os.path.join(".twbuild", "reports")
TASKS = os.path.join(".twbuild", "tasks")


class CycleState(TypedDict, total=False):
    smoked: str          # 마지막 smoke 가 잰 과제 id (측정용)
    root: str
    phase: str
    feature: str
    screens: list
    order: list          # [{"kind": "data"|"screen", "id": str}]
    cursor: int
    attempts: dict       # id → 시도 수
    results: dict        # id → {"ios": …, "android": …}
    dev: dict            # 마지막 dispatch 의 개발자 결과
    reports: list
    blocked: dict
    log: Annotated[list, operator.add]


def _task(name, message, submit_shape, **fields):
    return interrupt({"kind": "task", "graph": "cycle", "task": name, "message": message, "submit": submit_shape, **fields})


# ─────────────────────────── intake ───────────────────────────

def n_intake(s):
    root = s["root"]
    summary = design.summary(root)
    idx = design.index(root)
    features = sorted({k.split("/", 1)[0] for k, v in idx["screens"].items() if v.get("status") != "removed"})
    payload = _task(
        "intake",
        "Start a feature cycle. 1) Ask the user (AskUserQuestion, Korean) which feature to build and, if its design is not imported yet, "
        "which Claude Design project and screen files to import. 2) If a design run is needed: call design_start(feature, project_id, screens), "
        "read the listed .dc.html (and whatever list_files shows that the hook allows) with the Claude Design connector — the capture hook "
        "writes them into design/ — then design_trial() to see the detected screens, confirm/rename screen ids with the user, and design_finish(spec). "
        "3) Write a short brief (requirements for this feature, Korean, from the user's words). "
        "Submit {feature, brief, screens?}. `features` lists features that already have an imported design.",
        {"feature": "string (lowercase, e.g. forest)", "brief": "string (Korean, multi-line)", "screens": "optional list of screen ids to build in this cycle"},
        features=features, ledger=summary, app=config.load(root).get("app"),
    )
    feature = str((payload or {}).get("feature") or "").strip()
    keys = [k for k, v in idx["screens"].items() if k.startswith(feature + "/") and v.get("status") != "removed"]
    if not feature or not keys:
        return {"phase": "intake", "feature": feature, "log": [f"intake:retry:{feature or '?'}"]}
    if (payload or {}).get("brief"):
        util.write_text(os.path.join(root, util.FEATURES_DIR, feature, "brief.md"), f"# {feature}\n\n{str(payload['brief']).strip()}\n")
    want = payload.get("screens") if isinstance(payload.get("screens"), list) and payload.get("screens") else [k.split("/", 1)[1] for k in keys]
    return {"phase": "plan", "feature": feature, "screens": [str(x) for x in want], "order": [], "cursor": 0, "attempts": {}, "results": {},
            "dev": {}, "reports": [], "blocked": None, "log": [f"intake:{feature}"]}


def _after_intake(s):
    return "plan" if s.get("phase") == "plan" else "intake"


# ─────────────────────────── plan ───────────────────────────

def _layouts(root, feature):
    out = {}
    d = os.path.join(root, util.DESIGN_DIR, feature, "layout")
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            if n.endswith(".json"):
                out[n[:-5]] = util.read_json(os.path.join(d, n))
    return out


def plan_material(root, feature, screens):
    lays = _layouts(root, feature)
    mat = {"screens": {}}
    for sid in screens:
        lay = lays.get(sid)
        if not lay:
            mat["screens"][sid] = {"error": "no layout"}
            continue
        st = tree.status(lay)
        an = draft.analyze(lay)
        mat["screens"][sid] = {"kind": lay.get("kind"), "nodes": st["nodes"], "binds": st["binds"], "handlers": st["handlers"], "lists": st["lists"],
                               "ifs": st["ifs"], "slots": st["screen_refs"], "classes": st["classes"], "unknown": st["unknown"],
                               "state_fields": an.fields, "item_types": {k: sorted(v) for k, v in an.items.items()}, "actions": sorted(an.actions),
                               "layout": f"design/{feature}/layout/{sid}.json"}
    try:
        mat["routes"] = [f"{r['method']} {r['path']} ({r['name']})" for r in contract.routes(contract.merged(root))]
    except contract.ContractError as e:
        mat["routes"] = [f"(contract error: {e})"]
    mat["brief"] = util.read_text(os.path.join(root, util.FEATURES_DIR, feature, "brief.md"), "")
    idx = design.index(root)
    mat["catalog"] = [c["name"] for c in design.catalog(root)]                     # 디자인 시스템 컴포넌트 (첫 사이클의 ds 과제가 만든다)
    mat["ds_built"] = bool((idx.get("ds") or {}).get("built"))
    mat["decisions"] = [d for d in decide.ledger(root)["decisions"] if d["feature"] in (feature, "general") and d["status"] != "flipped"]
    return mat


def n_plan(s):
    root, feature = s["root"], s["feature"]
    mat = plan_material(root, feature, s.get("screens") or [])
    payload = _task(
        "plan",
        "Write the screen plans for this feature from `material` (layout trees are the structure — plans only reference them). "
        "For each screen: states (if keys), interactions (handler → navigation/API), data entities it reads/writes (name them like PostRepository → 'Post'), "
        "catalog components (class nodes), translations needed (node ids whose CSS the tree cannot decide). Decide the build order: data layer first, "
        "then screens so that hosts (shell) come after the screens they slot in. If the contract (api/openapi.yaml body) needs new paths/schemas, "
        "put the full new body text in `openapi`. Submit {order, data, plans, openapi?}.",
        {"order": "list of screen ids in build order", "data": "list of entity names for the data task (may be empty)",
         "plans": "{screen: {states, interactions, data, components, translations, notes}}", "openapi": "optional full text of api/openapi.yaml"},
        material=mat,
    )
    order = [str(x) for x in (payload.get("order") or s.get("screens") or [])]
    known = set(_layouts(root, feature))
    bad = [x for x in order if x not in known]
    if bad or not order:
        return {"phase": "plan", "log": [f"plan:retry:{bad}"]}
    if payload.get("openapi"):
        try:
            text = str(payload["openapi"])
            doc = yaml_lite.loads(text)
            if not isinstance(doc, dict) or "openapi" not in doc:
                raise contract.ContractError("openapi 본문이 아니다")
            util.write_text(contract.body_path(root), text)
            contract.write_generated(root)
            cfg = config.load(root)
            gen.write(root, cfg)                         # 계약 → 클라이언트 생성물도 같이 (워크트리는 main 에서 자른다)
            pkg = cfg["app"]["id"].replace(".", "/")
            git.commit_paths(root, f"contract({feature}): openapi · generated", "api", "apps/ios/App/Core/Networking",
                             f"apps/android/app/src/main/kotlin/{pkg}/core/networking", "apps/android/app/src/test")
        except (contract.ContractError, gen.GenError) as e:
            return {"phase": "plan", "log": [f"plan:contract-error:{e}"]}
    plans = payload.get("plans") if isinstance(payload.get("plans"), dict) else {}
    for sid in order:
        p = plans.get(sid) if isinstance(plans.get(sid), dict) else {}
        doc = {"layout": f"design/{feature}/layout/{sid}.json", **p}
        util.write_text(os.path.join(root, PLANS, feature, f"{sid}.yaml"), yaml_lite.dumps(doc))
        try:
            design.set_status(root, f"{feature}/{sid}", "planned")
        except design.DesignError:
            pass
    data = [str(x) for x in (payload.get("data") or []) if str(x).strip()]
    prev = (yaml_lite.loads(util.read_text(os.path.join(root, PLANS, feature, "_data.yaml"), "")) or {}).get("entities") or []
    ds_first = bool(design.catalog(root)) and not (design.index(root).get("ds") or {}).get("built")       # 디자인 시스템 과제 → 데이터 과제 → 화면 (4장 build)
    tasks = ([{"kind": "ds", "id": "ds"}] if ds_first else []) + ([{"kind": "data", "id": "data"}] if data else []) + [{"kind": "screen", "id": sid} for sid in order]
    util.write_text(os.path.join(root, PLANS, feature, "_data.yaml"), yaml_lite.dumps({"entities": sorted(set(prev) | set(data))}))   # 이전 사이클의 엔티티를 지우지 않는다
    return {"phase": "build", "screens": order, "order": tasks, "cursor": 0, "log": [f"plan:{len(order)} screens, data {data}"]}


def _after_plan(s):
    return "prepare" if s.get("phase") == "build" else "plan"


# ─────────────────────────── prepare (결정적) ───────────────────────────

def _task_now(s):
    order = s.get("order") or []
    i = s.get("cursor", 0)
    return order[i] if i < len(order) else None


def worktree_name(platform, task_id):
    return f"{platform}-{task_id}"


def _draft_into(root, wt, lay, feature, platform, vars_):
    """구조 초안을 워크트리에 쓴다 — 이미 draft 커밋이 있으면 건너뛴다 (멱등, 개발자 코드를 덮지 않는다)."""
    sid = lay["screen"]
    if git.run(wt, "log", "--oneline", "--grep", f"^draft({sid})", check=False).stdout.strip():
        return []
    catalog = gate.ds_types(wt, platform, vars_) & design.catalog_names(git.main_root(wt) or wt)     # 이 플랫폼에 이미 구현된 카탈로그 컴포넌트만 감싼다
    files = draft.swift(lay, feature, vars_, catalog) if platform == "ios" else draft.kotlin(lay, feature, vars_, catalog)
    written = []
    for rel, text in files.items():
        p = os.path.join(wt, util.APPS[platform], rel)
        util.write_text(p, text)
        written.append(os.path.relpath(p, wt))
    edits = draft.route_edits(sid, feature, vars_, lambda rel: util.read_text(os.path.join(wt, rel), ""))
    for rel, text in edits.items():
        if rel.startswith(util.APPS[platform]):
            util.write_text(os.path.join(wt, rel), text)
            written.append(rel)
    git.commit_all(wt, f"draft({sid}): structure draft from layout tree {lay.get('hash', '')}")
    return written


def task_prompt(root, s, platform, task, wt, drafted, rework):
    """개발자 과제 프롬프트 (영어) — 서브에이전트는 메인 대화를 못 본다. 빠짐없이 싣는다."""
    feature = s["feature"]
    cfg = config.load(root)
    vars_ = config.app_vars(cfg)
    other = "android" if platform == "ios" else "ios"
    L = [f"# twbuild task — {platform}: {task['kind']} `{task['id']}` (feature `{feature}`)", "",
         f"You are `{platform}-dev`. Work ONLY inside the worktree `{wt}` (branch twbuild/{worktree_name(platform, task['id'])}), ONLY under `{util.APPS[platform]}/`.",
         f"The {other} developer builds the same {task['kind']} in parallel in another worktree. You never touch design/, api/, the other platform, or shared files outside your platform.",
         "", "## Sources of truth (read these first)",
         f"- Brief: `features/{feature}/brief.md`", f"- App overview: `features/app.md`",
         f"- Architecture: MVVM + UDF — View · UiState · Action · ViewModel; data objects *Repository / *Store / *Draft live in Core and are created in AppContainer (AGENT.md §14 rules are in your preloaded skills).",
         f"- App id `{vars_['id']}` · product `{vars_['product']}` · min OS iOS {vars_['min_ios']} / Android API {vars_['min_android']}."]
    if task["kind"] == "screen":
        sid = task["id"]
        L += [f"- Layout tree (STRUCTURE, 1:1): `design/{feature}/layout/{sid}.json` — nesting, order, `if`, `list`, handlers and node ids are binding. No merging, dropping, reordering or extra containers.",
              f"- Plan: `.twbuild/plans/{feature}/{sid}.yaml` (states · interactions · data · translations).",
              f"- Design source (for look only): `design/{feature}/` · tokens `design/ds/tokens.json` → generated `Tokens.*` constants.",
              f"- Fonts (generated, registered on both platforms — never add font files yourself, gate T9): iOS `FontFamily.heading` / `FontFamily.body` + `FontFamily.font(…)` in `App/Core/DesignSystem/Fonts.swift`; Android `FontFamilies.heading` / `FontFamilies.body` in `core/designsystem/Fonts.kt`. CSS `var(--font-heading)` → those; if the file is missing the fonts were not fetched — fall back to system fonts and say so in your note.",
              f"- Structure draft (already committed as `draft({sid})`): {', '.join(drafted) if drafted else 'see Features/<feature>/<Screen>'}. It compiles; it is yours now."]
        L += ["", "## What to do",
              "1. Translate every `// style:` comment into native styling using your translate skill. Values that match a token use the `Tokens.*` constant; other values come from the tree as written. Never invent colors/sizes that are not in the tree.",
              "2. Implement the ViewModel: Action → new UiState. Wire data through the container's repositories/stores (data task output, if any). Navigation goes through Route/Router.",
              "3. Replace icon placeholders with real icons (SF Symbols / Material icons closest to the SVG; note raw-svg paths in a comment).",
              "4. Keep every accessibility identifier / test tag exactly as in the tree. Keep UiState field names, Action names and Route names as generated (the gate compares both platforms).",
              "5. Run `twbuild check` (the static gate T1~T6 for your screen, parity when the other worktree exists; `--build` adds the platform build) and the platform build from your playbook until both are clean. Commit in small steps; finish with a commit.",
              "6. If a CSS → native translation is ambiguous for a node, record it: `twbuild decide <node id> \"<your interpretation>\" --by " + platform + "`. If a decision for that node already exists, follow it.",
              "7. If something outside your boundary must change (contract, shared component, design, a different structure), stop and report `blocked` with the exact reason."]
    elif task["kind"] == "ds":
        cat = design.catalog(root)
        L += ["- Design-system task: implement the catalog components as reusable views under `App/Core/DesignSystem/Catalog/<Name>.swift` (iOS) · `core/designsystem/catalog/<Name>.kt` (Android) — one file per component, the SAME names and parameter names on both platforms (gate T7 compares them):"]
        L += [f"  - `{c['name']}` ← class `.{c.get('class', '')}` in `{c['file']}`" + (f"; parts: {', '.join('.' + p for p in c['parts'])}" if c.get("parts") else "")
              + (f"; variants (modifier classes → parameters with defaults): {', '.join('.' + m for m in c['modifiers'])}" if c.get("modifiers") else "") for c in cat]
        L += ["- Convention the structure drafts rely on: every component takes trailing content — SwiftUI `struct <Name><Content: View>: View { init(@ViewBuilder content: () -> Content) }`, Compose `@Composable fun <Name>(modifier: Modifier = Modifier, content: @Composable () -> Unit)`; every other parameter has a default. Colors · spacing · radius through `Tokens.*`; no literal values that are not in the component html.",
              "", "## What to do", "1. Read each component html. 2. Implement it with the convention above (plus a preview). 3. Build; `twbuild check` shows the T7 name parity once the other platform's worktree exists. Commit.",
              "4. No screen code, no data code. Report blocked for anything outside Core/DesignSystem."]
    else:
        ents = (yaml_lite.loads(util.read_text(os.path.join(root, PLANS, feature, "_data.yaml"), "")) or {}).get("entities") or []
        L += [f"- Data task: implement the data layer for entities {ents}: for each entity a `<Entity>Repository` protocol/interface + a local implementation (in-memory or local DB) and a mock/API implementation using the generated contract routes (`api/generated/routes.json`). Register them in `AppContainer`.",
              "- Follow AGENT.md §14 data layer: Repository (synced entity, local DB is the source of truth), Store (app-wide state), Draft (flow-scoped). Expose observation (AsyncStream / Flow) so several screens can subscribe.",
              "", "## What to do", "1. Create the data objects under Core/Data (iOS) · core/data (Android) with the SAME names and method names as the other platform (the gate compares them): `fetch`, `observe`, `upsert`, `delete`.",
              "2. Wire them into AppContainer (constructor injection). 3. Build until it compiles; `twbuild check` shows the T6 name parity once the other platform has pushed its worktree. Commit. 4. Report blocked for anything outside your boundary."]
    decs = [d for d in decide.ledger(root)["decisions"] if d["feature"] in (feature, "general") and d["status"] != "flipped"]
    if decs:
        L += ["", "## Team decisions (binding)"] + [f"- {d['id']} [{d['status']}] `{d['topic']}` — {d['text']} (by {d['by']})" for d in decs]
    if rework:
        L += ["", "## Rework — the previous attempt failed the gate", "(Measured before any harness fix since then — run `twbuild check` first; if it is clean and the build passes, finish without changing code.)", rework]
    L += ["", "## Finish",
          f"- Write a short task note to `.twbuild/tasks/{task['id']}-{platform}.md` (inside the worktree; git-ignored — do NOT force-add it, the harness collects it at merge): what you did, what you decided (D-ids), what is uncertain, build result.",
          "- Everything committed in the worktree. Then end with a one-paragraph summary: status (done|blocked), commits, note path, open questions.",
          "- Never run git push, never edit files outside your worktree/platform, never read .env* or keys (hooks block these anyway)."]
    return "\n".join(L)


def n_prepare(s):
    """워크트리 2개 + 구조 초안 + 과제 메모 자리. 멱등."""
    root, feature = s["root"], s["feature"]
    task = _task_now(s)
    if not task:
        return {"phase": "done", "log": ["prepare:none"]}
    cfg = config.load(root)
    setup.install_precommit(root)                        # 개발자 커밋 전 시크릿 검사 — 워크트리도 같은 훅을 쓴다 (멱등)
    setup.ensure_gitignore(root)                         # .gitignore 블록이 템플릿과 다르면 갱신 (멱등)
    vars_ = config.app_vars(cfg)
    lays = _layouts(root, feature)
    prepared = {}
    for p in cfg.get("platforms") or []:
        wt, created = git.ensure_worktree(root, worktree_name(p, task["id"]))
        if not created:                                  # 브랜치를 자른 뒤 main 이 움직였다(다른 화면 머지 · 생성물 · 폰트) — 재배차 전에 합친다 (머지 커밋, 이력 재작성 아님)
            try:
                git.merge_main(wt)
            except git.GitError as e:
                return {"phase": "blocked", "blocked": {"reason": "worktree merge conflict", "job": task,
                                                        "detail": f"{worktree_name(p, task['id'])} 에 main 을 합치지 못했다 — 사람이 워크트리에서 충돌을 풀고(또는 커밋하고) submit({{}}): {e}"},
                        "log": [f"prepare:merge-conflict:{p}"]}
        if gen.drift(wt, cfg):                           # 계약 생성물이 브랜치에 없거나 낡았다(브랜치를 자른 뒤 계약이 바뀜) — 결정적이라 다시 쓰고 커밋한다
            gen.write(wt, cfg)
            git.commit_all(wt, "generated(contract): models · client from api/openapi.yaml")
        if p == "android":
            gate.ensure_android_props(wt)                # local.properties(gitignore) — 개발자 빌드가 바로 되게
        drafted = []
        if task["kind"] == "screen" and task["id"] in lays:
            drafted = _draft_into(root, wt, lays[task["id"]], feature, p, vars_)
            try:
                design.set_status(root, f"{feature}/{task['id']}", "building", built={"tree": lays[task["id"]].get("hash")})
            except design.DesignError:
                pass
        prepared[p] = {"worktree": wt, "created": created, "drafted": drafted}
    # 훅(결정 주입 · 측정)이 읽는 현재 과제 — 서브에이전트는 메인 대화를 못 보고 훅은 그래프 상태를 못 읽는다
    util.write_json(util.tw(root, util.TASKS, "_current.json"), {"t": util.now(), "feature": feature, "task": task,
                                                                "worktrees": {p: v["worktree"] for p, v in prepared.items()}})
    return {"phase": "dispatch", "dev": {"_prepared": prepared}, "log": [f"prepare:{task['id']}"]}


def _after_prepare(s):
    return "blocked" if s.get("phase") == "blocked" else "dispatch"


# ─────────────────────────── dispatch (묻는 노드) ───────────────────────────

def _rework_text(s, task_id, platform=None):
    """재작업 프롬프트의 실패 상세 — platform 을 주면 그 플랫폼의 층 + 양쪽 공통(패리티)만 (상대 플랫폼 로그는 소음)."""
    res = (s.get("results") or {}).get(task_id) or {}
    out = []
    for p, r in res.items():
        if not isinstance(r, dict) or (platform and p != platform):
            continue
        for v in (r.get("static") or {}).get("violations") or []:
            out.append(f"- [{p}] {v['rule']}: {v['detail']}")
        b = r.get("build") or {}
        if b.get("status") == "fail":
            out.append(f"- [{p}] build failed: {b.get('detail')}\n```\n{b.get('tail', '')}\n```")
        for layer, label in (("contract_decode", "contract decoding failed (generated models vs api/openapi.yaml examples)"), ("device", "device smoke failed (app did not stay alive)")):
            d = r.get(layer) or {}
            if d.get("status") == "fail":
                lg = d.get("log") or ""
                tail = gate.tail(lg) if isinstance(lg, str) and os.path.isfile(lg) else str(lg)[-1500:]
                out.append(f"- [{p}] {label}: {d.get('detail')}\n```\n{tail}\n```")
        for v in (r.get("parity") or {}).get("violations") or []:
            line = f"- [both] {v['rule']}: {v['detail']}"
            if line not in out:                 # 패리티는 양쪽 결과에 같은 내용이 실린다 — 한 번만
                out.append(line)
    return "\n".join(out)


def n_dispatch(s):
    root, feature = s["root"], s["feature"]
    task = _task_now(s)
    cfg = config.load(root)
    prepared = (s.get("dev") or {}).get("_prepared") or {}
    attempt = (s.get("attempts") or {}).get(task["id"], 0) + 1
    prompts, models = {}, {}
    for p in cfg.get("platforms") or []:
        wt = prepared.get(p, {}).get("worktree") or util.tw(root, util.WORKTREES, worktree_name(p, task["id"]))
        prompts[p] = task_prompt(root, s, p, task, wt, prepared.get(p, {}).get("drafted") or [], _rework_text(s, task["id"], p) if attempt > 1 else "")
        models[p] = (cfg.get("agents", {}).get(p) or {}).get("model", "sonnet")
    payload = _task(
        "build",
        f"Dispatch the developers for {task['kind']} `{task['id']}` (attempt {attempt}/{cfg['budget']['attempts_per_screen']}): launch BOTH agents at once, "
        "in one message, with the Agent tool — subagent_type `twbuild:ios-dev` with prompts.ios and `twbuild:android-dev` with prompts.android "
        "(model per `models`). Pass each prompt verbatim; do not summarize. Wait for both to finish. Then submit their results: "
        "{ios: {status: done|blocked, summary, note}, android: {...}}. Do not fix their code yourself.",
        {"ios": "{status: done|blocked, summary: string, note: path}", "android": "{status: done|blocked, summary: string, note: path}"},
        job=task, attempt=attempt, prompts=prompts, models=models, worktrees={p: prepared.get(p, {}).get("worktree") for p in prepared},
    )
    dev = {p: (payload.get(p) if isinstance(payload.get(p), dict) else {"status": "done", "summary": str(payload.get(p) or "")}) for p in cfg.get("platforms") or []}
    attempts = {**(s.get("attempts") or {}), task["id"]: attempt}
    blocked = [p for p, r in dev.items() if str(r.get("status", "")).lower() == "blocked"]
    if blocked:
        return {"phase": "blocked", "dev": dev, "attempts": attempts,
                "blocked": {"reason": "developer blocked", "platforms": blocked, "detail": {p: dev[p].get("summary", "") for p in blocked}, "job": task},
                "log": [f"dispatch:blocked:{blocked}"]}
    return {"phase": "smoke", "dev": dev, "attempts": attempts, "log": [f"dispatch:{task['id']}#{attempt}"]}


def _after_dispatch(s):
    return "blocked" if s.get("phase") == "blocked" else "smoke"


# ─────────────────────────── smoke (결정적) ───────────────────────────

def static_results(root, feature, task, wts, cfg):
    """정적 층(T1~T4) + 패리티(T5 · T6) — smoke 노드와 `twbuild check` 가 같은 함수를 쓴다. wts: 플랫폼 → 워크트리."""
    vars_ = config.app_vars(cfg)
    lays = _layouts(root, feature)
    tk = tokens.load(root) or {}
    hexes = [e["hex"][1:] for e in (tk.get("color") or {}).values() if e.get("kind") == "color"]
    res = {}
    for p, wt in wts.items():
        if task["kind"] == "screen" and task["id"] in lays and os.path.isdir(wt):
            src_hex = gate.source_hexes(util.read_text(os.path.join(root, lays[task["id"]].get("source") or ""), ""))
            catalog = gate.ds_types(wt, p, vars_) & design.catalog_names(root)       # T8 은 이 플랫폼에 구현된 컴포넌트만 요구한다
            res[p] = {"static": gate.static_check(wt, p, lays[task["id"]], hexes, src_hex, catalog)}
        else:
            res[p] = {"static": {"status": "unmeasured", "violations": [], "checked": 0}}
    both = [w for w in (wts.get("ios"), wts.get("android")) if w and os.path.isdir(w)]
    if len(both) == 2:
        par = gate.parity_check(wts["ios"], wts["android"], vars_)
        fp = fonts.parity(wts["ios"], cfg)                                   # T9 — 폰트 등록은 하네스가 main 에서 하므로 어느 워크트리든 같다
        extras = [gate.data_parity_check(wts["ios"], wts["android"], vars_), gate.ds_parity_check(wts["ios"], wts["android"], vars_),
                  {"status": "fail" if fp else "pass", "violations": fp}]        # T6 · T7 · T9
        if task["kind"] == "screen":
            extras.append(gate.state_parity_check(wts["ios"], wts["android"], vars_, feature, task["id"]))   # T10 — UiState · Action 이름 · 타입
        for extra in extras:
            if extra["status"] == "fail":
                par = {"status": "fail", "violations": par["violations"] + extra["violations"]}
        for p in res:
            res[p]["parity"] = par
    return res


def check_cli(cwd, platform=None, build=False):
    """`twbuild check [--platform ios|android] [--build]` — 개발자가 과제 중 직접 돌리는 게이트. 워크트리 안에서 부르면 그 플랫폼. → (code, 한국어 출력)."""
    main = git.main_root(cwd)
    if not main or not util.is_wired(main):
        return 2, "twbuild 레포(또는 그 워크트리) 안에서 실행한다"
    cur = util.read_json(util.tw(main, "tasks", "_current.json"), {}) or {}
    task, feature = cur.get("task"), cur.get("feature")
    if not task or not feature:
        return 2, "진행 중인 과제가 없다 (.twbuild/tasks/_current.json)"
    cfg = config.load(main)
    wts = {p: w for p, w in (cur.get("worktrees") or {}).items() if os.path.isdir(w)}
    here = os.path.abspath(cwd)
    if not platform:
        platform = next((p for p, w in wts.items() if here == os.path.abspath(w) or here.startswith(os.path.abspath(w) + os.sep)), None)
    res = static_results(main, feature, task, wts, cfg)
    lines, fail = [f"twbuild check — {feature}/{task['id']} ({task['kind']})" + (f" · {platform}" if platform else "")], False
    for p, r in res.items():
        if platform and p != platform:
            continue
        st = r["static"]
        lines.append(f"[{p}] 정적 {st['status']} (검사 {st.get('checked', 0)}개)" + ("" if st["status"] != "unmeasured" else " — 화면 과제가 아니거나 워크트리가 없다"))
        lines += [f"  - {v['rule']}: {v['detail']}" for v in st.get("violations") or []]
        fail = fail or st["status"] == "fail"
        if build and p in wts:
            b = gate.build(wts[p], p, config.app_vars(cfg), util.tw(main, util.LOGS_DIR, f"check-{feature}-{task['id']}-{p}.log"))
            lines.append(f"[{p}] 빌드 {b['status']} — {b.get('detail', '')} ({metrics._fmt_ms(b.get('ms'))})")
            if b["status"] == "fail":
                fail = True
                lines.append(gate.tail(b["log"]))
    par = next(iter(res.values()), {}).get("parity") if res else None
    if par:
        lines.append(f"[both] 패리티(T5 · T6) {par['status']}")
        lines += [f"  - {v['rule']}: {v['detail']}" for v in par.get("violations") or []]
        fail = fail or par["status"] == "fail"
    else:
        lines.append("[both] 패리티 못 잼 — 상대 플랫폼 워크트리가 없다")
    lines.append("실패" if fail else "통과 — 스모크는 머지 전에 빌드 · 계약 · 기기 층을 다시 잰다")
    return (1 if fail else 0), "\n".join(lines)


def n_smoke(s):
    root, feature = s["root"], s["feature"]
    task = _task_now(s)
    cfg = config.load(root)
    vars_ = config.app_vars(cfg)
    wts = {p: util.tw(root, util.WORKTREES, worktree_name(p, task["id"])) for p in cfg.get("platforms") or []}
    res = static_results(root, feature, task, wts, cfg)                 # 정적 층 + 패리티 (twbuild check 와 같은 함수)
    for p, wt in wts.items():
        r = res[p]
        log = util.tw(root, util.LOGS_DIR, f"smoke-{feature}-{task['id']}-{p}.log")
        b = gate.build(wt, p, vars_, log)
        if b.get("status") == "fail":
            b["tail"] = gate.tail(log)
        r["build"] = b
        r["contract_decode"] = (gen.decode_check(wt, p, util.tw(root, util.LOGS_DIR, f"decode-{feature}-{task['id']}-{p}.log"), cfg=cfg) if b.get("status") == "pass"
                                else {"status": "unmeasured", "detail": "빌드 층이 통과하지 않아 건너뜀"})           # 계약 층(6장)
    ok = all(r["static"]["status"] != "fail" and r["build"]["status"] != "fail" and (r.get("parity") or {}).get("status") != "fail"
             and r["contract_decode"]["status"] != "fail" for r in res.values())
    # 기기 층(6장): 설정 smoke.device — every 는 매번, merge 는 다른 층을 다 통과한 시도(= 머지 직전)에만, off 는 안 잰다. 못 잼은 머지를 막지 않고 보고서에 남는다. fail 은 막는다.
    policy = (cfg.get("smoke") or {}).get("device", "merge")
    for p, r in res.items():
        if policy == "off":
            r["device"] = {"status": "unmeasured", "detail": "설정 smoke.device: off"}
        elif r["build"]["status"] != "pass":
            r["device"] = {"status": "unmeasured", "detail": "빌드 층이 통과하지 않아 건너뜀"}
        elif policy == "every" or ok:
            d = device.run(wts[p], p, vars_, util.tw(root, util.LOGS_DIR, f"device-{feature}-{task['id']}-{p}.log"))
            r["device"] = {**d, "detail": leaks.mask_all(d.get("detail") or ""), "log": leaks.mask_all(d.get("log") or "")}
        else:
            r["device"] = {"status": "unmeasured", "detail": "다른 층이 실패한 시도 — 머지 직전에만 잰다(smoke.device: merge)"}
    ok = ok and all(r["device"]["status"] != "fail" for r in res.values())
    util.write_json(os.path.join(root, RESULTS, feature, f"{task['id']}.json"), {"t": util.now(), "attempt": (s.get("attempts") or {}).get(task["id"]), "pass": ok, "results": res})
    results = {**(s.get("results") or {}), task["id"]: res}
    if ok:
        return {"phase": "merge", "results": results, "smoked": task["id"], "log": [f"smoke:pass:{task['id']}"]}
    if (s.get("attempts") or {}).get(task["id"], 0) >= int(cfg["budget"]["attempts_per_screen"]):
        return {"phase": "blocked", "results": results,
                "blocked": {"reason": "budget exhausted", "job": task, "detail": _rework_text({"results": results}, task["id"])},
                "smoked": task["id"], "log": [f"smoke:budget:{task['id']}"]}
    return {"phase": "rework", "results": results, "smoked": task["id"], "log": [f"smoke:fail:{task['id']}"]}


def _after_smoke(s):
    return {"merge": "merge", "blocked": "blocked"}.get(s.get("phase"), "prepare")


# ─────────────────────────── merge (결정적) ───────────────────────────

def evidence(root, feature, task, s, commits):
    res = (s.get("results") or {}).get(task["id"]) or {}
    L = [f"## {feature} / {task['id']} — 증거 보고서", "", f"- 시도: {(s.get('attempts') or {}).get(task['id'])}회", f"- 커밋: {', '.join(f'{p} {c[:7]}' for p, c in commits.items() if c)}",
         "", "| 층 | iOS | Android |", "|---|---|---|"]
    def m(r):
        st = (r or {}).get("status")
        return "✅" if st == "pass" else ("❌" if st == "fail" else "— 못 잼")
    for layer in ("static", "build", "parity", "device", "contract_decode"):
        L.append(f"| {layer} | {m((res.get('ios') or {}).get(layer))} | {m((res.get('android') or {}).get(layer))} |")
    sid_rx = re.compile(rf"(^|\.){re.escape(task['id'])}(\.|$)")           # n.sound.* 뿐 아니라 data.sound.readonly · nav.sound.* 도 이 화면의 결정이다
    decs = [d for d in decide.ledger(root)["decisions"] if (d.get("screen") == task["id"] or sid_rx.search(d.get("topic") or "")) and d["status"] != "flipped"]
    if decs:
        L += ["", "적용된 결정: " + ", ".join(f"{d['id']}({d['status']})" for d in decs)]
    L += ["", f"되돌리기: `git revert {' '.join(c[:7] for c in commits.values() if c)}`"]
    return "\n".join(L) + "\n"


def n_merge(s):
    root, feature = s["root"], s["feature"]
    task = _task_now(s)
    cfg = config.load(root)
    lays = _layouts(root, feature)
    idx = design.index(root)
    key = f"{feature}/{task['id']}"
    if task["kind"] == "screen":
        cur = (idx["screens"].get(key) or {}).get("tree")
        built = ((idx["screens"].get(key) or {}).get("built") or {}).get("tree")
        if cur and built and cur != built:
            return {"phase": "blocked", "blocked": {"reason": "tree changed during build", "job": task,
                                                    "detail": f"원장 트리 {cur} ≠ 빌드 트리 {built} — 새 design run 이 들어왔다. 재작업 과제로 다시 만든다."},
                    "log": [f"merge:stale:{task['id']}"]}
    for p in cfg.get("platforms") or []:                 # 머지 전 시크릿 · 민감 파일 검사 — 브랜치가 바꾼 파일 전부 (11장)
        b = git.branch(worktree_name(p, task["id"]))
        if git.branch_exists(root, b):
            hits = leaks.scan_files(root, git.changed_files(root, "HEAD", b), reader=lambda rel, b=b: git.show(root, f"{b}:{rel}"))
            if hits:
                return {"phase": "blocked", "blocked": {"reason": "secret in branch", "job": task,
                                                        "detail": f"{b} 에 시크릿 · 민감 파일 의심 {len(hits)}건: " + ", ".join(f"{rel}({kind})" for rel, kind, _ in hits[:6])
                                                                  + " — 사람이 브랜치에서 지우고(값은 .env.local) submit({}) 으로 다시 돈다"},
                        "log": [f"merge:secret:{p}"]}
    commits = {}
    for p in cfg.get("platforms") or []:
        name = worktree_name(p, task["id"])
        b = git.branch(name)
        if git.branch_exists(root, b):
            try:
                commits[p] = git.merge_squash(root, b, f"{task['kind']}({feature}/{task['id']}): {p}")
            except git.GitError as e:
                return {"phase": "blocked", "blocked": {"reason": "merge conflict", "job": task, "detail": str(e)}, "log": [f"merge:conflict:{p}"]}
    git.tag(root, f"{task['kind']}/{feature}/{task['id']}", f"{feature}/{task['id']} merged")
    config.lock(root, cfg)                               # 첫 머지 — architecture · min_os · app.id · app.product 잠김 (14장 · 설정)
    if task["kind"] == "screen":
        try:
            design.set_status(root, key, "consumed", built={"tree": (idx["screens"].get(key) or {}).get("tree"), "commits": commits})
        except design.DesignError:
            pass
    elif task["kind"] == "ds":
        design.set_ds_built(root, {"hash": (idx.get("ds") or {}).get("hash"), "commits": commits, "components": sorted(design.catalog_names(root))})
    for p in cfg.get("platforms") or []:
        wt = util.tw(root, util.WORKTREES, worktree_name(p, task["id"]))
        notes = os.path.join(wt, TASKS)
        if os.path.isdir(notes):                  # 과제 메모(.twbuild/tasks, gitignore)는 워크트리를 지우기 전에 메인으로 거둔다
            for n in os.listdir(notes):
                if n.endswith(".md"):
                    util.write_text(os.path.join(root, TASKS, n), util.read_text(os.path.join(notes, n), ""))
        git.remove_worktree(root, worktree_name(p, task["id"]))
    rep = evidence(root, feature, task, s, commits)
    util.write_text(os.path.join(root, REPORTS, feature, f"{task['id']}.md"), rep)
    # 원장(design/index.json) · 결정(.claude/rules/team) · brief · 기능 측정 요약(13장) · 설정 잠금은 커밋 대상이다 — 머지마다 main 에 남긴다
    summary_rel = metrics.write_feature_summary(root, feature)
    git.commit_paths(root, f"ledger({feature}/{task['id']}): index · decisions · brief · metrics",
                     os.path.join("design", "index.json"), os.path.join(".claude", "rules", "team"), os.path.join(util.FEATURES_DIR, feature),
                     summary_rel, os.path.join(util.TW_DIR, config.LOCK))
    reports = list(s.get("reports") or []) + [rep]
    cursor = s.get("cursor", 0) + 1
    return {"phase": "build" if cursor < len(s.get("order") or []) else "done", "cursor": cursor, "reports": reports, "blocked": None,
            "log": [f"merge:{task['id']}"]}


def _after_merge(s):
    return {"build": "prepare", "blocked": "blocked"}.get(s.get("phase"), "done")


# ─────────────────────────── blocked · done ───────────────────────────

def n_blocked(s):
    b = s.get("blocked") or {}
    interrupt({"kind": "blocked", "graph": "cycle", "reason": b.get("reason"), "detail": b.get("detail"), "job": b.get("job"),
               "message": "Blocked. Show the user what blocks (Korean) and what must be done. When it is resolved, call submit({}) to retry the task."})
    attempts = dict(s.get("attempts") or {})
    if b.get("job"):
        jid = b["job"]["id"]
        # 하네스 · 사람 원인 멈춤(개발자 blocked · 머지 충돌 · 시크릿 …)은 시도로 세지 않는다 — 그 배차는 스모크까지 못 갔다. 예산 소진은 0 으로 되돌린다 (실측: 하네스 버그로 2회가 깎였다)
        attempts[jid] = 0 if b.get("reason") == "budget exhausted" else max(0, attempts.get(jid, 0) - 1)
    return {"phase": "build", "blocked": None, "attempts": attempts, "log": ["blocked:resume"]}


def n_done(s):
    root, feature = s["root"], s["feature"]
    reps = s.get("reports") or []
    rep = f"# {feature} — 사이클 완료\n\n화면 {len([t for t in s.get('order') or [] if t['kind'] == 'screen'])}개 머지. 되돌리기 명령은 화면별 보고서에 있다.\n\n" + "\n".join(reps)
    util.write_text(os.path.join(root, REPORTS, feature, "_cycle.md"), rep)
    return {"phase": "done", "log": ["done"]}


def build_cycle():
    g = StateGraph(CycleState)
    for name, fn in (("intake", n_intake), ("plan", n_plan), ("prepare", n_prepare), ("dispatch", n_dispatch), ("smoke", n_smoke),
                     ("merge", n_merge), ("blocked", n_blocked), ("done", n_done)):
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", _after_intake, {"intake": "intake", "plan": "plan"})
    g.add_conditional_edges("plan", _after_plan, {"plan": "plan", "prepare": "prepare"})
    g.add_conditional_edges("prepare", _after_prepare, {"dispatch": "dispatch", "blocked": "blocked"})
    g.add_conditional_edges("dispatch", _after_dispatch, {"blocked": "blocked", "smoke": "smoke"})
    g.add_conditional_edges("smoke", _after_smoke, {"merge": "merge", "blocked": "blocked", "prepare": "prepare"})
    g.add_conditional_edges("merge", _after_merge, {"prepare": "prepare", "blocked": "blocked", "done": "done"})
    g.add_edge("blocked", "prepare")
    g.add_edge("done", END)
    return g
