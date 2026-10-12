"""기기 실행 스모크 층(device.py) 검사 — 가짜 xcrun · adb · emulator · log 를 PATH 앞에 두고 pass · crash · boot · hang · 기기 없음을 흉내 낸다.

  python3 -c "import sys; sys.path[:0]=['tests','server']; import cases, cases_device; cases.main([])"
"""
import os
import shutil
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cases import case, check  # noqa: E402
from twbuild import device, util  # noqa: E402

XCRUN = r'''#!/bin/sh
mode="${TWBUILD_FAKE_MODE:-pass}"
echo "xcrun $*" >> "$TWBUILD_FAKE_LOG"
case "$*" in
  "simctl list -j devices available")
    [ "$mode" = hang ] && sleep 10
    if [ "$mode" = boot ]; then booted=Shutdown; else booted=Booted; fi
    printf '{"devices":{"com.apple.CoreSimulator.SimRuntime.iOS-26-0":[{"name":"iPhone 17","udid":"UDID-17","state":"Shutdown","isAvailable":true}],"com.apple.CoreSimulator.SimRuntime.iOS-18-5":[{"name":"iPhone 16","udid":"UDID-16","state":"%s","isAvailable":true}],"com.apple.CoreSimulator.SimRuntime.watchOS-11-0":[{"name":"Apple Watch","udid":"UDID-W","state":"Shutdown","isAvailable":true}]}}' "$booted" ;;
  "simctl bootstatus "*) ;;
  "simctl install "*) ;;
  "simctl launch "*) echo "com.example.mini: 4242" ;;
  "simctl spawn "*" launchctl list")
    printf 'PID\tStatus\tLabel\n'
    if [ "$mode" = crash ]; then printf -- '-\t0\tUIKitApplication:com.example.mini[7a1b][rb-legacy]\n'; else printf '4242\t0\tUIKitApplication:com.example.mini[7a1b][rb-legacy]\n'; fi
    printf '77\t0\tcom.apple.springboard\n' ;;
  "simctl terminate "*) ;;
  *) echo "unexpected xcrun: $*" >&2; exit 1 ;;
esac
'''

ADB = r'''#!/bin/sh
mode="${TWBUILD_FAKE_MODE:-pass}"
echo "adb $*" >> "$TWBUILD_FAKE_LOG"
case "$*" in
  devices)
    [ "$mode" = hang ] && sleep 10
    printf 'List of devices attached\n'
    [ "$mode" = nodevice ] || printf 'emulator-5554\tdevice\n' ;;
  *" install -r "*) echo "Performing Streamed Install"; echo "Success" ;;
  *" shell am start "*) echo "Starting: Intent { cmp=com.example.mini/.MainActivity }"; echo "Status: ok" ;;
  *" shell pidof "*) [ "$mode" = crash ] || echo 3131 ;;
  *" logcat "*) echo "E/AndroidRuntime: FATAL EXCEPTION: main"; echo "E/AndroidRuntime: java.lang.RuntimeException: boom" ;;
  *" shell am force-stop "*) ;;
  *) echo "unexpected adb: $*" >&2; exit 1 ;;
esac
'''

EMULATOR = '#!/bin/sh\necho "emulator $*" >> "$TWBUILD_FAKE_LOG"\ncase "$*" in -list-avds) echo "Pixel_Fake_API_35" ;; esac\n'
LOG = '#!/bin/sh\necho "fake unified log: process crashed"\n'


