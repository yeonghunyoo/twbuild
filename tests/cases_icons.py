"""아이콘 연결 — 트리 svg → TwIcon(Swift) · TwIcons(Kotlin) 생성 · 초안 호출 · 게이트 T11 (icons.py)."""
import math
import os
import shutil

from cases import MINI, MINI_CSS, _wired_repo, case, check

from twbuild import config, design, draft, gate, icons, tokens, tree, util


def _close(a, b, eps=1e-6):
    return all(abs(x - y) < eps for x, y in zip(a, b)) and len(a) == len(b)


@case
def icon_path_parser():
    p = icons.parse_path("M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5z")
    check(p[0] == ("M", 7.0, 4.5) and p[1] == ("L", 7.0, 19.5), p[:2])
    arc = [c for c in p if c[0] == "C"]
    check(arc and _close(arc[-1][5:], (8.5, 20.36)), arc)                                     # 호 끝점 = (7, 19.5) + 상대 (1.5, .86) — `1.5.86` 은 숫자 둘
    check(p[-1] == ("Z",) and _close(p[-2][1:], (20.5, 12.86)), p)
    # 숫자 구분자 없음 · 암묵 반복 · 상대 M 뒤 l
    q = icons.parse_path("m1 2 3 4-1-2 .5.5h1v1")
    check(q == [("M", 1, 2), ("L", 4, 6), ("L", 3, 4), ("L", 3.5, 4.5), ("L", 4.5, 4.5), ("L", 4.5, 5.5)], q)
    # 호 플래그가 붙어 있어도 · 반원 = 90° 이하 조각 둘
    a = icons.parse_path("M0 0A5 5 0 0010 0")
    check(len(a) == 3 and all(c[0] == "C" for c in a[1:]) and _close(a[-1][5:], (10, 0)), a)
    # 반지름 정확도 — 조각 중간점이 원 위에 (1e-3 이내: 3차 근사 오차)
    c1 = a[1]
    t = 0.5
    bx = (1 - t) ** 3 * 0 + 3 * (1 - t) ** 2 * t * c1[1] + 3 * (1 - t) * t ** 2 * c1[3] + t ** 3 * c1[5]
    by = (1 - t) ** 3 * 0 + 3 * (1 - t) ** 2 * t * c1[2] + 3 * (1 - t) * t ** 2 * c1[4] + t ** 3 * c1[6]
    check(abs(math.hypot(bx - 5, by) - 5) < 1e-3, (bx, by))
    # S · T 반사 · 절대 Q
    s = icons.parse_path("M0 0C1 1 2 1 3 0S5 -1 6 0Q7 1 8 0T10 0")
    check(s[2] == ("C", 4, -1, 5, -1, 6, 0) and s[4] == ("Q", 9, -1, 10, 0), s)
    # 도형
    circ = icons.commands_of("circle(cx=12 cy=12 r=9)")
    check(circ[0] == ("M", 21, 12) and circ[-1] == ("Z",) and sum(1 for c in circ if c[0] == "C") == 4 and _close(circ[-2][5:], (21, 12)), circ)
    rect = icons.commands_of("rect(width=18 height=18 x=3 y=4 rx=2)")
    check(rect[0] == ("M", 5, 4) and sum(1 for c in rect if c[0] == "C") == 4 and rect[-1] == ("Z",), rect)
    poly = icons.commands_of("polygon(points=1,2 3,4 5,6)")
    check(poly == [("M", 1, 2), ("L", 3, 4), ("L", 5, 6), ("Z",)], poly)
    check(icons.commands_of("line(x1=1 y1=2 x2=3 y2=4)") == [("M", 1, 2), ("L", 3, 4)], "line")
    try:
        icons.parse_path("10 10")
        check(False, "명령 없이 시작하면 오류")
    except icons.IconError:
        pass


