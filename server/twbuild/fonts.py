"""폰트 — 디자인 시스템 `design/ds/styles.css` 의 웹폰트를 하네스가 받아 두 앱에 등록한다 (AGENT.md 2장 · 6장 "리소스 양쪽 등록").

  styles.css  @import url(https://fonts.googleapis.com/css2?family=…) · @font-face · --font-<역할>: "Family", …
     → design/ds/fonts/<Family>-<Weight>[Italic].ttf + index.json      디자인 스냅숏 (커밋, 출처 · sha 기록)
     → apps/ios/App/Resources/Fonts/<같은 파일>  + project.yml  info.properties.UIAppFonts   (xcodegen 이 Info.plist 를 만든다)
     → apps/android/app/src/main/res/font/<family>_<weight>[_italic].ttf                     (리소스 이름 규칙: a-z0-9_)
     → Fonts.swift(enum FontFamily) · Fonts.kt(object FontFamilies)   역할 → 폰트 이름, 두 플랫폼 같은 역할 이름 (생성물)
  T9  두 플랫폼에 등록된 폰트 집합(family · weight · style)이 같다 — 게이트 정적 층이 부른다.

Google Fonts 는 User-Agent 로 형식을 고른다 — 브라우저 UA 에는 woff/woff2 를 unicode-range 로 쪼개 주고, 브라우저가 아닌 UA(curl · twbuild/…)에는
weight 마다 정적 TTF 하나를 준다 (실측 2026-10-13). iOS 는 PostScript 이름(TTF `name` 테이블 id 6)으로 폰트를 부르므로 TTF 를 받아 이름을 읽는다.
라이선스: Google Fonts 의 폰트는 OFL 1.1 또는 Apache 2.0 — 앱 번들에 넣어 배포할 수 있다. 출처 URL 을 index.json 에 남긴다.
표준 라이브러리만. 네트워크는 fetch(url, headers) -> bytes 하나로 — 테스트가 가짜를 준다. 절대 raise 하지 않는다(errors 에 한국어 한 줄).
"""
import hashlib
import os
import re
import struct
import urllib.parse
import urllib.request

from . import config, util

STYLES = os.path.join(util.DESIGN_DIR, "ds", "styles.css")
FONTS_DIR = os.path.join(util.DESIGN_DIR, "ds", "fonts")
INDEX = "index.json"
IOS_FONTS = os.path.join("App", "Resources", "Fonts")
IOS_SWIFT = os.path.join("App", "Core", "DesignSystem", "Fonts.swift")
ANDROID_FONTS = os.path.join("app", "src", "main", "res", "font")
ANDROID_KT = os.path.join("app", "src", "main", "kotlin", "{pkg_path}", "core", "designsystem", "Fonts.kt")
INFO_PLIST = "App/Info.plist"
USER_AGENT = "twbuild/{ver} (+https://github.com/yeonghunyoo/twbuild)"      # 브라우저 UA 가 아니면 Google 이 정적 TTF 를 준다
TIMEOUT = 60
MAX_BYTES = 8 * 1024 * 1024
WEIGHT_NAMES = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}
KOTLIN_WEIGHTS = {100: "W100", 200: "W200", 300: "W300", 400: "W400", 500: "W500", 600: "W600", 700: "W700", 800: "W800", 900: "W900"}
EXTS = ("ttf", "otf", "woff2", "woff")

_IMPORT_RE = re.compile(r"@import\s+(?:url\()?\s*['\"]?(https?://[^'\")\s]+)['\"]?\s*\)?[^;]*;", re.I)      # URL 안의 ; (wght@400;600) 는 끝이 아니다
RULE = "T9"             # 게이트 규칙 ID — 두 플랫폼 폰트 등록 집합 일치 (T7 · T8 은 디자인 시스템 컴포넌트 규칙)
_FACE_RE = re.compile(r"@font-face\s*\{([^}]*)\}", re.I | re.S)
_ROLE_RE = re.compile(r"--font-([a-z0-9-]+)\s*:\s*([^;]+);", re.I)


# ─────────────────────────── styles.css 해석 ───────────────────────────

def _google_families(url):
    """css2 · css URL 의 family= 매개변수 → [(family, [(ital, wght)…])]."""
    q = urllib.parse.urlparse(url).query
    out = []
    for key, val in urllib.parse.parse_qsl(q, keep_blank_values=True):
        if key != "family":
            continue
        for spec in (val.split("|") if "|" in val else [val]):           # 옛 css API 는 | 로 여러 가족
            name, _, axes = spec.partition(":")
            name = name.replace("+", " ").strip()
            if not name:
                continue
            combos = _axes(axes)
            out.append((name, combos))
    return out


