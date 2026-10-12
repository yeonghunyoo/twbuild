"""폰트 — styles.css 의 웹폰트 받기 · 두 앱 등록 · T9 패리티 (fonts.py). 네트워크 없이 가짜 fetch 로 본다."""
import os
import shutil
import struct

from cases import _wired_repo, case, check

from twbuild import config, fonts, util

IMPORT = ("@import url('https://fonts.googleapis.com/css2?family=Caprasimo:wght@400&family=Figtree:wght@400;600;700&display=swap');\n"
          ":root {\n  --font-heading: \"Caprasimo\", system-ui, sans-serif;\n  --font-heading-weight: 400;\n  --font-body: \"Figtree\", system-ui, sans-serif;\n"
          "  --font-mono: var(--font-body);\n}\n")

GOOGLE_CSS = "".join(
    f"/* latin */\n@font-face {{\n  font-family: '{fam}';\n  font-style: normal;\n  font-weight: {w};\n  font-display: swap;\n"
    f"  src: url(https://fonts.gstatic.com/s/{fam.lower()}/v1/{fam}-{fonts.weight_name(w)}.ttf) format('truetype');\n}}\n"
    for fam, w in (("Caprasimo", 400), ("Figtree", 400), ("Figtree", 600), ("Figtree", 700)))

WOFF_CSS = GOOGLE_CSS.replace(".ttf) format('truetype')", ".woff2) format('woff2')")


def fake_ttf(family, sub, ps):
    """`name` 테이블만 있는 최소 TTF — id 1 · 2 · 4 · 6, platform 3 (UTF-16BE)."""
    strings = {1: family, 2: sub, 4: f"{family} {sub}", 6: ps}
    recs, blob = b"", b""
    for nid in sorted(strings):
        s = strings[nid].encode("utf-16-be")
        recs += struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(s), len(blob))
        blob += s
    name = struct.pack(">HHH", 0, len(strings), 6 + len(recs)) + recs + blob
    head = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    rec = b"name" + struct.pack(">III", 0, 12 + 16, len(name))
    return head + rec + name


def fake_fetch(url, headers):
    if "googleapis.com" in url:
        check(headers.get("User-Agent", "").startswith("twbuild/"), headers)
        return GOOGLE_CSS.encode()
    base = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]           # Figtree-SemiBold
    fam, _, w = base.partition("-")
    return fake_ttf(fam, w, base)


