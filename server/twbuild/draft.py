"""구조 초안 — 레이아웃 트리 → 네이티브 화면 골격 (AGENT.md 3 · 14장). 생성기는 구조만, 스타일은 개발자가 번역한다.

같은 트리 = 같은 바이트. 컴파일되게 낸다. 확실하지 않은 것은 주석(`// style:` · `// style_bind:` · `// slot:` · `// unknown`)으로 남긴다.
초안은 잠긴 생성물이 아니라 개발자 소유 코드다 — build 가 화면 과제 배차 직전에 양쪽 워크트리에 한 번 생성하고 `draft(<화면>)` 커밋한다.

  analyze(layout)  → UiState 필드 · 리스트 항목 타입 · Action 목록 (트리의 bind · if · list · on_* 에서 결정적으로)
  swift(layout, feature, vars)  → {상대경로: 텍스트}   Features/<Feature>/<Screen>/{View, UiState, Action, ViewModel}.swift
  kotlin(layout, feature, vars) → {상대경로: 텍스트}   features/<feature>/<screen>/{Screen, UiState, Action, ViewModel}.kt
  route_edits(...)              → Route · Router/NavHost 에 화면 추가 (마커 주석 뒤에 삽입, 멱등)
"""
import re

from . import util

VIEW_KINDS = ("row", "column", "grid", "group", "box", "text", "icon", "input", "image", "unknown")
IDENT_RE = re.compile(r"[^0-9A-Za-z]+")


def pascal(s):
    return util.pascal(s) or "X"


def camel(s):
    p = pascal(s)
    return p[:1].lower() + p[1:]


def _flat(expr):
    """'obSlide.title' → 'obSlideTitle' · 'navStyle.home' → 'navStyleHome'."""
    parts = [p for p in re.split(r"[.\[\]]+", expr) if p]
    return parts[0] + "".join(pascal(p) for p in parts[1:]) if parts else "value"


def _item_type(items_expr):
    return pascal(_flat(items_expr)) + "Item"


# ─────────────────────────── 분석 ───────────────────────────

class Analysis:
    def __init__(self):
        self.fields = {}        # UiState: 이름 → 타입 (String · Bool · [Item] · Double)
        self.items = {}         # 항목 타입 이름 → {필드: 타입}
        self.actions = {}       # Action 이름 → [(파라미터 이름, 타입)]
        self.slots = []         # 다른 화면 슬롯 ref

    def field(self, name, typ):
        if name not in self.fields or self.fields[name] == "String":
            self.fields[name] = typ

    def item_field(self, item, name, typ):
        f = self.items.setdefault(item, {})
        if name not in f or f[name] == "String":
            f[name] = typ

    def action(self, name, params):
        self.actions.setdefault(name, params)


def _scope_field(an, expr, typ, scope):
    """표현식이 리스트 변수(as)로 시작하면 항목 필드, 아니면 화면 상태 필드."""
    head = expr.split(".")[0]
    if scope and head in scope:
        rest = expr[len(head) + 1:]
        if rest:
            an.item_field(scope[head], _flat(rest), typ)
        return ("item", head, _flat(rest) if rest else None)
    an.field(_flat(expr), typ)
    return ("state", None, _flat(expr))


def _handler_action(an, expr, scope, extra=None):
    """핸들러 표현식 → (Action 이름, 인자 코드 목록). 리스트 안이면 항목을 인자로 넘긴다."""
    head = expr.split(".")[0]
    params = []
    if scope and head in scope:
        item_type = scope[head]
        rest = expr[len(head) + 1:] or "tap"
        name = camel(item_type[:-4] if item_type.endswith("Item") else item_type) + pascal(_flat(rest))
        params.append(("item", item_type))
    else:
        name = camel(_flat(expr))
    if extra:
        params.append(extra)
    an.action(name, params)
    return name


