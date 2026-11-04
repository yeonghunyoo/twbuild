#!/usr/bin/env bash
# twbuild iOS 빌드 머신(Mac) 셋업 — AGENT.md 15장 · "twbuild 빌드 머신 셋업 가이드"의 Mac 절.
#
#   1) 관리자 계정에서:   bash mac-setup.sh admin  [--create-user]
#   2) 러너 계정에서:     bash mac-setup.sh runner <소유자>/<앱 레포>
#   3) 언제든:            bash mac-setup.sh check
#
# 러너 등록 토큰은 GitHub 앱 레포 → Settings → Actions → Runners → New self-hosted runner 화면의
# `--token` 값이다(1시간 유효). 스크립트가 입력을 숨겨 묻는다 — 명령줄 인자로 넘기지 않는다(셸 기록에 남는다).
set -euo pipefail

RUNNER_USER="${TWBUILD_RUNNER_USER:-twbuild-runner}"
RUNNER_DIR="${TWBUILD_RUNNER_DIR:-$HOME/actions-runner}"
LABEL="twbuild-ios"
NAME="${TWBUILD_RUNNER_NAME:-mac-ios}"

ok()   { printf '  ✅ %s\n' "$*"; }
bad()  { printf '  ❌ %s\n' "$*"; FAILED=1; }
step() { printf '\n▶ %s\n' "$*"; }
die()  { printf '❌ %s\n' "$*" >&2; exit 1; }

brew_bin() {
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && { echo "$b"; return; }; done
  command -v brew || true
}

py_ok() {   # python3 가 3.10 이상인가
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

# ─────────────────────────── check ───────────────────────────
check() {
  FAILED=0
  step "점검 ($(whoami))"
  [ "$(uname -s)" = "Darwin" ] || die "macOS 가 아니다"
  if xcodebuild -version >/dev/null 2>&1; then ok "$(xcodebuild -version | head -1)"; else bad "Xcode 없음 — App Store 에서 설치 후 admin 단계"; fi
  case "$(xcode-select -p 2>/dev/null)" in
    */Xcode*.app/Contents/Developer) ok "xcode-select → $(xcode-select -p)";;
    *) bad "xcode-select 가 Xcode 를 가리키지 않는다 ($(xcode-select -p 2>/dev/null || echo 없음))";;
  esac
  local n; n=$(xcrun simctl list devices available 2>/dev/null | grep -c "iPhone" || true)
  if [ "${n:-0}" -gt 0 ]; then ok "iPhone 시뮬레이터 ${n}대"; else bad "iPhone 시뮬레이터 없음 — xcodebuild -downloadPlatform iOS"; fi
  if command -v xcodegen >/dev/null; then ok "xcodegen $(xcodegen --version 2>/dev/null | tail -1)"; else bad "xcodegen 없음 (PATH 에 Homebrew 가 있는가)"; fi
  if py_ok python3; then ok "$(python3 --version) ($(command -v python3))"; else bad "python3 3.10+ 아님: $(python3 --version 2>&1) ($(command -v python3)) — Homebrew python 이 PATH 앞에 와야 한다"; fi
  if command -v git >/dev/null; then ok "$(git --version)"; else bad "git 없음"; fi
  if [ -d "$RUNNER_DIR" ]; then
    ok "러너 폴더 $RUNNER_DIR"
    if [ -f "$RUNNER_DIR/.path" ]; then
      grep -q "homebrew\|/usr/local/bin" "$RUNNER_DIR/.path" && ok ".path 에 Homebrew 있음" || bad ".path 에 Homebrew 경로가 없다 — 고친 뒤 ./svc.sh stop && ./svc.sh start"
    fi
    if [ -x "$RUNNER_DIR/svc.sh" ] && (cd "$RUNNER_DIR" && ./svc.sh status 2>/dev/null | grep -qi "started\|running"); then ok "러너 서비스 실행 중"; else printf '  — 러너 서비스 상태 못 잼 (cd %s && ./svc.sh status)\n' "$RUNNER_DIR"; fi
  else
    printf '  — 러너 폴더 없음 (runner 단계에서 만든다)\n'
  fi
  [ "$FAILED" = 0 ] && printf '\n점검 통과\n' || printf '\n❌ 위 항목을 고친다\n'
  return "$FAILED"
}

