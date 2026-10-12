"""레이아웃 트리 — Claude Design 화면 원본(.dc.html)에서 결정적으로 만든 화면 구조 (AGENT.md 1 · 3장). 같은 입력 = 같은 바이트.

  split(html)            → markup(템플릿) · script(로직) · frame(x-import 기기 프레임)
  refs(html)             → 원본이 참조하는 파일 (helmet link/script · x-import from) — 허용 목록을 늘리는 재료
  detect_screens(...)    → 화면 후보: 상태 분기(<sc-if value="{{ isX }}">) · 탭 파생 플래그 · 오버레이(style="{{ xStyle }}")
  layout(...)            → 화면 하나의 트리 {screen, kind, root} — 노드마다 고정 ID(경로 기반), 스타일 속성 전부(토큰과 맞으면 토큰 상수 이름)
  status(layout)         → 노드 수 · 못 잼 · 바인딩 · 핸들러 · 카탈로그 클래스 — intake 시험 실행 보고

트리는 구조의 정본이다 — 두 플랫폼은 중첩 · 순서 · if · list · 핸들러를 그대로 따른다. 다른 화면에 속한 블록은 {"kind": "screen", "ref": id} 슬롯이다.
"""
import html.parser as htmlparser
import re

from . import tokens as tokens_mod
from . import util

VOID = {"br", "img", "input", "hr", "meta", "link", "path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "use", "stop", "source", "wbr"}
TEXT_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "b", "i", "strong", "em", "label", "a", "button", "small", "li"}
KNOWN_TAGS = TEXT_TAGS | {"div", "section", "header", "footer", "main", "nav", "article", "aside", "ul", "ol", "form", "sc-if", "sc-for",
                          "svg", "input", "img", "textarea", "select", "option", "table", "tr", "td", "th", "tbody", "thead"}
SKIP_ATTRS = {"style", "value", "list", "as", "hint-placeholder-val", "hint-placeholder-count", "hint-size", "component-from-global-scope", "from", "dark"}
_BIND = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_WHOLE_BIND = re.compile(r"^\s*\{\{\s*([^{}]+?)\s*\}\}\s*(.*)$", re.S)
_TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>", re.S)
_SCRIPT = re.compile(r'<script\b[^>]*type="text/x-dc"[^>]*>(.*?)</script>', re.S)
_HELMET = re.compile(r"<helmet>.*?</helmet>", re.S)
_XDC = re.compile(r"<x-dc>(.*?)</x-dc>", re.S)
_XIMPORT = re.compile(r'<x-import\b([^>]*)>(.*)</x-import>', re.S)
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
_CSS_VAR = re.compile(r"var\(--([\w-]+)\)")
_PX_TOKEN = re.compile(r"^(-?\d+(?:\.\d+)?)px$")
_HEX_TOKEN = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_RADIUS_PROPS = {"border-radius", "border-top-left-radius", "border-top-right-radius", "border-bottom-left-radius", "border-bottom-right-radius"}
_SPACE_PROPS = {"padding", "margin", "gap", "row-gap", "column-gap", "inset", "top", "left", "right", "bottom"}


# ─────────────────────────── 원본 나누기 ───────────────────────────

def split(html):
    """→ (markup, script, frame). markup 은 <x-dc> 안에서 <helmet> 과 <x-import> 껍데기를 벗긴 템플릿."""
    m = _XDC.search(html or "")
    body = m.group(1) if m else (html or "")
    body = _HELMET.sub("", body)
    frame = None
    mi = _XIMPORT.search(body)
    if mi:
        attrs = dict(_ATTR.findall(mi.group(1)))
        size = [int(x.replace("px", "")) for x in re.findall(r"\d+", attrs.get("hint-size", ""))][:2]
        frame = {"component": attrs.get("component-from-global-scope"), "from": attrs.get("from"), "size": size or None,
                 "dark": "true" in (attrs.get("dark") or "")}
        body = mi.group(2)
    ms = _SCRIPT.search(html or "")
    return body.strip(), (ms.group(1) if ms else ""), frame


