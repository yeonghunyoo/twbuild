"""측정 — .twbuild/metrics/events.jsonl (추가 전용, gitignore). AGENT.md 13장.

쓰는 곳은 그래프 구동 래퍼(graph.run) · 훅 · CLI 뿐이다. 그래프 노드 안에서는 쓰지 않는다 — 재개 때 노드가 처음부터 다시 돌아 중복된다.
같은 key 는 한 번만 들어간다. 모든 기록에 플러그인 버전 · 커밋 · 설정 해시가 붙는다.
"""
import json
import os
import time

from . import config, util

EVENTS = "events.jsonl"
OPEN = "open.json"          # 발행됐지만 아직 submit 되지 않은 과제 — {key: 발행 시각(epoch)}


def _dir(root):
    return util.tw(root, util.METRICS_DIR)


def _keys(path):
    out = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    k = json.loads(line).get("key")
                except ValueError:
                    continue
                if k:
                    out.add(k)
    except OSError:
        pass
    return out


def record(root, ev, key=None, **fields):
    """한 줄 추가. key 가 이미 있으면 건너뛰고 False."""
    d = _dir(root)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, EVENTS)
    if key and key in _keys(path):
        return False
    rec = {"t": util.now(), "ev": ev, "ver": {**util.plugin_version(), "config": config.digest(config.load(root))}}
    if key:
        rec["key"] = key
    rec.update(fields)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def node_done(root, graph, node, step, ms, error=None, feature=None):
    """노드 실행 — interrupt 없이 끝난 실행만 (graph.run 이 debug 스트림에서 잰다). 사이클 노드는 기능을 붙여 기능별 요약에 쓴다."""
    return record(root, "node", key=f"{graph}:{node}:{step}", graph=graph, node=node, step=step, ms=round(ms, 1),
                  **({"error": str(error)[:200]} if error else {}), **({"feature": feature} if feature else {}))


def task_issued(root, graph, task, step):
    """과제 발행 — open.json 에 시각을 남긴다. 이미 발행된 같은 과제(재개)는 다시 세지 않는다."""
    d = _dir(root)
    os.makedirs(d, exist_ok=True)
    opened = util.read_json(os.path.join(d, OPEN), {}) or {}
    k = f"{graph}:{task}:{step}"
    if k in opened:
        return False
    opened[k] = time.time()
    util.write_json(os.path.join(d, OPEN), opened)
    return record(root, "task_issued", key=f"issued:{k}", graph=graph, task=task, step=step)


def task_done(root, graph, task, step):
    """과제 submit — 발행부터 걸린 시간(사람 · LLM 작업 시간)."""
    d = _dir(root)
    opened = util.read_json(os.path.join(d, OPEN), {}) or {}
    k = f"{graph}:{task}:{step}"
    t0 = opened.pop(k, None)
    util.write_json(os.path.join(d, OPEN), opened)
    ms = round((time.time() - t0) * 1000, 1) if t0 else None
    return record(root, "task_done", key=f"done:{k}", graph=graph, task=task, step=step, ms=ms)


