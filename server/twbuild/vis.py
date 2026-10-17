"""시각 비교(vis) — 디자인 기준 이미지 · 기기 스크린샷을 나란히 놓고 차이를 잰다 (6장 기기 층 · 화면 순회).

게이트 T1~T11 은 구조(노드 · 이름 · 타입 · 토큰)를 본다. 시트가 반투명하다 · 배경막이 회색이다 · 하위 탭이 카드 위에 겹친다 같은
"보이는 모양" 은 구조가 맞아도 틀린다 (실측 2026-10-17: Android 결함 4건이 게이트와 순회를 통과했다). 그래서 사람이 보는 그림을 같이 만든다.

  기준 이미지  design/<범위>/shots/<화면>.png — design run 안에서 Claude Design 미리보기(render_preview 의 serve_url)를 헤드리스 Chrome 으로 연다.
               디자인 런타임(support.js)은 받지 않으므로(D3) 호스팅된 미리보기를 쓴다. 문서 응답만 가로채 로직 인스턴스를 window 에 건다.
               화면마다 보이는 상태는 디자인 안에서 찾는다: 트리의 모든 on_click 핸들러를 실제로 불러 보며(넓이 우선) 각 화면이 처음 보이는 상태를 고른다.
               (트리의 when · style 로 화면이 보이는지 판정 — tree.detect_screens 와 같은 기준.) 기기 프레임은 둥근 모서리를 빼고 3배로 찍는다.
  비교         비교 이미지(디자인 | iOS | Android) + 칸별 색 차이 점수 — 같은 Chrome 의 캔버스로 잰다. 점수는 우선순위 신호다: 데이터 · 글꼴 · 시계가 달라 0 이 될 수 없다.
               판정은 사람(lead)이 비교 이미지를 보고 한다.

serve_url 은 토큰이 든 단기 링크다 — 파일 · 로그 · 보고서에 남기지 않는다 (인자로만 받는다).
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

from . import util

SHOTS = "shots"
SCALE = 3                                   # 기기 프레임 402×874 × 3 = iPhone 17 Pro 시뮬레이터 1206×2622
CHROMES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium",
           "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
           "google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
HOT = 0.18                                  # 칸 차이가 이보다 크면 뜨거운 칸 (0~1)
EDGE = 6                                    # 윤곽 밀도 차이 배율 — 색 차이와 같은 눈금으로


class VisError(RuntimeError):
    pass


def chrome():
    """헤드리스 Chrome 경로 — TWBUILD_CHROME 이 먼저. 없으면 None."""
    for c in ((os.environ.get("TWBUILD_CHROME") or ""),) + CHROMES:
        if c and (os.path.isfile(c) or shutil.which(c)):
            return c if os.path.isfile(c) else shutil.which(c)
    return None


# ─────────────────────────── DevTools 프로토콜 ───────────────────────────

class Browser:
    """헤드리스 Chrome 하나 + 페이지 하나. 표준 라이브러리 + websockets(sync)."""

    def __init__(self, timeout=60):
        exe = chrome()
        if not exe:
            raise VisError("Chrome 이 없다 — Google Chrome 을 설치하거나 TWBUILD_CHROME 에 경로를 둔다")
        self.dir = tempfile.mkdtemp(prefix="twvis-")
        self.proc = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={self.dir}",
                                      "--no-first-run", "--no-default-browser-check", "--hide-scrollbars", "--mute-audio",
                                      "--disable-gpu", "--window-size=1200,1000", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = os.path.join(self.dir, "DevToolsActivePort")
        deadline = time.time() + 20
        while not (os.path.isfile(port_file) and len(util.read_text(port_file).split()) >= 2):
            if time.time() > deadline or self.proc.poll() is not None:
                self.close()
                raise VisError("Chrome 이 디버깅 포트를 열지 않았다")
            time.sleep(0.1)
        port = util.read_text(port_file).split()[0]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            page = json.loads(r.read().decode())
        from websockets.sync.client import connect
        self.ws = connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=10)
        self.timeout = timeout
        self.n = 0
        self.events = []

    def send(self, method, params=None, timeout=None):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + (timeout or self.timeout)
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise VisError(f"{method}: 응답 없음")
            msg = json.loads(self.ws.recv(timeout=left))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise VisError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result") or {}
            if "method" in msg:
                self.events.append(msg)

    def fire(self, method, params=None):
        """응답을 기다리지 않고 보낸다 — 가로챈 요청이 풀려야 답이 오는 명령(Page.navigate)."""
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))

    def event(self, method, timeout=30):
        for i, e in enumerate(self.events):
            if e["method"] == method:
                return self.events.pop(i)
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise VisError(f"{method}: 이벤트 없음")
            msg = json.loads(self.ws.recv(timeout=left))
            if msg.get("method") == method:
                return msg
            if "method" in msg:
                self.events.append(msg)

    def eval(self, expr, timeout=None):
        r = self.send("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, timeout=timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            raise VisError("JS: " + str((d.get("exception") or {}).get("description") or d.get("text"))[:400])
        return (r.get("result") or {}).get("value")

    def wait(self, expr, timeout=30, every=0.2):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.eval(expr):
                    return True
            except VisError:
                pass
            time.sleep(every)
        return False

    def shot(self, path, clip=None):
        p = {"format": "png", "captureBeyondViewport": False}
        if clip:
            p["clip"] = {**clip, "scale": 1}
        data = self.send("Page.captureScreenshot", p, timeout=60)["data"]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path

    def close(self):
        try:
            self.ws.close()
        except Exception:                                          # noqa: BLE001
            pass
        if getattr(self, "proc", None) and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


# ─────────────────────────── 기준 이미지 ───────────────────────────

HOOK = "__twLogic = (window.__tw = this, 0);"            # 로직 클래스 필드 — 생성될 때 인스턴스를 건다

EXPLORE = r"""
async (spec) => {
  const L = window.__tw, sleep = ms => new Promise(r => setTimeout(r, ms));
  const set = st => new Promise(r => L.setState(st, r));
  const vals = () => { try { return L.renderVals() || {}; } catch (e) { return {}; } };
  const get = (o, path) => path.split('.').reduce((a, k) => a == null ? a : a[k], o);
  const hidden = s => /display:\s*none|opacity:\s*0(?![.\d])|translate[XY]?\(\s*100%|visibility:\s*hidden/.test(String(s || ''));
  const visible = () => {
    const v = vals();
    return spec.screens.filter(sc => sc.kind === 'overlay'
      ? sc.style.length > 0 && !hidden(v[sc.style[sc.style.length - 1]])
      : sc.when.length > 0 && !!v[sc.when[0]]).map(sc => sc.id);
  };
  const fns = h => {
    const v = vals(), parts = h.expr.split('.'), head = parts[0], rest = parts.slice(1).join('.');
    if (h.scope[head]) {
      const arr = get(v, h.scope[head]);
      return (Array.isArray(arr) ? arr.slice(0, 1) : []).map(b => rest ? get(b, rest) : b).filter(f => typeof f === 'function');
    }
    const base = v[head] !== undefined ? v[head] : L[head];
    const f = rest ? get(base, rest) : base;
    return typeof f === 'function' ? [f] : [];
  };
  const snap = () => JSON.parse(JSON.stringify(L.state));
  const found = {}, via = {}, seen = new Set();
  const mark = (st, path) => { for (const s of visible()) if (!(s in found)) { found[s] = st; via[s] = path; } };
  const init = snap();
  await set(init); await sleep(60);
  mark(init, []); seen.add(visible().sort().join(','));
  const q = [[init, []]];
  let calls = 0;
  while (q.length && calls < spec.limit) {
    const [st, path] = q.shift();
    await set(st); await sleep(15);
    const on = new Set(visible());
    for (const h of spec.handlers) {
      if (!h.screens.some(x => on.has(x))) continue;          // 안 보이는 화면의 버튼은 누를 수 없다
      await set(st); await sleep(15);
      for (const f of fns(h)) {
        calls++;
        try { f({ target: { value: 0 }, stopPropagation() {}, preventDefault() {} }); } catch (e) {}
        await sleep(50);
        const now = snap(), sig = visible().sort().join(','), p = path.concat([h.expr]);
        mark(now, p);
        if (!seen.has(sig)) { seen.add(sig); q.push([now, p]); }
      }
    }
  }
  await set(init);
  return { found, via, calls };
}
"""


def _scopes(lay):
    """[{expr, scope: {별칭: items 식}}] — 트리의 on_click 마다 (리스트 안이면 리스트 별칭 → items)."""
    out = []

    def walk(n, scope):
        if not isinstance(n, dict):
            return
        if n.get("kind") == "list" and n.get("items"):
            scope = {**scope, n.get("as") or "item": n["items"]}
        v = n.get("on_click")
        if isinstance(v, str):
            out.append({"expr": v, "scope": {k: s for k, s in scope.items() if v.split(".")[0] == k}})
        for c in n.get("children") or []:
            walk(c, scope)
    walk(lay.get("root"), {})
    return out


def _spec(lays):
    """탐색 입력 — 화면(보이는지 판정할 when · style)과 핸들러(그 노드가 있는 화면들). 핸들러는 자기 화면이 보일 때만 부른다."""
    screens = [{"id": s, "kind": lay.get("kind") or "state", "when": lay.get("when") or [], "style": lay.get("style") or []}
               for s, lay in sorted(lays.items())]
    handlers, idx = [], {}
    for s in sorted(lays):
        for h in _scopes(lays[s]):
            k = json.dumps(h, sort_keys=True)                     # 닫기 · 초기화도 넣는다 — 다른 화면 위의 상태를 지우는 길이 된다
            if k not in idx:
                idx[k] = len(handlers)
                handlers.append({**h, "screens": []})
            if s not in handlers[idx[k]]["screens"]:
                handlers[idx[k]]["screens"].append(s)
    return {"screens": screens, "handlers": handlers, "limit": 600}


def _patch(html):
    m = re.search(r"class\s+Component\s+extends\s+DCLogic\s*\{", html)
    if not m:
        raise VisError("디자인 스크립트에 `class Component extends DCLogic` 가 없다 — 로직 인스턴스를 걸 수 없다")
    return html[:m.end()] + "\n  " + HOOK + html[m.end():]


FRAME_CSS = "[data-om-starter=ios-frame]{border-radius:0!important;box-shadow:none!important}"


def _open_design(b, url, source_name):
    """미리보기를 열되 문서 응답(<화면>.dc.html)만 가로채 로직 훅을 넣는다. 다른 요청은 그대로."""
    b.send("Page.enable")
    b.send("Runtime.enable")
    b.send("Emulation.setDeviceMetricsOverride", {"width": 1200, "height": 1000, "deviceScaleFactor": SCALE, "mobile": False})
    b.send("Fetch.enable", {"patterns": [{"urlPattern": f"*{source_name}*", "resourceType": "Document", "requestStage": "Response"}]})
    b.fire("Page.navigate", {"url": url})
    ev = b.event("Fetch.requestPaused", timeout=60)["params"]
    body = b.send("Fetch.getResponseBody", {"requestId": ev["requestId"]})
    raw = base64.b64decode(body["body"]).decode("utf-8") if body.get("base64Encoded") else body["body"]
    headers = [h for h in ev.get("responseHeaders") or [] if h["name"].lower() not in ("content-length", "content-encoding")]
    b.send("Fetch.fulfillRequest", {"requestId": ev["requestId"], "responseCode": ev.get("responseStatusCode") or 200,
                                    "responseHeaders": headers, "body": base64.b64encode(_patch(raw).encode("utf-8")).decode()})
    b.send("Fetch.disable")
    if not b.wait("!!window.__tw && !!document.querySelector('[data-om-starter=ios-frame]')", timeout=60):
        raise VisError("디자인이 그려지지 않았다 (로직 · 기기 프레임 없음)")
    b.eval(f"(() => {{ const s = document.createElement('style'); s.textContent = {json.dumps(FRAME_CSS)}; document.head.appendChild(s); return 1; }})()")
    time.sleep(1.0)


def _frame_clip(b):
    r = b.eval("(() => { const r = document.querySelector('[data-om-starter=ios-frame]').getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; })()")
    return r


def _design_layouts(root, scope):
    d = os.path.join(root, util.DESIGN_DIR, scope, "layout")
    lays = {}
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.endswith(".json"):
            lay = util.read_json(os.path.join(d, n), {}) or {}
            if lay.get("screen") and lay.get("root"):
                lays[lay["screen"]] = lay
    return lays


def shots_dir(root, scope):
    return os.path.join(root, util.DESIGN_DIR, scope, SHOTS)


def design_shots(root, scope, url, only=None):
    """디자인 기준 이미지 — 범위의 화면마다 design/<범위>/shots/<화면>.png. url: render_preview 의 serve_url (남기지 않는다).
    → {"shots": {화면: 경로}, "via": {화면: [핸들러]}, "unreached": [화면], "calls"}"""
    lays = _design_layouts(root, scope)
    if not lays:
        raise VisError(f"{scope}: 레이아웃 트리가 없다")
    sources = {os.path.basename(l.get("source") or "") for l in lays.values()} - {""}
    if len(sources) != 1:
        raise VisError(f"{scope}: 화면 파일이 하나여야 한다 ({', '.join(sorted(sources)) or '없음'})")
    spec = _spec(lays)
    out_dir = shots_dir(root, scope)
    with Browser() as b:
        _open_design(b, url, sources.pop())
        res = b.eval(f"({EXPLORE})({json.dumps(spec, ensure_ascii=False)})", timeout=240) or {}
        found = res.get("found") or {}
        shots = {}
        for s in sorted(found):
            if only and s not in only:
                continue
            if (lays[s].get("kind") == "shell"):
                continue                                         # 셸은 슬롯 화면과 같이 보인다 — 따로 찍지 않는다 (순회와 같다)
            b.eval(f"new Promise(r => window.__tw.setState({json.dumps(found[s], ensure_ascii=False)}, r))")
            time.sleep(1.2)                                      # 시트 · 페이드 전환이 끝나게
            shots[s] = b.shot(os.path.join(out_dir, f"{s}.png"), _frame_clip(b))
    unreached = [s for s in sorted(lays) if s not in found and lays[s].get("kind") != "shell"]
    util.write_json(os.path.join(out_dir, "_shots.json"), {"via": res.get("via") or {}, "unreached": unreached,
                                                          "hashes": {s: lays[s].get("hash") for s in shots}})
    return {"shots": shots, "via": res.get("via") or {}, "unreached": unreached, "calls": res.get("calls")}


def reference(root, screen):
    """화면의 기준 이미지 경로 — 트리 해시가 찍을 때와 같을 때만 (디자인이 바뀌면 낡은 그림으로 판정하지 않는다)."""
    d = os.path.join(root, util.DESIGN_DIR)
    for scope in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = os.path.join(d, scope, SHOTS, f"{screen}.png")
        if os.path.isfile(p):
            meta = util.read_json(os.path.join(d, scope, SHOTS, "_shots.json"), {}) or {}
            lay = util.read_json(os.path.join(d, scope, "layout", f"{screen}.json"), {}) or {}
            if (meta.get("hashes") or {}).get(screen) in (None, lay.get("hash")):
                return p
    return None


# ─────────────────────────── 비교 ───────────────────────────

COMPARE_JS = r"""
async (spec) => {
  const load = src => new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = src; });
  const W = 402, H = 874, CW = 34, CH = 34, TOP = 60, BOTTOM = 34;
  const cells = img => {
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const g = c.getContext('2d'); g.drawImage(img, 0, 0, W, H);
    const d = g.getImageData(0, 0, W, H).data, out = [];
    const lum = k => (d[k] * 0.299 + d[k + 1] * 0.587 + d[k + 2] * 0.114) / 255;
    for (let y = 0; y < H; y += CH) for (let x = 0; x < W; x += CW) {
      let r = 0, gg = 0, b = 0, e = 0, n = 0;
      for (let yy = y; yy < Math.min(H - 1, y + CH); yy += 2) for (let xx = x; xx < Math.min(W - 1, x + CW); xx += 2) {
        const k = (yy * W + xx) * 4, l = lum(k);
        r += d[k]; gg += d[k + 1]; b += d[k + 2];
        e += Math.abs(l - lum(k + 4)) + Math.abs(l - lum(k + W * 4)); n++;
      }
      out.push({ x, y, c: [r / n, gg / n, b / n], e: e / n });     // e: 윤곽 밀도 — 글자 · 테두리가 어디 있는가 (자리 어긋남)
    }
    return out;
  };
  const ref = await load(spec.design), refCells = cells(ref);
  const root = document.getElementById('cols'), scores = {};
  const col = (label, img, hot) => {
    const box = document.createElement('div'); box.className = 'col';
    box.innerHTML = '<div class="lab">' + label + '</div>';
    const wrap = document.createElement('div'); wrap.className = 'wrap';
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const g = c.getContext('2d'); g.drawImage(img, 0, 0, W, H);
    if (hot) { g.strokeStyle = 'rgba(255,45,85,.55)'; g.lineWidth = 1; for (const h of hot) g.strokeRect(h.x + .5, h.y + .5, CW - 1, CH - 1); }
    wrap.appendChild(c); box.appendChild(wrap); root.appendChild(box);
  };
  col('design', ref, null);
  for (const [name, src] of spec.shots) {
    const img = await load(src), cs = cells(img);
    let sum = 0, n = 0; const hot = [];
    cs.forEach((cell, i) => {
      if (cell.y < TOP || cell.y + CH > H - BOTTOM) return;
      const a = refCells[i].c, dc = (Math.abs(a[0] - cell.c[0]) + Math.abs(a[1] - cell.c[1]) + Math.abs(a[2] - cell.c[2])) / (3 * 255);
      const de = Math.min(1, Math.abs(refCells[i].e - cell.e) * spec.edge), d = Math.max(dc, de);
      sum += d; n++; if (d > spec.hot) hot.push(cell);
    });
    scores[name] = { score: +(sum / Math.max(1, n)).toFixed(3), hot: +(hot.length / Math.max(1, n)).toFixed(3) };
    col(name + ' · ' + scores[name].score + ' · hot ' + Math.round(scores[name].hot * 100) + '%', img, hot);
  }
  document.getElementById('title').textContent = spec.title;
  const r = document.body.getBoundingClientRect();
  return { scores, width: Math.ceil(r.width), height: Math.ceil(r.height) };
}
"""

PAGE = """<!doctype html><meta charset="utf-8"><style>
body{margin:0;background:#111;color:#eee;font:13px/1.4 -apple-system,system-ui,sans-serif;display:inline-block;padding:12px}
#title{font-weight:600;margin:0 0 8px}#cols{display:flex;gap:12px}.lab{margin-bottom:4px;color:#bbb}
.wrap canvas{display:block;width:402px;height:874px;border-radius:6px}
</style><div id="title"></div><div id="cols"></div>"""


def _data_uri(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def compare(design_png, shots, out_png, title="", b=None):
    """비교 이미지(디자인 | 플랫폼…) + 칸별 색 차이 점수. shots: [(이름, png)]. → {이름: {"score", "hot"}} (0~1, 낮을수록 같다)."""
    own = b is None
    b = b or Browser()
    try:
        page = os.path.join(b.dir, "compare.html")
        util.write_text(page, PAGE)
        b.send("Page.enable")
        b.send("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        b.send("Page.navigate", {"url": "file://" + page})
        b.wait("document.readyState === 'complete' && !!document.getElementById('cols')", timeout=20)
        spec = {"design": _data_uri(design_png), "shots": [[n, _data_uri(p)] for n, p in shots], "hot": HOT, "edge": EDGE, "title": title}
        r = b.eval(f"({COMPARE_JS})({json.dumps(spec)})", timeout=120)
        b.shot(out_png, {"x": 0, "y": 0, "width": r["width"], "height": r["height"]})
        return r["scores"]
    finally:
        if own:
            b.close()


def compare_all(root, shots_by_screen, out_dir):
    """화면마다 기준 이미지가 있으면 비교 이미지를 만든다. shots_by_screen: {화면: {플랫폼: png}}.
    → {화면: {"image", "scores": {플랫폼: {...}}}} — 기준 이미지가 없는 화면은 {"image": None, "reason"}."""
    out = {}
    todo = []
    for s in sorted(shots_by_screen):
        ref = reference(root, s)
        if not ref:
            out[s] = {"image": None, "scores": {}, "reason": "기준 이미지 없음 (design run 의 `design shots`)"}
            continue
        todo.append((s, ref))
    if not todo:
        return out
    if not chrome():
        for s, _ in todo:
            out[s] = {"image": None, "scores": {}, "reason": "Chrome 없음"}
        return out
    with Browser() as b:
        for s, ref in todo:
            img = os.path.join(out_dir, f"{s}-compare.png")
            try:
                scores = compare(ref, sorted(shots_by_screen[s].items()), img, title=s, b=b)
                out[s] = {"image": img, "scores": scores}
            except VisError as e:
                out[s] = {"image": None, "scores": {}, "reason": str(e)}
    return out
