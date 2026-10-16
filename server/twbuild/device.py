"""기기 실행 스모크 — 빌드된 앱을 시뮬레이터 · 에뮬레이터(기기)에 올려 띄우고 몇 초 뒤 살아 있는지 본다 (AGENT.md 6장 "빌드 · 실행" 층, PoC 5).

게이트의 빌드 층이 먼저 돈 뒤에 부른다 — 여기서는 빌드하지 않는다. iOS 산출물은 gate.build 의 derivedDataPath
(<base>/.twbuild/derived/ios/Build/Products/Debug-iphonesimulator/<product>.app), Android 는 app-debug.apk.
외부 명령은 전부 시간 제한이 있다 — adb 가 멈춘 적이 있어서. 시간 초과 · 도구 없음 · 산출물 없음은 fail 이 아니라 unmeasured("못 잼").
예외는 밖으로 내지 않는다.

  run(base, platform, vars_, log_path, timeout=600) → {"status": "pass"|"fail"|"unmeasured", "detail": 한국어, "log": 꼬리, "ms": float}
"""
import json
import os
import re
import shutil
import subprocess
import time

from . import util

ALIVE_WAIT = 5.0            # 띄운 뒤 살아 있는지 보기까지 기다리는 시간(초)
LOG_TAIL = 40
ANDROID_APK = os.path.join("app", "build", "outputs", "apk", "debug", "app-debug.apk")
ANDROID_ACTIVITY = ".MainActivity"      # templates/monorepo/android AndroidManifest.xml


class _Unmeasured(Exception):
    """잴 수 없다 — 도구 · 기기 · 산출물이 없거나 시간이 넘었다. 메시지는 한국어 detail."""


class _Fail(Exception):
    """앱이 뜨지 않았거나 죽었다. 메시지는 한국어 detail."""


class _Session:
    """한 번의 실행 — 남은 시간 예산 안에서 명령을 돌리고 로그를 모은다."""

    def __init__(self, log_path, timeout):
        self.log_path = log_path
        self.deadline = time.monotonic() + timeout
        self.lines = []

    def remaining(self):
        return self.deadline - time.monotonic()

    def note(self, text):
        self.lines.append(text)

    def sh(self, cmd, limit=60, check=False, env=None, quiet=False):
        """명령 한 번 → (rc, out). 시간 초과(명령 자체 또는 전체 예산)는 _Unmeasured. quiet 면 출력을 로그에 남기지 않는다(긴 목록)."""
        budget = min(limit, self.remaining())
        if budget <= 0:
            raise _Unmeasured("시간 예산 초과")
        self.note("$ " + " ".join(cmd))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=budget, env=env)
        except subprocess.TimeoutExpired:
            self.note(f"(시간 초과 {budget:.0f}s)")
            raise _Unmeasured(f"명령이 {budget:.0f}s 안에 끝나지 않았다: {' '.join(cmd[:3])}")
        except OSError as e:
            self.note(f"(실행 실패: {e})")
            raise _Unmeasured(f"실행 실패: {cmd[0]} — {e}")
        out = (r.stdout or "") + (r.stderr or "")
        if out.strip() and not quiet:
            self.lines.extend(out.rstrip().splitlines()[-200:])
        if check and r.returncode != 0:
            raise _Fail(f"exit {r.returncode}: {' '.join(cmd[:3])}")
        return r.returncode, out

    def flush(self):
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        util.write_text(self.log_path, "\n".join(self.lines) + "\n")

    def tail(self, n=LOG_TAIL):
        return "\n".join([l for l in self.lines if l.strip()][-n:])


def _tools(tools):
    if tools is None:
        from . import probe
        tools = probe.toolchain()
    return tools


# ─────────────────────────── iOS ───────────────────────────

