"""Asking the running Emacs to do things, by emacsclient."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import Config
from .export import elisp_file


def string(text: str) -> str:
    return json.dumps(text)  # close enough to an elisp string literal


def run(cfg: Config, form: str, args: list[str] = (), timeout: float = 10) -> tuple[str, str]:
    """Evaluate FORM in the running Emacs, return (printed value, error)."""
    cmd = [*cfg.emacsclient, *args, "--eval", form]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        return "", str(err)
    if proc.returncode:
        err = proc.stderr.strip()
        return "", err.splitlines()[-1] if err else f"exit {proc.returncode}"
    return proc.stdout.strip(), ""


def evaluate(cfg: Config, form: str) -> str:
    """Evaluate FORM in the running Emacs.  Return "" on success, else why not."""
    return run(cfg, form)[1]


#: True if the Emacs has a frame of its own, not just a daemon's hidden one.
HAS_FRAME = "(if (delq terminal-frame (frame-list)) t nil)"


def edit_form(cfg: Config, source: Path) -> str:
    """Visit SOURCE and, if ox-hugo can be had, re-export it on each save.

    myweb's load path is appended, so the Emacs keeps its own org and
    finds ox-hugo (and tomelr) only where it has none.
    """
    dirs = " ".join(string(str(d)) for d in cfg.emacs_load_path)
    return (
        f"(progn (dolist (d (list {dirs})) (add-to-list 'load-path d t))"
        f" (find-file {string(str(source))})"
        " (select-frame-set-input-focus (selected-frame))"
        " (when (and (require 'ox-hugo nil t) (require 'org-hugo-auto-export-mode nil t))"
        f" (load {string(str(elisp_file()))} nil t)"
        " (org-hugo-auto-export-mode 1))"
        " (if (bound-and-true-p org-hugo-auto-export-mode) \"auto-export\" \"no ox-hugo\"))"
    )


def edit(cfg: Config, source: Path) -> tuple[str, str]:
    """Open SOURCE in the running Emacs, in a new frame if it has none (a
    daemon).  Return (what, error): "auto-export" or "no ox-hugo", or why
    it failed."""
    has, err = run(cfg, HAS_FRAME)
    if err:
        return "", err
    return run(cfg, edit_form(cfg, source), [] if has == "t" else ["-c", "-n"])
