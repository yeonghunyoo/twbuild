"""계약 — api/openapi.yaml(본문) + api/fragments/*.yaml(조각) → api/generated/ (생성물).

셋업은 조각만, 사이클의 plan 은 본문만 고친다. 여기서 둘을 합친다 — 같은 입력이면 같은 바이트.
생성물: openapi.merged.json(합친 계약) · routes.json(라우트 목록). 플랫폼 코드(Swift · Kotlin 모델 · 클라이언트 · mock)는 뒤 단계에서 같은 자리에 더한다.
"""
import os
import re

from . import util, yaml_lite

METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
COMPONENT_KINDS = ("schemas", "parameters", "responses", "requestBodies", "headers", "securitySchemes")
MERGED = "openapi.merged.json"
ROUTES = "routes.json"


class ContractError(ValueError):
    pass


def body_path(root):
    return os.path.join(root, util.API_DIR, util.API_FILE)


def fragment_paths(root):
    d = os.path.join(root, util.FRAGMENTS_DIR)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith((".yaml", ".yml"))]


def _load(path):
    doc = yaml_lite.loads(util.read_text(path, ""))
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise ContractError(f"{os.path.basename(path)}: 문서가 매핑이 아니다")
    return doc


def merged(root):
    """본문 + 조각. 같은 경로 · 메서드나 같은 이름의 다른 컴포넌트가 겹치면 ContractError."""
    body = _load(body_path(root))
    if "openapi" not in body:
        raise ContractError("openapi.yaml 에 openapi 버전이 없다")
    out = {k: v for k, v in body.items()}
    out.setdefault("paths", {})
    out.setdefault("components", {})
    for fp in fragment_paths(root):
        frag = _load(fp)
        name = os.path.basename(fp)
        for path, ops in (frag.get("paths") or {}).items():
            cur = out["paths"].setdefault(path, {})
            for m, op in (ops or {}).items():
                if m in cur:
                    raise ContractError(f"{name}: {m.upper()} {path} 가 이미 있다")
                cur[m] = op
        for kind, items in (frag.get("components") or {}).items():
            bucket = out["components"].setdefault(kind, {})
            for cname, val in (items or {}).items():
                if cname in bucket and bucket[cname] != val:
                    raise ContractError(f"{name}: components.{kind}.{cname} 이 본문(또는 다른 조각)과 다르다")
                bucket[cname] = val
        for key in ("security", "tags"):
            if key in frag and key not in out:
                out[key] = frag[key]
    return out


def _camel(path):
    parts = []
    for seg in path.strip("/").split("/"):
        if not seg:
            continue
        if seg.startswith("{"):
            p = "".join(w[:1].upper() + w[1:] for w in seg.strip("{}").replace("-", "_").split("_") if w)
            parts.append("By" + p)
        else:
            parts.append(re.sub(r"[^0-9A-Za-z]+", " ", seg).title().replace(" ", ""))
    return "".join(parts) or "Root"


def routes(doc):
    """[{name, method, path, summary, tag}] — operationId 가 있으면 그 이름, 없으면 method+Path. 이름이 겹치면 오류."""
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        raise ContractError("paths 가 매핑이 아니다")
    out, seen = [], set()
    for path in sorted(paths):
        ops = paths[path]
        if not isinstance(path, str) or not path.startswith("/"):
            raise ContractError(f"경로는 / 로 시작한다: {path!r}")
        if not isinstance(ops, dict):
            raise ContractError(f"{path} 아래가 매핑이 아니다")
        for method in METHODS:
            if method not in ops:
                continue
            op = ops[method] if isinstance(ops[method], dict) else {}
            name = op.get("operationId") or (method + _camel(path))
            name = re.sub(r"[^0-9A-Za-z_]", "_", str(name))
            name = name[0].lower() + name[1:]
            if name in seen:
                raise ContractError(f"라우트 이름이 겹친다: {name} ({method.upper()} {path})")
            seen.add(name)
            tags = op.get("tags") if isinstance(op.get("tags"), list) else []
            out.append({"name": name, "method": method.upper(), "path": path, "tag": str(tags[0]) if tags else "",
                        "summary": str(op.get("summary") or op.get("description") or "")[:120]})
    return out


def expected(root):
    """{상대경로: 바이트 문자열} — 지금 계약에서 나와야 하는 생성물 전부."""
    doc = merged(root)
    rs = routes(doc)
    return {
        os.path.join(util.API_GENERATED, MERGED): util.stable_json(doc),
        os.path.join(util.API_GENERATED, ROUTES): util.stable_json(rs),
    }


def write_generated(root):
    files = expected(root)
    for rel, text in files.items():
        util.write_text(os.path.join(root, rel), text)
    return sorted(files)


def drift(root):
    """생성물이 지금 계약과 다른(또는 없는) 파일 목록. 비어 있으면 일치."""
    out = []
    for rel, text in expected(root).items():
        if util.read_text(os.path.join(root, rel), None) != text:
            out.append(rel)
    return out