def _axes(axes):
    """`wght@400;600` · `ital,wght@0,400;1,700` · 옛 `400,700` · 빈 값 → [(ital, wght)…]."""
    if not axes:
        return [(0, 400)]
    if "@" in axes:
        names, _, values = axes.partition("@")
        names = [n.strip() for n in names.split(",")]
        combos = []
        for tup in values.split(";"):
            parts = [p.strip() for p in tup.split(",")]
            d = dict(zip(names, parts))
            try:
                w = int(str(d.get("wght", "400")).split("..")[0])      # 가변 범위(300..900)는 시작값으로 적는다
            except ValueError:
                w = 400
            combos.append((1 if str(d.get("ital", "0")) == "1" else 0, w))
        return combos or [(0, 400)]
    combos = []
    for tok in axes.split(","):
        tok = tok.strip().lower()
        m = re.match(r"(\d+)(i|italic)?$", tok)
        if m:
            combos.append((1 if m.group(2) else 0, int(m.group(1))))
        elif tok in ("italic", "i"):
            combos.append((1, 400))
    return combos or [(0, 400)]


def _css_string(v):
    return v.strip().strip("'\"").strip()


def font_faces(css_text):
    """@font-face 블록 → [{"family", "weight", "style", "url", "format"}] (src 의 첫 url; 여럿이면 ttf/otf 를 우선)."""
    out = []
    for m in _FACE_RE.finditer(css_text or ""):
        body = m.group(1)
        props = {}
        for line in body.split(";"):
            k, _, v = line.partition(":")
            if k.strip():
                props[k.strip().lower()] = v.strip()
        fam = _css_string(props.get("font-family", ""))
        if not fam or "src" not in props:
            continue
        srcs = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)(?:\s*format\(\s*['\"]?([a-z0-9-]+)['\"]?\s*\))?", props["src"], re.I)
        if not srcs:
            continue
        srcs.sort(key=lambda s: 0 if s[0].lower().endswith((".ttf", ".otf")) or s[1].lower() in ("truetype", "opentype") else 1)
        url, fmt = srcs[0]
        w = props.get("font-weight", "400").split()[0]
        try:
            weight = int(w)
        except ValueError:
            weight = {"normal": 400, "bold": 700}.get(w.lower(), 400)
        out.append({"family": fam, "weight": weight, "style": "italic" if "italic" in props.get("font-style", "").lower() else "normal",
                    "url": url.strip(), "format": (fmt or _ext_of(url)).lower()})
    return out


def _ext_of(url):
    path = urllib.parse.urlparse(url).path.lower()
    for e in EXTS:
        if path.endswith("." + e):
            return e
    return "ttf"


def google_imports(css_text):
    """@import 의 Google Fonts URL 목록."""
    return [u for u in _IMPORT_RE.findall(css_text or "") if "fonts.googleapis.com" in u]


def families(css_text):
    """styles.css 가 쓰는 웹폰트 가족 — [{"family", "weights": [int…], "styles": ["normal"|"italic"…]}], 가족 이름순."""
    acc = {}
    for url in google_imports(css_text):
        for name, combos in _google_families(url):
            f = acc.setdefault(name, {"weights": set(), "styles": set()})
            for ital, w in combos:
                f["weights"].add(w)
                f["styles"].add("italic" if ital else "normal")
    for face in font_faces(css_text):
        f = acc.setdefault(face["family"], {"weights": set(), "styles": set()})
        f["weights"].add(face["weight"])
        f["styles"].add(face["style"])
    return [{"family": n, "weights": sorted(v["weights"]), "styles": sorted(v["styles"])} for n, v in sorted(acc.items())]


def roles(css_text):
    """`--font-<역할>: "Family", system-ui` → {역할: Family}. 값이 숫자(--font-heading-weight: 400)면 역할이 아니다."""
    out = {}
    for role, val in _ROLE_RE.findall(css_text or ""):
        first = _css_string(val.split(",")[0])
        if not first or first[0].isdigit() or first.startswith("var("):
            continue
        out[role.lower()] = first
    return out


def role_weights(css_text):
    """`--font-<역할>-weight: 600` → {역할: 600}."""
    out = {}
    for role, val in _ROLE_RE.findall(css_text or ""):
        if role.lower().endswith("-weight"):
            try:
                out[role.lower()[:-7]] = int(_css_string(val))
            except ValueError:
                pass
    return out


# ─────────────────────────── 이름 ───────────────────────────

def weight_name(weight):
    return WEIGHT_NAMES.get(weight, str(weight))


def file_name(family, weight, style, ext="ttf"):
    """디자인 스냅숏 · iOS 리소스 파일 이름 — Caprasimo-Regular.ttf · Figtree-SemiBold.ttf · Figtree-Italic.ttf · Figtree-BoldItalic.ttf."""
    base = re.sub(r"[^A-Za-z0-9]", "", family)
    if style == "italic":
        suffix = "Italic" if weight == 400 else weight_name(weight) + "Italic"
    else:
        suffix = weight_name(weight)
    return f"{base}-{suffix}.{ext}"


def android_name(family, weight, style):
    """res/font 리소스 이름 — a-z0-9_ 만, 숫자로 시작하지 않는다: caprasimo_regular · figtree_semibold · figtree_bold_italic."""
    fam = re.sub(r"[^a-z0-9]+", "_", family.lower()).strip("_")
    name = f"{fam}_{weight_name(weight).lower()}" + ("_italic" if style == "italic" else "")
    return name if name[:1].isalpha() else "f_" + name


def convention_name(family, weight, style):
    """PostScript 이름을 못 읽을 때(woff2 등) 쓰는 관례 이름 — Family-Weight[Italic]."""
    return file_name(family, weight, style, "ttf")[:-4]


def postscript_name(data):
    """TTF/OTF 의 `name` 테이블에서 PostScript 이름(id 6; 없으면 full name id 4 의 공백 제거). 못 읽으면 None. 표준 라이브러리 struct 만."""
    try:
        if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            return None
        n = struct.unpack(">H", data[4:6])[0]
        tabs = {}
        for i in range(n):
            tag = data[12 + 16 * i:16 + 16 * i]
            off, ln = struct.unpack(">II", data[20 + 16 * i:28 + 16 * i])
            tabs[tag] = (off, ln)
        if b"name" not in tabs:
            return None
        off, ln = tabs[b"name"]
        fmt, cnt, so = struct.unpack(">HHH", data[off:off + 6])
        found = {}
        for i in range(cnt):
            pid, eid, lid, nid, l, o = struct.unpack(">HHHHHH", data[off + 6 + 12 * i:off + 18 + 12 * i])
            if nid not in (4, 6):
                continue
            raw = data[off + so + o:off + so + o + l]
            s = raw.decode("utf-16-be", "replace") if pid in (0, 3) else raw.decode("latin-1", "replace")
            rank = (0 if nid == 6 else 1, 0 if (pid == 3 and lid == 0x409) else 1 if pid == 3 else 2)
            if nid not in found or rank < found[nid][0]:
                found[nid] = (rank, s.strip("\x00").strip())
        if 6 in found and found[6][1]:
            return found[6][1]
        if 4 in found and found[4][1]:
            return re.sub(r"\s+", "", found[4][1])
    except (struct.error, IndexError, ValueError):
        return None
    return None


# ─────────────────────────── 받기 ───────────────────────────

def _default_fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(MAX_BYTES + 1)


def _ua():
    return USER_AGENT.format(ver=util.plugin_version().get("plugin", "0"))


def _index_path(root):
    return os.path.join(root, FONTS_DIR, INDEX)


def index(root):
    return util.read_json(_index_path(root), {}) or {}


def fetch(root, fetch=None):
    """styles.css 의 웹폰트를 design/ds/fonts/ 에 받는다. → {"files": [상대경로…], "skipped": [...], "errors": [한국어…]}. 멱등 · raise 없음."""
    get = fetch or _default_fetch
    out = {"files": [], "skipped": [], "errors": []}
    css = util.read_text(os.path.join(root, STYLES), "")
    if not css.strip():
        out["errors"].append("design/ds/styles.css 가 없다 — 디자인 import(design run) 뒤에 받는다")
        return out
    faces = []
    for url in google_imports(css):
        try:
            text = get(url, {"User-Agent": _ua(), "Accept": "text/css,*/*"}).decode("utf-8", "replace")
        except Exception as e:
            out["errors"].append(f"Google Fonts CSS 를 못 받았다 ({_short(url)}): {str(e)[:120]}")
            continue
        got = font_faces(text)
        if not got:
            out["errors"].append(f"Google Fonts 응답에 @font-face 가 없다 ({_short(url)})")
            continue
        fmts = sorted({f["format"] for f in got})
        if "truetype" not in fmts and "ttf" not in fmts:
            out["errors"].append(f"Google Fonts 가 TTF 대신 {', '.join(fmts)} 를 줬다 — PostScript 이름은 관례(Family-Weight)로 적는다 ({_short(url)})")
        faces += _dedupe(got)
    for face in font_faces(css):                       # styles.css 자체의 @font-face — 절대 URL 만 받는다
        if re.match(r"https?://", face["url"]):
            faces.append(face)
        else:
            out["skipped"].append(f"{face['url']} (상대 경로 — 사람이 design/ds/fonts/ 에 넣는다)")
    if not faces and not out["errors"]:
        out["errors"].append("styles.css 에 웹폰트(@import Google Fonts · @font-face url)가 없다")
        return out
    idx = index(root)
    for face in faces:
        ext = _ext_of(face["url"])
        name = file_name(face["family"], face["weight"], face["style"], ext)
        dest = os.path.join(root, FONTS_DIR, name)
        rel = os.path.join(FONTS_DIR, name)
        if os.path.isfile(dest) and (idx.get(name) or {}).get("source") == face["url"]:
            out["skipped"].append(rel)
            continue
        try:
            data = get(face["url"], {"User-Agent": _ua()})
        except Exception as e:
            out["errors"].append(f"{name} 을 못 받았다: {str(e)[:120]}")
            continue
        if not data or len(data) > MAX_BYTES:
            out["errors"].append(f"{name}: 응답이 비었거나 {MAX_BYTES // (1 << 20)} MiB 를 넘는다")
            continue
        sha = hashlib.sha256(data).hexdigest()
        if os.path.isfile(dest) and (idx.get(name) or {}).get("sha256") == sha:
            idx[name] = {**idx[name], "source": face["url"]}
            out["skipped"].append(rel)
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        ps = postscript_name(data) if ext in ("ttf", "otf") else None
        idx[name] = {"family": face["family"], "weight": face["weight"], "style": face["style"], "format": ext, "sha256": sha, "bytes": len(data),
                     "source": face["url"], "postscript": ps or convention_name(face["family"], face["weight"], face["style"]),
                     "postscript_from": "name-table" if ps else "convention", "t": util.now()}
        out["files"].append(rel)
    if faces:
        util.write_json(_index_path(root), dict(sorted(idx.items())))
    return out


def _dedupe(faces):
    """같은 (family, weight, style) 은 하나만 — unicode-range 로 쪼개진 응답(woff2)은 첫 조각만 쓴다."""
    seen, out = set(), []
    for f in faces:
        k = (f["family"], f["weight"], f["style"])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def _short(url):
    return url if len(url) <= 70 else url[:67] + "…"


# ─────────────────────────── 등록 (설치) ───────────────────────────

def _entries(root):
    """index.json → [(파일 이름, 항목)] 가족 · weight · style 순."""
    return sorted(index(root).items(), key=lambda kv: (kv[1].get("family", ""), kv[1].get("weight", 400), kv[1].get("style", "")))


def install(root, cfg=None):
    """받은 폰트를 두 앱에 복사 · 등록하고 Fonts.swift · Fonts.kt 를 만든다. → {"ios": [상대경로…], "android": [...], "errors": [...]}. 멱등."""
    cfg = cfg or config.load(root)
    vars_ = config.app_vars(cfg)
    out = {"ios": [], "android": [], "errors": []}
    entries = _entries(root)
    if not entries:
        out["errors"].append("받은 폰트가 없다 — `twbuild fonts fetch` 먼저")
        return out
    css = util.read_text(os.path.join(root, STYLES), "")
    for p in cfg.get("platforms") or []:
        app = util.app_dir(root, p)
        if not os.path.isdir(app):
            out["errors"].append(f"{p} 골격이 없다 — 셋업(scaffold) 뒤에 등록한다")
            continue
        if p == "ios":
            out["ios"] += _install_ios(root, app, vars_, entries, css)
        else:
            out["android"] += _install_android(root, app, vars_, entries, css)
    return out


def _copy(src, dest):
    data = open(src, "rb").read()
    if os.path.isfile(dest) and open(dest, "rb").read() == data:
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return True


def _write_if_changed(path, text):
    if util.read_text(path, None) == text:
        return False
    util.write_text(path, text)
    return True


def _install_ios(root, app, vars_, entries, css):
    rels = []
    names = []
    for name, e in entries:
        src = os.path.join(root, FONTS_DIR, name)
        if not os.path.isfile(src):
            continue
        _copy(src, os.path.join(app, IOS_FONTS, name))
        rels.append(os.path.relpath(os.path.join(app, IOS_FONTS, name), root))
        names.append(name)
    pj = os.path.join(app, "project.yml")
    text = util.read_text(pj, "")
    if text:
        new = register_uiappfonts(text, vars_["product"], names)
        if new != text:
            util.write_text(pj, new)
        rels.append(os.path.relpath(pj, root))
    sw = os.path.join(app, IOS_SWIFT)
    _write_if_changed(sw, swift(css, dict(entries)))
    rels.append(os.path.relpath(sw, root))
    return rels


def _install_android(root, app, vars_, entries, css):
    rels = []
    for name, e in entries:
        src = os.path.join(root, FONTS_DIR, name)
        if not os.path.isfile(src):
            continue
        dest = os.path.join(app, ANDROID_FONTS, android_name(e["family"], e["weight"], e["style"]) + "." + e.get("format", "ttf"))
        _copy(src, dest)
        rels.append(os.path.relpath(dest, root))
    kt = os.path.join(app, ANDROID_KT.format(pkg_path=vars_["pkg_path"]))
    _write_if_changed(kt, kotlin(css, dict(entries), vars_["id"]))
    rels.append(os.path.relpath(kt, root))
    return rels


def register_uiappfonts(text, product, names):
    """project.yml 의 타깃에 `info: {path: App/Info.plist, properties: {UIAppFonts: […]}}` 를 넣거나 갱신한다 — 다른 줄은 건드리지 않는다.

    xcodegen 은 info.path 에 Info.plist 를 생성하고 GENERATE_INFOPLIST_FILE 의 키들과 합친다 (실측: 빌드된 앱의 Info.plist 에 UIAppFonts 가 들어간다).
    """
    lines = text.split("\n")
    flow = "        UIAppFonts: [" + ", ".join(names) + "]"
    t_idx = next((i for i, l in enumerate(lines) if l.strip() == "targets:" and not l.startswith(" ")), None)
    if t_idx is None:
        return text
    tgt = next((i for i in range(t_idx + 1, len(lines)) if lines[i].startswith(f"  {product}:")), None)
    if tgt is None:
        tgt = next((i for i in range(t_idx + 1, len(lines)) if re.match(r"  [^\s#].*:\s*$", lines[i])), None)
    if tgt is None:
        return text
    end = tgt + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith("    ")):
        end += 1
    while end > tgt + 1 and not lines[end - 1].strip():
        end -= 1                                         # 블록 끝의 빈 줄은 블록 밖으로
    info = next((i for i in range(tgt + 1, end) if lines[i].startswith("    info:")), None)
    if info is None:
        block = ["    info:", f"      path: {INFO_PLIST}", "      properties:", flow]
        return "\n".join(lines[:end] + block + lines[end:])
    i_end = info + 1
    while i_end < end and (not lines[i_end].strip() or lines[i_end].startswith("      ")):
        i_end += 1
    ui = next((i for i in range(info + 1, i_end) if lines[i].strip().startswith("UIAppFonts:")), None)
    if ui is not None:
        j = ui + 1
        while j < i_end and lines[j].strip().startswith("- "):
            j += 1
        return "\n".join(lines[:ui] + [flow] + lines[j:])
    props = next((i for i in range(info + 1, i_end) if lines[i].strip() == "properties:"), None)
    if props is not None:
        return "\n".join(lines[:props + 1] + [flow] + lines[props + 1:])
    has_path = any(lines[i].strip().startswith("path:") for i in range(info + 1, i_end))
    block = ([] if has_path else [f"      path: {INFO_PLIST}"]) + ["      properties:", flow]
    return "\n".join(lines[:i_end] + block + lines[i_end:])


def uiappfonts(text):
    """project.yml 에 등록된 UIAppFonts 파일 이름들 (flow · block 둘 다)."""
    m = re.search(r"UIAppFonts:\s*\[([^\]]*)\]", text)
    if m:
        return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
    m = re.search(r"UIAppFonts:\s*\n((?:\s+-\s+.*\n?)+)", text)
    if m:
        return [re.sub(r"^\s*-\s+", "", l).strip().strip("'\"") for l in m.group(1).splitlines() if l.strip()]
    return []


# ─────────────────────────── 생성물: Fonts.swift · Fonts.kt ───────────────────────────

def _by_family(entries):
    fams = {}
    for name, e in entries.items():
        fams.setdefault(e["family"], {})[(e["weight"], e["style"])] = e
    return fams


def _role_lines(css, fams):
    """[(역할, 가족, weight, 받았는가)] — 역할 이름순."""
    rw = role_weights(css)
    out = []
    for role, fam in sorted(roles(css).items()):
        w = rw.get(role, 400)
        have = fams.get(fam) or {}
        if have and (w, "normal") not in have:
            w = min(have, key=lambda k: (k[1] != "normal", abs(k[0] - w)))[0]
        out.append((role, fam, w, bool(have)))
    return out


def swift(css, entries):
    """Fonts.swift — 역할 → PostScript 이름. 두 플랫폼 같은 역할 이름(heading · body …)."""
    fams = _by_family(entries)
    L = ["import SwiftUI", "",
         "/// Fonts — GENERATED by twbuild from `design/ds/styles.css` (@import · --font-<role>). Do not edit.",
         "/// Names are PostScript names read from each TTF's `name` table (id 6) and registered in project.yml → Info.plist UIAppFonts.",
         "enum FontFamily {"]
    for role, fam, w, have in _role_lines(css, fams):
        ps = (fams.get(fam, {}).get((w, "normal")) or {}).get("postscript") or convention_name(fam, w, "normal")
        L.append(f"    /// --font-{role}: \"{fam}\" (weight {w}){'' if have else ' — not fetched: falls back to the system font'}")
        L.append(f"    static let {_ident(role)} = \"{ps}\"" if have else f"    static let {_ident(role)}: String? = nil")
        L.append(f"    static let {_ident(role)}Weight: Font.Weight = {_swift_weight(w)}")
    L += ["", "    /// family → weight → PostScript name (upright). Italics are in `italics`."]
    L += _swift_table("names", fams, "normal")
    L += _swift_table("italics", fams, "italic")
    L += ["", "    /// The custom font of a family at a weight (nearest fetched weight), or the system font when the family was not fetched.",
          "    static func font(_ family: String, weight: Int = 400, italic: Bool = false, size: CGFloat) -> Font {",
          "        let table = italic ? italics[family] : names[family]",
          "        guard let table, !table.isEmpty else { return .system(size: size) }",
          "        let w = table.keys.min { abs($0 - weight) < abs($1 - weight) } ?? weight",
          "        return .custom(table[w] ?? table.values.sorted().first!, size: size)",
          "    }", "}", ""]
    return "\n".join(L)


def _swift_table(name, fams, style):
    """`static let <name>: [String: [Int: String]] = [...]` — 비면 `[:]` (Swift 는 빈 딕셔너리 리터럴이 [:] 다)."""
    rows = []
    for fam in sorted(fams):
        tbl = {w: e.get("postscript") or convention_name(fam, w, style) for (w, st), e in fams[fam].items() if st == style}
        if tbl:
            rows.append(f"        \"{fam}\": [" + ", ".join(f"{w}: \"{tbl[w]}\"" for w in sorted(tbl)) + "],")
    head = f"    static let {name}: [String: [Int: String]] = "
    return [head + "[:]"] if not rows else [head + "["] + rows + ["    ]"]


def _swift_weight(w):
    return {100: ".ultraLight", 200: ".thin", 300: ".light", 400: ".regular", 500: ".medium", 600: ".semibold", 700: ".bold", 800: ".heavy", 900: ".black"}.get(w, ".regular")


def _ident(role):
    parts = re.split(r"[^A-Za-z0-9]+", role)
    s = parts[0].lower() + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)
    return s if s and not s[0].isdigit() else "font" + s