def analyze(lay):
    an = Analysis()

    def walk(n, scope):
        k = n.get("kind")
        if k == "screen":
            an.slots.append(n.get("ref"))
            return
        if k == "if":
            _scope_field(an, n["when"], "Bool", scope)
        elif k == "list":
            it = _item_type(n["items"])
            an.field(_flat(n["items"]), f"[{it}]")
            an.items.setdefault(it, {})
            scope = {**scope, n.get("as") or "item": it}
        b = n.get("bind")
        for x in (b if isinstance(b, list) else [b]) if b else []:
            _scope_field(an, x, "String", scope)
        for x in n.get("params") or []:
            _scope_field(an, x, "String", scope)
        if n.get("style_bind"):
            _scope_field(an, n["style_bind"], "String", scope)
        for v in (n.get("style") or {}).values():          # background:{{ p.grad }} 처럼 값 안의 바인딩도 상태/항목 필드다
            for m in re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", str(v)):
                _scope_field(an, m.group(1).strip(), "String", scope)
        for key, v in n.items():
            if key.startswith("on_"):
                if key == "on_input" and k == "input":
                    extra = ("value", "Double" if n.get("type") == "range" else "String")
                    _handler_action(an, v, scope, extra)
                else:
                    _handler_action(an, v, scope)
        if k == "input" and n.get("value") and "{{" not in str(n.get("value")):
            pass
        if k == "input":
            # value="{{ x }}" 는 바인딩 — 트리에는 attr 로 남아 있다
            m = re.search(r"\{\{\s*([^{}]+?)\s*\}\}", str(n.get("value") or ""))
            if m:
                _scope_field(an, m.group(1).strip(), "Double" if n.get("type") == "range" else "String", scope)
        for c in n.get("children") or []:
            walk(c, scope)
    if lay.get("root"):
        walk(lay["root"], {})
    return an


# ─────────────────────────── 공통 ───────────────────────────

def _style_comment(n, pad, cmt="//"):
    out = []
    if n.get("style_bind"):
        out.append(f"{pad}{cmt} style_bind: {n['style_bind']}")
    if n.get("style"):
        out.append(f"{pad}{cmt} style: " + "; ".join(f"{k}: {v}" for k, v in n["style"].items()))
    if n.get("class"):
        out.append(f"{pad}{cmt} class: {' '.join(n['class'])}  (design-system component)")
    return out


def catalog_component(n, catalog):
    """노드의 class 가운데 카탈로그 컴포넌트(Pascal 이름)에 있는 것 — 없으면 None. 생성기와 게이트(T8)가 같은 판정을 쓴다."""
    for c in n.get("class") or []:
        name = pascal(c)
        if name in (catalog or ()):
            return name
    return None


def _grid_cols(n):
    cols = str((n.get("style") or {}).get("grid-template-columns", ""))
    c = len(cols.split()) if cols else 2
    return max(1, min(c, 6))


def _text_expr(n, scope, lang, an=None):
    """문구 노드 → 코드 표현식. 바인딩은 상태/항목 필드(문자열이 아니면 문자열로 바꿔서), 섞인 문구는 보간."""
    b = n.get("bind")
    if b and not isinstance(b, list):
        r = _ref(b, scope, lang)
        if an is not None and _field_type(an, b, scope) != "String":
            return ('"\\(' + r + ')"') if lang == "swift" else ('"${' + r + '}"')
        return r
    if n.get("text") and n.get("params"):
        s = _quote(n["text"])        # 리터럴을 먼저 이스케이프하고 자리표시만 보간으로 바꾼다 (보간의 백슬래시는 살린다)
        for p in n["params"]:
            r = _ref(p, scope, lang)
            s = s.replace("{" + p + "}", ("\\(" + r + ")") if lang == "swift" else ("${" + r + "}"))
        return s
    return _quote(n.get("text") or "")


def _field_type(an, expr, scope):
    head = expr.split(".")[0]
    if scope and head in scope:
        rest = expr[len(head) + 1:]
        return (an.items.get(scope[head]) or {}).get(_flat(rest), "String") if rest else "String"
    return an.fields.get(_flat(expr), "String")


