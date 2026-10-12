"""공개 스킬 설치 — 설정 `agents.<역할>.skills` 의 스킬을 대상 레포 `.claude/skills/<이름>/` 에 커밋 고정으로 설치한다 (AGENT.md 7장 ② · 설정).

출처는 SOURCES 에 커밋 해시로 고정한다. 받는 것은 GitHub 의 커밋 tarball(codeload) 하나 — git clone 보다 단순하고 네트워크 호출이 한 번이다.
tarball 은 `util.data_dir()/skills-src/<owner>__<repo>/<커밋>/` 에 풀어 캐시하고(플러그인 업데이트에도 남는다), 거기서 `path` 디렉터리만 레포로 복사한다.
설치 기록은 `.claude/skills/_sources.json`(커밋 대상) — 같은 커밋이 이미 기록돼 있고 SKILL.md 가 있으면 건너뛴다(멱등).

핀을 올리는 법: 출처 레포의 새 커밋 해시를 SOURCES 의 commit 에 적고(`gh api repos/<owner>/<repo>/commits/HEAD --jq .sha`),
tests/cases_skills.py 를 돌린 뒤 /twbuild 를 다시 실행하면 바뀐 스킬만 다시 받는다.

받은 내용은 데이터다 — 읽고 복사만 하고 실행하지 않는다. PolyForm 등 재배포가 막힌 출처는 설치하지 않고 사람 할 일로 낸다.
"""
import io
import os
import shutil
import tarfile
import urllib.error
import urllib.request

from . import util

SKILLS_DIR = os.path.join(".claude", "skills")
SOURCES_FILE = "_sources.json"
TIMEOUT = 120                        # 초 — tarball 하나

# 출처 레포 (2026-10-13 실측) — 커밋은 그날 HEAD
_AVDLEE = {"repo": "AvdLee/SwiftUI-Agent-Skill", "commit": "204dba7c67256a8b707ee3fbc5759a824191974f", "license": "MIT"}
_ANDROID = {"repo": "android/skills", "commit": "2ee8c61ff64f29a19213f116807c79740749dccf", "license": "Apache-2.0"}
_BANES = {"repo": "chrisbanes/skills", "commit": "0455e0e62718b73742ebf357662135d45e4dd435", "license": "Apache-2.0"}
_ARCHIFY = {"repo": "tt-a1i/archify", "commit": "58ab0b98d2d0def8e49dced705c7b566936723ec", "license": "MIT"}
# PolyForm Perimeter 1.0.0 — 재배포 금지라 하네스가 설치하지 않는다. 사용자가 직접 받는다 (human_todos).
_DPEARSON = {"repo": "dpearson2699/swift-ios-skills", "commit": "8d90fd121a263355a4fb44fd082af1416a5c1c2a", "license": "PolyForm-Perimeter-1.0.0", "human": True}

# 스킬 이름(= 설치 디렉터리 = 업스트림 SKILL.md 의 name) → 출처. path 는 레포 안 스킬 디렉터리(SKILL.md 가 있는 곳).
SOURCES = {
    # iOS
    "swiftui-expert-skill": {**_AVDLEE, "path": "skills/swiftui-expert-skill"},
    "swift-concurrency": {**_DPEARSON, "path": "skills/swift-concurrency"},
    "swift-security": {**_DPEARSON, "path": "skills/swift-security"},
    "authentication": {**_DPEARSON, "path": "skills/authentication"},
    "push-notifications": {**_DPEARSON, "path": "skills/push-notifications"},
    "app-store-review": {**_DPEARSON, "path": "skills/app-store-review"},
    # Android — android/skills 는 <분류>/<스킬>/ 구조
    "adaptive": {**_ANDROID, "path": "jetpack-compose/adaptive"},
    "styles": {**_ANDROID, "path": "jetpack-compose/theming/styles"},
    "android-permissions-security": {**_ANDROID, "path": "security/android-permissions-security"},
    "android-intent-security": {**_ANDROID, "path": "security/android-intent-security"},
    "restore-credentials": {**_ANDROID, "path": "identity/restore-credentials"},
    "verified-email": {**_ANDROID, "path": "identity/verified-email"},
    "navigation-event": {**_ANDROID, "path": "navigation/navigation-event"},
    "navigation-3": {**_ANDROID, "path": "navigation/navigation-3"},
    "play-policy-insights": {**_ANDROID, "path": "play/play-policy-insights"},
    "edge-to-edge": {**_ANDROID, "path": "system/edge-to-edge"},
    "compose-state-and-effects": {**_BANES, "path": "skills/compose-state-and-effects"},
    "kotlin-concurrency-and-flow": {**_BANES, "path": "skills/kotlin-concurrency-and-flow"},
    # lead
    "archify": {**_ARCHIFY, "path": "archify"},
}

