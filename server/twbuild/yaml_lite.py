"""YAML 부분집합 — 의존성 없이 config.yaml · openapi.yaml 을 읽고 쓴다.

loads: 매핑 · 시퀀스 · 스칼라 · 인용문자열 · 블록 스칼라(| >) · 한 줄 flow([] {}) · 주석. 앵커 · 태그 · 다중 문서는 없다.
dumps: 결정적 직렬화 — 키 순서는 입력 순서, 스칼라 리스트는 flow([a, b]), 매핑 리스트는 블록. 주석은 남지 않는다
(주석이 필요한 첫 config 는 templates/config.yaml 에서 치환해 쓴다).
"""
import json
import re

_KEY_RE = re.compile(r"^(\"[^\"]*\"|'[^']*'|[^\s\"'#][^:]*?)\s*:(?:\s+|$)")


# ─────────────────────────── 읽기 ───────────────────────────

def _strip_comment(line):
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            out.append(ch)
            if ch == q and (i == 0 or line[i - 1] != "\\"):
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(s):
    s = s.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        body = s[1:-1]
        if s[0] == '"':
            body = body.encode().decode("unicode_escape") if "\\" in body else body
        else:
            body = body.replace("''", "'")
        return body
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(x) for x in _split_flow(inner)] if inner else []
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        out = {}
        for part in _split_flow(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                out[_scalar(k)] = _scalar(v)
        return out
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s):
        return float(s)
    return s


def _split_flow(s):
    parts, depth, q, cur = [], 0, None, []
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur.append(ch)
        elif ch in "[{":
            depth += 1
            cur.append(ch)
        elif ch in "]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def _lines(text):
    out = []
    for raw in text.splitlines():
        if raw.strip() in ("---", "...") or raw.lstrip().startswith("#"):
            continue
        line = _strip_comment(raw.replace("\t", "  "))
        if line.strip():
            out.append((len(line) - len(line.lstrip(" ")), line.strip()))
    return out


def loads(text):
    """YAML(부분집합) 또는 JSON 문자열 → 파이썬 값. 빈 문서는 None."""
    text = text or ""
    try:
        return json.loads(text)
    except Exception:
        pass
    lines = _lines(text)
    if not lines:
        return None
    val, _ = _parse(lines, 0, lines[0][0])
    return val


def _parse(lines, i, indent):
    ind, body = lines[i]
    if body.startswith("- ") or body == "-":
        return _parse_seq(lines, i, ind)
    if body.startswith(("{", "[")):          # flow 값 — `{k: v}` 의 `{k` 를 키로 읽지 않는다
        return _scalar(body), i + 1
    if _KEY_RE.match(body):
        return _parse_map(lines, i, ind)
    return _scalar(body), i + 1


def _block_scalar(lines, i, indent, style):
    parts = []
    j = i
    while j < len(lines) and lines[j][0] > indent:
        parts.append(" " * (lines[j][0] - indent - 2) + lines[j][1] if lines[j][0] > indent + 2 else lines[j][1])
        j += 1
    text = ("\n" if style == "|" else " ").join(parts)
    return text, j


def _value_after_key(lines, i, indent, rest):
    """key: 뒤의 값. 같은 줄에 있으면 스칼라, 없으면 다음 더 들여쓴 블록."""
    if rest.strip() in ("|", ">", "|-", ">-"):
        return _block_scalar(lines, i + 1, indent, rest.strip()[0])
    if rest.strip():
        return _scalar(rest), i + 1
    if i + 1 < len(lines) and (lines[i + 1][0] > indent or
                               (lines[i + 1][0] == indent and lines[i + 1][1].startswith("- "))):
        return _parse(lines, i + 1, lines[i + 1][0])
    return None, i + 1


def _parse_map(lines, i, indent):
    out = {}
    while i < len(lines) and lines[i][0] == indent:
        body = lines[i][1]
        m = _KEY_RE.match(body)
        if not m:
            break
        key = _scalar(m.group(1))
        rest = body[m.end():]
        val, i = _value_after_key(lines, i, indent, rest)
        out[key] = val
    return out, i


def _parse_seq(lines, i, indent):
    out = []
    while i < len(lines) and lines[i][0] == indent and (lines[i][1].startswith("- ") or lines[i][1] == "-"):
        item = lines[i][1][2:].strip()
        if not item:
            val, i = _value_after_key(lines, i, indent, "")
            out.append(val)
            continue
        if item.startswith(("{", "[")):
            out.append(_scalar(item))
            i += 1
        elif _KEY_RE.match(item):
            # "- key: v" — 항목이 매핑이다. 이 줄을 indent+2 매핑의 첫 줄로 바꿔 읽는다
            sub = [(indent + 2, item)]
            j = i + 1
            while j < len(lines) and lines[j][0] > indent:
                sub.append(lines[j])
                j += 1
            val, _ = _parse_map(sub, 0, indent + 2)
            out.append(val)
            i = j
        else:
            out.append(_scalar(item))
            i += 1
    return out, i


# ─────────────────────────── 쓰기 ───────────────────────────

_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_./+-]*$")
_LOOKS_SPECIAL = re.compile(r"^([-+]?\d|true$|false$|null$|~$|yes$|no$|on$|off$)", re.I)


def _str(s):
    if s == "" or not _PLAIN.match(s) or _LOOKS_SPECIAL.match(s) or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    return s


def _scalar_out(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    return _str(str(v))


def _is_scalar(v):
    return v is None or isinstance(v, (bool, int, float, str))


def _flow(v):
    if isinstance(v, list):
        return "[" + ", ".join(_flow(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_scalar_out(k)}: {_flow(x)}" for k, x in v.items()) + "}"
    return _scalar_out(v)


def dumps(obj):
    """파이썬 값 → YAML 문자열(끝에 개행). 스칼라만 든 리스트 · 매핑은 한 줄 flow 로, 나머지는 블록으로."""
    if _is_scalar(obj):
        return _scalar_out(obj) + "\n"
    return "\n".join(_emit(obj, 0)) + "\n"


def _small(v):
    """한 줄 flow 로 써도 되는 값 — 스칼라만 든 리스트/매핑, 비어 있는 컨테이너."""
    if isinstance(v, list):
        return all(_is_scalar(x) for x in v)
    if isinstance(v, dict):
        return not v or all(_is_scalar(x) for x in v.values())
    return True


def _emit(obj, depth):
    pad = "  " * depth
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = _scalar_out(k)
            if _small(v):
                out.append(f"{pad}{key}: {_flow(v)}")
            else:
                out.append(f"{pad}{key}:")
                out += _emit(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            if _is_scalar(v) or _small(v):
                out.append(f"{pad}- {_flow(v)}")
            elif isinstance(v, dict):
                lines = _emit(v, depth + 1)
                out.append(f"{pad}- " + lines[0].lstrip())
                out += lines[1:]
            else:
                out.append(f"{pad}-")
                out += _emit(v, depth + 1)
    return out
