import hashlib
import os
from pathlib import Path

from .errors import BridgeError
from .processes import environment, run
from .settings import private_dir


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", *args],
        repo,
        env or environment(),
        30,
        max_bytes=10000000,
    )
    if result["reason"] == "output_limit":
        raise BridgeError("budget_exceeded", "Git output exceeds artifact quota")
    if result["reason"] or result["exit_code"]:
        raise BridgeError(
            "invalid_request", "Git command failed or timed out; inspect repository/base ref"
        )
    return result["output"]


def base_sha(repo: Path, ref: str) -> str:
    if ref.startswith("-"):
        raise BridgeError("invalid_request", "Invalid base reference")
    return (
        git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
    )


def create(repo: Path, root: Path, job_id: str, sha: str) -> Path:
    root = private_dir(root)
    target = root / job_id
    branch = "deepseek-bridge/" + job_id
    if target.exists() or target.is_symlink():
        raise BridgeError("invalid_request", "Worktree destination already exists")
    if base_sha(repo, sha) != sha:
        raise BridgeError("invalid_request", "Base commit is no longer available")
    git(repo, "worktree", "add", "-b", branch, str(target), sha)
    return target


def snapshot(repo: Path) -> str:
    status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    names = set(git(repo, "ls-files", "-z").split(b"\0"))
    names.update(git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"))
    hashed = hashlib.sha256(status)
    for raw in sorted(names):
        if not raw:
            continue
        path = repo / os.fsdecode(raw)
        hashed.update(raw)
        if path.is_symlink():
            hashed.update(os.readlink(path).encode())
        elif path.is_file():
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(65536), b""):
                    hashed.update(chunk)
    return hashed.hexdigest()


def patch(worktree: Path, sha: str, private: Path) -> tuple[bytes, list[str]]:
    index = private / "collection.index"
    env = environment()
    env["GIT_INDEX_FILE"] = str(index)
    index.unlink(missing_ok=True)
    try:
        git(worktree, "read-tree", sha, env=env)
        # Reject changed symlinks and submodules before staging.
        for raw in git(worktree, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
            if raw and (worktree / os.fsdecode(raw)).is_symlink():
                raise BridgeError("out_of_scope", "Worker created an unexpected symlink")
        git(worktree, "add", "-A", "--", ".", env=env)
        changed = git(worktree, "diff", "--cached", "--name-only", "-z", sha, env=env)
        files = [os.fsdecode(n) for n in changed.split(b"\0") if n]
        for name in files:
            if (worktree / name).is_symlink():
                raise BridgeError("out_of_scope", "Worker changed a symlink")
        modes = git(worktree, "diff", "--cached", "--raw", sha, env=env)
        if b"160000" in modes:
            raise BridgeError("out_of_scope", "Worker changed a submodule")
        return git(worktree, "diff", "--cached", "--binary", "--full-index", sha, env=env), files
    finally:
        index.unlink(missing_ok=True)


def cleanup(repo: Path, root: Path, job_id: str, patch_saved: bool = False) -> None:
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise BridgeError("invalid_request", "Invalid job ID")
    target = root.resolve() / job_id
    entries = git(repo, "worktree", "list", "--porcelain").decode().split("\n\n")
    expected_branch = "refs/heads/deepseek-bridge/" + job_id
    if not any(
        "worktree " + str(target) in e.splitlines()
        and "branch " + expected_branch in e.splitlines()
        for e in entries
    ):
        raise BridgeError("permission_boundary", "Worktree ownership is not established")
    if target.is_symlink():
        raise BridgeError("permission_boundary", "Refusing symlink cleanup")
    # Workers never commit, so forcing is needed; without a saved patch changes must survive.
    git(repo, "worktree", "remove", *(["--force"] if patch_saved else []), str(target))
    git(repo, "branch", "-D" if patch_saved else "-d", "deepseek-bridge/" + job_id)