def _ref(expr, scope, lang):
    head = expr.split(".")[0]
    if scope and head in scope:
        rest = expr[len(head) + 1:]
        return f"{head}.{_flat(rest)}" if rest else head
    return f"state.{_flat(expr)}"


def _quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _is_zstack(n):
    return any("absolute" in str((c.get("style") or {}).get("position", "")) for c in n.get("children") or [])


# ─────────────────────────── Swift ───────────────────────────

def _swift_type(t):
    return t


def _swift_node(n, an, scope, depth, out, wrapped=False):
    pad = "    " * depth
    k = n.get("kind")
    nid = n.get("id", "")
    comp = None if (wrapped or k in ("if", "list", "screen")) else catalog_component(n, getattr(an, "catalog", ()))
    if comp:                                             # 카탈로그 컴포넌트로 감싼다 (T8) — 노드 자체(구조 · ID)는 그 안에 그대로
        out.append(f"{pad}{comp} {{  // catalog component ← class {' '.join(n.get('class') or [])}")
        _swift_node(n, an, scope, depth + 1, out, wrapped=True)
        out.append(f"{pad}}}")
        return
    out += _style_comment(n, pad)
    if k == "screen":
        out.append(f"{pad}// slot: {n.get('ref')} — host {pascal(n.get('ref'))}View here (built as its own screen)")
        out.append(f"{pad}Color.clear.accessibilityIdentifier({_quote(nid)})")
        return
    if k == "if":
        out.append(f"{pad}if {_ref(n['when'], scope, 'swift')} {{")
        for c in n.get("children") or []:
            _swift_node(c, an, scope, depth + 1, out)
        out.append(f"{pad}}}")
        return
    if k == "list":
        var = n.get("as") or "item"
        out.append(f"{pad}ForEach({_ref(n['items'], scope, 'swift')}) {{ {var} in")
        for c in n.get("children") or []:
            _swift_node(c, an, {**scope, var: _item_type(n["items"])}, depth + 1, out)
        out.append(f"{pad}}}")
        return
    mods = [f".accessibilityIdentifier({_quote(nid)})"]
    for key, v in n.items():
        if key == "on_click":
            name = _handler_action(an, v, scope)
            args = _action_args(an, name, scope, v)
            mods.append(f".onTapGesture {{ viewModel.send(.{name}{args}) }}")
    if k in ("row", "column", "grid", "group", "box"):
        if k == "row":
            opener = "HStack {"
        elif k == "column":
            opener = "VStack {"
        elif k == "grid":
            cols = ", ".join(["GridItem(.flexible())"] * _grid_cols(n))
            opener = f"LazyVGrid(columns: [{cols}]) {{"
        elif k == "group":
            opener = "ZStack {" if _is_zstack(n) else "VStack {"
        else:
            opener = "ZStack {"
        kids = n.get("children") or []
        text = n.get("text") or n.get("bind")
        out.append(f"{pad}{opener}")
        if text:
            out.append(f"{pad}    Text({_text_expr(n, scope, 'swift', an)})")
        for c in kids:
            _swift_node(c, an, scope, depth + 1, out)
        if not kids and not text:
            out.append(f"{pad}    Color.clear")
        out.append(f"{pad}}}")
    elif k == "text":
        out.append(f"{pad}Text({_text_expr(n, scope, 'swift', an)})")
    elif k == "icon":
        out.append(f"{pad}Image(systemName: \"circle\")  // raw-svg ({n.get('paths', 0)} paths, {n.get('width', '?')}x{n.get('height', '?')}) — replace with the asset")
    elif k == "image":
        out.append(f"{pad}Image({_quote(str(n.get('src') or ''))})")
    elif k == "input":
        val = re.search(r"\{\{\s*([^{}]+?)\s*\}\}", str(n.get("value") or ""))
        vref = _ref(val.group(1).strip(), scope, "swift") if val else _quote("")
        handler = n.get("on_input")
        if n.get("type") == "range":
            if handler:
                name = _handler_action(an, handler, scope, ("value", "Double"))
                args = _action_args(an, name, scope, handler, extra="$0")
                setter = f"viewModel.send(.{name}{args})"
            else:
                setter = "_ = $0"
            out.append(f"{pad}Slider(value: Binding(get: {{ {vref} }}, set: {{ {setter} }}), in: {n.get('min', 0)}...{n.get('max', 100)})")
        else:
            if handler:
                name = _handler_action(an, handler, scope, ("value", "String"))
                args = _action_args(an, name, scope, handler, extra="$0")
                setter = f"viewModel.send(.{name}{args})"
            else:
                setter = "_ = $0"
            out.append(f"{pad}TextField({_quote(str(n.get('placeholder') or ''))}, text: Binding(get: {{ {vref} }}, set: {{ {setter} }}))")
    else:
        out.append(f"{pad}EmptyView()  // unknown tag <{n.get('tag')}> — 못 잼")
    for m in mods:
        out[-1] = out[-1] if k in ("row", "column", "grid", "group", "box") else out[-1]
    # 수정자는 마지막 뷰 표현식(또는 닫는 괄호) 뒤에 붙인다
    if k in ("row", "column", "grid", "group", "box"):
        out[-1] = out[-1] + "".join(mods)
    elif k == "icon":
        line = out[-1].split("  //", 1)
        out[-1] = line[0] + "".join(mods) + ("  //" + line[1] if len(line) > 1 else "")
    elif k == "unknown":
        line = out[-1].split("  //", 1)
        out[-1] = line[0] + "".join(mods) + ("  //" + line[1] if len(line) > 1 else "")
    else:
        out[-1] = out[-1] + "".join(mods)


