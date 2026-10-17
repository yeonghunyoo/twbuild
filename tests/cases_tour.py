"""화면 순회 — 트리 · 플랜 → 한 번 실행으로 도는 걷기(깊이 우선, 닫기 · 탭 · 뒤로) · 생성물 · 골격 환경 (tour.py)."""
import os
import shutil

from cases import _wired_repo, case, check

from twbuild import config, tour, util


def _n(nid, kind="box", children=None, **kw):
    return {"id": nid, "kind": kind, "children": children or [], **kw}


LAYS = {
    "shell": {"kind": "shell", "root": _n("n.shell", "column", [
        _n("n.shell.slot0", "screen", ref="home"), _n("n.shell.slot1", "screen", ref="sound"),
        _n("n.shell.tab0", "group", on_click="setTabHome"), _n("n.shell.tab1", "group", on_click="setTabSound")])},
    "home": {"kind": "state", "root": _n("n.home", "column", [
        _n("n.home.gear", on_click="openSettings"),
        _n("n.home.list", "list", [_n("n.home.list.card", "row", on_click="p.open")], items="favorites", **{"as": "p"}),
        _n("n.home.list2", "list", [_n("n.home.list2.card", "row", on_click="p.open")], items="favorites", **{"as": "p"})])},
    "onboarding": {"kind": "state", "root": _n("n.onboarding", "column", [_n("n.onboarding.skip", "text", on_click="skipOnboarding")])},
    "settings": {"kind": "overlay", "root": _n("n.settings", "column", [
        _n("n.settings.box0", on_click="closeSettings"),                       # 시트 뒤 배경막 — 누르면 시트가 받는다
        _n("n.settings.sheet", "group", [_n("n.settings.sheet.handle", "grid", on_click="closeSettings")])])},
    "player": {"kind": "overlay", "root": _n("n.player", "column", [_n("n.player.pause", "grid", on_click="togglePlay")])},
    "sound": {"kind": "state", "root": _n("n.sound", "column", [])},
    "extra": {"kind": "state", "root": _n("n.extra", "column", [])},     # 아직 머지 안 된 화면 — 순회에서 빠진다
}


def _repo():
    root = _wired_repo()
    for s, lay in LAYS.items():
        util.write_json(os.path.join(root, util.DESIGN_DIR, "mini", "layout", f"{s}.json"), {"screen": s, **lay})
    util.write_text(os.path.join(root, util.TW_DIR, "plans", "mini", "home.yaml"),
                    "interactions:\n  - \"HOME-1: favoritesOpen -> Route.player(presetId)\"\n")
    idx = util.read_json(os.path.join(root, util.DESIGN_DIR, "index.json"), {}) or {}
    idx.setdefault("screens", {}).update({f"mini/{s}": {"status": "consumed" if s != "extra" else "drafted"} for s in LAYS})
    util.write_json(os.path.join(root, util.DESIGN_DIR, "index.json"), idx)
    return root


