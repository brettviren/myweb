"""Version stamps, ``version.txt``.

A stamp names the last commit that changed what it covers, as ``git
describe`` gives it, followed by that commit's full hash.  Every
``version.txt`` is excluded from what any stamp covers, so writing and
committing a stamp does not change it.  A stamp is therefore rewritten if
and only if the content it covers has changed since it was written.

The workflow: commit content, run ``update``, commit the stamps.  Content
not yet committed is stamped ``-dirty``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .vcs import git

FILENAME = "version.txt"
EXCLUDE = [f":(exclude,glob)**/{FILENAME}", f":(exclude){FILENAME}"]


@dataclass
class Stamp:
    path: Path
    old: str
    new: str

    @property
    def changed(self) -> bool:
        return self.old != self.new


def compute(repo: Path, covers: Path) -> str:
    """Return the stamp text for the content under COVERS, '' if never committed."""
    rel = str(covers.relative_to(repo)) if covers != repo else "."
    spec = ["--", rel, *EXCLUDE]
    commit = git(repo, "log", "-1", "--format=%H", *spec)
    if not commit:
        return ""
    desc = git(repo, "describe", "--tags", "--always", "--long", commit)
    dirty = git(repo, "status", "--porcelain", *spec)
    if dirty:
        desc += "-dirty"
    return f"{desc}\n{commit}\n"


def stamp(repo: Path, covers: Path, write: bool = True) -> Stamp:
    path = covers / FILENAME
    old = path.read_text() if path.exists() else ""
    new = compute(repo, covers)
    result = Stamp(path, old, new)
    if write and new and result.changed:
        path.write_text(new)
    return result
