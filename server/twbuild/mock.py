"""mock 서버 — 계약(api/openapi.yaml + 조각)의 응답 예시를 그대로 돌려준다 (AGENT.md 10장: 앱은 mock 으로 끝까지 가고, 실서버 전환은 API_BASE_URL 하나).

  twbuild mock [--port 8787]   (CLI 배선은 run.py)

경로 · 메서드마다 가장 낮은 2xx 응답의 예시(example · examples 첫 값 · 스키마 example)를 그 상태 코드로 낸다. 예시가 없으면 {} (204 는 빈 본문).
보호된 오퍼레이션(security 가 비어 있지 않음)에 Bearer 가 없으면 401 — components.responses.Unauthorized 의 예시로.
표준 라이브러리만. 결정적 — LLM 은 없다.
"""
import http.server
import json
import re
import threading
import urllib.parse

from . import contract, gen

DEFAULT_PORT = 8787


def _example_of(doc, resp):
    """응답 → 예시 값 (없으면 None). example · examples 첫 값 · 스키마의 example 순."""
    resp = gen._resolve(doc, resp, "responses")
    media = (resp.get("content") or {}).get("application/json")
    if not media:
        return None, False
    if "example" in media:
        return media["example"], True
    exs = media.get("examples") or {}
    for k in sorted(exs):
        v = exs[k]
        return (v.get("value") if isinstance(v, dict) and "value" in v else v), True
    schema = media.get("schema")
    if schema is not None:
        sch = gen._resolve(doc, schema)
        if "example" in sch:
            return sch["example"], True
    return None, False


def _unauthorized(doc):
    resp = ((doc.get("components") or {}).get("responses") or {}).get("Unauthorized")
    if resp:
        ex, ok = _example_of(doc, resp)
        if ok:
            return ex
    return {"code": "unauthorized", "message": "missing bearer token"}


def routes(root):
    """[{method, path, status, secured, example: bool, regex}] — 라우트 순서(contract.routes)."""
    doc = contract.merged(root)
    doc_sec = doc.get("security") or []
    out = []
    for r in contract.routes(doc):
        op = (doc["paths"][r["path"]] or {}).get(r["method"].lower()) or {}
        status, body, has = None, None, False
        for st in sorted(op.get("responses") or {}, key=lambda s: (not str(s).isdigit(), int(s) if str(s).isdigit() else 0)):
            if str(st).startswith("2"):
                status = int(st)
                body, has = _example_of(doc, (op["responses"] or {})[st])
                break
        sec = op.get("security") if "security" in op else doc_sec
        regex = "^" + re.sub(r"\{[^/}]+\}", r"[^/]+", re.escape(r["path"]).replace(r"\{", "{").replace(r"\}", "}")) + "$"
        out.append({"name": r["name"], "method": r["method"], "path": r["path"], "status": status or 200, "secured": bool(sec),
                    "example": has, "body": body, "regex": re.compile(regex)})
    return out, _unauthorized(doc)


def table(root):
    """사람이 읽는 라우트 표 (한국어)."""
    rs, _ = routes(root)
    L = ["  메서드   경로                              상태  보호  예시", ]
    for r in rs:
        L.append(f"  {r['method']:<7} {r['path']:<33} {r['status']:<5} {'🔒' if r['secured'] else '  ':<4}  {'✅' if r['example'] else '— ({})'}")
    return "\n".join(L)


def _handler(rs, unauthorized):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "twbuild-mock"

        def log_message(self, fmt, *args):     # 조용히 — 터미널 표만
            pass

        def _send(self, status, body):
            data = (json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b"")
            self.send_response(status)
            if data:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def _serve(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)                     # 본문은 읽어서 버린다 — 검증하지 않는다
            path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
            method = self.command.upper()
            if method == "POST" and self.headers.get("X-HTTP-Method-Override", "").upper() == "PATCH":
                method = "PATCH"
            matched = [r for r in rs if r["regex"].match(path)]
            if not matched:
                return self._send(404, {"code": "not_found", "message": f"no route for {path}"})
            route = next((r for r in matched if r["method"] == method), None)
            if route is None:
                return self._send(405, {"code": "method_not_allowed", "message": f"{method} {path}", "allowed": sorted(r["method"] for r in matched)})
            if route["secured"] and not self.headers.get("Authorization", "").startswith("Bearer "):
                return self._send(401, unauthorized)
            if route["status"] == 204:
                return self._send(204, None)
            return self._send(route["status"], route["body"] if route["example"] else {})

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _serve

    return Handler


def make_server(root, port=DEFAULT_PORT):
    """ThreadingHTTPServer — 테스트는 port=0 으로 띄워 server_address[1] 을 본다."""
    rs, unauthorized = routes(root)
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), _handler(rs, unauthorized))


def start(root, port=DEFAULT_PORT):
    """백그라운드 스레드로 띄운다 → (server, port)."""
    srv = make_server(root, port)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, srv.server_address[1]


def serve(root, port=DEFAULT_PORT):
    """막는 실행 — 표를 찍고 Ctrl-C 까지."""
    srv = make_server(root, port)
    print(f"twbuild mock — http://127.0.0.1:{srv.server_address[1]}  (API_BASE_URL)")
    print(table(root))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