def kotlin(css, entries, app_id):
    """Fonts.kt — 역할 → FontFamily(Font(R.font.…, FontWeight)). res/font 이름은 android_name()."""
    fams = _by_family(entries)
    uses_italic = any(st == "italic" for f in fams.values() for (_, st) in f)
    L = [f"package {app_id}.core.designsystem", "",
         "import androidx.compose.ui.text.font.Font", "import androidx.compose.ui.text.font.FontFamily"]
    if uses_italic:
        L.append("import androidx.compose.ui.text.font.FontStyle")
    L += ["import androidx.compose.ui.text.font.FontWeight", f"import {app_id}.R", "",
          "/**", " * Fonts — GENERATED by twbuild from `design/ds/styles.css` (@import · --font-<role>). Do not edit.",
          " * res/font resources are named <family>_<weight>[_italic]; roles match iOS `FontFamily`.", " */",
          "object FontFamilies {"]
    for role, fam, w, have in _role_lines(css, fams):
        L.append(f"    /** --font-{role}: \"{fam}\" (weight {w}){'' if have else ' — not fetched: system default'} */")
        L.append(f"    val {_ident(role)}: FontFamily = {_kt_family(fam, fams.get(fam) or {})}")
        L.append(f"    val {_ident(role)}Weight: FontWeight = FontWeight.{KOTLIN_WEIGHTS.get(w, 'W400')}")
    L += ["", "    /** Every fetched family by name. */", "    val all: Map<String, FontFamily> = mapOf("]
    for fam in sorted(fams):
        L.append(f"        \"{fam}\" to {_kt_family(fam, fams[fam])},")
    L += ["    )", "}", ""]
    return "\n".join(L)


