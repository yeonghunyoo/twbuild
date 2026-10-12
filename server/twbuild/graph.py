"""그래프 — LangGraph 상태기계 둘. 셋업(레포마다) · 사이클(기능마다). langgraph 를 import 하는 유일한 파일.

  셋업:  START → probe → wire → interview ⇄ (남은 질문이 있으면 다시) → scaffold → selfcheck → report → END
  사이클: 뒤 단계(M3)에서 붙는다.

멈춤은 두 종류다 — task(LLM 과제 → submit 으로 재개) · blocked(사람 할 일 · 예산 소진 → 사람이 풀면 재개).
한 노드 안에 부작용 뒤 interrupt 를 두지 않는다 — 재개 시 노드가 처음부터 다시 실행된다. 묻는 노드(interview)는 interrupt 만 한다.
측정은 노드 안이 아니라 run() 래퍼가 debug 스트림에서 잰다 (AGENT.md 13장).
"""
import contextlib
import datetime
import operator
import os
from typing import Annotated, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import metrics, probe, setup, util

THREADS = {"setup": "setup", "cycle": "cycle"}
RECURSION = 40
ANSWER_KEYS = setup.QUESTIONS + ("ascii_name",)


def _cfg(which):
    return {"configurable": {"thread_id": THREADS[which]}, "recursion_limit": RECURSION}


# ─────────────────────────── 셋업 그래프 ───────────────────────────

class SetupState(TypedDict, total=False):
    root: str
    probe: dict
    wired: list
    answers: dict
    scaffold: dict
    selfcheck: dict
    report: str
    log: Annotated[list, operator.add]


def _task(name, message, submit_shape, **fields):
    """LLM 과제 — 응답에 무엇을 submit 해야 하는지가 적힌다. 에이전트가 읽으므로 영어."""
    return interrupt({"kind": "task", "graph": "setup", "task": name, "message": message, "submit": submit_shape, **fields})


QUESTION_TEXT = {
    "topic": {"ask": "앱 주제 — 어떤 앱인가요? 한 문장으로.", "hint": "Free text. No default."},
    "name": {"ask": "앱 이름 — 스토어와 홈 화면에 보일 이름.", "hint": "Offer the default (repo folder name) as the recommended option; free text allowed."},
    "requirements": {"ask": "요구사항 — 꼭 들어가야 할 기능 · 제약 · 참고할 것 (여러 줄 가능).", "hint": "Free text, multi-line. No default."},
    "ascii_name": {"ask": "영문 이름 — 식별자(com.example.<slug>)와 모듈 이름에 쓸 ASCII 이름.", "hint": "Asked only when the app name has no ASCII letters. Offer a transliteration as the recommended option."},
}


def n_probe(s):
    return {"probe": probe.probe(s["root"]), "log": ["probe"]}


def n_wire(s):
    return {"wired": setup.wire(s["root"], s.get("probe") or {}), "log": ["wire"]}


def n_interview(s):
    """묻는 노드 — 부작용 없이 interrupt 만. 남은 질문이 없으면 그냥 지나간다."""
    root = s["root"]
    rest = setup.remaining(root, s.get("answers"))
    if not rest:
        return {"log": ["interview:skip"]}
    d = setup.defaults(root)
    questions = [{"id": q, **QUESTION_TEXT[q], "default": d["name"] if q == "name" else None} for q in rest]
    payload = _task(
        "interview",
        "Ask the user the remaining setup questions with the AskUserQuestion tool, in Korean, all in one call when possible "
        "(options + free text; put the default first as '(추천)'). Do not ask anything else — platforms, login, architecture "
        "and smoke settings are decided from probing and defaults and shown in the final report. "
        "Then submit the answers. Partial answers are fine: the task comes back with what is still missing.",
        {q: "string" for q in rest},
        questions=questions, defaults=d,
    )
    answers = dict(s.get("answers") or {})
    if isinstance(payload, dict):
        for k in ANSWER_KEYS:
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                answers[k] = v.strip()
    return {"answers": answers, "log": ["interview"]}


def _after_interview(s):
    return "interview" if setup.remaining(s["root"], s.get("answers")) else "scaffold"


def n_scaffold(s):
    return {"scaffold": setup.scaffold(s["root"], s.get("answers")), "log": ["scaffold"]}


def n_selfcheck(s):
    return {"selfcheck": setup.selfcheck(s["root"]), "log": ["selfcheck"]}


def n_report(s):
    root = s["root"]
    setup.mark_applied(root)
    pr = probe.probe(root)          # scaffold 뒤 다시 실측 — 보고서는 지금 상태를 보인다
    return {"probe": pr, "report": setup.report(root, pr, s.get("selfcheck") or {}, s.get("scaffold")), "log": ["report"]}


def build_setup():
    g = StateGraph(SetupState)
    for name, fn in (("probe", n_probe), ("wire", n_wire), ("interview", n_interview),
                     ("scaffold", n_scaffold), ("selfcheck", n_selfcheck), ("report", n_report)):
        g.add_node(name, fn)
    g.add_edge(START, "probe")
    g.add_edge("probe", "wire")
    g.add_edge("wire", "interview")
    g.add_conditional_edges("interview", _after_interview, {"interview": "interview", "scaffold": "scaffold"})
    g.add_edge("scaffold", "selfcheck")
    g.add_edge("selfcheck", "report")
    g.add_edge("report", END)
    return g


