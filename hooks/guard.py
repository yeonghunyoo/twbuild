#!/usr/bin/env python3
"""PreToolUse 차단 훅 — 욜로(bypass) 모드에는 확인 창이 없으므로 위험 동작은 여기서 막는다 (AGENT.md 11장).

stdlib 만 쓰고 서버 코드를 import 하지 않는다 — 훅이 서버에 매이면 서버가 깨질 때 입력이 막힌다.
판단이 안 서면 통과시킨다(실패는 통과) — 단, 아래 규칙에 걸리면 거부하고 규칙 ID 를 사유로 돌려준다.

  H1 원격 push                     git push
  H2 git 이력 재작성               reset --hard · rebase · filter-branch/repo · commit --amend · reflog expire · push --force
  H3 레포 밖 쓰기 · 삭제           Write/Edit 경로가 레포(또는 임시 디렉터리) 밖 · Bash 리다이렉트/변경 명령의 대상이 밖
  H4 보호 구역                     design/ · api/generated/ · api/fragments/ · .twbuild/(tasks/ 제외) · .git/ 에 쓰기 · 삭제
  H5 민감 파일 · 환경 변수 덤프     .env · 키 · 인증서 · ~/.ssh 등 읽기/쓰기/검색, env/printenv 전체 출력
  H6 설치 · 권한 상승              sudo · brew install · pip/npm/gem 전역 설치 · curl|sh — 설치는 사람이 한다(report 가 명령을 안내)
  H7 Claude Design 쓰기            쓰기 · 삭제 · 복사 · 공유 · 멤버 · 대화 · 미리보기 — 읽기 전용이다
"""
import fnmatch
import json
import os
import re
import sys
import tempfile

TW = ".twbuild"
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "Grep", "Glob"}
PROTECTED =("design/", "api/generated/", "api/fragments/", ".git/")
GENERATED_RE = re.compile(r"(^|/)(Networking/Generated|networking/generated)/")     # 계약에서 생성한 클라이언트 · 모델 (gen.py)
TW_WRITABLE = (TW + "/tasks/",)
SENSITIVE = (".env", ".env.*", "*.env", "*.pem", "*.key", "*.p8", "*.p12", "*.pfx", "*.keystore", "*.jks",
             "*.tfstate", "*.tfvars", "*credentials*.json", "*service-account*.json", "google-services.json", "GoogleService-Info.plist",
             "id_rsa", "id_ed25519", "id_ecdsa", "*.mobileprovision", "secrets.yaml", "secrets.yml", "secrets.json",
             ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".htpasswd", "*.secret", "*.gpg", "*.asc", "*.ovpn", "*.kdbx")
BARE_SENSITIVE = {g for g in SENSITIVE if "*" not in g and "/" not in g}      # id_rsa 같은 와일드카드 없는 이름은 맨 단어로도 본다
SENSITIVE_DIR = re.compile(r"(^|/)(\.ssh|\.aws|\.kube|\.gnupg|\.docker|\.azure|\.config/gcloud)(/|$)")
EXAMPLE = re.compile(r"\.(example|sample|template|dist)$", re.I)
HOME_VAR = re.compile(r"\$\{?HOME\}?")

PUSH = re.compile(r"\bgit\b[^|;&\n]*\bpush\b")
REWRITE = re.compile(r"\bgit\b[^|;&\n]*\b(reset\s+--hard|rebase|filter-branch|filter-repo|commit\s+[^|;&\n]*--amend|reflog\s+expire|update-ref\s+-d)\b")
INSTALL = re.compile(r"(^|[\s;&|(])(sudo|doas)\b|\bbrew\s+(install|uninstall|upgrade)\b|\bpip3?\s+install\b(?![^|;&\n]*(\.venv|/venv/))|"
                     r"\bnpm\s+(i|install)\s+(-g|--global)\b|\bgem\s+install\b|\bapt(-get)?\s+install\b|curl\b[^|;&\n]*\|\s*(ba|z)?sh\b")