@case
def icon_tree_paint_and_hash():
    markup, script, frame = tree.split(MINI)
    specs = tree.detect_screens(markup, script)
    tm = tree.TokenMap(tokens.tokens(MINI_CSS))
    lay = tree.layout(markup, specs[0], specs, tm, source="x.dc.html", frame=frame)
    painted_markup = markup.replace('<svg width="14" height="14" viewBox="0 0 24 24">',
                                    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.75" stroke-linecap="round">')
    check(painted_markup != markup, "테스트 전제: 픽스처에 svg 가 있다")
    lay2 = tree.layout(painted_markup, specs[0], specs, tm, source="x.dc.html", frame=frame)
    check(lay["hash"] == lay2["hash"], "svg_paint 는 해시에 안 들어간다")
    found = []
    icons._walk(lay2["root"], found)
    p = found[0]["svg_paint"]
    check(p == {"fill": "none", "stroke": "current", "stroke-width": "2.75", "stroke-linecap": "round"}, p)
    check(icons.paint_of(found[0]) == {"fill": False, "stroke": True, "stroke_width": 2.75, "linecap": "round", "linejoin": "miter", "fill_rule": "nonzero"}, icons.paint_of(found[0]))
    # 상태 바인딩 style 은 칠이 bind
    bound = tree.layout(markup.replace('<svg width="14" height="14" viewBox="0 0 24 24">', '<svg width="14" height="14" viewBox="0 0 24 24" stroke-width="2" style="{{ favStyle }}">'),
                        specs[0], specs, tm)
    f2 = []
    icons._walk(bound["root"], f2)
    check(f2[0]["svg_paint"]["fill"] == "bind:favStyle" and icons.paint_of(f2[0])["fill"] == "bind", f2[0].get("svg_paint"))
    # 이름: 결정적 · 칠 방식이 다르면 다른 이름 · 같으면 하나로
    n1, n2 = icons.name_of(found[0]), icons.name_of(found[0])
    plain = []
    icons._walk(lay["root"], plain)
    check(n1 == n2 and n1.startswith("ic") and n1 != icons.name_of(plain[0]), (n1, icons.name_of(plain[0])))
    ics, nodes = icons.collect({"a": lay2, "b": lay2})
    check(len(ics) == 1 and list(nodes.values()) == [n1] and ics[n1]["stroke"] is True and ics[n1]["viewbox"] == "0 0 24 24", ics)
    sw, kt = icons.swift(ics), icons.kotlin(ics, "com.x.y")
    check(icons.HEADER in sw and f"case {n1}" in sw and "p.move(to: t(7, 4.5))" in sw and "p.addLine(to: t(7, 19.5))" in sw and "lineCap: paint.cap.cg" in sw, sw[:900])
    check("package com.x.y.core.designsystem.generated" in kt and f"val {n1}: ImageVector by lazy" in kt and "moveTo(7f, 4.5f)" in kt
          and "lineTo(7f, 19.5f)" in kt and "StrokeCap.Round" in kt and "strokeLineWidth = 2.75f" in kt, kt)
    check(icons.swift(ics) == sw and icons.kotlin(ics, "com.x.y") == kt, "결정적")
    # viewBox 원점 이동
    shifted = icons._shift([("M", 5, 6), ("C", 1, 2, 3, 4, 5, 6)], (1, 2, 10, 10))
    check(shifted == [("M", 4, 4), ("C", 0, 0, 2, 2, 4, 4)], shifted)


@case
def icon_generated_files_draft_and_t11():
    root = _wired_repo()
    try:
        markup, script, frame = tree.split(MINI)
        specs = tree.detect_screens(markup, script)
        tm = tree.TokenMap(tokens.tokens(MINI_CSS))
        lay = tree.layout(markup, specs[0], specs, tm, source="design/mini/mini.dc.html", frame=frame)
        util.write_text(os.path.join(root, "design/mini/layout/home.json"), util.stable_json(lay))
        cfg = config.load(root)
        vars_ = config.app_vars(cfg)
        files = icons.write(root, cfg)
        pkg = vars_["id"].replace(".", "/")
        check(files == sorted(["apps/ios/App/Core/DesignSystem/Generated/Icons.swift",
                               f"apps/android/app/src/main/kotlin/{pkg}/core/designsystem/generated/Icons.kt"]), files)
        check(icons.drift(root, cfg) == [], "쓴 직후 drift 없음")
        util.write_text(os.path.join(root, files[0]), "x")
        check(icons.drift(root, cfg) == [files[0]], "drift 감지")
        icons.write(root, cfg)
        code, text = icons.cli([], root)
        check(code == 0 and "아이콘 1개" in text, text)
        # 초안 — 경로 데이터가 있는 아이콘은 생성 아이콘 호출
        name = icons.name_of([n for n in _icons_of(lay)][0])
        sw = draft.swift(lay, "mini", vars_)
        kt = draft.kotlin(lay, "mini", vars_)
        view = next(t for r, t in sw.items() if r.endswith("HomeView.swift"))
        screen = next(t for r, t in kt.items() if r.endswith("HomeScreen.kt"))
        check(f"TwIconView(.{name}, size: 14)" in view and ".accessibilityIdentifier(" in view.split(f"TwIconView(.{name}", 1)[1].splitlines()[0], view)
        check(f"Icon(TwIcons.{name}, contentDescription = null, modifier = Modifier.testTag(" in screen and ".size(14.dp))" in screen
              and f"import {vars_['id']}.core.designsystem.generated.TwIcons" in screen and "import androidx.compose.material3.Icon" in screen, screen[:1500])
        # T11 — 호출을 지우면 위반, 되돌리면 통과
        for rel, text in sw.items():
            util.write_text(os.path.join(root, "apps/ios", rel), text)
        st = gate.static_check(root, "ios", lay)
        check(not [v for v in st["violations"] if v["rule"] == "T11"], st["violations"])
        vpath = os.path.join(root, "apps/ios", next(r for r in sw if r.endswith("HomeView.swift")))
        util.write_text(vpath, view.replace(f"TwIconView(.{name}, size: 14)", 'Image(systemName: "star")'))
        st = gate.static_check(root, "ios", lay)
        check([v for v in st["violations"] if v["rule"] == "T11" and name in v["detail"]], st["violations"])
        # 경로 데이터가 없는 아이콘은 예전 자리표시 그대로
        bare = {**lay, "root": _strip_svg(lay["root"])}
        check("TwIconView" not in next(t for r, t in draft.swift(bare, "mini", vars_).items() if r.endswith("HomeView.swift")), "svg 없는 아이콘")
        check("TwIcons" not in next(t for r, t in draft.kotlin(bare, "mini", vars_).items() if r.endswith("HomeScreen.kt")), "svg 없으면 import 도 없다")
        check(icons.expected(root, cfg) and icons.collect({"x": bare})[0] == {}, "svg 없는 트리는 아이콘 없음")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _icons_of(lay):
    out = []
    icons._walk(lay["root"], out)
    return out


def _strip_svg(n):
    if not isinstance(n, dict):
        return n
    return {k: ([_strip_svg(c) for c in v] if k == "children" else v) for k, v in n.items() if k not in ("svg", "svg_paint")}


@case
def icon_design_run_writes_files():
    root = _wired_repo()
    try:
        design.start(root, "mini", "P1", ["mini.dc.html"])
        design.capture(root, "mini.dc.html", MINI, "e1", "P1")
        design.capture(root, "_ds/mini-ds/styles.css", MINI_CSS, "c1", "P1")
        out = design.finish(root)
        check(out["icons"]["files"] and all(os.path.isfile(os.path.join(root, f)) for f in out["icons"]["files"]), out.get("icons"))
        from cases import _git
        check("Icons.swift" in _git(root, "show", "--name-only", "HEAD"), _git(root, "show", "--name-only", "HEAD"))
    finally:
        shutil.rmtree(root, ignore_errors=True)
