"""설정 — .twbuild/config.yaml. 기본값 · 읽기(기본값 병합) · 쓰기 · 검증 · 해시 · diff.

첫 config 는 templates/config.yaml(주석 포함)에서 만들고, 그 뒤 프로그램이 고칠 때는 yaml_lite.dumps 로 다시 쓴다(주석은 사라진다).
"""
import copy
import os

from . import util, yaml_lite

PLATFORMS = ("ios", "android")
ARCHITECTURES = ("mvvm-udf",)
AUTH_PROVIDERS = ("email", "apple", "google")
SMOKE_DEVICE = ("every", "merge", "off")

DEFAULTS = {
    "platforms": ["ios", "android"],
    "architecture": "mvvm-udf",
    "min_os": {"ios": 17, "android": 26},
    "app": {"name": "", "product": "", "id": ""},        # product: ASCII PascalCase (타겟 · 모듈 이름) · id: com.example.<slug>
    "auth": {"providers": ["email", "apple", "google"]},
    "smoke": {"device": "merge"},
    "budget": {"attempts_per_screen": 5},
    "design": {"fetch": {"include": [], "exclude": [], "max_bytes": 262144}},
    "setup": {"build": True},                             # selfcheck 에서 툴체인이 있으면 빈 골격을 한 번 빌드한다
    "agents": {
        "lead": {"skills": ["archify"]},
        "ios": {"model": "sonnet", "skills": ["swiftui-expert", "swift-concurrency", "swift-security", "authentication",
                                               "push-notifications", "app-store-review"]},
        "android": {"model": "sonnet", "skills": ["jetpack-compose", "compose-state-and-effects", "kotlin-concurrency-and-flow",
                                                   "security", "identity", "navigation", "play", "edge-to-edge"]},
    },
}

# 첫 화면이 머지되면 잠기는 항목 — 바꾸면 이미 만든 코드와 어긋난다 (AGENT.md 14장)
LOCKED_AFTER_FIRST_MERGE = ("architecture", "min_os", "app.id", "app.product")
# 바꾸면 scaffold 를 다시 돌려야 하는 항목
SCAFFOLD_KEYS = ("platforms", "architecture", "min_os", "app", "auth")


def _merge(base, user):
    out = copy.deepcopy(base)
    for k, v in (user or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(root):
    """config.yaml + 기본값. 파일이 없으면 기본값만."""
    raw = yaml_lite.loads(util.read_text(util.config_path(root), ""))
    return _merge(DEFAULTS, raw if isinstance(raw, dict) else {})


def raw(root):
    """파일에 적힌 것만 (기본값 병합 없이). 없으면 None."""
    text = util.read_text(util.config_path(root), "")
    if not text.strip():
        return None
    v = yaml_lite.loads(text)
    return v if isinstance(v, dict) else {}


def write(root, cfg):
    util.write_text(util.config_path(root), yaml_lite.dumps(cfg))


def write_template(root, vars_):
    """첫 config — 주석이 있는 템플릿에서."""
    text = util.render(util.read_text(os.path.join(util.TEMPLATES, "config.yaml")), vars_)
    util.write_text(util.config_path(root), text)


def update(root, **changes):
    """점 경로로 값을 바꾼다 — update(root, **{"app.id": "..."}). 파일에 적힌 것만 다시 쓴다(기본값은 섞지 않는다)."""
    cur = raw(root) or {}
    for path, val in changes.items():
        node = cur
        parts = path.split(".")
        for p in parts[:-1]:
            if not isinstance(node.get(p), dict):
                node[p] = {}
            node = node[p]
        node[parts[-1]] = val
    write(root, cur)
    return cur


def problems(cfg):
    """사람이 고칠 설정 오류 — 한국어 한 줄씩. 비어 있으면 유효."""
    out = []
    plats = cfg.get("platforms")
    if not isinstance(plats, list) or not plats or any(p not in PLATFORMS for p in plats):
        out.append(f"platforms 는 {list(PLATFORMS)} 중 하나 이상이어야 한다: {plats!r}")
    if cfg.get("architecture") not in ARCHITECTURES:
        out.append(f"architecture 는 {list(ARCHITECTURES)} 중 하나다: {cfg.get('architecture')!r}")
    mo = cfg.get("min_os") or {}
    if not isinstance(mo.get("ios"), int) or mo["ios"] < 17:
        out.append(f"min_os.ios 는 17 이상의 정수다(@Observable): {mo.get('ios')!r}")
    if not isinstance(mo.get("android"), int) or mo["android"] < 24:
        out.append(f"min_os.android 는 24 이상의 정수다: {mo.get('android')!r}")
    auth = (cfg.get("auth") or {}).get("providers")
    if not isinstance(auth, list) or any(p not in AUTH_PROVIDERS for p in auth):
        out.append(f"auth.providers 는 {list(AUTH_PROVIDERS)} 의 부분집합이다: {auth!r}")
    if (cfg.get("smoke") or {}).get("device") not in SMOKE_DEVICE:
        out.append(f"smoke.device 는 {list(SMOKE_DEVICE)} 중 하나다")
    b = (cfg.get("budget") or {}).get("attempts_per_screen")
    if not isinstance(b, int) or b < 1:
        out.append("budget.attempts_per_screen 은 1 이상의 정수다")
    app = cfg.get("app") or {}
    if app.get("id") and not all(part.isidentifier() or part.isalnum() for part in str(app["id"]).split(".")):
        out.append(f"app.id 는 점으로 나눈 영숫자 식별자다: {app['id']!r}")
    return out


def digest(cfg):
    """설정 해시 12자 — 측정 기록과 applied.json 에 같은 값이 찍힌다."""
    return util.sha_text(util.stable_json(cfg))[:12]


def diff_keys(old, new, prefix=""):
    """바뀐 최상위 점 경로 목록 (재귀, 리프 단위)."""
    out = []
    keys = set((old or {}).keys()) | set((new or {}).keys())
    for k in sorted(keys):
        a, b = (old or {}).get(k), (new or {}).get(k)
        path = f"{prefix}{k}"
        if isinstance(a, dict) and isinstance(b, dict):
            out += diff_keys(a, b, path + ".")
        elif a != b:
            out.append(path)
    return out


def needs_scaffold(changed):
    return any(c == k or c.startswith(k + ".") for c in changed for k in SCAFFOLD_KEYS)


def app_vars(cfg):
    """템플릿 치환 변수 — 앱 이름 · 식별자 · 패키지 경로 · 최소 OS."""
    app = cfg.get("app") or {}
    pid = app.get("id") or "com.example.app"
    return {
        "name": app.get("name") or "App",
        "product": app.get("product") or "App",
        "id": pid,
        "id_prefix": pid.rsplit(".", 1)[0] if "." in pid else pid,
        "pkg_path": pid.replace(".", "/"),
        "min_ios": str((cfg.get("min_os") or {}).get("ios", 17)),
        "min_android": str((cfg.get("min_os") or {}).get("android", 26)),
        "architecture": cfg.get("architecture") or "mvvm-udf",
    }
