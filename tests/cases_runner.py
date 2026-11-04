"""빌드 머신 — 원격 러너 (AGENT.md 15장). 맨 origin(bare) 하나와 같은 프로세스의 가짜 러너 스레드로 git 왕복을 끝까지 돈다."""
import os
import shutil
import subprocess
import tempfile
import threading
import time

from cases import case, check, tmp_repo
from twbuild import config, cycle, device, gate, probe, runner, util

FAKE_TC = {"os": "Linux", "xcodebuild": None, "xcodegen": None, "simulators": None, "java": 17, "android_sdk": "/sdk", "gradle": None, "adb": "/sdk/adb"}
NONE_TC = {**FAKE_TC, "java": None, "android_sdk": None, "adb": None}


def _git(cwd, *a):
    return subprocess.run(["git", "-C", cwd, *a], check=True, capture_output=True, text=True).stdout.strip()


def _origin_pair():
    bare = tempfile.mkdtemp(prefix="twbuild-origin-")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    root = tmp_repo()
    util.write_text(os.path.join(root, "apps/android/app.txt"), "ok\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    _git(root, "remote", "add", "origin", bare)
    _git(root, "push", "-q", "origin", "main")
    return bare, root


class FakeRunner:
    """bare 의 <prefix>/run/** 를 지켜보다 체크아웃해 run-job 을 돌리고 결과를 push 한다 — 워크플로 대역."""

    def __init__(self, bare):
        self.bare, self.stop, self.seen, self.work = bare, False, [], tempfile.mkdtemp(prefix="twbuild-runner-")
        self.t = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        while not self.stop:
            refs = subprocess.run(["git", "--git-dir", self.bare, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/twbuild/run/"],
                                  capture_output=True, text=True).stdout.split("\n")
            for line in filter(None, refs):
                ref, sha = line.split()
                if ref in self.seen:
                    continue
                self.seen.append(ref)
                src = os.path.join(self.work, f"src{len(self.seen)}")
                subprocess.run(["git", "clone", "-q", self.bare, src], check=True)
                _git(src, "checkout", "-q", sha)
                runner.run_job_cli(src, os.path.join(self.work, f"out{len(self.seen)}"), push=True, clean=True)
            time.sleep(0.1)


def _patch():
    """러너 쪽 툴체인 · 빌드 · 기기를 가짜로 — 빌드는 작업 트리에 BROKEN 이 있으면 실패."""
    saved = (probe.toolchain, gate.build, device.run, device.artifact_bytes)

    def build(base, p, vars_, log_path, timeout=1800):
        broken = "BROKEN" in util.read_text(os.path.join(base, "apps/android/app.txt"), "")
        util.write_text(log_path, "> Task :app:compileDebugKotlin\n" + ("e: Unresolved reference: foo token=ghp_abcdefghijklmnopqrstuvwxyz0123456789\n" if broken else "BUILD SUCCESSFUL\n"))
        return {"status": "fail" if broken else "pass", "detail": "exit 1: gradlew assembleDebug" if broken else "1단계 통과", "log": log_path, "ms": 5.0}

    def run(base, p, vars_, log_path, timeout=600, tools=None, screenshot=None):
        util.write_text(log_path, "alive\n")
        if screenshot:
            with open(screenshot, "wb") as f:
                f.write(b"\x89PNG fake")
        return {"status": "pass", "detail": "5초 생존", "log": "alive", "ms": 7.0, **({"screenshot": screenshot} if screenshot else {})}

    probe.toolchain, gate.build, device.run, device.artifact_bytes = (lambda: FAKE_TC), build, run, (lambda *a: 1234)
    return saved


def _unpatch(saved):
    probe.toolchain, gate.build, device.run, device.artifact_bytes = saved


def _cfg(**remote):
    return config._merge(config.DEFAULTS, {"platforms": ["android"], "app": {"name": "Mini", "product": "Mini", "id": "com.example.mini"},
                                           "build": {"runner": "remote", "remote": {"timeout": 30, "poll": 0.1, **remote}}})


@case
def runner_mode_eligibility():
    cfg = config._merge(config.DEFAULTS, {"build": {"runner": {"ios": "remote", "android": "nope"}}})
    check(any("build.runner" in p for p in config.problems(cfg)), config.problems(cfg))
    root = tmp_repo()
    try:
        auto = config._merge(config.DEFAULTS, {})
        os.environ.pop("TWBUILD_NO_BUILD", None)
        try:
            check(runner.mode(root, auto, "android", FAKE_TC) == "local", "툴체인 있으면 local")
            check(runner.mode(root, auto, "android", NONE_TC) == "local", "워크플로가 없으면 local(못 잼)")
            runner.install(root, auto, commit=False)
            check(runner.mode(root, auto, "android", NONE_TC) == "remote", "툴체인 없고 워크플로 있으면 remote")
            check(runner.mode(root, config._merge(auto, {"build": {"runner": {"android": "local"}}}), "android", NONE_TC) == "local", "플랫폼별 설정")
        finally:
            os.environ["TWBUILD_NO_BUILD"] = "1"
        text = util.read_text(os.path.join(root, runner.WORKFLOW))
        check("__" not in text and "twbuild/run/**" in text and "twbuild-android" in text and "run-job" in text, text[:400])
        for url, want in (("https://github.com/o/app.git", "o/app"), ("git@github.com:o/app.git", "o/app"),
                          ("http://local_proxy@127.0.0.1:1234/git/o/app", "o/app"), ("https://gitlab.com/o/app.git", None)):
            subprocess.run(["git", "-C", root, "remote", "remove", "origin"], capture_output=True)
            _git(root, "remote", "add", "origin", url)
            check(runner.origin_repo(root) == want, (url, runner.origin_repo(root)))
        for vis, ok in (("public", False), ("private", True), ("unknown", None), ("not-github", False)):
            os.environ["TWBUILD_VISIBILITY"] = vis
            check(runner.eligible(root)[0] is ok, (vis, runner.eligible(root)))
        try:
            runner.parse_request("twbuild-run android x\n\n" + '{"platform": "android", "jobs": ["rm -rf"], "result_ref": "refs/heads/twbuild/result/android/x"}')
            check(False, "열거형 밖 잡을 받았다")
        except runner.RunnerError:
            pass
    finally:
        os.environ.pop("TWBUILD_VISIBILITY", None)
        shutil.rmtree(root, ignore_errors=True)


@case
def runner_roundtrip_smoke_layers():
    bare, root = _origin_pair()
    fr = FakeRunner(bare)
    saved = _patch()
    os.environ["TWBUILD_VISIBILITY"] = "private"
    try:
        fr.t.start()
        cfg, vars_ = _cfg(), {"product": "Mini", "id": "com.example.mini"}
        logs = {k: os.path.join(root, ".twbuild", "logs", f"{k}.log") for k in ("build", "decode", "device")}
        shot = os.path.join(root, ".twbuild", "reports", "shot.png")
        util.write_text(os.path.join(root, "apps/android/app.txt"), "BROKEN — 커밋 안 된 변경도 러너가 본다\n")
        head = _git(root, "rev-parse", "HEAD")
        rl = runner.remote_layers(root, root, "android", vars_, cfg, ["build", "decode"], logs)
        b = rl["build"]
        check(b["status"] == "fail" and not b.get("runner_error") and "Unresolved reference" in b.get("tail", ""), b)
        check("ghp_abcdef" not in util.read_text(logs["build"]), "러너가 로그를 마스킹한다")
        check(rl["contract_decode"]["status"] == "unmeasured", rl)
        check(_git(root, "rev-parse", "HEAD") == head and "BROKEN" in util.read_text(os.path.join(root, "apps/android/app.txt")), "워크트리 HEAD · 파일은 그대로")
        check(cycle.classify_failure({"android": rl})["kind"] == "rework", "원격 빌드 실패는 개발자 몫")
        util.write_text(os.path.join(root, "apps/android/app.txt"), "fixed\n")
        rl = runner.remote_layers(root, root, "android", vars_, cfg, ["build", "device"], logs, screenshot=shot)
        check(rl["build"]["status"] == "pass" and rl["build"]["bytes"] == 1234 and "왕복" in rl["build"]["runner"], rl["build"])
        check(rl["device"]["status"] == "pass" and rl["device"].get("screenshot") == shot and os.path.getsize(shot) > 0, rl["device"])
        left = subprocess.run(["git", "--git-dir", bare, "for-each-ref", "refs/heads/twbuild/"], capture_output=True, text=True).stdout
        check(left.strip() == "", f"run · result 브랜치가 남았다: {left}")
        # 러너가 없으면 시간 초과 → build fail + runner_error → blocked(harness)
        fr.stop = True
        fr.t.join(timeout=5)
        rl = runner.remote_layers(root, root, "android", vars_, _cfg(timeout=1), ["build", "decode"], logs)
        check(rl["build"]["status"] == "fail" and rl["build"].get("runner_error") and "응답 없음" in rl["build"]["detail"], rl)
        cls = cycle.classify_failure({"android": {"static": {"status": "pass"}, **rl}})
        check(cls["kind"] == "blocked" and cls["owner"] == "harness", cls)
        # public 레포는 왕복 전에 거부
        os.environ["TWBUILD_VISIBILITY"] = "public"
        rl = runner.remote_layers(root, root, "android", vars_, cfg, ["build"], logs)
        check(rl["build"].get("runner_error") and "public" in rl["build"]["detail"], rl)
    finally:
        fr.stop = True
        _unpatch(saved)
        os.environ.pop("TWBUILD_VISIBILITY", None)
        for d in (bare, root, fr.work):
            shutil.rmtree(d, ignore_errors=True)


@case
def runner_ping_and_doctor():
    bare, root = _origin_pair()
    fr = FakeRunner(bare)
    saved = _patch()
    os.environ["TWBUILD_VISIBILITY"] = "private"
    try:
        os.makedirs(os.path.join(root, ".twbuild"), exist_ok=True)
        config.write(root, {"platforms": ["android"], "build": {"runner": "remote", "remote": {"timeout": 30, "poll": 0.1}}})
        cfg = config.load(root)
        check(runner.ping(root, "android", cfg)["ok"] is False, "워크플로 없으면 ping 실패")
        runner.install(root, cfg)
        fr.t.start()
        r = runner.ping(root, "android", cfg)
        check(r["ok"] and r["host"] and r["seconds"] >= 0, r)
        rows = {c["id"]: c for c in probe.checks(root, cfg, NONE_TC)}
        check(rows["runner_android"]["ok"] is True and rows["android_sdk"]["ok"] is None, (rows["runner_android"], rows["android_sdk"]))
        check("remote" in runner.status_markdown(root, cfg), runner.status_markdown(root, cfg))
    finally:
        fr.stop = True
        _unpatch(saved)
        os.environ.pop("TWBUILD_VISIBILITY", None)
        for d in (bare, root, fr.work):
            shutil.rmtree(d, ignore_errors=True)