ENV_DUMP = re.compile(r"(^|[\s;&|(])(env|printenv|export\s+-p|set)\s*($|[;&|)])")
MUTATORS = re.compile(r"(^|[\s;&|(])(rm|rmdir|mv|cp|tee|sed\s+-i|truncate|touch|mkdir|unzip|tar|ln|chmod|chown|"
                      r"git\s+(checkout|restore|rm|mv|clean|worktree\s+remove))\b")
DELETE = re.compile(r"(^|[\s;&|(])(rm|rmdir|git\s+(rm|clean|worktree\s+remove|branch\s+-D))\b")
REDIRECT = re.compile(r">{1,2}\s*([^\s;&|]+)")
DESIGN_WRITE = re.compile(r"^mcp__.*claude[-_]design__(write_files|delete_files|copy_files|create_project|add_member|remove_member|"
                          r"update_member_role|update_sharing|put_conversation|render_preview|finalize_plan|create_support_js|ack_comments)$")

GUIDE = {
    "H1": "[H1] 원격 push 는 하네스가 하지 않는다 — 머지는 로컬 main 까지다. 사람이 직접 push 한다.",
    "H2": "[H2] git 이력 재작성(reset --hard · rebase · amend · filter)은 금지다 — 되돌리기는 보고서의 revert 명령으로.",
    "H3": "[H3] 레포 밖에는 쓰지 않는다 — 임시 파일은 .twbuild/tmp/ 나 시스템 임시 디렉터리에.",
    "H4": "[H4] 보호 구역이다 — design/ · api/generated/ · api/fragments/ · .twbuild/ · Networking/Generated 는 하네스가 쓴다. 바꾸려면 design run · plan · 설정 · 계약(openapi.yaml)으로.",
    "H5": "[H5] 민감 파일 · 환경 변수 전체는 읽지도 쓰지도 않는다 — 값이 필요하면 이름만 printenv NAME, 있는지만 [ -n \"$NAME\" ].",
    "H6": "[H6] 설치 · 권한 상승은 사람이 한다 — report 의 사람 할 일 명령을 안내하고 placeholder 로 진행한다.",
    "H7": "[H7] Claude Design 은 읽기 전용이다 — 디자인 수정은 사용자가 Claude Design 에서 한다.",
}


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)


def find_root(start):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, TW, "config.yaml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def expand(path):
    return os.path.expanduser(HOME_VAR.sub("~", path))


def is_sensitive(rel):
    name = rel.rsplit("/", 1)[-1]
    if EXAMPLE.search(name):
        return False
    return bool(SENSITIVE_DIR.search(rel)) or any(fnmatch.fnmatch(name, g) for g in SENSITIVE)


def tmp_ok(ap):
    """시스템 임시 디렉터리 · 플러그인 데이터 디렉터리는 레포 밖이라도 쓸 수 있다."""
    allowed = [tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders", "/dev",
               os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data"),
               os.path.join(os.path.expanduser("~"), ".claude", "projects"),          # Claude 의 세션 메모리 — lead 가 쓴다
               os.environ.get("TMPDIR") or "", os.environ.get("TWBUILD_DATA") or ""]
    return any(a and ap.startswith(os.path.normpath(a)) for a in allowed)


def rel_of(root, path, cwd):
    """레포 기준 상대 경로. 워크트리 안이면 워크트리 기준. 레포 밖이면 None."""
    p = expand(path)
    p = p if os.path.isabs(p) else os.path.join(cwd, p)
    p = os.path.normpath(p)
    try:
        rel = os.path.relpath(p, root).replace(os.sep, "/")
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    m = re.match(rf"{re.escape(TW)}/worktrees/[^/]+(?:/(.*))?$", rel)       # 워크트리 루트 자체(cd <wt>)도 워크트리 안이다
    return (m.group(1) or "") if m else rel


def protected(rel):
    if rel == TW or rel.startswith(TW + "/"):
        return not any(rel.startswith(w) for w in TW_WRITABLE)
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in PROTECTED) or bool(GENERATED_RE.search(rel))