def _action_args(an, name, scope, expr, extra=None):
    params = an.actions.get(name) or []
    vals = []
    head = expr.split(".")[0]
    for pname, ptype in params:
        if pname == "item":
            vals.append(head if scope and head in scope else "item")
        elif pname == "value":
            vals.append(extra or "value")
    return "(" + ", ".join(vals) + ")" if vals else ""


def swift(lay, feature, vars_, catalog=()):
    """{상대경로(apps/ios 기준): 텍스트}. catalog: 이미 구현된 카탈로그 컴포넌트 이름 — class 노드를 그것으로 감싼다."""
    an = analyze(lay)
    an.catalog = set(catalog or ())
    screen = lay["screen"]
    S = pascal(screen)
    F = pascal(feature)
    base = f"App/Features/{F}/{S}"
    body = []
    if lay.get("root"):
        _swift_node(lay["root"], an, {}, 3, body)
    else:
        body.append("            Text(\"(no layout)\")")
    an2 = an      # body 생성 중 발견된 action 인자까지 반영된 분석
    files = {}
    files[f"{base}/{S}View.swift"] = "\n".join([
        "import SwiftUI", "",
        f"/// {S} — structure draft GENERATED by twbuild from design/{feature}/layout/{screen}.json (tree {lay.get('hash', '')}).",
        "/// Keep the nesting, order, `if`/`ForEach` and accessibility identifiers exactly; translate the `// style:` comments with ios-translate.",
        "/// This file is yours after generation — the draft is a starting point, not a locked artifact.",
        f"struct {S}View: View {{",
        f"    @State private var viewModel: {S}ViewModel",
        "",
        "    init(container: AppContainer) {",
        f"        _viewModel = State(initialValue: {S}ViewModel(container: container))",
        "    }",
        "",
        "    var body: some View {",
        "        let state = viewModel.state",
        "        ScrollView {",
        *body,
        "        }",
        f"        .accessibilityIdentifier({_quote('n.' + screen)})",
        "    }",
        "}", ""])
    st = ["import Foundation", "",
          f"/// UiState of {S} — GENERATED from the tree's `bind` · `if` · `list` keys. Immutable; only the ViewModel replaces it.",
          f"struct {S}UiState: Equatable {{"]
    for name, typ in sorted(an2.fields.items()):
        st.append(f"    var {name}: {typ} = {_swift_default(typ)}")
    st.append("}")
    for item, fields in sorted(an2.items.items()):
        st += ["", f"struct {item}: Identifiable, Equatable {{", "    var id: String = UUID().uuidString"]
        for name, typ in sorted(fields.items()):
            if name != "id":
                st.append(f"    var {name}: {typ} = {_swift_default(typ)}")
        st.append("}")
    files[f"{base}/{S}UiState.swift"] = "\n".join(st + [""])
    ac = ["import Foundation", "", f"/// Actions of {S} — GENERATED from the tree's `on_*` handlers. The View sends, the ViewModel handles.",
          f"enum {S}Action: Equatable {{"]
    for name, params in sorted(an2.actions.items()):
        if params:
            ac.append(f"    case {name}({', '.join(t for _, t in params)})")
        else:
            ac.append(f"    case {name}")
    if not an2.actions:
        ac.append("    case noop")
    ac.append("}")
    files[f"{base}/{S}Action.swift"] = "\n".join(ac + [""])
    vm = ["import Foundation", "import Observation", "",
          f"/// ViewModel of {S} — MVVM + UDF: Action in, new UiState out. Data comes from the container's repositories/stores.",
          "@Observable",
          f"final class {S}ViewModel {{",
          f"    private(set) var state = {S}UiState()",
          "    private let container: AppContainer", "",
          "    init(container: AppContainer) {", "        self.container = container", "    }", "",
          f"    func send(_ action: {S}Action) {{",
          "        switch action {"]
    for name, params in sorted(an2.actions.items()):
        vm.append(f"        case .{name}:" if not params else f"        case .{name}:")
        vm.append("            break  // TODO: handle")
    if not an2.actions:
        vm += ["        case .noop:", "            break"]
    vm += ["        }", "    }", "}", ""]
    files[f"{base}/{S}ViewModel.swift"] = "\n".join(vm)
    return files


