"""git — 레포 · 워크트리 · 커밋 · 머지. 본선에 쓰는 곳은 merge() · commit_paths() 다.

화면 과제의 워크트리는 .twbuild/worktrees/<플랫폼>-<화면>, 브랜치 twbuild/<플랫폼>-<화면>.
"""
import os
import subprocess
import threading

from . import util

PREFIX = "twbuild/"
# `git worktree add` 는 동시 실행에 안전하지 않다 — 생성만 직렬화한다
_WORKTREE_LOCK = threading.Lock()


class GitError(RuntimeError):
    pass


def run(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", cwd, "-c", "core.quotePath=false", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:400]}")
    return r


def is_repo(root):
    return run(root, "rev-parse", "--git-dir", check=False).returncode == 0


def toplevel(path):
    """path 가 속한 레포의 최상위 (워크트리면 그 워크트리). 레포가 아니면 None."""
    r = run(path, "rev-parse", "--show-toplevel", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def common_dir(path):
    """메인 레포의 .git — 워크트리 안에서 불려도 메인 레포 루트를 찾는 열쇠."""
    r = run(path, "rev-parse", "--git-common-dir", check=False)
    if r.returncode != 0:
        return None
    d = r.stdout.strip()
    return d if os.path.isabs(d) else os.path.normpath(os.path.join(path, d))


def main_root(path):
    """path(메인 또는 워크트리 안)가 속한 메인 레포 루트."""
    cd = common_dir(path)
    return os.path.dirname(cd) if cd else None


def init(root):
    if not is_repo(root):
        run(root, "init", "-q", "-b", "main")


def head(root):
    return run(root, "rev-parse", "HEAD").stdout.strip()


def has_commits(root):
    return run(root, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


def identity(root):
    name = run(root, "config", "user.name", check=False).stdout.strip()
    email = run(root, "config", "user.email", check=False).stdout.strip()
    return name, email


def branch(name):
    return PREFIX + name


def branch_exists(root, name):
    return run(root, "rev-parse", "--verify", "-q", name, check=False).returncode == 0


def status_lines(cwd):
    out = run(cwd, "status", "--porcelain", "-uall").stdout
    return [(l[:2], l[3:].strip().strip('"')) for l in out.splitlines() if l.strip()]


def ensure_worktree(root, name):
    wt = util.tw(root, util.WORKTREES, name)
    b = branch(name)
    with _WORKTREE_LOCK:
        if os.path.isdir(wt):
            return wt, False
        os.makedirs(os.path.dirname(wt), exist_ok=True)
        if branch_exists(root, b):
            run(root, "worktree", "add", wt, b)
        else:
            run(root, "worktree", "add", "-b", b, wt, "HEAD")
    return wt, True


def remove_worktree(root, name):
    wt = util.tw(root, util.WORKTREES, name)
    if os.path.isdir(wt):
        run(root, "worktree", "remove", "--force", wt, check=False)
    if branch_exists(root, branch(name)):
        run(root, "branch", "-D", branch(name), check=False)
    run(root, "worktree", "prune", check=False)


def commit_all(wt, message):
    run(wt, "add", "-A")
    if not run(wt, "status", "--porcelain").stdout.strip():
        return False
    run(wt, "commit", "-q", "-m", message)
    return True


def commit_paths(cwd, message, *paths):
    existing = [p for p in paths if os.path.exists(os.path.join(cwd, p))]
    if not existing:
        return False
    run(cwd, "add", "-A", "--", *existing)
    if run(cwd, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    run(cwd, "commit", "-q", "-m", message)
    return True


def tag(root, name, message=""):
    if run(root, "rev-parse", "--verify", "-q", f"refs/tags/{name}", check=False).returncode == 0:
        return False
    run(root, "tag", "-a", name, "-m", message or name)
    return True


def merge_squash(root, b, message):
    """브랜치를 화면 단위 squash 커밋 하나로 본선에 합친다."""
    r = run(root, "merge", "--squash", b, check=False)
    if r.returncode != 0:
        run(root, "reset", "--merge", check=False)
        raise GitError(f"{b} 머지 충돌: {(r.stderr or r.stdout).strip()[:400]}")
    if run(root, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    run(root, "commit", "-q", "-m", message)
    return head(root)


# ─────────────────────────── 검사 · 훅 ───────────────────────────

PRECOMMIT_MARK = "twbuild pre-commit"


def staged_files(cwd):
    r = run(cwd, "diff", "--cached", "--name-only", "--diff-filter=AM", check=False)
    return [l for l in r.stdout.splitlines() if l.strip()]


def staged_text(cwd, rel):
    r = run(cwd, "show", f":{rel}", check=False)
    return r.stdout if r.returncode == 0 else ""


def changed_files(root, base, ref):
    """base 와의 공통 조상 이후 ref 가 추가 · 수정한 파일."""
    r = run(root, "diff", "--name-only", "--diff-filter=AM", f"{base}...{ref}", check=False)
    return [l for l in r.stdout.splitlines() if l.strip()]


def show(root, spec):
    r = run(root, "show", spec, check=False)
    return r.stdout if r.returncode == 0 else ""


def hooks_dir(root):
    d = common_dir(root)
    return os.path.join(d, "hooks") if d else None


def install_hook(root, name, content, marker):
    """git 훅 설치 — 우리 것(marker)이면 갱신, 다른 훅이 있으면 건드리지 않고 None. 새로 썼으면 True, 같으면 False."""
    d = hooks_dir(root)
    if not d:
        return None
    path = os.path.join(d, name)
    cur = util.read_text(path, "")
    if cur and marker not in cur:
        return None
    if cur == content:
        return False
    util.write_text(path, content)
    os.chmod(path, 0o755)
    return True


def hook_installed(root, name, marker):
    d = hooks_dir(root)
    return bool(d) and marker in util.read_text(os.path.join(d, name), "")