def refs(html):
    """원본이 참조하는 경로 — helmet 의 link href · script src, x-import 의 from. './x' → 'x'."""
    out = []
    hm = _HELMET.search(html or "")
    if hm:
        out += re.findall(r'<link\b[^>]*href="([^"]+)"', hm.group(0))
        out += re.findall(r'<script\b[^>]*src="([^"]+)"', hm.group(0))
    out += re.findall(r'<x-import\b[^>]*\bfrom="([^"]+)"', html or "")
    seen, norm = set(), []
    for p in out:
        p = re.sub(r"^\./", "", p.strip())
        if p and p not in seen:
            seen.add(p)
            norm.append(p)
    return norm


# ─────────────────────────── 화면 후보 ───────────────────────────

def _lower_first(s):
    return s[:1].lower() + s[1:]


def _balanced_end(markup, start):
    """start 에서 열리는 태그의 닫힘 끝 위치. 같은 태그 이름으로 깊이를 센다."""
    m = _TAG.match(markup, start)
    if not m:
        return len(markup)
    name = m.group(2).lower()
    if m.group(4) or name in VOID:
        return m.end()
    depth = 0
    for t in _TAG.finditer(markup, start):
        if t.group(2).lower() != name:
            continue
        if t.group(1):
            depth -= 1
            if depth == 0:
                return t.end()
        elif not t.group(4):
            depth += 1
    return len(markup)


def _blocks(markup, pred):
    """pred(tag, attrs) 가 참인 가장 바깥 블록들 [(start, end, attrs)] — 안쪽에 겹치는 것은 빼고 문서 순서."""
    out, pos = [], 0
    while True:
        found = None
        for t in _TAG.finditer(markup, pos):
            if t.group(1) or t.group(4) or t.group(2).lower() in VOID:
                continue
            attrs = dict(_ATTR.findall(t.group(3)))
            if pred(t.group(2).lower(), attrs):
                found = (t.start(), attrs)
                break
        if not found:
            return out
        end = _balanced_end(markup, found[0])
        out.append((found[0], end, found[1]))
        pos = end


def _if_flag(attrs):
    m = _BIND.search(attrs.get("value", "") or "")
    return m.group(1).strip() if m else None


def _style_var(attrs):
    m = _WHOLE_BIND.match(attrs.get("style", "") or "")
    return m.group(1).strip() if m and not m.group(2).strip() else None


def _children(markup, start):
    """start 에서 열리는 요소의 직계 자식 블록 [(s, e, tag, attrs)]."""
    m = _TAG.match(markup, start)
    if not m or m.group(4) or m.group(2).lower() in VOID:
        return []
    end = _balanced_end(markup, start)
    out, pos = [], m.end()
    while pos < end:
        t = _TAG.search(markup, pos, end)
        if not t:
            break
        if t.group(1):                     # 닫는 태그 (부모의 것)
            pos = t.end()
            continue
        if t.group(4) or t.group(2).lower() in VOID:
            out.append((t.start(), t.end(), t.group(2).lower(), dict(_ATTR.findall(t.group(3)))))
            pos = t.end()
            continue
        e = _balanced_end(markup, t.start())
        out.append((t.start(), e, t.group(2).lower(), dict(_ATTR.findall(t.group(3)))))
        pos = e
    return out


def _page_root(markup):
    """페이지 루트 요소(기기 프레임 안의 첫 요소)의 시작 위치. 없으면 None."""
    for t in _TAG.finditer(markup):
        if not t.group(1) and not t.group(4) and t.group(2).lower() not in VOID:
            return t.start()
    return None