def _runtime_version(key):
    m = re.search(r"iOS-(\d+)-(\d+)", key or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def _pick_simulator(s):
    """부팅된 iPhone 이 있으면 그것, 없으면 가장 새 런타임의 iPhone. → (udid, 이름, 부팅됨)."""
    _, out = s.sh(["xcrun", "simctl", "list", "-j", "devices", "available"], limit=60, quiet=True)      # 수백 줄 JSON(홈 경로 포함) — 고른 기기만 남긴다
    try:
        devices = json.loads(out).get("devices", {})
    except ValueError:
        raise _Unmeasured("simctl 목록을 읽을 수 없다")
    phones = []
    for rt, devs in devices.items():
        if "iOS" not in rt:
            continue
        for d in devs:
            if "iPhone" in d.get("name", "") and d.get("isAvailable", True):
                phones.append((_runtime_version(rt), d))
    if not phones:
        raise _Unmeasured("iPhone 시뮬레이터가 없다 — Xcode > Settings > Components 에서 iOS 시뮬레이터를 설치한다")
    booted = [d for _, d in phones if d.get("state") == "Booted"]
    if booted:
        s.note(f"시뮬레이터: {booted[0]['name']} ({booted[0]['udid']}, 부팅됨)")
        return booted[0]["udid"], booted[0]["name"], True
    phones.sort(key=lambda p: p[0], reverse=True)
    d = phones[0][1]
    s.note(f"시뮬레이터: {d['name']} ({d['udid']}, iOS {'.'.join(map(str, phones[0][0]))})")
    return d["udid"], d["name"], False


def _ios_alive(s, udid, bundle):
    """시뮬레이터 안의 launchd 가 보는 앱 프로세스 — 라벨에 번들 ID 가 있고 PID 칸이 숫자면 살아 있다."""
    _, out = s.sh(["xcrun", "simctl", "spawn", udid, "launchctl", "list"], limit=60, quiet=True)      # 수백 줄 — 앱 줄만 남긴다
    for line in out.splitlines():
        if bundle in line:
            s.note(line.rstrip())
            pid = line.split()[0] if line.split() else "-"
            if pid.isdigit():
                return int(pid)
    s.note(f"(launchctl 목록에 {bundle} 가 없다)")
    return None


def _ios_crash_info(s, product):
    """죽은 이유 — 최근 1분 안의 진단 보고서 앞부분, 없으면 통합 로그 꼬리. 못 얻어도 그만."""
    reports = os.path.expanduser("~/Library/Logs/DiagnosticReports")
    try:
        cands = sorted((os.path.join(reports, f) for f in os.listdir(reports) if f.startswith(product + "-") and f.endswith(".ips")),
                       key=os.path.getmtime, reverse=True)
        if cands and time.time() - os.path.getmtime(cands[0]) < 120:
            s.note(f"진단 보고서 {os.path.basename(cands[0])}")
            s.lines.extend(util.read_text(cands[0], "").splitlines()[:40])
            return
    except OSError:
        pass
    if shutil.which("log"):
        try:
            s.sh(["log", "show", "--last", "30s", "--style", "compact", "--predicate", f'process == "{product}"'], limit=min(60, max(5, s.remaining())))
        except (_Unmeasured, _Fail):
            pass


def _ios(base, vars_, s, tools):
    if not tools.get("xcodebuild") or not shutil.which("xcrun"):
        raise _Unmeasured("Xcode(xcrun · simctl) 가 없다 — `xcode-select --install` 또는 Xcode 설치")
    product, bundle = vars_["product"], vars_["id"]
    app = os.path.join(base, ".twbuild", "derived", "ios", "Build", "Products", "Debug-iphonesimulator", f"{product}.app")
    if not os.path.isdir(app):
        raise _Unmeasured(f"빌드 산출물이 없다 — 빌드 층이 먼저 돌아야 한다 ({os.path.relpath(app, base)})")
    udid, name, booted = _pick_simulator(s)
    if not booted:
        s.note(f"{name} 부팅")
        s.sh(["xcrun", "simctl", "bootstatus", udid, "-b"], limit=240)      # 부팅하고 끝날 때까지 기다린다
    rc, out = s.sh(["xcrun", "simctl", "install", udid, app], limit=120)
    if rc != 0:
        raise _Fail(f"설치 실패 ({name}): {out.strip().splitlines()[-1] if out.strip() else rc}")
    rc, out = s.sh(["xcrun", "simctl", "launch", udid, bundle], limit=60)
    if rc != 0:
        raise _Fail(f"실행 실패 ({name}): {out.strip().splitlines()[-1] if out.strip() else rc}")
    m = re.search(r":\s*(\d+)\s*$", out.strip())
    pid = int(m.group(1)) if m else None
    time.sleep(min(ALIVE_WAIT, max(0.0, s.remaining())))
    alive = _ios_alive(s, udid, bundle)
    try:
        if alive is None:
            _ios_crash_info(s, product)
            raise _Fail(f"{name}에서 {ALIVE_WAIT:.0f}s 안에 죽었다 (launch pid {pid})")
        if s.screenshot:                                  # 증거 스크린샷 — 실패해도 스모크 판정과 무관
            try:
                s.sh(["xcrun", "simctl", "io", udid, "screenshot", s.screenshot], limit=30, quiet=True)
            except (_Unmeasured, _Fail):
                pass
        return f"{name}에서 {ALIVE_WAIT:.0f}s 뒤 살아 있다 (pid {alive})"
    finally:
        try:
            s.sh(["xcrun", "simctl", "terminate", udid, bundle], limit=30)
        except (_Unmeasured, _Fail):
            pass


# ─────────────────────────── Android ───────────────────────────

def _adb_env(tools):
    return {**os.environ, "ANDROID_HOME": tools.get("android_sdk") or os.environ.get("ANDROID_HOME", "")}


def _avds(s, tools):
    sdk = tools.get("android_sdk")
    emu = os.path.join(sdk, "emulator", "emulator") if sdk else None
    emu = emu if emu and os.path.isfile(emu) else shutil.which("emulator")
    if not emu:
        return []
    try:
        _, out = s.sh([emu, "-list-avds"], limit=20)
    except (_Unmeasured, _Fail):
        return []
    return [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("INFO") and " " not in l.strip()]


def _android(base, vars_, s, tools):
    adb = tools.get("adb")
    if not adb:
        raise _Unmeasured("Android SDK · adb 가 없다 — Android Studio 로 SDK platform-tools 를 설치한다")
    apk = os.path.join(base, util.APPS["android"], ANDROID_APK)
    if not os.path.isfile(apk):
        raise _Unmeasured(f"빌드 산출물이 없다 — 빌드 층이 먼저 돌아야 한다 ({os.path.relpath(apk, base)})")
    env = _adb_env(tools)
    _, out = s.sh([adb, "devices"], limit=20, env=env)
    serials = [l.split()[0] for l in out.splitlines()[1:] if l.strip() and l.split()[-1] == "device"]
    if not serials:
        avds = _avds(s, tools)
        hint = f"`emulator -avd {avds[0]}`" if avds else "Android Studio > Device Manager 에서 AVD 를 만들고 켠다"
        raise _Unmeasured(f"연결된 기기 · 에뮬레이터가 없다 — 에뮬레이터를 켜 두세요: {hint}")
    serial, pkg = serials[0], vars_["id"]
    rc, out = s.sh([adb, "-s", serial, "install", "-r", apk], limit=180, env=env)
    if rc != 0 or "Failure" in out:
        raise _Fail(f"설치 실패 ({serial}): {out.strip().splitlines()[-1] if out.strip() else rc}")
    rc, out = s.sh([adb, "-s", serial, "shell", "am", "start", "-W", "-n", f"{pkg}/{ANDROID_ACTIVITY}"], limit=60, env=env)
    if rc != 0 or "Error" in out:
        raise _Fail(f"실행 실패 ({serial}): {out.strip().splitlines()[-1] if out.strip() else rc}")
    time.sleep(min(ALIVE_WAIT, max(0.0, s.remaining())))
    try:
        _, out = s.sh([adb, "-s", serial, "shell", "pidof", pkg], limit=20, env=env)
        pid = out.strip().split()[0] if out.strip() and out.strip().split()[0].isdigit() else None
        if not pid:
            try:
                s.sh([adb, "-s", serial, "logcat", "-d", "-t", "200", "*:E"], limit=30, env=env)
            except (_Unmeasured, _Fail):
                pass
            raise _Fail(f"{serial}에서 {ALIVE_WAIT:.0f}s 안에 죽었다 ({pkg})")
        if s.screenshot:                                  # 증거 스크린샷 (adb exec-out 은 바이너리 — 따로 받는다)
            _screencap(adb, serial, env, s.screenshot, min(30, max(1, int(s.remaining()))))
        return f"{serial}에서 {ALIVE_WAIT:.0f}s 뒤 살아 있다 (pid {pid})"
    finally:
        try:
            s.sh([adb, "-s", serial, "shell", "am", "force-stop", pkg], limit=20, env=env)
        except (_Unmeasured, _Fail):
            pass


# ─────────────────────────── 입구 ───────────────────────────

def _screencap(adb, serial, env, path, limit):
    try:
        r = subprocess.run([adb, "-s", serial, "exec-out", "screencap", "-p"], capture_output=True, timeout=limit, env=env)
        if r.returncode == 0 and r.stdout[:8] == b"\x89PNG\r\n\x1a\n":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                f.write(r.stdout)
    except (OSError, subprocess.SubprocessError):
        pass


def run(base, platform, vars_, log_path, timeout=600, tools=None, screenshot=None):
    """빌드된 앱을 기기에 띄워 본다. → {"status", "detail", "log", "ms", "screenshot"?}. screenshot: 살아 있을 때 찍을 PNG 경로. 예외를 내지 않는다."""
    t0 = time.monotonic()
    s = _Session(log_path, timeout)
    s.screenshot = screenshot
    status, detail = "unmeasured", ""
    try:
        tools = _tools(tools)
        if platform not in ("ios", "android"):
            raise _Unmeasured(f"모르는 플랫폼: {platform}")
        detail = (_ios if platform == "ios" else _android)(base, vars_, s, tools)
        status = "pass"
    except _Unmeasured as e:
        status, detail = "unmeasured", str(e)
    except _Fail as e:
        status, detail = "fail", str(e)
    except Exception as e:                    # noqa: BLE001 — 스모크가 하네스를 죽이면 안 된다
        status, detail = "unmeasured", f"내부 오류: {type(e).__name__}: {e}"
    s.note(f"→ {status}: {detail}")
    try:
        s.flush()
    except OSError:
        pass
    out = {"status": status, "detail": detail, "log": s.tail(), "ms": round((time.monotonic() - t0) * 1000, 1)}
    if screenshot and os.path.isfile(screenshot) and os.path.getsize(screenshot) > 0:
        out["screenshot"] = screenshot
    return out


def artifact_bytes(base, platform, vars_):
    """빌드 산출물 크기 — iOS .app 디렉터리 합, Android apk. 없으면 None. (나중에: 크기 예산)"""
    if platform == "ios":
        app = os.path.join(base, ".twbuild", "derived", "ios", "Build", "Products", "Debug-iphonesimulator", f"{vars_['product']}.app")
        if not os.path.isdir(app):
            return None
        return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(app) for f in fs if os.path.isfile(os.path.join(d, f)))
    apk = os.path.join(base, util.APPS["android"], ANDROID_APK)
    return os.path.getsize(apk) if os.path.isfile(apk) else None