@case
def tour_walk_one_launch():
    root = _repo()
    try:
        t = tour.plan_tour(root, tour._built(root))
        check(t["entry"] == {"screen": "onboarding", "skip": "n.onboarding.skip"}, t["entry"])
        check(t["start"] == "home" and t["hosts"] == ["shell"], (t["start"], t["hosts"]))
        check(t["close"]["settings"] == "n.settings.sheet.handle", t["close"])          # 배경막 box 는 뒤로 미룬다
        check(t["reached"]["player"]["ids"] == ["n.home.list.card", "n.home.list2.card"], t["reached"]["player"])   # 같은 핸들러 노드는 후보로 다
        check("extra" not in t["reached"] and not t["unreached"], t)
        ops = tour.walk(t)
        shots = [o[1] for o in ops if o[0] == "shot"]
        check(shots == ["onboarding", "home", "settings", "player", "sound"], shots)
        check(ops[:3] == [("shot", "onboarding"), ("tap", ["n.onboarding.skip"], "first-run gate: onboarding"), ("gone", "onboarding")], ops[:3])
        i = ops.index(("shot", "settings"))
        check(ops[i + 1:i + 4] == [("tap", ["n.settings.sheet.handle"], "close settings"), ("gone", "settings"), ("expect", "home")], ops[i:i + 4])
        j = ops.index(("shot", "player"))
        check(ops[j + 1][0] == "back" and ops[j + 1][1] == "home" and ops[j + 2] == ("expect", "home"), ops[j:j + 3])   # 닫는 노드가 없다
        check(ops[-2:] == [("tap", ["n.shell.tab1"], "setTabSound"), ("shot", "sound")], ops[-2:])                       # 마지막 뒤로가기는 없다
        cfg = config.load(root)
        files = tour.expected(root, cfg)
        sw = next(v for k, v in files.items() if k.endswith(".swift"))
        kt = next(v for k, v in files.items() if k.endswith(".kt"))
        check("final class TwScreenTour" in sw and sw.count("t.shot(") == 5 and "t.relaunch()" in sw, sw)
        check("class TwScreenTour" in kt and kt.count("t.shot(") == 5 and "t.back()" in kt and f"package {config.app_vars(cfg)['id']}" in kt, kt)
        # 골격이 환경을 깐다 — 지원 파일 · UI 테스트 타깃 · androidTest 의존성
        v = config.app_vars(cfg)
        check(os.path.isfile(os.path.join(root, "apps", "ios", "UITests", "TwTour.swift")), "iOS 지원 파일")
        check(os.path.isfile(os.path.join(root, tour.android_test_rel(v, "TwTour.kt"))), "Android 지원 파일")
        yml = util.read_text(os.path.join(root, "apps", "ios", "project.yml"))
        check(f"{v['product']}UITests:" in yml and "testTargets" in yml, yml)
        check("ui-test-junit4" in util.read_text(os.path.join(root, "apps", "android", "app", "build.gradle.kts")), "androidTest 의존성")
        written = tour.write(root, cfg)
        check(sorted(written) == sorted(files), written)                                  # 골격이 있으니 배선은 건드리지 않는다
        check(not tour.drift(root, cfg) and tour.write(root, cfg) == [], "멱등")
    finally:
        shutil.rmtree(root, ignore_errors=True)


@case
def tour_wires_pre_scaffold_app():
    """골격 이전에 만든 앱 — 지원 파일 · 타깃 · 의존성을 write() 가 채운다 (한 번만)."""
    root = _repo()
    try:
        cfg = config.load(root)
        v = config.app_vars(cfg)
        yml_p = os.path.join(root, "apps", "ios", "project.yml")
        gr_p = os.path.join(root, "apps", "android", "app", "build.gradle.kts")
        yml = util.read_text(yml_p)
        util.write_text(yml_p, yml[:yml.index("  # twbuild: screen tour UI tests")].replace(f"    scheme:\n      testTargets: [{v['product']}UITests]\n", ""))
        gr = util.read_text(gr_p)
        util.write_text(gr_p, "\n".join(l for l in gr.split("\n") if "androidTest" not in l and "screen tour" not in l and "testInstrumentationRunner" not in l))
        os.remove(os.path.join(root, "apps", "ios", "UITests", "TwTour.swift"))
        written = tour.write(root, cfg)
        check(os.path.join("apps", "ios", "project.yml") in written and os.path.join("apps", "android", "app", "build.gradle.kts") in written, written)
        check(os.path.join("apps", "ios", "UITests", "TwTour.swift") in written, written)
        yml = util.read_text(yml_p)
        check(yml.count(f"{v['product']}UITests:") == 1 and f"testTargets: [{v['product']}UITests]" in yml, yml)
        gr = util.read_text(gr_p)
        check("ui-test-junit4" in gr and "testInstrumentationRunner" in gr, gr)
        check(tour.write(root, cfg) == [], "두 번째는 바꿀 것이 없다")
    finally:
        shutil.rmtree(root, ignore_errors=True)