QUOTED_TEXT = re.compile(r"\"[^\"\n]*\s[^\"\n]*\"|'[^'\n]*\s[^'\n]*'")     # 공백이 든 따옴표 문자열 = 자연어(결정 본문 · 커밋 메시지) — 경로 · 명령으로 보지 않는다
PATHLIKE = re.compile(r"[/.~$]")


HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n[\s\S]*?\n\s*\1\b")     # 히어독 본문(과제 메모 · 커밋 본문) = 자연어 — 경로 · 명령으로 보지 않는다


def check_bash(cmd, root, cwd):
    cmd = HEREDOC.sub("<<EOF\nEOF", cmd)
    cmd = QUOTED_TEXT.sub('""', cmd)
    if PUSH.search(cmd):
        deny(GUIDE["H1"])
    if REWRITE.search(cmd):
        deny(GUIDE["H2"])
    if INSTALL.search(cmd):
        deny(GUIDE["H6"])
    if ENV_DUMP.search(cmd):
        deny(GUIDE["H5"])
    tokens = [t for t in re.findall(r"[\w./~${}:+-]+", cmd) if PATHLIKE.search(t) or t in BARE_SENSITIVE]   # 맨 단어(key · token)는 파일이 아니다
    for tk in tokens:
        ap = os.path.normpath(expand(tk)) if tk.startswith(("/", "~", "$")) else None
        if ap and os.path.isabs(ap) and (SENSITIVE_DIR.search(ap) or is_sensitive(ap)):
            deny(GUIDE["H5"] + f" ({tk})")
        rel = rel_of(root, tk, cwd)
        if rel and is_sensitive(rel):
            deny(GUIDE["H5"] + f" ({rel})")
    writes = [m.group(1) for m in REDIRECT.finditer(cmd)]
    mutating = bool(MUTATORS.search(cmd))
    if mutating:
        writes += [t for t in tokens if "/" in t or t.startswith((".", "~", "$"))]
    for tk in writes:
        if tk.startswith("-"):
            continue
        rel = rel_of(root, tk, cwd)
        if rel is None:
            ap = os.path.normpath(expand(tk) if os.path.isabs(expand(tk)) else os.path.join(cwd, tk))
            if os.path.isabs(expand(tk)) and not tmp_ok(ap) and (mutating or REDIRECT.search(cmd)):
                deny(GUIDE["H3"] + f" ({tk})")
            continue
        if protected(rel):
            deny(GUIDE["H4"] + f" ({rel})")
    if DELETE.search(cmd):
        for tk in tokens:
            rel = rel_of(root, tk, cwd)
            if rel in ("", ".") and ("-r" in cmd or "-R" in cmd):
                deny(GUIDE["H4"] + " (레포 루트 삭제)")


def check_path_tool(tool, path, root, cwd):
    ap = os.path.normpath(expand(path) if os.path.isabs(expand(path)) else os.path.join(cwd, path))
    if SENSITIVE_DIR.search(ap.replace(os.sep, "/")) or is_sensitive(ap.replace(os.sep, "/")):
        deny(GUIDE["H5"] + f" ({path})")
    rel = rel_of(root, path, cwd)
    if tool in ("Read", "Grep", "Glob"):
        return
    if rel is None:
        if not tmp_ok(ap):
            deny(GUIDE["H3"] + f" ({path})")
        return
    if protected(rel):
        deny(GUIDE["H4"] + f" ({rel})")


def main():
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if DESIGN_WRITE.match(tool):
        deny(GUIDE["H7"])
    root = find_root(cwd) or find_root(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    if not root:
        return
    if tool == "Bash":
        check_bash(inp.get("command", ""), root, cwd)
        return
    if tool not in FILE_TOOLS:          # MCP 도구의 path 는 로컬 파일이 아니다 — 여기서 판단하지 않는다
        return
    path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
    if path:
        check_path_tool(tool, path, root, cwd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
