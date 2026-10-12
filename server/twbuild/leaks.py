"""시크릿 · 개인정보 · 민감 파일 — 패턴은 경보용이다. 블랙리스트는 진다; 그래도 없는 것보단 낫다.

  find / mask / mask_deep              시크릿 값 (키 · 토큰 · 개인키 · 접속 문자열 · 비밀번호 대입)
  find_pii / mask_all / mask_all_deep  + 개인정보 (이메일 · 휴대전화 · 주민번호 · 카드번호 · 홈 경로). 채팅으로 나가는 것은 전부 이것을 거친다
  is_sensitive_file                    민감 파일 이름 (hooks/guard.py 의 SENSITIVE 와 같은 목록 — 훅은 서버를 import 못 하므로 의도된 중복)
"""
import fnmatch
import os
import re

SENSITIVE_GLOBS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p8", "*.p12", "*.pfx", "*.keystore", "*.jks",
    "*.tfstate", "*.tfvars", "*credentials*.json", "*service-account*.json", "google-services.json", "GoogleService-Info.plist",
    "id_rsa", "id_ed25519", "id_ecdsa", "*.mobileprovision", "secrets.yaml", "secrets.yml", "secrets.json",
    ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd", "*.secret", "*.gpg", "*.asc", "*.ovpn", "*.kdbx",
)
SENSITIVE_DIR_RE = re.compile(r"(^|/)(\.ssh|\.aws|\.kube|\.gnupg|\.docker|\.azure|\.config/gcloud)(/|$)")
EXAMPLE_RE = re.compile(r"\.(example|sample|template|dist)$", re.I)

SECRET_RES = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("stripe-key", re.compile(r"\b[sr]k_(live|test)_[0-9A-Za-z]{16,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("assignment", re.compile(
        r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
        r"password|passwd|db[_-]?password)\b\s*[:=]\s*['\"]([^'\"\s]{12,})['\"]")),
    ("connection-string", re.compile(r"\b\w+://[^:/\s]+:[^@/\s]{6,}@[^\s'\"]+")),
]
_PLACEHOLDER = re.compile(r"(?i)^(your|my|xxx|example|placeholder|change|replace|dummy|test|<)")
MASK = "•••"

# 개인정보 — 예시 도메인·번호는 남긴다 (디자인 목업의 자리표시)
_PII_EXEMPT_EMAIL = re.compile(r"(?i)@(example\.(com|org|net)|test\.com|localhost|invalid|email\.com|domain\.com|users\.noreply\.github\.com)$|^(noreply|no-reply|hello|info|support|contact)@")
PII_RES = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("kr-rrn", re.compile(r"\b\d{6}-[1-8]\d{6}\b")),                                   # 주민등록번호
    ("kr-mobile", re.compile(r"(?<![\d-])(?:\+82[- ]?1|01)[016789][- ]?\d{3,4}[- ]?\d{4}(?![\d-])")),
    ("card", re.compile(r"(?<!\d)(?:\d{4}[- ]){3}\d{4}(?!\d)")),
    ("home-path", re.compile(r"(?<![\w/])/(?:Users|home)/[A-Za-z0-9._-]+")),        # 개발자 홈 경로 — 채팅 출력에서 ~ 로
]
_PII_EXEMPT_NUM = re.compile(r"^(?:\+82[- ]?1|01)[016789][- ]?(?:0000|1234|1111|9999)[- ]?(?:0000|1234|5678|1111|9999)$")


def _pii_exempt(name, val):
    if name == "email":
        return bool(_PII_EXEMPT_EMAIL.search(val))
    if name == "kr-mobile":
        return bool(_PII_EXEMPT_NUM.match(val))
    if name == "card":
        digits = val.replace("-", "").replace(" ", "")
        return len(set(digits)) <= 2 or digits.startswith(("4111111111111111", "1234", "0000"))
    return False


def find_pii(text):
    """[(종류, 값)] — 예시 값은 걸지 않는다."""
    hits = []
    for name, rx in PII_RES:
        for m in rx.finditer(text or ""):
            if not _pii_exempt(name, m.group(0)):
                hits.append((name, m.group(0)))
    return hits