def _script(path, text):
    util.write_text(path, text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class _Fake:
    """가짜 도구 상자 — PATH 앞에 두고, 끝나면 되돌린다."""

    def __init__(self):
        self.d = tempfile.mkdtemp(prefix="twbuild-device-")
        self.bin = os.path.join(self.d, "bin")
        self.sdk = os.path.join(self.d, "sdk")
        for name, text in (("xcrun", XCRUN), ("log", LOG)):
            _script(os.path.join(self.bin, name), text)
        _script(os.path.join(self.sdk, "platform-tools", "adb"), ADB)
        _script(os.path.join(self.sdk, "emulator", "emulator"), EMULATOR)
        self.calls = os.path.join(self.d, "calls.log")
        util.write_text(self.calls, "")
        self.base = os.path.join(self.d, "repo")
        os.makedirs(os.path.join(self.base, ".twbuild", "derived", "ios", "Build", "Products", "Debug-iphonesimulator", "Mini.app"))
        util.write_text(os.path.join(self.base, "apps", "android", device.ANDROID_APK), "apk")
        self.vars = {"product": "Mini", "id": "com.example.mini"}
        self.ios_tools = {"xcodebuild": "Xcode fake", "simulators": 2, "android_sdk": None, "adb": None}
        self.android_tools = {"xcodebuild": None, "simulators": None, "android_sdk": self.sdk, "adb": os.path.join(self.sdk, "platform-tools", "adb")}
        self.saved = {k: os.environ.get(k) for k in ("PATH", "TWBUILD_FAKE_MODE", "TWBUILD_FAKE_LOG")}
        self.saved_wait = device.ALIVE_WAIT

    def __enter__(self):
        os.environ["PATH"] = self.bin + os.pathsep + self.saved["PATH"]
        os.environ["TWBUILD_FAKE_LOG"] = self.calls
        device.ALIVE_WAIT = 0.2
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        device.ALIVE_WAIT = self.saved_wait
        shutil.rmtree(self.d, ignore_errors=True)

    def run(self, platform, mode="pass", timeout=30):
        os.environ["TWBUILD_FAKE_MODE"] = mode
        tools = self.ios_tools if platform == "ios" else self.android_tools
        return device.run(self.base, platform, self.vars, os.path.join(self.base, ".twbuild", "logs", f"device-{platform}.log"), timeout=timeout, tools=tools)

    def called(self):
        return util.read_text(self.calls, "")


@case
def device_ios_pass_crash_boot():
    with _Fake() as f:
        r = f.run("ios")
        check(r["status"] == "pass" and "iPhone 16" in r["detail"] and "살아 있다" in r["detail"] and "pid 4242" in r["detail"], r)
        check("simctl install UDID-16" in f.called() and "simctl terminate UDID-16 com.example.mini" in f.called() and "bootstatus" not in f.called(), f.called())
        check(os.path.isfile(os.path.join(f.base, ".twbuild", "logs", "device-ios.log")) and r["ms"] > 0 and "→ pass" in r["log"], r)
        r = f.run("ios", "crash")
        check(r["status"] == "fail" and "죽었다" in r["detail"] and "fake unified log" in r["log"], r)
        check("simctl terminate" in f.called().splitlines()[-1], "죽어도 terminate 는 한다")
        r = f.run("ios", "boot")       # 부팅된 게 없으면 가장 새 런타임의 iPhone 을 부팅한다 (watchOS 는 제외)
        check(r["status"] == "pass" and "iPhone 17" in r["detail"] and "simctl bootstatus UDID-17 -b" in f.called(), (r, f.called()))


@case
def device_ios_unmeasured():
    with _Fake() as f:
        t0 = time.monotonic()
        r = f.run("ios", "hang", timeout=2)
        check(r["status"] == "unmeasured" and "끝나지 않았다" in r["detail"] and time.monotonic() - t0 < 6, r)
        shutil.rmtree(os.path.join(f.base, ".twbuild", "derived"))
        r = f.run("ios")
        check(r["status"] == "unmeasured" and "빌드 산출물" in r["detail"], r)
        r = device.run(f.base, "ios", f.vars, os.path.join(f.base, ".twbuild", "logs", "x.log"), tools={"xcodebuild": None})
        check(r["status"] == "unmeasured" and "Xcode" in r["detail"], r)
        r = device.run(f.base, "web", f.vars, os.path.join(f.base, ".twbuild", "logs", "x.log"), tools={})
        check(r["status"] == "unmeasured" and "모르는 플랫폼" in r["detail"], r)


@case
def device_android_pass_crash_nodevice():
    with _Fake() as f:
        r = f.run("android")
        check(r["status"] == "pass" and "emulator-5554" in r["detail"] and "pid 3131" in r["detail"], r)
        c = f.called()
        check("install -r" in c and "shell am start -W -n com.example.mini/.MainActivity" in c and "shell am force-stop com.example.mini" in c, c)
        r = f.run("android", "crash")
        check(r["status"] == "fail" and "죽었다" in r["detail"] and "FATAL EXCEPTION" in r["log"], r)
        r = f.run("android", "nodevice")
        check(r["status"] == "unmeasured" and "에뮬레이터를 켜 두세요" in r["detail"] and "emulator -avd Pixel_Fake_API_35" in r["detail"], r)
        t0 = time.monotonic()
        r = f.run("android", "hang", timeout=2)
        check(r["status"] == "unmeasured" and "끝나지 않았다" in r["detail"] and time.monotonic() - t0 < 6, r)
        os.remove(os.path.join(f.base, "apps", "android", device.ANDROID_APK))
        r = f.run("android")
        check(r["status"] == "unmeasured" and "빌드 산출물" in r["detail"], r)


@case
def device_available():
    with _Fake() as f:
        os.environ["TWBUILD_FAKE_MODE"] = "pass"
        a = device.available({**f.ios_tools, **{"android_sdk": f.sdk, "adb": f.android_tools["adb"]}})
        check(a == {"ios": True, "android": True}, a)
        os.environ["TWBUILD_FAKE_MODE"] = "nodevice"
        check(device.available(f.android_tools) == {"ios": None, "android": False}, "기기 없음 → False")
        os.environ["TWBUILD_FAKE_MODE"] = "hang"
        t0 = time.monotonic()
        check(device.available(f.android_tools)["android"] is None and time.monotonic() - t0 < 15, "adb 멈춤 → None")
        check(device.available({}) == {"ios": None, "android": None}, "툴체인 없음 → None")