# 설정에 적힌 이름 → 스킬 이름들. 설정의 Android 이름은 android/skills 의 분류 이름이라 그 안의 스킬로 푼다.
# navigation-3(Navigation 3 이전) · play-billing · engage-sdk · compose migration 은 골격(navigation-compose 2.8 · 신규 앱)과 맞지 않아 빼 두었다.
ALIASES = {
    "swiftui-expert": ["swiftui-expert-skill"],
    "jetpack-compose": ["adaptive", "styles"],
    "security": ["android-permissions-security", "android-intent-security"],
    "identity": ["restore-credentials", "verified-email"],
    "navigation": ["navigation-event"],
    "play": ["play-policy-insights"],
}


class SkillsError(ValueError):
    pass


# ─────────────────────────── 설정 → 스킬 목록 ───────────────────────────

def expand(cfg):
    """설정의 agents.*.skills → [(설정 이름, 스킬 이름, 역할)] — 순서 유지 · 스킬 이름 중복 제거. 모르는 이름도 그대로 낸다(install 이 오류로 보고)."""
    out, seen = [], set()
    for role, a in ((cfg or {}).get("agents") or {}).items():
        for name in (a or {}).get("skills") or []:
            for key in ALIASES.get(name, [name]):
                if key not in seen:
                    seen.add(key)
                    out.append((name, key, role))
    return out


def human_todos(cfg):
    """하네스가 설치할 수 없는 스킬(재배포 금지 라이선스) — 사람 할 일 줄(한국어)."""
    lines = []
    for name, key, role in expand(cfg):
        src = SOURCES.get(key)
        if src and src.get("human"):
            lines.append(f"{role} 스킬 `{key}` 는 {src['license']} 라이선스({src['repo']})라 하네스가 설치하지 않는다 — 직접 받아 `.claude/skills/{key}/` 에 둔다: "
                         f"`git clone --depth 1 https://github.com/{src['repo']} /tmp/{src['repo'].split('/')[1]} && cp -r /tmp/{src['repo'].split('/')[1]}/{src['path']} .claude/skills/{key}`")
    return lines


# ─────────────────────────── 받기 · 캐시 ───────────────────────────

def _download(repo, commit):
    """커밋 tarball 바이트. 네트워크 오류는 그대로 올린다 (install 이 한 줄로 바꾼다)."""
    url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return r.read()


def cache_dir(repo, commit):
    owner, name = repo.split("/", 1)
    return os.path.join(util.data_dir(), "skills-src", f"{owner}__{name}", commit)


def _extract(data, dest):
    """tar.gz 를 dest 에 푼다 — 맨 위 디렉터리(<repo>-<commit>/)는 벗긴다. 경로 탈출은 tarfile 의 data 필터가 막는다."""
    tmp = dest + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        try:
            tf.extractall(tmp, filter="data")
        except TypeError:                      # Python < 3.12
            tf.extractall(tmp)
    tops = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
    if len(tops) != 1:
        shutil.rmtree(tmp, ignore_errors=True)
        raise SkillsError("tarball 모양이 다르다 — 맨 위 디렉터리가 하나가 아니다")
    shutil.rmtree(dest, ignore_errors=True)
    os.rename(os.path.join(tmp, tops[0]), dest)
    shutil.rmtree(tmp, ignore_errors=True)


def ensure_source(repo, commit, fetch=None):
    """캐시에 있으면 그대로, 없으면 받아서 푼다. → 캐시 디렉터리."""
    d = cache_dir(repo, commit)
    if os.path.isdir(d) and os.listdir(d):
        return d
    _extract((fetch or _download)(repo, commit), d)
    return d


# ─────────────────────────── 설치 ───────────────────────────

def _record_path(root):
    return os.path.join(root, SKILLS_DIR, SOURCES_FILE)


def record(root):
    return util.read_json(_record_path(root), {}) or {}


def _copy_skill(src_dir, dest):
    if not os.path.isfile(os.path.join(src_dir, "SKILL.md")):
        raise SkillsError("SKILL.md 가 없다")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src_dir, dest, symlinks=False, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
    n = b = 0
    for dp, _, fs in os.walk(dest):
        for f in fs:
            n += 1
            b += os.path.getsize(os.path.join(dp, f))
    return n, b