def _swift_default(typ):
    if typ == "Bool":
        return "false"
    if typ == "Double":
        return "0"
    if typ.startswith("["):
        return "[]"
    return '""'


# ─────────────────────────── Kotlin ───────────────────────────

def _kt_node(n, an, scope, depth, out, in_lazy=False, wrapped=False):
    pad = "    " * depth
    k = n.get("kind")
    nid = n.get("id", "")
    comp = None if (wrapped or k in ("if", "list", "screen")) else catalog_component(n, getattr(an, "catalog", ()))
    if comp:                                             # 카탈로그 컴포넌트로 감싼다 (T8)
        out.append(f"{pad}{comp} {{  // catalog component ← class {' '.join(n.get('class') or [])}")
        _kt_node(n, an, scope, depth + 1, out, in_lazy, wrapped=True)
        out.append(f"{pad}}}")
        return
    out += _style_comment(n, pad)
    if k == "screen":
        out.append(f"{pad}// slot: {n.get('ref')} — host {pascal(n.get('ref'))}Screen here (built as its own screen)")
        out.append(f"{pad}Box(modifier = Modifier.testTag({_quote(nid)}))")
        return
    if k == "if":
        out.append(f"{pad}if ({_ref(n['when'], scope, 'kt')}) {{")
        for c in n.get("children") or []:
            _kt_node(c, an, scope, depth + 1, out, in_lazy)
        out.append(f"{pad}}}")
        return
    if k == "list":
        var = n.get("as") or "item"
        items = _ref(n["items"], scope, "kt")
        if in_lazy:
            out.append(f"{pad}items({items}) {{ {var} ->")
        else:
            out.append(f"{pad}{items}.forEach {{ {var} ->")
        for c in n.get("children") or []:
            _kt_node(c, an, {**scope, var: _item_type(n["items"])}, depth + 1, out, False)
        out.append(f"{pad}}}")
        return
    mod = [f"Modifier.testTag({_quote(nid)})"]
    for key, v in n.items():
        if key == "on_click":
            name = _handler_action(an, v, scope)
            args = _action_args(an, name, scope, v)
            mod.append(f".clickable {{ onAction({pascal(_screen_of(an))}Action.{pascal(name)}{args}) }}")
    m = "".join(mod)
    if k in ("row", "column", "grid", "group", "box"):
        kids = n.get("children") or []
        text = n.get("text") or n.get("bind")
        lazy = False
        if k == "row":
            opener = f"Row(modifier = {m}) {{"
        elif k == "column":
            opener = f"Column(modifier = {m}) {{"
        elif k == "grid":
            opener = f"LazyVerticalGrid(columns = GridCells.Fixed({_grid_cols(n)}), modifier = {m}) {{"
            lazy = True
        else:
            opener = f"Box(modifier = {m}) {{" if (k == "box" or _is_zstack(n)) else f"Column(modifier = {m}) {{"
        out.append(f"{pad}{opener}")
        if text:
            line = f"Text(text = {_text_expr(n, scope, 'kt', an)})"
            out.append(f"{pad}    " + (f"item {{ {line} }}" if lazy else line))
        for c in kids:
            if lazy and c.get("kind") not in ("list",):
                out.append(f"{pad}    item {{")
                _kt_node(c, an, scope, depth + 2, out, False)
                out.append(f"{pad}    }}")
            else:
                _kt_node(c, an, scope, depth + 1, out, lazy)
        out.append(f"{pad}}}")
    elif k == "text":
        out.append(f"{pad}Text(text = {_text_expr(n, scope, 'kt', an)}, modifier = {m})")
    elif k == "icon":
        out.append(f"{pad}Box(modifier = {m}.size(24.dp))  // raw-svg ({n.get('paths', 0)} paths, {n.get('width', '?')}x{n.get('height', '?')}) — replace with the asset")
    elif k == "image":
        out.append(f"{pad}Box(modifier = {m})  // image: {n.get('src')}")
    elif k == "input":
        val = re.search(r"\{\{\s*([^{}]+?)\s*\}\}", str(n.get("value") or ""))
        vref = _ref(val.group(1).strip(), scope, "kt") if val else _quote("")
        handler = n.get("on_input")
        A = pascal(_screen_of(an)) + "Action"
        if n.get("type") == "range":
            if handler:
                name = _handler_action(an, handler, scope, ("value", "Double"))
                args = _action_args(an, name, scope, handler, extra="it.toDouble()")
                setter = f"onAction({A}.{pascal(name)}{args})"
            else:
                setter = "Unit"
            out.append(f"{pad}Slider(value = ({vref}).toFloat(), onValueChange = {{ {setter} }}, valueRange = {n.get('min', 0)}f..{n.get('max', 100)}f, modifier = {m})")
        else:
            if handler:
                name = _handler_action(an, handler, scope, ("value", "String"))
                args = _action_args(an, name, scope, handler, extra="it")
                setter = f"onAction({A}.{pascal(name)}{args})"
            else:
                setter = "Unit"
            out.append(f"{pad}TextField(value = {vref}, onValueChange = {{ {setter} }}, placeholder = {{ Text({_quote(str(n.get('placeholder') or ''))}) }}, modifier = {m})")
    else:
        out.append(f"{pad}Box(modifier = {m})  // unknown tag <{n.get('tag')}> — 못 잼")


