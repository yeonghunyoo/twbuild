"""공용 — 경로 · 파일 · 해시 · 시각 · 이름 변환.

대상 레포 안의 자리:
  .twbuild/            도구 상태 (gitignore) — config.yaml · graph.sqlite · applied.json · metrics/ · logs/ · worktrees/ · tasks/
  design/              디자인 정본 (커밋, 하네스가 쓴다)
  features/            app.md(앱 개요) · <기능>/ 기능 팩
  api/                 openapi.yaml(본문) · fragments/(조각) · generated/(합친 계약 · 라우트 — 생성물)
  apps/ios · apps/android
  .claude/rules/       프로젝트 장기 메모리 (전부 경로 스코프)
"""
import datetime
import hashlib
import json
import os
import re
import subprocess

TW_DIR = ".twbuild"
CONFIG = "config.yaml"
GRAPH_DB = "graph.sqlite"
APPLIED = "applied.json"          # 마지막 셋업이 적용한 것 — 설정 해시 · 시각. probe 가 설정 diff 를 이것과 잰다
SELFCHECK = "selfcheck.json"
METRICS_DIR = "metrics"
LOGS_DIR = "logs"
WORKTREES = "worktrees"
TASKS = "tasks"

DESIGN_DIR = "design"
FEATURES_DIR = "features"
APP_BRIEF = os.path.join(FEATURES_DIR, "app.md")
API_DIR = "api"
API_FILE = "openapi.yaml"
FRAGMENTS_DIR = os.path.join(API_DIR, "fragments")
API_GENERATED = os.path.join(API_DIR, "generated")
APPS = {"ios": os.path.join("apps", "ios"), "android": os.path.join("apps", "android")}
RULES_DIR = os.path.join(".claude", "rules")
RULE_SCOPES = ("ios", "android", "team", "lead")

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES = os.path.join(PLUGIN_ROOT, "templates")


# ─────────────────────────── 경로 ───────────────────────────

def tw(root, *parts):
    return os.path.join(root, TW_DIR, *parts)


def config_path(root):
    return tw(root, CONFIG)


def is_wired(root):
    return os.path.isfile(config_path(root))


def app_dir(root, platform):
    return os.path.join(root, APPS[platform])


def data_dir():
    """플러그인 데이터 디렉터리 — venv · 공개 스킬 캐시. 플러그인 업데이트에도 남는다.
    Bash 도구에는 CLAUDE_PLUGIN_DATA 가 없어서 고정 경로를 쓴다 (TWBUILD_DATA 로 바꿀 수 있다)."""
    d = os.environ.get("TWBUILD_DATA", "")
    if not d or d.startswith("$"):
        d = os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "twbuild")
    return d


# ─────────────────────────── 플러그인 버전 ───────────────────────────

_version = None


def plugin_version():
    """{"plugin": "0.0.1", "commit": "abc1234"} — 측정 기록마다 붙인다."""
    global _version
    if _version is None:
        manifest = read_json(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), {}) or {}
        commit = ""
        try:
            r = subprocess.run(["git", "-C", PLUGIN_ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
            commit = r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            pass
        _version = {"plugin": str(manifest.get("version") or "0"), "commit": commit}
    return _version


# ─────────────────────────── 시각 · 파일 · 해시 ───────────────────────────

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def read_text(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(directory):
    """디렉터리 전체의 결정적 해시 (상대경로 + 내용). 없으면 빈 문자열. 숨김 파일은 뺀다."""
    if not os.path.isdir(directory):
        return ""
    h = hashlib.sha256()
    for base, dirs, names in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for n in sorted(names):
            if n.startswith("."):
                continue
            p = os.path.join(base, n)
            rel = os.path.relpath(p, directory).replace(os.sep, "/")
            h.update(rel.encode())
            h.update(b"\0")
            h.update(sha_file(p).encode())
            h.update(b"\n")
    return h.hexdigest()


def stable_json(obj):
    """같은 입력 = 같은 바이트 — 생성물 비교에 쓰는 직렬화."""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ─────────────────────────── 이름 ───────────────────────────

def ascii_words(name):
    """이름에서 ASCII 단어만 — 한글 등은 버린다. 식별자 유도의 재료."""
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", str(name or "")) if p]
    words = []
    for p in parts:
        words += re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", p) or [p]
    return words


def slug(name):
    """com.example.<slug> 의 slug — 소문자 영숫자. 글자가 없으면 빈 문자열(호출자가 다시 묻는다)."""
    s = "".join(w.lower() for w in ascii_words(name))
    s = s.lstrip("0123456789")
    return s


def pascal(name):
    """Swift 타겟 · Kotlin 모듈에 쓰는 PascalCase 이름."""
    words = ascii_words(name)
    out = "".join(w[:1].upper() + w[1:].lower() for w in words)
    if out and out[0].isdigit():
        out = "App" + out
    return out


def render(text, vars_):
    """템플릿 치환 — {{key}} 만. 모르는 키는 그대로 둔다(생성물 검사가 잡는다)."""
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(vars_.get(m.group(1), m.group(0))), text)