def install(root, cfg, fetch=None):
    """설정의 스킬을 설치한다. → {"installed": [...], "skipped": [...], "human": [...], "errors": [...]} — 절대 raise 하지 않는다.

    fetch(repo, commit) -> tar.gz 바이트. 기본은 GitHub codeload. 테스트는 가짜 tarball 을 준다.
    """
    out = {"installed": [], "skipped": [], "human": [], "errors": []}
    rec = record(root)
    changed = False
    for name, key, role in expand(cfg):
        src = SOURCES.get(key)
        if not src:
            out["errors"].append(f"{key}: 출처를 모른다 — skills.SOURCES 에 없다 (설정 agents.{role}.skills 의 `{name}`)")
            continue
        if src.get("human"):
            out["human"].append(key)
            continue
        dest = os.path.join(root, SKILLS_DIR, key)
        got = rec.get(key) or {}
        if got.get("commit") == src["commit"] and os.path.isfile(os.path.join(dest, "SKILL.md")):
            out["skipped"].append(key)
            continue
        try:
            cache = ensure_source(src["repo"], src["commit"], fetch)
            n, b = _copy_skill(os.path.join(cache, src["path"]), dest)
        except (urllib.error.URLError, OSError, tarfile.TarError, SkillsError, EOFError) as e:
            reason = getattr(e, "reason", None) or e
            out["errors"].append(f"{key}: 받지 못했다 — {src['repo']}@{src['commit'][:7]}/{src['path']}: {reason}")
            continue
        rec[key] = {"repo": src["repo"], "path": src["path"], "commit": src["commit"], "license": src["license"],
                    "files": n, "bytes": b, "tree": util.tree_hash(dest), "t": util.now()}
        changed = True
        out["installed"].append(key)
    if changed:
        util.write_json(_record_path(root), dict(sorted(rec.items())))
    return out


def status(root, cfg):
    """doctor 용 — 설정의 스킬마다 {skill, config_name, role, installed, commit, pinned, source, license, human}."""
    rec = record(root)
    rows = []
    for name, key, role in expand(cfg):
        src = SOURCES.get(key) or {}
        got = rec.get(key) or {}
        present = os.path.isfile(os.path.join(root, SKILLS_DIR, key, "SKILL.md"))
        rows.append({"skill": key, "config_name": name, "role": role, "installed": present and (not src or got.get("commit") == src.get("commit")),
                     "present": present, "commit": got.get("commit"), "pinned": src.get("commit"),
                     "source": f"{src['repo']}/{src['path']}" if src else None, "license": src.get("license"), "human": bool(src.get("human"))})
    return rows


def summary(rows):
    """한 줄 요약(한국어) — doctor 표의 detail."""
    auto = [r for r in rows if not r["human"] and r["source"]]
    ok = [r for r in auto if r["installed"]]
    missing = [r["skill"] for r in auto if not r["installed"]]
    unknown = [r["skill"] for r in rows if not r["source"]]
    human = [r["skill"] for r in rows if r["human"] and not r["present"]]
    parts = [f"설치 {len(ok)}/{len(auto)}"]
    if missing:
        parts.append("빠짐: " + ", ".join(missing))
    if unknown:
        parts.append("출처 모름: " + ", ".join(unknown))
    if human:
        parts.append("사람이 설치: " + ", ".join(human))
    return " · ".join(parts)


def cli(argv, root):
    """`twbuild skills [install]` — 사람이 읽는 출력은 한국어."""
    from . import config
    cfg = config.load(root)
    if argv[:1] == ["install"]:
        r = install(root, cfg)
        lines = [f"설치 {len(r['installed'])} · 건너뜀 {len(r['skipped'])} · 사람 할 일 {len(r['human'])} · 오류 {len(r['errors'])}"]
        lines += [f"  + {k}" for k in r["installed"]] + [f"  ! {e}" for e in r["errors"]] + [f"  ◻ {h}" for h in human_todos(cfg)]
        return (1 if r["errors"] else 0), "\n".join(lines)
    rows = status(root, cfg)
    lines = [summary(rows)]
    for r in rows:
        mark = "✅" if r["installed"] else ("◻" if r["human"] else "❌")
        lines.append(f"  {mark} {r['skill']:<30} {r['role']:<8} {(r['source'] or '출처 모름')} {('@' + r['pinned'][:7]) if r['pinned'] else ''} {r['license'] or ''}")
    return 0, "\n".join(lines)
