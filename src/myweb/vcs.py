"""git and datalad operations on the site dataset."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class VcsError(Exception):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if check and proc.returncode:
        raise VcsError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()


def save(repo: Path, message: str, paths: list[Path] | None = None) -> None:
    """Record changes, with datalad if this is a dataset, else plain git."""
    rels = [str(p.relative_to(repo)) if p.is_absolute() else str(p) for p in paths or []]
    if (repo / ".datalad").is_dir() and shutil.which("datalad"):
        cmd = ["datalad", "save", "-d", str(repo), "-m", message, *rels]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode:
            raise VcsError(f"datalad save: {proc.stderr.strip() or proc.stdout.strip()}")
        return
    git(repo, "add", "--", *(rels or ["."]))
    if git(repo, "diff", "--cached", "--name-only"):
        git(repo, "commit", "-m", message)


def tags(repo: Path, pattern: str) -> list[str]:
    out = git(repo, "tag", "--list", pattern)
    return out.split() if out else []


def tag(repo: Path, name: str, message: str) -> None:
    git(repo, "tag", "-a", name, "-m", message)