def _screen_of(an):
    return an.screen


def kotlin(lay, feature, vars_, catalog=()):
    """{상대경로(apps/android 기준): 텍스트}"""
    an = analyze(lay)
    an.catalog = set(catalog or ())
    an.screen = lay["screen"]
    screen = lay["screen"]
    S = pascal(screen)
    pkg = vars_["id"]
    feat = re.sub(r"[^a-z0-9]", "", feature.lower()) or "feature"
    scr = re.sub(r"[^a-z0-9]", "", screen.lower()) or "screen"
    base = f"app/src/main/kotlin/{pkg.replace('.', '/')}/features/{feat}/{scr}"
    P = f"{pkg}.features.{feat}.{scr}"
    body = []
    if lay.get("root"):
        _kt_node(lay["root"], an, {}, 3, body)
    else:
        body.append('            Text(text = "(no layout)")')
    files = {}
    files[f"{base}/{S}Screen.kt"] = "\n".join([
        f"package {P}", "",
        "import androidx.compose.foundation.clickable",
        "import androidx.compose.foundation.layout.Box",
        "import androidx.compose.foundation.layout.Column",
        "import androidx.compose.foundation.layout.Row",
        "import androidx.compose.foundation.layout.size",
        "import androidx.compose.foundation.lazy.grid.GridCells",
        "import androidx.compose.foundation.lazy.grid.LazyVerticalGrid",
        "import androidx.compose.foundation.lazy.grid.items",
        "import androidx.compose.foundation.rememberScrollState",
        "import androidx.compose.foundation.verticalScroll",
        "import androidx.compose.material3.Slider",
        "import androidx.compose.material3.Text",
        "import androidx.compose.material3.TextField",
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.runtime.getValue",
        "import androidx.compose.ui.Modifier",
        "import androidx.compose.ui.platform.testTag",
        "import androidx.compose.ui.unit.dp",
        "import androidx.lifecycle.compose.collectAsStateWithLifecycle", "",
        f"/** {S} — structure draft GENERATED by twbuild from design/{feature}/layout/{screen}.json (tree {lay.get('hash', '')}).",
        " *  Keep the nesting, order, `if`/`items` and test tags exactly; translate the `// style:` comments with android-translate.",
        " *  This file is yours after generation — the draft is a starting point, not a locked artifact. */",
        "@Composable",
        f"fun {S}Screen(viewModel: {S}ViewModel, modifier: Modifier = Modifier) {{",
        "    val state by viewModel.state.collectAsStateWithLifecycle()",
        f"    {S}Content(state = state, onAction = viewModel::onAction, modifier = modifier)",
        "}", "",
        "@Composable",
        f"fun {S}Content(state: {S}UiState, onAction: ({S}Action) -> Unit, modifier: Modifier = Modifier) {{",
        f"    Column(modifier = modifier.verticalScroll(rememberScrollState()).testTag({_quote('n.' + screen)})) {{",
        *body,
        "    }",
        "}", ""])
    st = [f"package {P}", "", f"/** UiState of {S} — GENERATED from the tree's `bind` · `if` · `list` keys. Immutable; only the ViewModel replaces it. */",
          f"data class {S}UiState("]
    fields = sorted(an.fields.items())
    for i, (name, typ) in enumerate(fields):
        st.append(f"    val {name}: {_kt_type(typ)} = {_kt_default(typ)},")
    if not fields:
        st.append("    val placeholder: Boolean = false,")
    st.append(")")
    for item, f in sorted(an.items.items()):
        st += ["", f"data class {item}(", '    val id: String = "",']
        for name, typ in sorted(f.items()):
            if name != "id":
                st.append(f"    val {name}: {_kt_type(typ)} = {_kt_default(typ)},")
        st.append(")")
    files[f"{base}/{S}UiState.kt"] = "\n".join(st + [""])
    ac = [f"package {P}", "", f"/** Actions of {S} — GENERATED from the tree's `on_*` handlers. The Screen sends, the ViewModel handles. */",
          f"sealed interface {S}Action {{"]
    for name, params in sorted(an.actions.items()):
        if params:
            ac.append(f"    data class {pascal(name)}({', '.join(f'val {p}: {_kt_type(t)}' for p, t in params)}) : {S}Action")
        else:
            ac.append(f"    data object {pascal(name)} : {S}Action")
    if not an.actions:
        ac.append(f"    data object Noop : {S}Action")
    ac.append("}")
    files[f"{base}/{S}Action.kt"] = "\n".join(ac + [""])
    vm = [f"package {P}", "",
          "import androidx.lifecycle.ViewModel",
          f"import {pkg}.core.AppContainer",
          "import kotlinx.coroutines.flow.MutableStateFlow",
          "import kotlinx.coroutines.flow.StateFlow",
          "import kotlinx.coroutines.flow.asStateFlow", "",
          f"/** ViewModel of {S} — MVVM + UDF: Action in, new UiState out. Data comes from the container's repositories/stores. */",
          f"class {S}ViewModel(private val container: AppContainer) : ViewModel() {{",
          f"    private val _state = MutableStateFlow({S}UiState())",
          f"    val state: StateFlow<{S}UiState> = _state.asStateFlow()", "",
          f"    fun onAction(action: {S}Action) {{",
          "        when (action) {"]
    for name, params in sorted(an.actions.items()):
        vm.append(f"            is {S}Action.{pascal(name)} -> Unit  // TODO: handle")
    if not an.actions:
        vm.append(f"            is {S}Action.Noop -> Unit")
    vm += ["        }", "    }", "}", ""]
    files[f"{base}/{S}ViewModel.kt"] = "\n".join(vm)
    return files


