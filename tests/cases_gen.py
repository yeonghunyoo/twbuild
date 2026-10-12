"""계약 코드 생성 · 디코딩 층 · mock 의 자기 검사 — cases.py 의 러너에 등록된다.

  python3 -c "import sys; sys.path[:0]=['tests','server']; import cases, cases_gen; cases.main([])"
"""
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request

from cases import _wired_repo, case, check

from twbuild import config, contract, gen, mock, util  # noqa: E402


def _get(url, method="GET", headers=None, body=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


@case
def gen_models_and_clients():
    root = _wired_repo()           # Mini · com.example.mini · 두 플랫폼 · 기본 조각(auth · push · offline)
    try:
        files = gen.expected(root)
        check(set(files) == {"apps/ios/App/Core/Networking/Generated/Models.swift", "apps/ios/App/Core/Networking/Generated/Client.swift",
                             "apps/android/app/src/main/kotlin/com/example/mini/core/networking/generated/Models.kt",
                             "apps/android/app/src/main/kotlin/com/example/mini/core/networking/generated/Client.kt",
                             "apps/android/app/src/test/kotlin/com/example/mini/core/networking/generated/ContractDecodeTest.kt"}, sorted(files))
        check(all(gen.HEADER in t.splitlines()[0] for t in files.values()), "헤더")
        sw = files["apps/ios/App/Core/Networking/Generated/Models.swift"]
        check("public struct TokenPair: Codable, Equatable, Sendable {" in sw and "public let expiresIn: Int" in sw, sw)
        check("public enum DevicePlatform: String, Codable, Equatable, Sendable {" in sw and 'case ios = "ios"' in sw, sw)
        check("public let deletedAt: String?" in sw and "public let params: [String: String]?" in sw, sw)
        check("JSONValue" not in sw, "기본 계약에는 free-form JSON 이 없다")
        cl = files["apps/ios/App/Core/Networking/Generated/Client.swift"]
        check("public func login(body: LoginRequest) async throws -> TokenPair {" in cl, cl)
        check("public func unregisterDevice(deviceId: String) async throws {" in cl and '"/devices/\\(escape(deviceId))"' in cl, cl)
        check("public func health() async throws -> Health {" in cl and "secured: false" in cl, cl)
        check("public func registerDevice(body: DeviceRegistration) async throws -> Device {" in cl and "secured: true" in cl, cl)
        check("case unauthorized" in cl and "if status == 401 { throw ApiError.unauthorized }" in cl, cl)
        kt = files["apps/android/app/src/main/kotlin/com/example/mini/core/networking/generated/Models.kt"]
        check("package com.example.mini.core.networking.generated" in kt and "data class TokenPair(" in kt
              and '@SerialName("expiresIn") val expiresIn: Int,' in kt and '@SerialName("deletedAt") val deletedAt: String? = null,' in kt, kt)
        check("enum class DevicePlatform {" in kt and '@SerialName("android") ANDROID,' in kt and "Map<String, String>? = null" in kt, kt)
        kc = files["apps/android/app/src/main/kotlin/com/example/mini/core/networking/generated/Client.kt"]
        check("suspend fun login(body: LoginRequest): TokenPair {" in kc and "suspend fun unregisterDevice(deviceId: String) {" in kc, kc)
        check("object Unauthorized : ApiException" in kc and "if (status == 401) throw ApiException.Unauthorized" in kc, kc)
        check("decode(TokenPair.serializer(), text)" in kc and "json.encodeToString(LoginRequest.serializer(), body)" in kc, kc)
        test = files["apps/android/app/src/test/kotlin/com/example/mini/core/networking/generated/ContractDecodeTest.kt"]
        check("class ContractDecodeTest {" in test and "// POST /auth/login 200" in test and "TokenPair.serializer()" in test
              and "// POST /auth/login 401" in test and "ErrorModel.serializer()" in test, test)
        check("public struct ErrorModel: Codable" in sw and "data class ErrorModel(" in kt and "struct Error:" not in sw, "표준 타입과 겹치는 이름은 Model 접미사")
        # 결정적 · 쓰기 · drift
        check(gen.expected(root) == files, "같은 입력 = 같은 바이트")
        written = gen.write(root)
        check(written == sorted(files) and gen.drift(root) == [], gen.drift(root))
        p = os.path.join(root, "apps/ios/App/Core/Networking/Generated/Models.swift")
        util.write_text(p, util.read_text(p) + "\n// edited\n")
        check(gen.drift(root) == ["apps/ios/App/Core/Networking/Generated/Models.swift"], gen.drift(root))
        gen.write(root)
        check(gen.drift(root) == [], "다시 쓰면 일치")
        # 플랫폼 하나만이면 그 쪽만
        config.update(root, platforms=["ios"])
        check(all(rel.startswith("apps/ios/") for rel in gen.expected(root)), sorted(gen.expected(root)))
        # 응답 예시 수집 — 명시 예시 · $ref 응답(Unauthorized) 의 예시 · 204 는 제외
        doc = contract.merged(root)
        exs = gen.examples(doc)
        names = {e["name"] for e in exs}
        check("POST /auth/login 200" in names and "POST /auth/login 401" in names and "GET /health 200" in names, sorted(names))
        check(not any(n.endswith(" 204") for n in names), sorted(names))
        login = next(e for e in exs if e["name"] == "POST /auth/login 200")
        check(login["type"] == ("ref", "TokenPair") and json.loads(login["json"])["expiresIn"] == 3600, login)
        # 계약을 넓혀도 생성이 된다 — 인라인 enum · 배열 응답 · 쿼리 · 헤더 · allOf · free-form object (plan 이 본문을 고친 상황)
        body = util.read_text(os.path.join(root, "api/openapi.yaml"))
        body = body.replace("paths:\n", "paths:\n" + """  /items:
    get:
      operationId: listItems
      parameters:
        - {$ref: "#/components/parameters/Since"}
        - {name: limit, in: query, schema: {type: integer}}
      responses:
        "200":
          description: Items
          content:
            application/json:
              schema: {type: array, items: {$ref: "#/components/schemas/Item"}}
              example: [{id: "7f3c9a2e-1b4d-4c6e-9f0a-2d8b5e7c1a3f", updatedAt: "2026-01-01T00:00:00Z", name: "Rain", kind: white-noise, meta: {a: 1}}]
    post:
      operationId: createItem
      parameters:
        - {$ref: "#/components/parameters/IdempotencyKey"}
      requestBody: {required: true, content: {application/json: {schema: {$ref: "#/components/schemas/Item"}}}}
      responses:
        "201": {description: Created, content: {application/json: {schema: {$ref: "#/components/schemas/Item"}}}}
""", 1)
        body = body.replace("  schemas:\n", "  schemas:\n" + """    Item:
      allOf:
        - {$ref: "#/components/schemas/SyncMeta"}
        - type: object
          required: [name]
          properties:
            name: {type: string}
            kind: {type: string, enum: [nature, white-noise]}
            meta: {type: object}
""", 1)
        util.write_text(os.path.join(root, "api/openapi.yaml"), body)
        config.update(root, platforms=["ios", "android"])
        files = gen.expected(root)
        sw, cl = files["apps/ios/App/Core/Networking/Generated/Models.swift"], files["apps/ios/App/Core/Networking/Generated/Client.swift"]
        check("public struct Item: Codable, Equatable, Sendable {" in sw and "public let updatedAt: String" in sw and "public let kind: ItemKind?" in sw
              and "public let meta: [String: JSONValue]?" in sw and "public enum JSONValue" in sw, sw)
        check("public enum ItemKind: String, Codable, Equatable, Sendable {" in sw and 'case whiteNoise = "white-noise"' in sw, sw)
        check("public func listItems(since: String? = nil, limit: Int? = nil) async throws -> [Item] {" in cl, cl)
        check("public func createItem(body: Item, idempotencyKey: String) async throws -> Item {" in cl and '"Idempotency-Key": idempotencyKey' in cl, cl)
        kt, kc = files["apps/android/app/src/main/kotlin/com/example/mini/core/networking/generated/Models.kt"], files["apps/android/app/src/main/kotlin/com/example/mini/core/networking/generated/Client.kt"]
        check('@SerialName("kind") val kind: ItemKind? = null,' in kt and '@SerialName("white-noise") WHITE_NOISE,' in kt and "Map<String, JsonElement>? = null" in kt, kt)
        check("suspend fun listItems(since: String? = null, limit: Int? = null): List<Item> {" in kc and "ListSerializer(Item.serializer())" in kc
              and 'query = listOf("since" to since?.toString(), "limit" to limit?.toString())' in kc, kc)
        check("suspend fun createItem(body: Item, idempotencyKey: String): Item {" in kc and 'headers = mapOf("Idempotency-Key" to idempotencyKey)' in kc, kc)
        exs = gen.examples(contract.merged(root))
        lst = next(e for e in exs if e["name"] == "GET /items 200")
        check(lst["type"] == ("array", ("ref", "Item")), lst)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@case
def gen_mock_server():
    root = _wired_repo()
    try:
        srv, port = mock.start(root, port=0)
        try:
            base = f"http://127.0.0.1:{port}"
            st, body = _get(f"{base}/health")
            check(st == 200 and json.loads(body) == {"status": "ok"}, (st, body))
            st, body = _get(f"{base}/auth/login", "POST", {"Content-Type": "application/json"}, b'{"email":"a@b.c","password":"x"}')
            check(st == 200 and json.loads(body)["expiresIn"] == 3600, (st, body))
            st, body = _get(f"{base}/devices", "POST", {"Content-Type": "application/json"}, b'{"platform":"ios","token":"t"}')
            check(st == 401 and json.loads(body)["code"] == "unauthorized", (st, body))
            st, body = _get(f"{base}/devices", "POST", {"Content-Type": "application/json", "Authorization": "Bearer x"}, b'{"platform":"ios","token":"t"}')
            check(st == 201 and json.loads(body)["platform"] == "ios", (st, body))
            st, body = _get(f"{base}/devices/7f3c9a2e?x=1", "DELETE", {"Authorization": "Bearer x"})
            check(st == 204 and body == "", (st, body))
            st, body = _get(f"{base}/nope")
            check(st == 404, (st, body))
            st, body = _get(f"{base}/health", "DELETE")
            check(st == 405 and json.loads(body)["allowed"] == ["GET"], (st, body))
        finally:
            srv.shutdown()
            srv.server_close()
        rs, unauthorized = mock.routes(root)
        check(unauthorized == {"code": "unauthorized", "message": "token expired"} and any(r["name"] == "health" and not r["secured"] for r in rs), (unauthorized, rs[:2]))
        t = mock.table(root)
        check("GET" in t and "/health" in t and "🔒" in t, t)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@case
def gen_decode_unmeasured():
    """툴체인이 없으면 못 잼 — 통과로 세지 않는다. 실제 디코딩은 tests/ 밖(툴체인 있는 기기)에서 돈다."""
    root = _wired_repo()
    saved = {k: os.environ.get(k) for k in ("PATH", "TWBUILD_NO_BUILD")}
    empty = tempfile.mkdtemp(prefix="twbuild-nopath-")
    try:
        log = util.tw(root, "logs", "decode.log")
        r = gen.decode_check(root, "ios", log)
        check(r["status"] == "unmeasured" and r["detail"] == "TWBUILD_NO_BUILD", r)
        os.environ.pop("TWBUILD_NO_BUILD", None)
        os.environ["PATH"] = empty
        r = gen.decode_check(root, "ios", log)
        check(r["status"] == "unmeasured" and "없음" in r["detail"], r)
        r = gen.decode_check(root, "android", log)
        check(r["status"] == "unmeasured" and ("gradlew" in r["detail"] or "없음" in r["detail"]), r)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(empty, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)