def build_cycle():
    from . import cycle
    return cycle.build_cycle()


BUILDERS = {"setup": build_setup, "cycle": build_cycle}


def values(root, which):
    """thread 의 저장 상태 (없으면 {})."""
    if not os.path.isfile(util.tw(root, util.GRAPH_DB)):
        return {}
    with _app(root, which) as app:
        return app.get_state(_cfg(which)).values or {}


# ─────────────────────────── 구동 ───────────────────────────

@contextlib.contextmanager
def _app(root, which):
    os.makedirs(util.tw(root), exist_ok=True)
    with SqliteSaver.from_conn_string(util.tw(root, util.GRAPH_DB)) as cp:
        yield BUILDERS[which]().compile(checkpointer=cp)


def _pending(app, cfg):
    st = app.get_state(cfg)
    for t in st.tasks:
        for i in t.interrupts:
            return i.value
    return None


def pending(root, which):
    """지금 멈춰 있는 과제 — {"kind": "task", ...} 또는 None."""
    if which not in BUILDERS or not os.path.isfile(util.tw(root, util.GRAPH_DB)):
        return None
    with _app(root, which) as app:
        return _pending(app, _cfg(which))


def _ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def _stream(root, which, app, cfg, inp, feature=None):
    """debug 스트림으로 돌리며 노드 실행 시간을 잰다 — interrupt 없이 끝난 실행만 기록 (재개 때 다시 돈 노드는 그 완료분만 한 번).
    사이클 기록에는 기능을 붙인다(노드 결과의 feature 가 우선 — intake 가 새 기능을 정한 직후)."""
    started = {}
    for ev in app.stream(inp, cfg, stream_mode="debug"):
        p = ev.get("payload") or {}
        if ev.get("type") == "task":
            started[p.get("id")] = (p.get("name"), ev.get("step"), _ts(ev.get("timestamp")))
        elif ev.get("type") == "task_result":
            name, step, t0 = started.pop(p.get("id"), (p.get("name"), ev.get("step"), None))
            t1 = _ts(ev.get("timestamp"))
            if p.get("interrupts"):
                continue
            ms = (t1 - t0) * 1000 if (t0 and t1) else 0.0
            result = p.get("result")
            feat = ((result.get("feature") if isinstance(result, dict) else None) or feature) if which == "cycle" else None
            metrics.node_done(root, which, name, step, ms, error=p.get("error"), feature=feat)
            _node_metrics(root, which, name, step, result, feat)


def _node_metrics(root, which, name, step, result, feature=None):
    """노드 결과에서 지표를 뽑는다 — 노드 안이 아니라 구동 래퍼에서 (재개 중복 없음). smoke 의 시도 · 층별 결과 · 빌드 시간, merge 의 화면 완료."""
    if which != "cycle" or not isinstance(result, dict):
        return
    if name == "smoke":
        tid = result.get("smoked")
        res_all = result.get("results") or {}
        for tid, res in ([(tid, res_all.get(tid))] if tid else res_all.items()):      # 이번에 잰 과제만 — results 는 누적이다
            for plat, r in (res or {}).items():
                if not isinstance(r, dict):
                    continue
                metrics.record(root, "smoke", key=f"smoke:{tid}:{plat}:{step}", task=tid, platform=plat, step=step, feature=feature,
                               static=(r.get("static") or {}).get("status"), build=(r.get("build") or {}).get("status"), build_ms=(r.get("build") or {}).get("ms"),
                               violations=[v["rule"] for v in (r.get("static") or {}).get("violations") or []], passed=result.get("phase") == "merge")
    elif name == "merge" and result.get("phase") in ("build", "done"):
        metrics.record(root, "merged", key=f"merged:{step}", step=step, cursor=result.get("cursor"), feature=feature)


def run(root, which, resume=None):
    """그래프를 다음 멈춤(또는 끝)까지 돌린다. → (pending, values).

    멈춰 있고 resume 이 없으면 돌리지 않고 과제를 그대로 돌려준다. resume 이 있으면 그 값으로 재개한다.
    멈춰 있지 않으면 처음부터(또는 끝난 thread 면 새 실행으로) 돈다.
    """
    cfg = _cfg(which)
    with _app(root, which) as app:
        p = _pending(app, cfg)
        if p and resume is None:
            return p, app.get_state(cfg).values
        feature = (app.get_state(cfg).values or {}).get("feature") if which == "cycle" else None
        if p:
            # 빈 객체("그대로 진행")도 재개 값이어야 한다 — LangGraph 는 falsy 재개 값을 "재개 없음" 으로 본다
            _stream(root, which, app, cfg, Command(resume=resume if resume else {"ok": True}), feature)
        else:
            _stream(root, which, app, cfg, {"root": root, "log": []}, feature)
        return _pending(app, cfg), app.get_state(cfg).values


def step_of(root, which):
    """지금 멈춘 과제의 step 번호 — 측정 key 에 쓴다."""
    with _app(root, which) as app:
        st = app.get_state(_cfg(which))
        return (st.metadata or {}).get("step")