def _kt_family(fam, faces):
    if not faces:
        return "FontFamily.Default"
    fonts = []
    for (w, st) in sorted(faces, key=lambda k: (k[1], k[0])):
        res = android_name(fam, w, st)
        style = ", FontStyle.Italic" if st == "italic" else ""
        fonts.append(f"Font(R.font.{res}, FontWeight.{KOTLIN_WEIGHTS.get(w, 'W400')}{style})")
    return "FontFamily(" + ", ".join(fonts) + ")"


# ─────────────────────────── 패리티 (T9) · 상태 · CLI ───────────────────────────

def _key_of_file(name, idx):
    e = idx.get(name)
    if e:
        return (e["family"], e["weight"], e["style"])
    base = name.rsplit(".", 1)[0]
    fam, _, suffix = base.partition("-")
    italic = suffix.endswith("Italic")
    suffix = suffix[:-6] if italic else suffix
    w = next((k for k, v in WEIGHT_NAMES.items() if v == (suffix or "Regular")), 400)
    return (fam, w, "italic" if italic else "normal")


def _key_of_android(name, idx):
    for e in idx.values():
        if android_name(e["family"], e["weight"], e["style"]) == name:
            return (e["family"], e["weight"], e["style"])
    italic = name.endswith("_italic")
    base = name[:-7] if italic else name
    fam, _, wn = base.rpartition("_")
    w = next((k for k, v in WEIGHT_NAMES.items() if v.lower() == wn), 400)
    return (fam or base, w, "italic" if italic else "normal")


