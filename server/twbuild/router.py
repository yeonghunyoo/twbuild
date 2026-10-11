"""라우터 — `/twbuild` 의 유일한 진입. advance() 앞단에서 셋업 thread 와 사이클 thread 를 고른다 (AGENT.md 4장).

  멈춰 있는 과제가 있는 thread → 그 thread
  사이클이 진행 중(기능이 있고 done 이 아님) → 사이클 (설정 변경은 다음 사이클 전에 적용)
  미배선 · 미준비 · 설정 변경 → 셋업
  준비됨 → 사이클
저장 상태보다 실측이 이긴다 — 매 진입마다 probe.ready() 를 다시 잰다. 측정(과제 발행 · submit)은 여기서 기록한다.
"""
from . import design, graph, metrics, probe, util

GRAPHS = ("cycle", "setup")


def _cycle_active(root):
    v = graph.values(root, "cycle")
    return bool(v.get("feature")) and v.get("phase") not in (None, "done", "intake")


def status(root):
    """현재 상태 한 눈에 — 배선 · 준비 · 멈춤 · 설정 변경 · 원장 요약."""
    wired = util.is_wired(root)
    ok, reasons = probe.ready(root) if wired else (False, ["미배선"])
    pend = {w: graph.pending(root, w) for w in GRAPHS} if wired else {}
    pend = {w: p for w, p in pend.items() if p}
    cyc = graph.values(root, "cycle") if wired else {}
    out = {"ok": True, "wired": wired, "ready": ok, "reasons": reasons, "pending": pend, "version": util.plugin_version(),
           "cycle": {k: cyc.get(k) for k in ("phase", "feature", "screens", "cursor", "attempts")} if cyc else None,
           "design": design.summary(root) if wired else None}
    out["message"] = _status_message(out)
    return out


def _status_message(st):
    if st["pending"]:
        w, p = next(iter(st["pending"].items()))
        if p.get("kind") == "blocked":
            return f"The {w} graph is blocked: {p.get('reason')}. Show the user what to do; call submit({{}}) once resolved."
        return f"A {w} task is waiting: `{p.get('task')}`. Call advance to get it again, then submit(payload)."
    if not st["wired"]:
        return "Repo is not wired. Call advance — the setup graph will probe, wire and interview."
    if st["cycle"] and st["cycle"].get("phase") not in (None, "done"):
        return f"Cycle for `{st['cycle'].get('feature')}` is in progress (phase {st['cycle'].get('phase')}). Call advance."
    if st["ready"]:
        return "Ready. Call advance to start (or continue) a feature cycle."
    return "Not ready: " + " · ".join(st["reasons"]) + ". Call advance — the setup graph re-runs what changed."


def _route(root):
    if not util.is_wired(root):
        return "setup"
    for w in GRAPHS:
        if graph.pending(root, w):
            return w
    if _cycle_active(root):
        return "cycle"
    ok, _ = probe.ready(root)
    return "setup" if not ok else "cycle"


def _task_out(root, which, p, values):
    step = graph.step_of(root, which)
    if p.get("kind") == "blocked":
        return {"ok": True, "graph": which, "pending": p, "step": step,
                "message": (f"BLOCKED ({which}): {p.get('reason')} — {p.get('detail')}\n"
                            "Tell the user (Korean) what blocks and what to do. After they resolve it, call submit({}) to retry.")}
    metrics.task_issued(root, which, p.get("task"), step)
    return {"ok": True, "graph": which, "pending": p, "step": step,
            "message": (f"Task `{p.get('task')}` ({which} graph): {p.get('message')}\n"
                        f"Submit with submit(payload). Payload shape: {p.get('submit')}")}


def _done_out(root, which, values):
    out = {"ok": True, "graph": which, "pending": None}
    if which == "setup":
        out["report"] = values.get("report") or ""
        ok, reasons = probe.ready(root)
        out["ready"] = ok
        out["message"] = ("Setup graph finished. Show `report` to the user verbatim (it is Korean markdown). "
                          + ("Then call advance again to start the first feature cycle." if ok
                             else "Not ready yet — the report lists what the user must do: " + " · ".join(reasons)))
    else:
        reps = values.get("reports") or []
        out["report"] = f"# {values.get('feature')} — 사이클 완료\n\n" + "\n".join(reps) if reps else ""
        out["message"] = ("Cycle finished: all planned screens merged. Show `report` to the user verbatim (Korean). "
                          "Call advance to start the next feature.")
    return out


def advance(root):
    """그래프를 다음 멈춤까지 돌린다 — 라우터가 thread 를 고른다."""
    which = _route(root)
    p, values = graph.run(root, which)
    if p:
        return _task_out(root, which, p, values)
    return _done_out(root, which, values)


def submit(root, payload):
    """멈춰 있는 과제를 payload 로 재개한다."""
    for which in GRAPHS:
        p = graph.pending(root, which)
        if not p:
            continue
        if not isinstance(payload, dict):
            return {"ok": False, "message": "payload must be an object — see the task's `submit` shape."}
        if p.get("kind") == "task":
            metrics.task_done(root, which, p.get("task"), graph.step_of(root, which))
        nxt, values = graph.run(root, which, resume=payload)
        if nxt:
            return _task_out(root, which, nxt, values)
        return _done_out(root, which, values)
    return {"ok": False, "message": "No task is waiting. Call advance first."}
