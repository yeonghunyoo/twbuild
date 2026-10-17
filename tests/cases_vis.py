"""시각 비교(vis.py) · 시각 층(cycle.visual_layer · n_visual) — 디자인 탐색 입력 · 로직 훅 · 기준 이미지 신선도 · lead 판정 → 재작업 · 캔버스 점수."""
import os
import shutil
import struct
import zlib

from cases import _wired_repo, case, check

from twbuild import config, cycle, tour, util, vis


def _png(path, w, h, rgb):
    """단색 PNG — Pillow 없이."""
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _n(nid, kind="box", children=None, **kw):
    return {"id": nid, "kind": kind, "children": children or [], **kw}


LAYS = {
    "home": {"kind": "state", "when": ["isHome"], "style": [], "hash": "h1", "source": "design/mini/mini.dc.html", "root": _n("n.home", "column", [
        _n("n.home.gear", on_click="openSettings"),
        _n("n.home.list", "list", [_n("n.home.list.card", "row", on_click="p.open")], items="favPresets", **{"as": "p"})])},
    "settings": {"kind": "overlay", "when": [], "style": ["settingsBackdropStyle", "settingsSheetStyle"], "hash": "s1", "source": "design/mini/mini.dc.html",
                 "root": _n("n.settings", "column", [_n("n.settings.handle", on_click="closeSettings"), _n("n.settings.gear", on_click="openSettings")])},
}


def _repo():
    root = _wired_repo()
    for s, lay in LAYS.items():
        util.write_json(os.path.join(root, util.DESIGN_DIR, "mini", "layout", f"{s}.json"), {"screen": s, **lay})
    idx = util.read_json(os.path.join(root, util.DESIGN_DIR, "index.json"), {}) or {}
    idx.setdefault("screens", {}).update({"mini/home": {"status": "consumed"}, "mini/settings": {"status": "building"}})
    util.write_json(os.path.join(root, util.DESIGN_DIR, "index.json"), idx)
    return root


@case
def vis_design_spec_and_reference():
    root = _repo()
    try:
        lays = vis._design_layouts(root, "mini")
        spec = vis._spec(lays)
        check([s["id"] for s in spec["screens"]] == ["home", "settings"] and spec["screens"][1]["style"][-1] == "settingsSheetStyle", spec["screens"])
        by = {h["expr"]: h for h in spec["handlers"]}
        check(by["p.open"]["scope"] == {"p": "favPresets"} and by["openSettings"]["scope"] == {}, by)
        check(by["openSettings"]["screens"] == ["home", "settings"] and by["closeSettings"]["screens"] == ["settings"], "핸들러는 자기 화면이 보일 때만 — 화면 목록")
        html = '<script type="text/x-dc">\nclass Component extends DCLogic {\n  state = {};\n}\n</script>'
        check(vis.HOOK in vis._patch(html) and vis._patch(html).index(vis.HOOK) > html.index("DCLogic {"), "로직 훅")
        try:
            vis._patch("<div></div>")
            check(False, "로직 클래스가 없으면 실패")
        except vis.VisError:
            pass
        # 기준 이미지 — 찍을 때의 트리 해시와 지금 해시가 같을 때만 쓴다
        d = vis.shots_dir(root, "mini")
        _png(os.path.join(d, "home.png"), 4, 4, (10, 20, 30))
        util.write_json(os.path.join(d, "_shots.json"), {"hashes": {"home": "h1"}})
        check(vis.reference(root, "home") == os.path.join(d, "home.png") and vis.reference(root, "settings") is None, "기준 이미지")
        lay = util.read_json(os.path.join(root, util.DESIGN_DIR, "mini", "layout", "home.json"))
        util.write_json(os.path.join(root, util.DESIGN_DIR, "mini", "layout", "home.json"), {**lay, "hash": "h2"})
        check(vis.reference(root, "home") is None, "디자인이 바뀌면 낡은 그림으로 판정하지 않는다")
    finally:
        shutil.rmtree(root, ignore_errors=True)