def _kt_type(t):
    if t == "Bool":
        return "Boolean"
    if t.startswith("["):
        return f"List<{t[1:-1]}>"
    return t


def _kt_default(t):
    if t == "Bool":
        return "false"
    if t == "Double":
        return "0.0"
    if t.startswith("["):
        return "emptyList()"
    return '""'


# ─────────────────────────── 라우트 추가 (멱등) ───────────────────────────

ROUTE_MARK_SWIFT = "// Screens are appended here by the build step"
ROUTER_MARK_SWIFT = "// Screens are appended here by the build step, e.g. `case .detail(let id): DetailView(...)`."
ROUTE_MARK_KT = "// Screens are appended here by the build step"
NAV_MARK_KT = "// Screens are appended here by the build step."


def _insert_after(text, marker, lines):
    """마커 줄 뒤에 줄들을 넣는다 — 이미 있으면 그대로."""
    if not text or marker not in text:
        return text, False
    if all(l.strip() in text for l in lines):
        return text, False
    idx = text.index(marker)
    eol = text.index("\n", idx) + 1
    indent = re.match(r"[ \t]*", text[text.rfind("\n", 0, idx) + 1:idx]).group(0)
    block = "".join(indent + l + "\n" for l in lines)
    return text[:eol] + block + text[eol:], True


