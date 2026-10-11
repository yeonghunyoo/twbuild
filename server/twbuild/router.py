"""라우터 — `/twbuild` 의 유일한 진입. advance() 앞단에서 셋업 thread 와 사이클 thread 를 고른다 (AGENT.md 4장).

  멈춰 있는 셋업 과제 · 미배선 · 미준비 · 설정 변경 → 셋업
  준비됨 → 사이클 (뒤 단계)
저장 상태보다 실측이 이긴다 — 매 진입마다 probe.ready() 를 다시 잰다. 측정(과제 발행 · submit)은 여기서 기록한다.
"""
from . import graph, metrics, probe, util


def status(root):
    """현재 상태 한 눈에 — 배선 · 준비 · 멈춤 · 설정 변경."""
    wired = util.is_wired(root)
    ok, reasons = probe.ready(root) if wired else (False, ["미배선"])
    pend = graph.pending(root, "setup") if wired else None
    return {"ok": True, "wired": wired, "ready": ok, "reasons": reasons, "pending": pend,
            "version": util.plugin_version(),
            "message": _status_message(wired, ok, reasons, pend)}


def _status_message(wired, ok, reasons, pend):
    if pend:
        return f"A setup task is waiting: `{pend.get('task')}`. Call advance to get it again, then submit(payload)."
    if not wired:
        return "Repo is not wired. Call advance — the setup graph will probe, wire and interview."
    if ok:
        return "Ready for the cycle graph. Call advance."
    return "Not ready: " + " · ".join(reasons) + ". Call advance — the setup graph re-runs what changed."


def _route(root):
    if not util.is_wired(root):
        return "setup"
    if graph.pending(root, "setup"):
        return "setup"
    ok, _ = probe.ready(root)
    return "setup" if not ok else "cycle"


def _task_out(root, which, p, values):
    step = graph.step_of(root, which)
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
    return out


def advance(root):
    """그래프를 다음 멈춤까지 돌린다 — 라우터가 thread 를 고른다."""
    which = _route(root)
    if which == "cycle":
        return {"ok": True, "graph": "cycle", "pending": None, "ready": True,
                "message": ("Setup is complete and the repo is ready. The cycle graph (intake → plan → build → smoke → merge) "
                            "is not implemented in this plugin version yet — tell the user setup is done and stop.")}
    p, values = graph.run(root, "setup")
    if p:
        return _task_out(root, which, p, values)
    return _done_out(root, which, values)


def submit(root, payload):
    """멈춰 있는 과제를 payload 로 재개한다."""
    for which in ("setup",):
        p = graph.pending(root, which)
        if not p:
            continue
        if not isinstance(payload, dict):
            return {"ok": False, "message": "payload must be an object — see the task's `submit` shape."}
        metrics.task_done(root, which, p.get("task"), graph.step_of(root, which))
        nxt, values = graph.run(root, which, resume=payload)
        if nxt:
            return _task_out(root, which, nxt, values)
        return _done_out(root, which, values)
    return {"ok": False, "message": "No task is waiting. Call advance first."}