@case
def fonts_parse_fetch_install_parity():
    root = _wired_repo()
    try:
        styles = os.path.join(root, fonts.STYLES)
        util.write_text(styles, IMPORT)
        fams = fonts.families(IMPORT)
        check(fams == [{"family": "Caprasimo", "weights": [400], "styles": ["normal"]}, {"family": "Figtree", "weights": [400, 600, 700], "styles": ["normal"]}], fams)
        check(fonts.roles(IMPORT) == {"heading": "Caprasimo", "body": "Figtree"} and fonts.role_weights(IMPORT) == {"heading": 400}, fonts.roles(IMPORT))
        check(fonts._axes("ital,wght@0,400;1,400;0,700") == [(0, 400), (1, 400), (0, 700)] and fonts._axes("") == [(0, 400)], "axes")
        check(fonts.file_name("Figtree", 600, "normal") == "Figtree-SemiBold.ttf" and fonts.file_name("Figtree", 400, "italic") == "Figtree-Italic.ttf"
              and fonts.android_name("Figtree", 700, "italic") == "figtree_bold_italic" and fonts.android_name("3D Font", 400, "normal") == "f_3d_font_regular", "이름")
        check(fonts.postscript_name(fake_ttf("Figtree", "SemiBold", "Figtree-SemiBold")) == "Figtree-SemiBold" and fonts.postscript_name(b"wOF2xxxx") is None, "name 테이블")
        # 받기
        r = fonts.fetch(root, fetch=fake_fetch)
        check(len(r["files"]) == 4 and not r["errors"], r)
        idx = util.read_json(os.path.join(root, fonts.FONTS_DIR, fonts.INDEX))
        e = idx["Figtree-SemiBold.ttf"]
        check(e["postscript"] == "Figtree-SemiBold" and e["weight"] == 600 and e["postscript_from"] == "name-table" and e["source"].endswith("Figtree-SemiBold.ttf") and len(e["sha256"]) == 64, e)
        r2 = fonts.fetch(root, fetch=fake_fetch)
        check(len(r2["skipped"]) == 4 and not r2["files"] and not r2["errors"], r2)       # 멱등 — 같은 출처면 다시 받지 않는다
        # 설치 · 등록
        cfg = config.load(root)
        vars_ = config.app_vars(cfg)
        ins = fonts.install(root, cfg)
        check(not ins["errors"] and len(ins["ios"]) == 6 and len(ins["android"]) == 5, ins)      # 폰트 4 + project.yml + Fonts.swift / 폰트 4 + Fonts.kt
        pj_path = os.path.join(root, "apps", "ios", "project.yml")
        pj = util.read_text(pj_path)
        check("    info:\n      path: App/Info.plist\n      properties:\n        UIAppFonts: [Caprasimo-Regular.ttf, Figtree-Regular.ttf, Figtree-SemiBold.ttf, Figtree-Bold.ttf]" in pj, pj)
        check(pj.startswith("# xcodegen") and "SWIFT_STRICT_CONCURRENCY: complete" in pj, "다른 줄 유지")
        check(fonts.uiappfonts(pj) == ["Caprasimo-Regular.ttf", "Figtree-Regular.ttf", "Figtree-SemiBold.ttf", "Figtree-Bold.ttf"], fonts.uiappfonts(pj))
        for n in ("caprasimo_regular", "figtree_regular", "figtree_semibold", "figtree_bold"):
            check(os.path.isfile(os.path.join(root, "apps", "android", fonts.ANDROID_FONTS, n + ".ttf")), n)
        check(os.path.isfile(os.path.join(root, "apps", "ios", fonts.IOS_FONTS, "Figtree-Bold.ttf")), "iOS 복사")
        sw = util.read_text(os.path.join(root, "apps", "ios", fonts.IOS_SWIFT))
        check('static let heading = "Caprasimo-Regular"' in sw and 'static let body = "Figtree-Regular"' in sw and '600: "Figtree-SemiBold"' in sw
              and "static let headingWeight: Font.Weight = .regular" in sw and "GENERATED by twbuild" in sw and "mono" not in sw
              and "static let italics: [String: [Int: String]] = [:]" in sw, sw)        # 빈 딕셔너리는 [:] — 실측: [ ] 는 컴파일 오류
        kt = util.read_text(os.path.join(root, "apps", "android", fonts.ANDROID_KT.format(pkg_path=vars_["pkg_path"])))
        check(kt.startswith(f"package {vars_['id']}.core.designsystem\n") and f"import {vars_['id']}.R" in kt
              and "val heading: FontFamily = FontFamily(Font(R.font.caprasimo_regular, FontWeight.W400))" in kt
              and "Font(R.font.figtree_semibold, FontWeight.W600)" in kt and "FontStyle" not in kt, kt)
        check(fonts.parity(root, cfg) == [], fonts.parity(root, cfg))
        # 멱등 — 다시 설치해도 project.yml 그대로
        fonts.install(root, cfg)
        check(util.read_text(pj_path) == pj, "install 멱등")
        # 사람이 UIAppFonts 를 block 목록으로 고쳐 둔 경우에도 갱신한다
        util.write_text(pj_path, pj.replace("        UIAppFonts: [Caprasimo-Regular.ttf, Figtree-Regular.ttf, Figtree-SemiBold.ttf, Figtree-Bold.ttf]",
                                            "        UIAppFonts:\n          - Caprasimo-Regular.ttf\n        CFBundleName: Mini"))
        fonts.install(root, cfg)
        pj3 = util.read_text(pj_path)
        check("UIAppFonts: [Caprasimo-Regular.ttf, Figtree-Regular.ttf, Figtree-SemiBold.ttf, Figtree-Bold.ttf]\n        CFBundleName: Mini" in pj3, pj3)
        # T9 — Android 쪽 파일 하나를 지우면 위반
        os.remove(os.path.join(root, "apps", "android", fonts.ANDROID_FONTS, "figtree_bold.ttf"))
        v = fonts.parity(root, cfg)
        check(len(v) == 1 and v[0]["rule"] == fonts.RULE and "Figtree 700" in v[0]["detail"] and "figtree_bold" in v[0]["detail"], v)
        st = fonts.status(root, cfg)
        check(st["fetched"] == 4 and st["ios"] == 4 and st["android"] == 3 and st["missing"] == [v[0]["detail"]] and st["families"] == ["Caprasimo", "Figtree"], st)
        code, text = fonts.cli([], root)
        check(code == 1 and fonts.RULE in text and "Figtree-SemiBold" in text, text)
        # iOS 에 복사만 되고 등록이 빠진 경우
        fonts.install(root, cfg)
        util.write_text(pj_path, pj.replace(", Figtree-Bold.ttf]", "]"))
        v = fonts.parity(root, cfg)
        check(any("UIAppFonts 에 없다" in x["detail"] for x in v) and any("Android 에만" in x["detail"] for x in v), v)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@case