def route_edits(screen, feature, vars_, read):
    """화면을 Route · Router(NavHost) 에 등록하는 편집 — {상대경로: 새 텍스트}. read(rel) 로 현재 내용을 받는다."""
    S = pascal(screen)
    s = camel(screen)
    pkg = vars_["id"]
    feat = re.sub(r"[^a-z0-9]", "", feature.lower()) or "feature"
    scr = re.sub(r"[^a-z0-9]", "", screen.lower()) or "screen"
    out = {}
    rel = "apps/ios/App/Core/Navigation/Route.swift"
    t, ch = _insert_after(read(rel), ROUTE_MARK_SWIFT, [f"case {s}"])
    if ch:
        out[rel] = t
    rel = "apps/ios/App/Core/Navigation/Router.swift"
    t, ch = _insert_after(read(rel), ROUTER_MARK_SWIFT, [f"case .{s}:", f"    {S}View(container: container)"])
    if ch:
        out[rel] = t
    rel = f"apps/android/app/src/main/kotlin/{pkg.replace('.', '/')}/core/navigation/Route.kt"
    t, ch = _insert_after(read(rel), ROUTE_MARK_KT, ["@Serializable", f"data object {S} : Route"])
    if ch:
        out[rel] = t
    rel = f"apps/android/app/src/main/kotlin/{pkg.replace('.', '/')}/features/root/RootScreen.kt"
    cur = read(rel)
    imports = [f"import {pkg}.features.{feat}.{scr}.{S}Screen", f"import {pkg}.features.{feat}.{scr}.{S}ViewModel",
               "import androidx.lifecycle.viewmodel.compose.viewModel"]
    t, ch = _insert_after(cur, NAV_MARK_KT, [f"composable<Route.{S}> {{ {S}Screen(viewModel = viewModel {{ {S}ViewModel(container) }}) }}"])
    if ch:
        for imp in imports:
            if imp not in t:
                t = t.replace("\nimport ", f"\n{imp}\nimport ", 1)
        out[rel] = t
    return out