def _ios_registered(root, idx):
    """(iOS 에 복사되고 UIAppFonts 에 등록된 키 집합, 위반 상세 목록)."""
    app = util.app_dir(root, "ios")
    d = os.path.join(app, IOS_FONTS)
    files = sorted(n for n in (os.listdir(d) if os.path.isdir(d) else []) if n.lower().endswith(tuple("." + e for e in EXTS)))
    reg = uiappfonts(util.read_text(os.path.join(app, "project.yml"), ""))
    problems = [f"iOS: {n} 이 Resources/Fonts 에 있지만 project.yml UIAppFonts 에 없다" for n in files if n not in reg]
    problems += [f"iOS: UIAppFonts 의 {n} 이 Resources/Fonts 에 없다" for n in reg if n not in files]
    return {_key_of_file(n, idx) for n in files if n in reg}, problems


def _android_registered(root, idx):
    d = os.path.join(util.app_dir(root, "android"), ANDROID_FONTS)
    files = sorted(n for n in (os.listdir(d) if os.path.isdir(d) else []) if n.lower().endswith(tuple("." + e for e in EXTS)))
    return {_key_of_android(n.rsplit(".", 1)[0], idx) for n in files}, []


def _fmt_key(k):
    return f"{k[0]} {k[1]}{' italic' if k[2] == 'italic' else ''}"