def detect_screens(markup, script):
    """화면 후보 목록 — lead 가 확인 · 이름을 고친다 (intake). 못 가르면 lead 과제.

    [{id, kind: state|shell|overlay, when: [플래그], style: [스타일 변수]}]
      state   <sc-if value="{{ isX }}"> 어디에 있든 화면. 탭 비교로 파생된 플래그(showPresetList: s.tab === 'sound')는 그 탭 화면에 붙는다
      shell   is* 분기를 품은 비상태 분기 (탭 바 같은 공용 크롬)
      overlay 페이지 루트 바로 아래의 style="{{ xStyle }}" 블록 (시트 · 전체 화면 오버레이 · 팝오버). backdrop 은 다음 형제에 붙는다
    다른 화면 안에 든 조건 구역(showFavHero 처럼)은 화면이 아니라 그 화면의 if 노드다.
    """
    flags = []
    for m in re.finditer(r'<sc-if\s+value="\{\{\s*(\w+)\s*\}\}"', markup):
        if m.group(1) not in flags:
            flags.append(m.group(1))
    root_start = _page_root(markup)
    top = _children(markup, root_start) if root_start is not None else []
    top_flags = {_if_flag(a) for s, e, t, a in top if t == "sc-if"}
    # 탭 비교로 파생된 플래그 → 그 탭의 화면 (showPresetList: s.tab === 'sound' && …)
    tab_of = {}
    for name, expr in re.findall(r"^\s*(\w+):\s*(.+?),?\s*$", script, re.M):
        mt = re.search(r"\bs\.tab\s*===?\s*'(\w+)'", expr)
        if mt:
            tab_of[name] = mt.group(1)
    screens = []
    by_tab = {}
    for f in flags:
        if f.startswith("is") and len(f) > 2 and f[2].isupper():
            sid = _lower_first(f[2:])
            screens.append({"id": sid, "kind": "state", "when": [f], "style": []})
            if f in tab_of:
                by_tab[tab_of[f]] = screens[-1]
    for f in flags:
        if f.startswith("is") or f not in tab_of:
            continue
        host = by_tab.get(tab_of[f])
        if host:
            host["when"].append(f)
    for f in flags:
        if f.startswith("is") or f in tab_of or f not in top_flags:
            continue        # 다른 화면 안의 조건 구역은 화면이 아니다
        # 페이지 루트 바로 아래의 비상태 분기: is* 분기를 품으면 셸, 아니면 그 자체가 화면
        inner = [b for b in _blocks(markup, lambda t, a: t == "sc-if" and _if_flag(a) == f)]
        hosts = any(re.search(r'<sc-if\s+value="\{\{\s*is[A-Z]', markup[s:e]) for s, e, _ in inner)
        screens.append({"id": "shell" if hosts else _lower_first(f), "kind": "shell" if hosts else "state", "when": [f], "style": []})
    # 오버레이 — 페이지 루트 바로 아래의 style="{{ xStyle }}" 블록. backdrop 은 다음 형제 시트에 붙인다
    root_blocks = [(s, e, a) for s, e, t, a in top if t not in ("sc-if", "sc-for") and _style_var(a) and str(_style_var(a)).lower().endswith("style")]
    pending_backdrop = []
    for s, e, attrs in root_blocks:
        var = _style_var(attrs)
        stem = re.sub(r"(Backdrop|Sheet|Popover)?Style$", "", var)
        if "backdrop" in var.lower():
            pending_backdrop.append(var)
            continue
        sid = _lower_first(stem) if stem else _lower_first(var[:-5])
        screens.append({"id": sid, "kind": "overlay", "when": [], "style": pending_backdrop + [var]})
        pending_backdrop = []
    seen = set()
    for sc in screens:
        base, n = sc["id"], 2
        while sc["id"] in seen:
            sc["id"] = f"{base}{n}"
            n += 1
        seen.add(sc["id"])
    return screens


# ─────────────────────────── 트리 ───────────────────────────