def fonts_errors_and_fallbacks():
    root = _wired_repo()
    try:
        styles = os.path.join(root, fonts.STYLES)
        r = fonts.fetch(root, fetch=fake_fetch)
        check(not r["files"] and r["errors"] and "styles.css" in r["errors"][0], r)          # 디자인 import 전
        cfg = config.load(root)
        ins = fonts.install(root, cfg)
        check(ins["errors"] and "fetch" in ins["errors"][0] and not ins["ios"], ins)          # 받은 폰트 없음
        check(fonts.parity(root, cfg) == [] and fonts.status(root, cfg)["fetched"] == 0, "빈 상태는 위반이 아니다")

        def offline(url, headers):
            raise OSError("offline")
        util.write_text(styles, IMPORT)
        r = fonts.fetch(root, fetch=offline)
        check(not r["files"] and r["errors"] and "offline" in r["errors"][0], r)              # 네트워크 실패 — raise 없음
        check(not os.path.exists(os.path.join(root, fonts.FONTS_DIR, fonts.INDEX)), "실패하면 index 를 쓰지 않는다")

        def woff_only(url, headers):
            if "googleapis.com" in url:
                return WOFF_CSS.encode()
            return b"wOF2" + b"\x00" * 64
        r = fonts.fetch(root, fetch=woff_only)
        check(len(r["files"]) == 4 and r["errors"] and "woff2" in r["errors"][0], r)          # TTF 를 못 받으면 받되 알린다
        idx = fonts.index(root)
        e = idx["Figtree-SemiBold.woff2"]
        check(e["postscript"] == "Figtree-SemiBold" and e["postscript_from"] == "convention" and e["format"] == "woff2", e)
        ins = fonts.install(root, cfg)
        check(not ins["errors"] and os.path.isfile(os.path.join(root, "apps", "android", fonts.ANDROID_FONTS, "figtree_semibold.woff2")), ins)
        check(fonts.parity(root, cfg) == [], fonts.parity(root, cfg))
        # styles.css 자체의 @font-face: 절대 URL 은 받고 상대 경로는 건너뛴다
        util.write_text(styles, "@font-face { font-family: 'Local'; src: url(fonts/local.ttf); }\n@font-face { font-family: 'Remote'; font-weight: 700; src: url(https://cdn.example.com/Remote-Bold.ttf) format('truetype'); }\n")
        r = fonts.fetch(root, fetch=fake_fetch)
        check(r["files"] == [os.path.join(fonts.FONTS_DIR, "Remote-Bold.ttf")] and any("local.ttf" in s for s in r["skipped"]) and not r["errors"], r)
        check(fonts.families(util.read_text(styles)) == [{"family": "Local", "weights": [400], "styles": ["normal"]}, {"family": "Remote", "weights": [700], "styles": ["normal"]}], "families from @font-face")
        # 역할의 가족을 받지 않았으면 Swift 는 nil · Kotlin 은 Default 로
        css = "@import url('https://fonts.googleapis.com/css2?family=Nope:wght@400');\n:root { --font-heading: 'Nope', serif; }\n"
        sw = fonts.swift(css, dict(fonts._entries(root)))
        kt = fonts.kotlin(css, dict(fonts._entries(root)), "com.example.x")
        check("static let heading: String? = nil" in sw and "val heading: FontFamily = FontFamily.Default" in kt, (sw, kt))
    finally:
        shutil.rmtree(root, ignore_errors=True)