def parity(root, cfg=None):
    """T9 — 두 플랫폼에 등록된 폰트 집합(family · weight · style)이 같다. → [{"rule": RULE, "detail": 한국어}]."""
    cfg = cfg or config.load(root)
    plats = cfg.get("platforms") or []
    idx = index(root)
    out = []
    sets = {}
    if "ios" in plats and os.path.isdir(util.app_dir(root, "ios")):
        sets["ios"], probs = _ios_registered(root, idx)
        out += [{"rule": RULE, "detail": p} for p in probs]
    if "android" in plats and os.path.isdir(util.app_dir(root, "android")):
        sets["android"], _ = _android_registered(root, idx)
    if len(sets) == 2:
        for k in sorted(sets["ios"] - sets["android"]):
            out.append({"rule": RULE, "detail": f"폰트 {_fmt_key(k)} 가 iOS 에만 등록됐다 — Android res/font 에 {android_name(*k)} 가 없다"})
        for k in sorted(sets["android"] - sets["ios"]):
            out.append({"rule": RULE, "detail": f"폰트 {_fmt_key(k)} 가 Android 에만 등록됐다 — iOS Resources/Fonts · UIAppFonts 에 {file_name(*k)} 가 없다"})
    return out


def status(root, cfg=None):
    """doctor 재료 — {"families": [...], "fetched": n, "ios": n, "android": n, "missing": [한국어…]}."""
    cfg = cfg or config.load(root)
    css = util.read_text(os.path.join(root, STYLES), "")
    fams = families(css)
    idx = index(root)
    fetched = {(e["family"], e["weight"], e["style"]) for e in idx.values()}
    missing = [f"받지 않음: {f['family']} {w}{' italic' if st == 'italic' else ''}" for f in fams for w in f["weights"] for st in f["styles"]
               if (f["family"], w, st) not in fetched]
    ios_set, probs = _ios_registered(root, idx) if "ios" in (cfg.get("platforms") or []) and os.path.isdir(util.app_dir(root, "ios")) else (set(), [])
    and_set, _ = _android_registered(root, idx) if "android" in (cfg.get("platforms") or []) and os.path.isdir(util.app_dir(root, "android")) else (set(), [])
    missing += probs + [v["detail"] for v in parity(root, cfg) if v["detail"] not in probs]
    return {"families": [f["family"] for f in fams], "fetched": len(idx), "ios": len(ios_set), "android": len(and_set), "missing": missing,
            "roles": roles(css)}