# ─────────────────────────── admin ───────────────────────────
admin() {
  [ "$(uname -s)" = "Darwin" ] || die "macOS 가 아니다"
  if [ "${1:-}" = "--create-user" ]; then
    step "전용 표준 사용자 $RUNNER_USER 만들기"
    if id "$RUNNER_USER" >/dev/null 2>&1; then ok "이미 있다"; else
      sudo sysadminctl -addUser "$RUNNER_USER" -fullName "twbuild runner" -password - || die "사용자 생성 실패"
      ok "만들었다 (표준 사용자 — 관리자 아님)"
    fi
  fi

  step "Xcode"
  [ -d /Applications/Xcode.app ] || die "/Applications/Xcode.app 이 없다 — App Store 에서 Xcode 를 설치한 뒤 다시 실행한다"
  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
  sudo xcodebuild -license accept
  sudo xcodebuild -runFirstLaunch
  if xcrun simctl list runtimes 2>/dev/null | grep -q "iOS"; then ok "iOS 시뮬레이터 런타임 있음"; else
    printf '  iOS 시뮬레이터 런타임을 받는다 (수 GB, 몇 분)…\n'
    xcodebuild -downloadPlatform iOS
  fi
  ok "$(xcodebuild -version | head -1)"

  step "Homebrew 도구 (xcodegen · python)"
  local brew; brew=$(brew_bin)
  [ -n "$brew" ] || die "Homebrew 가 없다 — https://brew.sh 의 설치 명령을 실행한 뒤 다시 실행한다"
  "$brew" install xcodegen python      # python = 최신 3.x, python3 링크를 만든다 (macOS 기본 python3 는 3.9)
  ok "xcodegen · python"

  step "잠자기 끄기"
  sudo pmset -a sleep 0 disksleep 0
  ok "pmset sleep 0 · disksleep 0 (디스플레이 꺼짐 · 화면 잠금은 괜찮다)"

  cat <<EOF

다음:
  - (선택) 시스템 설정 → 사용자 및 그룹 → 자동 로그인 = $RUNNER_USER (FileVault 가 켜져 있으면 안 된다)
  - $RUNNER_USER 로 로그인해서:  bash $(basename "$0") runner <소유자>/<앱 레포>
EOF
}

# ─────────────────────────── runner ───────────────────────────
runner() {
  local repo="${1:-}"
  [[ "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "사용법: $0 runner <소유자>/<앱 레포>"
  [ "$(uname -s)" = "Darwin" ] || die "macOS 가 아니다"
  if [ "$(whoami)" != "$RUNNER_USER" ]; then
    printf '⚠️  지금 사용자는 %s 다 (권장: 전용 계정 %s). 계속하려면 Enter, 그만두려면 Ctrl-C ' "$(whoami)" "$RUNNER_USER"
    read -r _
  fi

  step "PATH 에 Homebrew"
  local brew; brew=$(brew_bin)
  [ -n "$brew" ] || die "Homebrew 가 없다 — 관리자 계정에서 admin 단계를 먼저"
  local line="eval \"\$($brew shellenv)\""
  grep -qF "$line" "$HOME/.zprofile" 2>/dev/null || echo "$line" >> "$HOME/.zprofile"
  eval "$("$brew" shellenv)"
  ok "$(command -v python3) · $(python3 --version)"

  step "시뮬레이터 첫 실행"
  open -a Simulator && sleep 8 && osascript -e 'quit app "Simulator"' >/dev/null 2>&1 || true
  ok "Simulator 를 한 번 열었다 닫았다"

  check || die "점검 실패 — 위 ❌ 를 고친 뒤 다시"

  step "Actions 러너 받기 → $RUNNER_DIR"
  mkdir -p "$RUNNER_DIR"
  cd "$RUNNER_DIR"
  if [ ! -x ./config.sh ]; then
    local arch; arch=$([ "$(uname -m)" = "arm64" ] && echo osx-arm64 || echo osx-x64)
    local meta; meta=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)
    local ver; ver=$(printf '%s' "$meta" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')
    local tgz="actions-runner-${arch}-${ver}.tar.gz"
    local want; want=$(printf '%s' "$meta" | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((a.get('digest') or '' for a in d['assets'] if a['name']=='$tgz'), ''))")
    curl -fsSL -o "$tgz" "https://github.com/actions/runner/releases/download/v${ver}/${tgz}"
    if [ -n "$want" ]; then
      [ "sha256:$(shasum -a 256 "$tgz" | cut -d' ' -f1)" = "$want" ] || die "체크섬 불일치 — $tgz 를 지우고 다시"
      ok "sha256 확인"
    fi
    tar xzf "$tgz" && rm -f "$tgz"
    ok "actions-runner $ver ($arch)"
  else
    ok "이미 받았다"
  fi

  step "러너 등록 (라벨 $LABEL)"
  if [ -f .runner ]; then ok "이미 등록됐다 — 다시 하려면 ./config.sh remove --token <토큰> 뒤 이 단계를 다시"; else
    local token
    printf 'GitHub %s → Settings → Actions → Runners → New self-hosted runner 화면의 --token 값을 붙여넣는다 (입력이 보이지 않는다): ' "$repo"
    read -rs token; echo
    [ -n "$token" ] || die "토큰이 비었다"
    ./config.sh --unattended --url "https://github.com/$repo" --token "$token" --labels "$LABEL" --name "$NAME" --work _work --replace
    unset token
    ok "등록: $NAME [$LABEL]"
  fi
  grep -q "homebrew\|/usr/local/bin" .path 2>/dev/null || { echo "$PATH" > .path; ok ".path 를 지금 PATH 로 갱신"; }

  step "상시 실행 (LaunchAgent)"
  ./svc.sh install >/dev/null 2>&1 || true
  ./svc.sh start
  ok "./svc.sh start — 이 계정이 로그인돼 있는 동안 돈다"

  cat <<EOF

다음:
  - GitHub $repo → Settings → Actions → Runners 에서 $NAME 이 Idle 인지 본다
  - 조종 기기(앱 레포)에서:  twbuild runner ping ios
EOF
}

case "${1:-}" in
  admin)  shift; admin "$@";;
  runner) shift; runner "$@";;
  check)  check;;
  *) sed -n '2,10p' "$0"; exit 2;;
esac
