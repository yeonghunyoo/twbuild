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


def node_done(root, graph, node, step, ms, error=None):
    """노드 실행 — interrupt 없이 끝난 실행만 (graph.run 이 debug 스트림에서 잰다)."""
    return record(root, "node", key=f"{graph}:{node}:{step}", graph=graph, node=node, step=step, ms=round(ms, 1),
                  **({"error": str(error)[:200]} if error else {}))


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


def screens_table(root):
    """화면(과제)별 — 시도 · 정적/빌드 결과 · 개발자 과제 시간 · 토큰 (smoke · agent 이벤트에서)."""
    rows = {}
    for e in events(root):
        if e.get("ev") == "smoke":
            r = rows.setdefault((e.get("task"), e.get("platform")), {"attempts": 0, "static_fail": 0, "build_fail": 0, "violations": [], "passed": False, "ms": 0.0, "tokens": 0, "agents": 0})
            r["attempts"] += 1
            r["static_fail"] += 1 if e.get("static") == "fail" else 0
            r["build_fail"] += 1 if e.get("build") == "fail" else 0
            r["violations"] += e.get("violations") or []
            r["passed"] = r["passed"] or bool(e.get("passed"))
        elif e.get("ev") == "agent":
            r = rows.setdefault((e.get("task"), e.get("platform")), {"attempts": 0, "static_fail": 0, "build_fail": 0, "violations": [], "passed": False, "ms": 0.0, "tokens": 0, "agents": 0})
            r["agents"] += 1
            r["ms"] += e.get("ms") or 0
            u = e.get("usage") or {}
            r["tokens"] += int(u.get("input") or 0) + int(u.get("output") or 0)
    if not rows:
        return ""
    lines = ["", "화면 · 플랫폼 (smoke · 개발자 과제)",
             f"  {'과제':<12}{'플랫폼':<9}{'시도':>4}{'정적 실패':>8}{'빌드 실패':>8}{'통과':>5}{'개발자 시간':>10}{'토큰':>9}  위반"]
    for (task, plat), r in sorted(rows.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        viol = ",".join(sorted(set(r["violations"]))) or "-"
        lines.append(f"  {str(task):<12}{str(plat):<9}{r['attempts']:>4}{r['static_fail']:>8}{r['build_fail']:>8}{'✅' if r['passed'] else '—':>5}"
                     f"{_fmt_ms(r['ms'] if r['agents'] else None):>10}{(r['tokens'] or '-'):>9}  {viol}")
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
