"""Put draft items with a deadline into org-agenda-files, and take them out.

The running Emacs is asked, via emacsclient, to change and save
`org-agenda-files' with customize, so the change persists the way the
rest of that variable is kept.
"""

from __future__ import annotations

from pathlib import Path

from . import emacs
from .config import Config


def _eval(cfg: Config, form: str) -> bool:
    if cfg.agenda != "emacsclient":
        return False
    return not emacs.evaluate(cfg, form)


def add(cfg: Config, path: Path) -> bool:
    form = (
        "(progn (require 'org-agenda)"
        f" (add-to-list 'org-agenda-files {emacs.string(str(path))} t)"
        " (customize-save-variable 'org-agenda-files org-agenda-files) t)"
    )
    return _eval(cfg, form)


def remove(cfg: Config, path: Path) -> bool:
    form = (
        "(progn (require 'org-agenda)"
        f" (setq org-agenda-files (delete {emacs.string(str(path))} org-agenda-files))"
        " (customize-save-variable 'org-agenda-files org-agenda-files) t)"
    )
    return _eval(cfg, form)


def instructions(path: Path) -> str:
    return f"add to org-agenda-files: {path}"