class TokenMap:
    """CSS 값 → 토큰 상수 이름이 있는 조각만 바꾼 값. 바인딩({{ }})은 손대지 않는다."""

    def __init__(self, tk):
        self.by_var, self.dims, self.colors = {}, {}, {}
        for g in tokens_mod.GROUPS:
            for short, e in (tk or {}).get(g, {}).items():
                c = tokens_mod.const(g, short)
                self.by_var[e.get("var", "")] = c
                if e.get("kind") == "dimension":
                    self.dims.setdefault((g, e["px"]), c)
                elif e.get("kind") == "color" and e.get("alpha", 1.0) == 1.0:
                    self.colors.setdefault(e["hex"], c)

    def value(self, prop, val):
        val = val.strip()
        if "{{" in val:
            return val
        out = _CSS_VAR.sub(lambda m: self.by_var.get(m.group(1), m.group(0)), val)
        kind = "radius" if prop in _RADIUS_PROPS else ("space" if prop in _SPACE_PROPS or prop.startswith(("padding-", "margin-")) else None)
        parts = []
        for tok in out.split():
            m = _PX_TOKEN.match(tok)
            if m and kind and (kind, float(m.group(1))) in self.dims:
                parts.append(self.dims[(kind, float(m.group(1)))])
                continue
            if _HEX_TOKEN.match(tok):
                hx = tokens_mod._hex6(tok[1:])[0]
                if hx in self.colors and tokens_mod._hex6(tok[1:])[1] == 1.0:
                    parts.append(self.colors[hx])
                    continue
            parts.append(tok)
        return " ".join(parts)