def events(root):
    out = []
    try:
        with open(os.path.join(_dir(root), EVENTS), encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def summary(root):
    """`twbuild stats` 의 재료 — 그래프 · 노드별 실행 수 · 합계 · 과제별 처리 시간."""
    nodes, tasks = {}, {}
    for e in events(root):
        if e.get("ev") == "node":
            k = (e.get("graph"), e.get("node"))
            n = nodes.setdefault(k, {"count": 0, "ms": 0.0, "errors": 0})
            n["count"] += 1
            n["ms"] += e.get("ms") or 0
            n["errors"] += 1 if e.get("error") else 0
        elif e.get("ev") == "task_done":
            k = (e.get("graph"), e.get("task"))
            t = tasks.setdefault(k, {"count": 0, "ms": 0.0, "unmeasured": 0})
            t["count"] += 1
            if e.get("ms") is None:
                t["unmeasured"] += 1
            else:
                t["ms"] += e["ms"]
    return {"nodes": nodes, "tasks": tasks}


def _fmt_ms(ms):
    if ms is None:
        return "못 잼"
    if ms < 1000:
        return f"{ms:.0f}ms"
    s = ms / 1000
    if s < 60:
        return f"{s:.1f}s"
    m, s = divmod(int(s), 60)
    return f"{m}m{s:02d}s" if m < 60 else f"{m // 60}h{m % 60:02d}m"


def _row():
    return {"attempts": 0, "static_fail": 0, "build_fail": 0, "build_ms": 0.0, "device": None, "device_ms": 0.0, "violations": [], "passed": False, "first_try": None,
            "ms": 0.0, "tokens": 0, "agents": 0}


def _mark(status):
    return {"pass": "✅", "fail": "❌", None: "-"}.get(status, "못 잼")


def screen_rows(root, feature=None, since=None):
    """(과제, 플랫폼) → 시도 · 정적/빌드 실패 · 빌드 시간 · 개발자 시간 · 토큰. feature 를 주면 그 기능의 이벤트만(기능이 없는 옛 기록은 포함)."""
    rows = {}
    for e in events(root):
        if since and (e.get("t") or "") < since:          # 사이클 범위 (retro)
            continue
        if feature and e.get("feature") and e.get("feature") != feature:
            continue
        if e.get("ev") == "smoke":
            r = rows.setdefault((e.get("task"), e.get("platform")), _row())
            r["attempts"] += 1
            r["static_fail"] += 1 if e.get("static") == "fail" else 0
            r["build_fail"] += 1 if e.get("build") == "fail" else 0
            r["build_ms"] += e.get("build_ms") or 0
            r["device"] = e.get("device") or r["device"]              # 마지막 기기 층 결과 (pass · fail · unmeasured)
            r["device_ms"] += e.get("device_ms") or 0
            r["violations"] += e.get("violations") or []
            r["passed"] = r["passed"] or bool(e.get("passed"))
            if r["first_try"] is None:
                r["first_try"] = bool(e.get("passed"))
        elif e.get("ev") == "visual" and e.get("verdict") == "rework":      # 스모크는 통과했지만 lead 가 시각 검수에서 돌려보냈다
            r = rows.setdefault((e.get("task"), e.get("platform")), _row())
            r["passed"] = False
            if r["attempts"] <= 1:
                r["first_try"] = False
        elif e.get("ev") == "agent":
            r = rows.setdefault((e.get("task"), e.get("platform")), _row())
            r["agents"] += 1
            r["ms"] += e.get("ms") or 0
            u = e.get("usage") or {}
            r["tokens"] += int(u.get("input") or 0) + int(u.get("output") or 0) + int(u.get("cache_create") or 0)
    return rows


def screens_table(root):
    """화면(과제)별 — 시도 · 정적/빌드 결과 · 빌드 시간 · 개발자 과제 시간 · 토큰 (smoke · agent 이벤트에서)."""
    rows = screen_rows(root)
    if not rows:
        return ""
    lines = ["", "화면 · 플랫폼 (smoke · 개발자 과제)",
             f"  {'과제':<12}{'플랫폼':<9}{'배차':>4}{'스모크':>5}{'정적 실패':>8}{'빌드 실패':>8}{'빌드 합':>8}{'기기':>5}{'통과':>5}{'개발자 시간':>10}{'토큰':>9}  위반"]
    for (task, plat), r in sorted(rows.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        viol = ",".join(sorted(set(r["violations"]))) or "-"
        lines.append(f"  {str(task):<12}{str(plat):<9}{(r['agents'] or '-'):>4}{r['attempts']:>5}{r['static_fail']:>8}{r['build_fail']:>8}{_fmt_ms(r['build_ms'] or None):>8}{_mark(r['device']):>5}{'✅' if r['passed'] else '—':>5}"
                     f"{_fmt_ms(r['ms'] if r['agents'] else None):>10}{(r['tokens'] or '-'):>9}  {viol}")
    return "\n".join(lines)


# ─────────────────────────── 기능별 요약 (merge 가 쓰고 커밋한다) ───────────────────────────

CYCLES_DIR = "cycles"


def _count_nodes(n):
    if not isinstance(n, dict):
        return 0
    return 1 + sum(_count_nodes(c) for c in n.get("children") or [])


def feature_summary(root, feature, only=None, since=None):
    """기능 하나의 측정 요약 — 화면 · 트리 노드 수 · 과제별 시도 · 첫 시도 통과율 · 빌드 · 개발자 시간 · 토큰(노드당) · 결정 수. 경로 없음 · 마스킹."""
    from . import decide, design, leaks
    idx = design.index(root)
    screens, tree_nodes = [], 0
    for key, v in sorted(idx["screens"].items()):
        feat, sid = key.split("/", 1)
        if feat != feature:
            continue
        screens.append(sid)
        lay = util.read_json(os.path.join(root, v.get("layout") or ""), {}) if v.get("layout") else {}
        tree_nodes += _count_nodes((lay or {}).get("root") or (lay or {}).get("tree") or lay)
    rows = screen_rows(root, feature, since)
    tasks = {}
    for (tid, plat), r in rows.items():
        if tid not in screens and tid not in ("data", "ds"):
            continue
        if only is not None and tid not in only:          # 사이클 범위 (retro)
            continue
        t = tasks.setdefault(tid, {"attempts": 0, "dispatches": 0, "first_try": True, "passed": True, "platforms": {}})
        t["attempts"] = max(t["attempts"], r["attempts"])            # 스모크 횟수
        t["dispatches"] = max(t["dispatches"], r["agents"])           # 배차 횟수(에이전트 측정이 있을 때만)
        t["first_try"] = t["first_try"] and bool(r["first_try"])
        t["passed"] = t["passed"] and r["passed"]
        t["platforms"][plat] = {k: r[k] for k in ("attempts", "static_fail", "build_fail", "build_ms", "device", "device_ms", "ms", "tokens", "agents")}
        t["platforms"][plat]["violations"] = sorted(set(r["violations"]))
    nodes = {}
    for e in events(root):
        if e.get("ev") == "node" and e.get("graph") == "cycle" and e.get("feature") == feature:
            n = nodes.setdefault(e["node"], {"count": 0, "ms": 0.0})
            n["count"] += 1
            n["ms"] += e.get("ms") or 0
    agent_ms = sum(p["ms"] for t in tasks.values() for p in t["platforms"].values())
    tokens = sum(p["tokens"] for t in tasks.values() for p in t["platforms"].values())
    measured_agents = sum(p["agents"] for t in tasks.values() for p in t["platforms"].values())
    decs = [d for d in decide.ledger(root)["decisions"] if d.get("feature") == feature]
    blocks = {}
    for e in events(root):
        if e.get("ev") == "blocked" and e.get("feature") == feature:
            blocks[e.get("reason") or "?"] = blocks.get(e.get("reason") or "?", 0) + 1
    done = [t for t in tasks.values() if t["passed"]]
    out = {"feature": feature, "t": util.now(), "ver": {**util.plugin_version(), "config": config.digest(config.load(root))},
           "screens": screens, "tree_nodes": tree_nodes, "tasks": tasks, "nodes": nodes,
           "first_try_pass_rate": (sum(1 for t in done if t["first_try"]) / len(done)) if done else None,
           "attempts_per_task": (sum(t["attempts"] for t in tasks.values()) / len(tasks)) if tasks else None,        # 스모크/과제
           "dispatches_per_task": (sum(t["dispatches"] for t in tasks.values()) / len(tasks)) if tasks else None,
           "build_ms": sum(p["build_ms"] for t in tasks.values() for p in t["platforms"].values()),
           "agent_ms": agent_ms if measured_agents else None, "tokens": tokens if measured_agents else None,
           "per_node": {"agent_ms": (agent_ms / tree_nodes) if (measured_agents and tree_nodes) else None,
                        "tokens": (tokens / tree_nodes) if (measured_agents and tree_nodes) else None},
           "blocks": blocks,
           "decisions": {"total": len(decs), "confirmed": sum(d["status"] == "confirmed" for d in decs),
                         "tentative": sum(d["status"] == "tentative" for d in decs), "flipped": sum(d["status"] == "flipped" for d in decs)},
           "unmeasured": {"agents": sum(1 for t in tasks.values() for p in t["platforms"].values() if not p["agents"]),
                          "builds": sum(1 for t in tasks.values() for p in t["platforms"].values() if not p["build_ms"])}}
    return leaks.mask_all_deep(out)


def write_feature_summary(root, feature):
    """`.twbuild/metrics/cycles/<기능>.json` — merge 가 쓰고 ledger 커밋에 넣는다. → 상대 경로."""
    rel = os.path.join(util.TW_DIR, util.METRICS_DIR, CYCLES_DIR, f"{feature}.json")
    util.write_json(os.path.join(root, rel), feature_summary(root, feature))
    return rel


HISTORY = ".history.json"
HARNESS_REASONS = ("harness fix needed", "lead fix needed", "worktree merge conflict", "secret in branch", "tree changed during build", "merge conflict")


def history(root, feature):
    return util.read_json(os.path.join(_dir(root), CYCLES_DIR, f"{feature}{HISTORY}"), []) or []


def close_cycle(root, feature, tasks=None, since=None):
    """사이클이 끝났다 — 이 사이클 과제(tasks)만의 숫자를 이력에 한 줄 보탠다(retro 가 이전 사이클과 비교한다). 같은 사이클을 두 번 닫지 않는다.
    tasks 가 없으면 기능 전체(누적) — 실측: 누적치가 사이클 회고로 보여 헷갈렸다."""
    s = feature_summary(root, feature, set(tasks) if tasks else None, since)
    hist = history(root, feature)
    snap = {"n": len(hist) + 1, "t": s["t"], "ver": s["ver"], "tasks": len(s["tasks"]), "task_ids": sorted(s["tasks"]), "tree_nodes": s["tree_nodes"],
            "first_try_pass_rate": s["first_try_pass_rate"], "attempts_per_task": s["attempts_per_task"], "dispatches_per_task": s.get("dispatches_per_task"),
            "build_ms": s["build_ms"], "agent_ms": s["agent_ms"], "tokens": s["tokens"], "per_node": s["per_node"], "blocks": s.get("blocks") or {},
            "violations": sorted({v for t in s["tasks"].values() for p in t["platforms"].values() for v in (p.get("violations") or [])}),
            "decisions": s["decisions"], "unmeasured": s["unmeasured"], "screens": s["screens"]}
    if hist and hist[-1].get("task_ids") == snap["task_ids"] and hist[-1].get("tokens") == snap["tokens"]:
        return hist[-1]
    hist.append(snap)
    util.write_json(os.path.join(_dir(root), CYCLES_DIR, f"{feature}{HISTORY}"), hist)
    return snap


def _delta(cur, prev, fmt, lower_is_better=True):
    if cur is None or prev is None:
        return fmt(cur) if cur is not None else "못 잼"
    arrow = "" if cur == prev else ("↓" if (cur < prev) == lower_is_better else "↑")
    return f"{fmt(cur)} (이전 {fmt(prev)} {arrow})".strip()


def retro_markdown(root, feature):
    """회고 보고서(한국어) — 이번 사이클 숫자 · 이전 사이클 대비 · 재작업 원인 · 멈춤 사유 · 제안. 자기신고 없이 기록만으로."""
    hist = history(root, feature)
    if not hist:
        return f"# {feature} — 회고\n\n이력이 없다."
    cur, prev = hist[-1], (hist[-2] if len(hist) > 1 else None)
    g = (lambda k: (prev or {}).get(k)) if prev else (lambda k: None)
    pn, ppn = cur.get("per_node") or {}, (prev or {}).get("per_node") or {}
    L = [f"# {feature} — 회고 (사이클 {cur['n']})", "",
         f"- 과제 {cur['tasks']}개({', '.join(cur.get('task_ids') or [])}) · 기능 트리 노드 {cur['tree_nodes']}개 · 플러그인 {cur['ver'].get('plugin')}@{cur['ver'].get('commit')}",
         f"- 첫 시도 통과율: {_delta(cur['first_try_pass_rate'], g('first_try_pass_rate'), _rate, lower_is_better=False)}",
         f"- 스모크/과제: {_delta(cur['attempts_per_task'], g('attempts_per_task'), lambda x: _num(x, '{:.1f}'))} · 배차/과제: {_delta(cur.get('dispatches_per_task'), g('dispatches_per_task'), lambda x: _num(x, '{:.1f}'))}",
         f"- 빌드 합: {_delta(cur['build_ms'], g('build_ms'), lambda x: _fmt_ms(x or None))} · 개발자/노드: {_delta(pn.get('agent_ms'), ppn.get('agent_ms'), _fmt_ms)} · 토큰/노드: {_delta(pn.get('tokens'), ppn.get('tokens'), _num)}",
         f"- 결정(기능 누적): {cur['decisions'].get('total', 0)}(확정 {cur['decisions'].get('confirmed', 0)} · 잠정 {cur['decisions'].get('tentative', 0)} · 뒤집힘/폐기 {cur['decisions'].get('flipped', 0)})",
         f"- 못 잼: 개발자 과제 {cur['unmeasured'].get('agents', 0)} · 빌드 {cur['unmeasured'].get('builds', 0)}"]
    if cur.get("violations"):
        L += ["", "## 재작업 원인 (규칙)", ""] + [f"- {v}" for v in cur["violations"]]
    if cur.get("blocks"):
        harness = sum(n for r, n in cur["blocks"].items() if r in HARNESS_REASONS)
        L += ["", "## 멈춤", ""] + [f"- {r}: {n}회" for r, n in sorted(cur["blocks"].items())] + [f"- 하네스 · lead 원인 {harness}회 / 전체 {sum(cur['blocks'].values())}회"]
    tips = []
    if (cur.get("first_try_pass_rate") or 0) < 0.5:
        tips.append("첫 시도 통과율이 절반 아래다 — 재작업 원인 규칙을 플레이북 · 번역표에 먼저 반영한다")
    if any(v in ("T6", "T7", "T10") for v in cur.get("violations") or []):
        tips.append("이름 · 타입 패리티 재작업이 있었다 — 데이터 · 컴포넌트 · UiState 이름 규약을 과제 프롬프트 맨 위에 올린다")
    if cur.get("blocks") and sum(n for r, n in cur["blocks"].items() if r in HARNESS_REASONS):
        tips.append("하네스 · lead 원인 멈춤이 있었다 — 그 run 의 리드 보고 '문제' 절을 고치고 테스트를 더한다")
    if (cur["unmeasured"].get("agents") or 0):
        tips.append("개발자 과제 시간 · 토큰을 못 잰 과제가 있다 — 플러그인 설치 세션(훅)에서 돌린다")
    if prev and pn.get("tokens") and ppn.get("tokens") and pn["tokens"] > ppn["tokens"] * 1.3:
        tips.append("노드당 토큰이 이전 사이클보다 30% 넘게 늘었다 — 과제 프롬프트 길이 · 재작업 횟수를 본다")
    L += ["", "## 제안", ""] + ([f"- {t}" for t in tips] or ["- 없음 — 같은 잣대로 다음 사이클을 비교한다"])
    return "\n".join(L) + "\n"


def summaries(root):
    d = os.path.join(_dir(root), CYCLES_DIR)
    out = []
    try:
        for n in sorted(os.listdir(d)):
            if n.endswith(".json") and not n.endswith(HISTORY):          # 이력(.history.json, 리스트)은 요약이 아니다 (실측: stats 가 죽었다)
                s = util.read_json(os.path.join(d, n), None)
                if isinstance(s, dict):
                    out.append(s)
    except OSError:
        pass
    return out


def _rate(x):
    return "못 잼" if x is None else f"{x * 100:.0f}%"


def _num(x, fmt="{:.0f}"):
    return "못 잼" if x is None else fmt.format(x)


def compare_table(root):
    """`twbuild stats --compare` — 기능(사이클)별 한 줄: 같은 잣대(노드당)로 비교한다."""
    ss = summaries(root)
    if not ss:
        return "기능별 요약이 없다 — 머지가 한 번 끝나면 .twbuild/metrics/cycles/ 에 쌓인다."
    lines = ["기능별 비교 (merge 요약 = 기능 누적 · 노드당 정규화; 사이클별은 stats --retro)",
             f"  {'기능':<12}{'화면':>4}{'노드':>5}{'첫시도 통과':>10}{'스모크/과제':>10}{'빌드 합':>9}{'개발자/노드':>11}{'토큰/노드':>10}  버전"]
    for s in ss:
        pn = s.get("per_node") or {}
        ver = s.get("ver") or {}
        lines.append(f"  {s['feature']:<12}{len(s.get('screens') or []):>4}{s.get('tree_nodes') or 0:>5}{_rate(s.get('first_try_pass_rate')):>10}"
                     f"{_num(s.get('attempts_per_task'), '{:.1f}'):>9}{_fmt_ms(s.get('build_ms') or None):>9}{_fmt_ms(pn.get('agent_ms')):>11}{_num(pn.get('tokens')):>10}"
                     f"  {ver.get('plugin', '?')}@{ver.get('commit', '?')}")
    return "\n".join(lines)


def feature_table(root, feature):
    """`twbuild stats --feature <기능>` — 그 기능의 요약을 표로."""
    s = next((x for x in summaries(root) if x.get("feature") == feature), None)
    if not s:
        return f"{feature}: 요약이 없다 (머지 전이거나 다른 기능 이름)."
    d = s.get("decisions") or {}
    lines = [f"{feature} — 화면 {len(s.get('screens') or [])}개 · 트리 노드 {s.get('tree_nodes')}개 · 첫 시도 통과 {_rate(s.get('first_try_pass_rate'))} · "
             f"결정 {d.get('total', 0)}(확정 {d.get('confirmed', 0)} · 잠정 {d.get('tentative', 0)}) · {s.get('ver', {}).get('plugin', '?')}@{s.get('ver', {}).get('commit', '?')}",
             f"  {'과제':<12}{'플랫폼':<9}{'배차':>4}{'스모크':>5}{'정적 실패':>8}{'빌드 실패':>8}{'빌드 합':>8}{'기기':>5}{'개발자 시간':>10}{'토큰':>9}  위반"]
    for tid, t in sorted((s.get("tasks") or {}).items()):
        for plat, p in sorted(t["platforms"].items()):
            lines.append(f"  {tid:<12}{plat:<9}{(p['agents'] or '-'):>4}{p['attempts']:>5}{p['static_fail']:>8}{p['build_fail']:>8}{_fmt_ms(p['build_ms'] or None):>8}{_mark(p.get('device')):>5}"
                         f"{_fmt_ms(p['ms'] if p['agents'] else None):>10}{(p['tokens'] or '-'):>9}  {','.join(p.get('violations') or []) or '-'}")
    u = s.get("unmeasured") or {}
    lines.append(f"  못 잼: 개발자 과제 {u.get('agents', 0)} · 빌드 {u.get('builds', 0)}")
    return "\n".join(lines)


def stats_table(root):
    """터미널 표 (한국어)."""
    s = summary(root)
    lines = []
    if not s["nodes"] and not s["tasks"]:
        return "측정 기록이 없다 — /twbuild 를 한 번 돌리면 쌓인다."
    lines.append("노드 실행 (결정적 코드)")
    lines.append(f"  {'그래프':<8}{'노드':<14}{'횟수':>5}{'합계':>10}{'평균':>10}{'오류':>5}")
    for (g, n), v in sorted(s["nodes"].items()):
        lines.append(f"  {g:<8}{n:<14}{v['count']:>5}{_fmt_ms(v['ms']):>10}{_fmt_ms(v['ms'] / v['count']):>10}{v['errors']:>5}")
    if s["tasks"]:
        lines.append("")
        lines.append("과제 처리 (발행 → submit)")
        lines.append(f"  {'그래프':<8}{'과제':<14}{'횟수':>5}{'합계':>10}{'평균':>10}")
        for (g, t), v in sorted(s["tasks"].items()):
            measured = v["count"] - v["unmeasured"]
            avg = v["ms"] / measured if measured else None
            lines.append(f"  {g:<8}{t:<14}{v['count']:>5}{_fmt_ms(v['ms'] if measured else None):>10}{_fmt_ms(avg):>10}")
    sc = screens_table(root)
    if sc:
        lines.append(sc)
    return "\n".join(lines)