@case
def visual_layer_lead_review():
    """스모크를 통과한 화면 과제 → 두 플랫폼을 그 화면까지 돌아 찍고 비교 이미지 → lead 판정: rework 는 메모 · 그림이 재작업 프롬프트로, accept 는 머지."""
    root = _repo()
    saved = (tour.run_focus, vis.chrome, vis.compare)
    try:
        cfg = config.load(root)
        ref = _png(os.path.join(vis.shots_dir(root, "mini"), "settings.png"), 4, 4, (1, 2, 3))
        util.write_json(os.path.join(vis.shots_dir(root, "mini"), "_shots.json"), {"hashes": {"settings": "s1"}})
        task = {"kind": "screen", "id": "settings"}
        wts = {"ios": os.path.join(root, "wt-ios"), "android": os.path.join(root, "wt-android")}
        ran = []

        def fake_focus(r, wt, p, vars_, screen, out_dir, cfg=None, tools=None):
            ran.append((p, screen))
            return {"status": "pass", "detail": "ok", "screens": {screen: f"/x/{screen}-{p}.png"}, "failures": [], "shot": f"/x/{screen}-{p}.png"}
        tour.run_focus = fake_focus
        vis.chrome = lambda: "/bin/chrome"
        vis.compare = lambda design_png, shots, out, title="", b=None: {"ios": {"score": 0.02, "hot": 0.01}, "android": {"score": 0.3, "hot": 0.5}}
        res = {p: {} for p in wts}
        cycle.visual_layer(root, "mini", task, wts, res, cfg)
        check(sorted(ran) == [("android", "settings"), ("ios", "settings")], ran)
        check(all(res[p]["visual"]["status"] == "review" and res[p]["visual"]["image"].endswith("settings-compare.png") and res[p]["visual"]["design"] == ref for p in res), res)
        check(res["android"]["visual"]["score"] == 0.3, res["android"])
        # lead 판정 — iOS accept, Android rework
        s = {"root": root, "feature": "mini", "order": [task], "cursor": 0, "attempts": {"settings": 1}, "results": {"settings": res}}
        asked = {}

        def fake_task(name, message, submit_shape, **fields):
            asked.update(name=name, fields=fields, submit=submit_shape)
            return asked.get("answer")
        saved_task = cycle._task
        cycle._task = fake_task
        try:
            asked["answer"] = {"ios": {"verdict": "accept"}, "android": {"verdict": "rework", "notes": "settings sheet must be opaque (design: solid surface; device: translucent)"}}
            out = cycle.n_visual(s)
            check(asked["name"] == "visual" and asked["fields"]["image"].endswith("settings-compare.png") and set(asked["submit"]) == {"ios", "android"}, asked)
            check(out["phase"] == "rework" and out["smoked"] == "settings", out)
            r = out["results"]["settings"]
            check(r["ios"]["visual"]["status"] == "pass" and r["android"]["visual"]["status"] == "fail", r)
            txt = cycle._rework_text(out, "settings", "android")
            check("visual check failed" in txt and "opaque" in txt and "settings-compare.png" in txt, txt)
            check(cycle._rework_text(out, "settings", "ios") == "", "통과한 플랫폼엔 시각 메모가 없다")
            check(cycle._after_visual(out) == "prepare", "재작업")
            asked["answer"] = {"ios": {"verdict": "accept"}, "android": {"verdict": "accept"}}
            out = cycle.n_visual(s)
            check(out["phase"] == "merge" and cycle._after_visual(out) == "merge", out)
            asked["answer"] = {"ios": {"verdict": "accept"}, "android": {"verdict": "rework", "notes": "x"}}
            out = cycle.n_visual({**s, "attempts": {"settings": int(cfg["budget"]["attempts_per_screen"])}})
            check(out["phase"] == "blocked" and out["blocked"]["reason"] == "budget exhausted", out)
        finally:
            cycle._task = saved_task
        # 기준 이미지가 없으면 · 설정 off 면 · 화면 과제가 아니면 못 잼 (머지를 막지 않는다)
        res = {p: {} for p in wts}
        cycle.visual_layer(root, "mini", {"kind": "screen", "id": "home"}, wts, res, cfg)
        check(all(res[p]["visual"]["status"] == "unmeasured" and "기준 이미지" in res[p]["visual"]["detail"] for p in res), res)
        res = {p: {} for p in wts}
        cycle.visual_layer(root, "mini", {"kind": "data", "id": "data"}, wts, res, cfg)
        check(all(res[p]["visual"]["status"] == "unmeasured" for p in res), res)
        res = {p: {} for p in wts}
        cycle.visual_layer(root, "mini", task, wts, res, {**cfg, "smoke": {**cfg["smoke"], "visual": "off"}})
        check(all("off" in res[p]["visual"]["detail"] for p in res), res)
    finally:
        tour.run_focus, vis.chrome, vis.compare = saved
        shutil.rmtree(root, ignore_errors=True)


@case
def vis_compare_scores():
    """캔버스 점수 — 같은 그림은 0, 색이 다르면 크다 (Chrome 이 있을 때만)."""
    if not vis.chrome() or os.environ.get("TWBUILD_NO_BROWSER"):
        return
    root = _wired_repo()
    d = util.tw(root, "tmp", "vis")
    try:
        a = _png(os.path.join(d, "a.png"), 402, 874, (40, 36, 32))
        b = _png(os.path.join(d, "b.png"), 402, 874, (40, 36, 32))
        c = _png(os.path.join(d, "c.png"), 402, 874, (160, 160, 160))
        scores = vis.compare(a, [("same", b), ("gray", c)], os.path.join(d, "cmp.png"), title="t")
        check(scores["same"]["score"] == 0 and scores["same"]["hot"] == 0, scores)
        check(scores["gray"]["score"] > 0.3 and scores["gray"]["hot"] == 1, scores)
        check(os.path.getsize(os.path.join(d, "cmp.png")) > 1000, "비교 이미지")
    finally:
        shutil.rmtree(root, ignore_errors=True)