def mask_pii(text):
    if not isinstance(text, str):
        return text
    out = text
    for name, rx in PII_RES:
        if name == "home-path":
            out = rx.sub("~", out)
        else:
            out = rx.sub(lambda m: m.group(0) if _pii_exempt(name, m.group(0)) else MASK, out)
    return out


def mask_all(text):
    """시크릿 + 개인정보. 채팅 · 상태 · 문서로 나가는 문자열은 전부 이것을 거친다."""
    return mask_pii(mask(text))


def mask_all_deep(obj):
    if isinstance(obj, str):
        return mask_all(obj)
    if isinstance(obj, dict):
        return {k: mask_all_deep(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_all_deep(v) for v in obj]
    return obj


def find(text):
    """[(규칙, 매치 문자열)] — 자리표시 값은 걸지 않는다."""
    hits = []
    text = text or ""
    for name, rx in SECRET_RES:
        for m in rx.finditer(text):
            val = m.group(2) if name == "assignment" else m.group(0)
            if name == "assignment" and (_PLACEHOLDER.match(val) or "${" in val or val.isupper()):
                continue
            if name == "assignment" and _EXAMPLE_LINE.search(text[text.rfind("\n", 0, m.start()) + 1:(text.find("\n", m.end()) if text.find("\n", m.end()) >= 0 else len(text))]):
                continue                                 # 같은 줄에 example · sample … 이 있으면 문서 예시다 (계약의 응답 예시)
            hits.append((name, val))
    return hits


_EXAMPLE_LINE = re.compile(r"(?i)\b(example|examples|sample|placeholder|dummy|fixture)\b")
_LOW_RISK_PATH = re.compile(r"(^|/)(api|design|docs?)/|\.(md|example|sample)$", re.I)       # 계약 · 디자인 원본 · 문서 — 예시 값이 많아 일반 규칙(assignment)은 안 본다


def mask(text):
    if not isinstance(text, str):
        return text
    out = text
    for name, rx in SECRET_RES:
        if name == "assignment":
            out = rx.sub(lambda m: m.group(0).replace(m.group(2), MASK), out)
        else:
            out = rx.sub(MASK, out)
    return out


def mask_deep(obj):
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, dict):
        return {k: mask_deep(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_deep(v) for v in obj]
    return obj


def is_sensitive_file(rel):
    rel = rel.replace(os.sep, "/")
    name = rel.rsplit("/", 1)[-1]
    if EXAMPLE_RE.search(name):
        return False
    if SENSITIVE_DIR_RE.search(rel):
        return True
    return any(fnmatch.fnmatch(name, g) for g in SENSITIVE_GLOBS)


# ─────────────────────────── 파일 검사 (pre-commit · 머지) ───────────────────────────

SCAN_MAX_BYTES = 1_048_576


def _peek(val):
    return (val[:3] + MASK) if isinstance(val, str) else MASK


def scan_text(rel, text):
    """파일 하나 — [(규칙, 엿보기)]. 민감 파일 이름이면 ('sensitive-file', 이름)도. 값은 앞 3글자만 보인다."""
    hits = [("sensitive-file", rel)] if is_sensitive_file(rel) else []
    low_risk = bool(_LOW_RISK_PATH.search(rel.replace(os.sep, "/")))
    hits += [(name, _peek(val)) for name, val in find(text or "") if not (low_risk and name == "assignment")]
    return hits


def scan_files(root, rels, reader=None):
    """[(경로, 규칙, 엿보기)]. reader(rel) 가 본문을 주면 그것을(스테이지 · 브랜치), 없으면 디스크. 바이너리 · 1 MiB 초과는 이름만 본다."""
    out = []
    for rel in rels:
        text = ""
        if reader:
            try:
                text = reader(rel) or ""
            except Exception:
                text = ""
        else:
            p = os.path.join(root, rel)
            try:
                if os.path.isfile(p) and os.path.getsize(p) <= SCAN_MAX_BYTES:
                    with open(p, encoding="utf-8") as f:
                        text = f.read()
            except (OSError, UnicodeDecodeError):
                text = ""
        out += [(rel, name, peek) for name, peek in scan_text(rel, text)]
    return out
