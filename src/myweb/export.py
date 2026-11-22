"""Org to markdown export of ox-hugo bundles by Emacs in batch."""

from __future__ import annotations

import subprocess
from importlib import resources
from pathlib import Path

from .config import Config
from .site import Bundle


class ExportError(Exception):
    pass


def elisp_file() -> Path:
    return Path(str(resources.files("myweb") / "myweb.el"))


def command(cfg: Config, files: list[Path]) -> list[str]:
    cmd = [cfg.emacs, "-Q", "--batch"]
    for path in cfg.emacs_load_path:
        cmd += ["-L", str(path)]
    cmd += ["-l", str(elisp_file()), "-f", "myweb-export-batch"]
    return cmd + [str(f) for f in files]


def export(cfg: Config, bundles: list[Bundle], force: bool = False) -> list[Bundle]:
    """Export the ox-hugo bundles that are stale (or all with FORCE).

    Return the bundles exported.
    """
    todo = [b for b in bundles if b.output is not None and (force or b.stale())]
    if not todo:
        return []
    # ox-hugo insists on a static/ directory existing.
    (cfg.site / "static").mkdir(exist_ok=True)
    proc = subprocess.run(
        command(cfg, [b.source for b in todo]),
        capture_output=True,
        text=True,
        cwd=cfg.site,
    )
    if proc.returncode:
        lines = [l.removeprefix("myweb: ") for l in proc.stderr.splitlines() if l.startswith("myweb:")]
        raise ExportError("\n".join(lines) or proc.stderr[-2000:])
    return todo