def summary(st):
    """doctor 한 줄."""
    if not st["families"]:
        return "styles.css 에 웹폰트 없음"
    s = f"가족 {len(st['families'])}({', '.join(st['families'])}) · 받음 {st['fetched']} · iOS {st['ios']} · Android {st['android']}"
    return s + (f" · 빠짐 {len(st['missing'])}" if st["missing"] else "")


def cli(argv, root):
    """`twbuild fonts [fetch|install|status]` — 사람이 읽는 출력은 한국어. → (코드, 텍스트)."""
    cfg = config.load(root)
    cmd = argv[0] if argv else "status"
    if cmd == "fetch":
        r = fetch(root)
        lines = [f"받음 {len(r['files'])} · 그대로 {len(r['skipped'])} · 오류 {len(r['errors'])}"] + [f"  + {f}" for f in r["files"]] + [f"  ! {e}" for e in r["errors"]]
        return (1 if r["errors"] else 0), "\n".join(lines)
    if cmd == "install":
        r = install(root, cfg)
        lines = [f"iOS {len(r['ios'])} · Android {len(r['android'])} · 오류 {len(r['errors'])}"] + [f"  ! {e}" for e in r["errors"]]
        v = parity(root, cfg)
        lines += [f"  {RULE} {x['detail']}" for x in v]
        return (1 if r["errors"] or v else 0), "\n".join(lines)
    if cmd == "status":
        st = status(root, cfg)
        lines = [summary(st)]
        if st["roles"]:
            lines.append("  역할: " + " · ".join(f"{k} → {v}" for k, v in sorted(st["roles"].items())))
        for name, e in _entries(root):
            lines.append(f"  {name:<28} {e.get('postscript', ''):<24} {e.get('bytes', 0):>7} B  {e.get('postscript_from', '')}")
        v = parity(root, cfg)
        lines += [f"  {RULE} {x['detail']}" for x in v]
        lines += [f"  ! {m}" for m in st["missing"] if m not in {x["detail"] for x in v}]
        return (1 if v or st["missing"] else 0), "\n".join(lines)
    return 2, "fonts fetch | install | status"
