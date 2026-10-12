"""공개 스킬 설치(skills.py) 검사 — 네트워크 없이 가짜 tarball 로. cases.py 와 같이 돈다:

  python3 -c "import sys; sys.path[:0]=['tests','server']; import cases, cases_skills; cases.main([])"
"""
import io
import os
import re
import tarfile
import tempfile

from cases import case, check, tmp_repo  # noqa: E402

from twbuild import config, skills, util  # noqa: E402


def _tarball(repo, commit, paths, skill_md="---\nname: x\n---\n# x\n", extra=None):
    """<repo>-<commit>/<path>/SKILL.md 들이 든 tar.gz 바이트 — 업스트림 codeload 와 같은 모양."""
    top = f"{repo.split('/')[1]}-{commit}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in paths:
            for rel, text in [("SKILL.md", skill_md), ("reference/notes.md", "notes\n")] + list((extra or {}).get(p, [])):
                data = text.encode()
                ti = tarfile.TarInfo(f"{top}/{p}/{rel}")
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _fake_fetch(calls=None, fail=()):
    """SOURCES 의 실제 경로대로 가짜 tarball 을 준다. fail 에 든 레포는 네트워크 오류."""
    def fetch(repo, commit):
        if calls is not None:
            calls.append(repo)
        if repo in fail:
            raise OSError("가짜 네트워크 오류")
        paths = sorted({s["path"] for s in skills.SOURCES.values() if s["repo"] == repo and s["commit"] == commit})
        return _tarball(repo, commit, paths)
    return fetch


def _isolated_data():
    d = tempfile.mkdtemp(prefix="twbuild-skills-data-")
    os.environ["TWBUILD_DATA"] = d
    return d


@case
def skills_sources_and_expand():
    for key, s in skills.SOURCES.items():
        check(re.fullmatch(r"[a-z0-9-]+", key), f"스킬 이름 형식: {key}")
        check(re.fullmatch(r"[0-9a-f]{40}", s["commit"]) and "/" in s["repo"] and s["path"] and s["license"], f"출처 필드: {key} {s}")
    # 기본 설정의 이름은 전부 출처가 있다 (별칭 포함) — 모르는 이름이 생기면 템플릿을 고친다
    rows = skills.expand(config.DEFAULTS)
    unknown = [k for _, k, _ in rows if k not in skills.SOURCES]
    check(not unknown, f"출처 모름: {unknown}")
    keys = [k for _, k, _ in rows]
    check(len(keys) == len(set(keys)), "중복")
    check(("jetpack-compose", "adaptive", "android") in rows and ("swiftui-expert", "swiftui-expert-skill", "ios") in rows, rows[:5])
    # PolyForm 은 사람 할 일로 나온다
    todos = skills.human_todos(config.DEFAULTS)
    check(len(todos) == 5 and all("PolyForm" in t and "dpearson2699" in t for t in todos), todos)
    check(all(skills.SOURCES[k].get("human") for k in ("swift-concurrency", "swift-security", "authentication", "push-notifications", "app-store-review")), "human 표시")