def available(tools=None):
    """플랫폼마다 기기 층을 잴 수 있는가 — True(기기 있음) · False(툴체인은 있으나 기기 없음) · None(툴체인 없음 · 못 잼). doctor 표용."""
    tools = _tools(tools)
    out = {"ios": None, "android": None}
    if tools.get("xcodebuild") and shutil.which("xcrun"):
        sims = tools.get("simulators")
        out["ios"] = bool(sims) if sims is not None else None
    adb = tools.get("adb")
    if adb:
        try:
            r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=10, env=_adb_env(tools))
            out["android"] = any(l.strip() and l.split()[-1] == "device" for l in (r.stdout or "").splitlines()[1:])
        except (OSError, subprocess.TimeoutExpired):
            out["android"] = None
    return out


def cli(argv, root):
    """`twbuild device ios|android [--base <경로>]` — 사람이 보는 출력은 한국어. → (코드, 텍스트)."""
    from . import config
    if not argv or argv[0] not in ("ios", "android"):
        return 2, "device ios|android [--base <워크트리>]"
    base = root
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1] if i + 1 < len(argv) else root
    vars_ = config.app_vars(config.load(root))
    res = run(base, argv[0], vars_, util.tw(root, util.LOGS_DIR, f"device-{argv[0]}.log"))
    mark = {"pass": "✅", "fail": "❌", "unmeasured": "못 잼"}[res["status"]]
    text = f"{argv[0]} 기기 실행: {mark} {res['detail']} ({res['ms'] / 1000:.1f}s)"
    if res["status"] == "fail" and res["log"]:
        text += "\n" + res["log"]
    return (0 if res["status"] == "pass" else 1), text