SVG_D_CAP = 4000
SVG_SHAPE_ATTRS = ("cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "width", "height", "points")


class _Node:
    __slots__ = ("tag", "attrs", "children", "text", "paths", "svg")

    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.children, self.text, self.paths, self.svg = tag, dict(attrs), [], [], 0, []


class _Parser(htmlparser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "use", "stop", "g", "defs"):
            for n in reversed(self.stack):
                if n.tag == "svg":
                    n.paths += 1
                    a = dict(attrs)
                    if tag == "path" and a.get("d"):                   # 경로 데이터 — 두 플랫폼이 같은 아이콘을 그리게 (해시에는 안 들어간다)
                        n.svg.append(str(a["d"])[:SVG_D_CAP])
                    elif tag in ("circle", "rect", "line", "polyline", "polygon", "ellipse"):
                        n.svg.append(tag + "(" + " ".join(f"{k}={v}" for k, v in a.items() if k in SVG_SHAPE_ATTRS) + ")")
                    break
            if tag in ("g", "defs"):
                self.stack.append(_Node(tag, attrs))
            return
        n = _Node(tag, attrs)
        self.stack[-1].children.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID and self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data.strip() and self.stack[-1].tag not in ("svg", "g", "defs"):
            self.stack[-1].text.append(re.sub(r"\s+", " ", data).strip())


def _style(attrs, tm):
    """style 속성 → (style_bind, {속성: 값}). 전체가 바인딩이면 style_bind 만, 앞에 바인딩 + 정적 선언이면 둘 다."""
    raw = attrs.get("style") or ""
    bind = None
    m = _WHOLE_BIND.match(raw)
    if m:
        bind, raw = m.group(1).strip(), m.group(2)
    style = {}
    for part in raw.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip().lower()
            if k:
                style[k] = tm.value(k, v)
    return bind, style


def _text(n):
    text = " ".join(n.text).strip()
    if not text:
        return {}
    names = []

    def ph(m):
        names.append(m.group(1).strip())
        return "{" + m.group(1).strip() + "}"
    fmt = _BIND.sub(ph, text)
    lit = re.sub(r"\{[^{}]+\}", "", fmt).strip()
    if names and not lit:
        return {"bind": names[0] if len(names) == 1 else names}
    if names:
        return {"text": fmt, "params": names, "raw_text": True}
    return {"text": text, "raw_text": True}


def _node_json(n, tm, slots):
    """노드 → JSON. slots: 다른 화면에 속한 플래그/스타일 변수 → 화면 id (슬롯으로 바꾼다)."""
    tag = n.tag
    out = {}
    if tag == "sc-if":
        flag = _if_flag(n.attrs)
        if flag in slots:
            return {"kind": "screen", "ref": slots[flag], "when": flag}
        out["kind"] = "if"
        out["when"] = flag
        if "hint-placeholder-val" in n.attrs:
            out["default"] = (n.attrs.get("hint-placeholder-val") or "").strip("{} ")
    elif tag == "sc-for":
        out["kind"] = "list"
        out["items"] = ((_BIND.search(n.attrs.get("list") or "") or [None, ""])[1] or "").strip() if _BIND.search(n.attrs.get("list") or "") else (n.attrs.get("list") or "")
        out["as"] = n.attrs.get("as")
        if "hint-placeholder-count" in n.attrs:
            out["placeholder_count"] = int(n.attrs["hint-placeholder-count"]) if str(n.attrs["hint-placeholder-count"]).isdigit() else n.attrs["hint-placeholder-count"]
    else:
        sv = _style_var(n.attrs)
        if sv in slots:
            return {"kind": "screen", "ref": slots[sv], "style_bind": sv}
    if tag == "svg":
        out["kind"] = "icon"
        out["icon"] = "raw-svg"
        out["paths"] = n.paths
        if n.svg:
            out["svg"] = list(n.svg)                      # 경로 · 도형 데이터 — 해시에서 빠진다 (구조가 아니라 그림)
        for k in ("width", "height", "viewbox"):
            if k in n.attrs:
                out[k] = n.attrs[k]
    elif tag == "input" or tag == "textarea":
        out["kind"] = "input"
        for k in ("type", "min", "max", "step", "value", "placeholder", "maxlength"):
            if k in n.attrs:
                out[k] = n.attrs[k]
    elif tag == "img":
        out["kind"] = "image"
        out["src"] = n.attrs.get("src")
        if "alt" in n.attrs:
            out["alt"] = n.attrs["alt"]
    bind, style = _style(n.attrs, tm)
    if "kind" not in out:
        disp, fd = style.get("display"), style.get("flex-direction")
        if tag not in KNOWN_TAGS:
            out["kind"] = "unknown"
        elif disp in ("flex", "inline-flex"):
            out["kind"] = "column" if fd and fd.startswith("column") else "row"
        elif disp == "grid":
            out["kind"] = "grid"
        elif n.text and not n.children:
            out["kind"] = "text"
        elif not n.children:
            out["kind"] = "box"
        else:
            out["kind"] = "group"
    if tag not in ("sc-if", "sc-for", "div", "span"):
        out["tag"] = tag
    for k, v in n.attrs.items():
        if k in SKIP_ATTRS:
            continue
        m = re.match(r"sc-camel-on-([a-z-]+)$", k)
        if m:
            out["on_" + m.group(1).replace("-", "_")] = (_BIND.search(v or "") or [None, v])[1].strip() if v else ""
        elif k.startswith("on") and v and "{{" in v:
            out["on_" + k[2:].lower()] = _BIND.search(v).group(1).strip()
        elif k == "class":
            out["class"] = (v or "").split()
        elif k in ("id", "role", "href", "aria-label", "title") or k.startswith(("data-", "hint-")):
            out[k] = v if v is not None else True
    out.update(_text(n))
    if bind:
        out["style_bind"] = bind
    if style:
        out["style"] = style
    kids = []
    for c in n.children:
        j = _node_json(c, tm, slots)
        if not j:
            continue
        # 같은 화면을 가리키는 연속 슬롯(탭 하나가 분기 셋으로 나뉜 경우)은 슬롯 하나다
        if j.get("kind") == "screen" and kids and kids[-1].get("kind") == "screen" and kids[-1].get("ref") == j.get("ref"):
            continue
        kids.append(j)
    if kids:
        out["children"] = kids
    return out


def _assign_ids(node, prefix):
    node["id"] = prefix
    for i, c in enumerate(node.get("children") or []):
        _assign_ids(c, f"{prefix}.{c.get('kind', 'node')}{i}")


def slices(markup, spec):
    """화면 spec 의 마크업 구역들 (문서 순서). when 플래그의 가장 바깥 sc-if 블록 · style 변수의 요소 블록."""
    want_flags, want_styles = set(spec.get("when") or []), set(spec.get("style") or [])
    found = _blocks(markup, lambda t, a: (t == "sc-if" and _if_flag(a) in want_flags) or (_style_var(a) in want_styles))
    return [markup[s:e] for s, e, _ in found]


def layout(markup, spec, all_specs, tm, source="", frame=None):
    """화면 하나의 레이아웃 트리. 다른 화면의 블록은 슬롯으로 바꾼다. 구역이 없으면 root 가 None (못 잼)."""
    slots = {}
    for other in all_specs:
        if other["id"] == spec["id"]:
            continue
        for f in other.get("when") or []:
            slots[f] = other["id"]
        for sv in other.get("style") or []:
            slots[sv] = other["id"]
    pieces = slices(markup, spec)
    roots = []
    for piece in pieces:
        p = _Parser()
        p.feed(piece)
        for c in p.root.children:
            j = _node_json(c, tm, slots)
            if j:
                roots.append(j)
    root = None
    if len(roots) == 1:
        root = roots[0]
    elif roots:
        root = {"kind": "group", "children": roots}
    if root:
        _assign_ids(root, f"n.{spec['id']}")
    out = {"screen": spec["id"], "kind": spec.get("kind", "state"), "when": spec.get("when") or [], "style": spec.get("style") or [],
           "source": source, "frame": frame, "root": root}
    out["hash"] = util.sha_text(util.stable_json(_hashable({k: v for k, v in out.items() if k not in ("hash", "source", "frame")})))[:12]
    return out


def _hashable(n):
    """해시 재료 — 노드의 svg(그림 데이터)는 뺀다. 같은 구조 = 같은 해시."""
    if isinstance(n, dict):
        return {k: _hashable(v) for k, v in n.items() if k != "svg"}
    if isinstance(n, list):
        return [_hashable(v) for v in n]
    return n


def status(lay):
    """시험 실행 보고 — 노드 수 · 못 잼 · 바인딩 · 핸들러 · 리스트 · 분기 · 카탈로그 클래스 · 슬롯."""
    st = {"screen": lay["screen"], "nodes": 0, "unknown": [], "icons": 0, "raw_text": 0, "classes": set(), "binds": set(),
          "handlers": set(), "lists": 0, "ifs": 0, "screen_refs": [], "style_binds": set(), "ok": lay.get("root") is not None}

    def walk(n):
        st["nodes"] += 1
        k = n.get("kind")
        if k == "unknown":
            st["unknown"].append(n.get("tag") or "?")
        elif k == "icon":
            st["icons"] += 1
        elif k == "list":
            st["lists"] += 1
        elif k == "if":
            st["ifs"] += 1
        elif k == "screen":
            st["screen_refs"].append(n.get("ref"))
        if n.get("raw_text"):
            st["raw_text"] += 1
        b = n.get("bind")
        for x in (b if isinstance(b, list) else [b]) if b else []:
            st["binds"].add(x)
        for x in n.get("params") or []:
            st["binds"].add(x)
        for key, v in n.items():
            if key.startswith("on_"):
                st["handlers"].add(v)
        if n.get("style_bind"):
            st["style_binds"].add(n["style_bind"])
        for c in n.get("class") or []:
            st["classes"].add(c)
        for c in n.get("children") or []:
            walk(c)
    if lay.get("root"):
        walk(lay["root"])
    for k in ("classes", "binds", "handlers", "style_binds"):
        st[k] = sorted(st[k])
    return st


def diff_ids(old_root, new_root):
    """두 트리의 노드 ID 단위 차이 → {added, removed, changed}. 재작업 과제의 재료."""
    def index(n, acc):
        if not n:
            return acc
        acc[n["id"]] = util.stable_json({k: v for k, v in n.items() if k != "children"})
        for c in n.get("children") or []:
            index(c, acc)
        return acc
    a, b = index(old_root, {}), index(new_root, {})
    return {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)),
            "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k])}