@case
def skills_install_fake():
    _isolated_data()
    root = tmp_repo()
    cfg = {"agents": {"lead": {"skills": ["archify"]}, "ios": {"skills": ["swiftui-expert", "swift-concurrency"]},
                      "android": {"skills": ["jetpack-compose", "edge-to-edge", "compose-state-and-effects", "nope-skill"]}}}
    calls = []
    r = skills.install(root, cfg, fetch=_fake_fetch(calls))
    check(set(r["installed"]) == {"archify", "swiftui-expert-skill", "adaptive", "styles", "edge-to-edge", "compose-state-and-effects"}, r)
    check(r["human"] == ["swift-concurrency"] and r["skipped"] == [], r)
    check(len(r["errors"]) == 1 and "nope-skill" in r["errors"][0] and "출처를 모른다" in r["errors"][0], r["errors"])
    # 레포마다 tarball 한 번 — 캐시
    check(sorted(calls) == sorted({"tt-a1i/archify", "AvdLee/SwiftUI-Agent-Skill", "android/skills", "chrisbanes/skills"}), calls)
    for k in r["installed"]:
        check(os.path.isfile(os.path.join(root, ".claude", "skills", k, "SKILL.md")), k)
    check(not os.path.exists(os.path.join(root, ".claude", "skills", "swift-concurrency")), "PolyForm 은 설치하지 않는다")
    rec = skills.record(root)
    check(set(rec) == set(r["installed"]) and rec["edge-to-edge"]["commit"] == skills.SOURCES["edge-to-edge"]["commit"]
          and rec["edge-to-edge"]["files"] == 2 and rec["edge-to-edge"]["license"] == "Apache-2.0" and rec["edge-to-edge"]["tree"], rec.get("edge-to-edge"))
    # 캐시 위치는 데이터 디렉터리 (레포 밖)
    check(os.path.isdir(skills.cache_dir("android/skills", skills.SOURCES["edge-to-edge"]["commit"])) and util.data_dir() in skills.cache_dir("android/skills", "x"), "캐시")
    # 멱등 — 두 번째는 전부 건너뛰고 받지 않는다
    calls2 = []
    r2 = skills.install(root, cfg, fetch=_fake_fetch(calls2))
    check(r2["installed"] == [] and set(r2["skipped"]) == set(r["installed"]) and calls2 == [], r2)
    # 스킬 디렉터리를 지우면 다시 설치한다 (캐시에서, 네트워크 없이)
    import shutil
    shutil.rmtree(os.path.join(root, ".claude", "skills", "edge-to-edge"))
    r3 = skills.install(root, cfg, fetch=_fake_fetch(calls2))
    check(r3["installed"] == ["edge-to-edge"] and calls2 == [], r3)
    # status · summary
    rows = skills.status(root, cfg)
    by = {x["skill"]: x for x in rows}
    check(by["edge-to-edge"]["installed"] and by["swift-concurrency"]["human"] and not by["swift-concurrency"]["installed"]
          and by["nope-skill"]["source"] is None, by)
    s = skills.summary(rows)
    check("설치 6/6" in s and "출처 모름: nope-skill" in s and "사람이 설치: swift-concurrency" in s, s)


@case
def skills_install_errors():
    _isolated_data()
    root = tmp_repo()
    cfg = {"agents": {"android": {"skills": ["edge-to-edge", "compose-state-and-effects"]}}}
    # 네트워크 오류 → errors 한 줄, raise 없음, 다른 출처는 설치됨
    r = skills.install(root, cfg, fetch=_fake_fetch(fail=("android/skills",)))
    check(r["installed"] == ["compose-state-and-effects"] and len(r["errors"]) == 1 and "edge-to-edge" in r["errors"][0] and "받지 못했다" in r["errors"][0], r)
    check(not os.path.exists(skills.cache_dir("android/skills", skills.SOURCES["edge-to-edge"]["commit"])), "실패한 받기는 캐시에 남지 않는다")
    # tarball 에 path 가 없다 → SKILL.md 없음 오류
    def bad(repo, commit):
        return _tarball(repo, commit, ["somewhere/else"])
    r = skills.install(root, {"agents": {"android": {"skills": ["edge-to-edge"]}}}, fetch=bad)
    check(r["installed"] == [] and len(r["errors"]) == 1 and "SKILL.md" in r["errors"][0], r)
    # 기록 파일은 설치된 것만
    check(set(skills.record(root)) == {"compose-state-and-effects"}, skills.record(root))
    # 설정에 스킬이 없으면 아무 일도 없다
    r = skills.install(root, {}, fetch=_fake_fetch())
    check(r == {"installed": [], "skipped": [], "human": [], "errors": []}, r)
    # cli 는 (code, 한국어 텍스트). config.load 는 기본값을 합치므로 lead(archify) · ios 기본 스킬도 표에 나온다
    util.write_text(util.config_path(root), "agents:\n  android: {skills: [compose-state-and-effects]}\n")
    code, text = skills.cli([], root)
    check(code == 0 and "설치 1/3" in text and "✅ compose-state-and-effects" in text and "빠짐: archify" in text and "◻ swift-concurrency" in text, text)
