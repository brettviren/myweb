"""The user's editor: ``editor`` of the config, else $EDITOR, else $VISUAL.

Any editor is run on the file and waited for.  An editor that is
emacsclient is instead asked, through the ``[emacs] client`` command when
one is configured (it may name a daemon's socket), to visit the file in
the running Emacs and re-export ox-hugo items on save (see emacs.py).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from . import emacs
from .config import Config

DEFAULT = ["vi"]


class EditorError(Exception):
    pass


def command(cfg: Config, env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    if cfg.editor:
        return list(cfg.editor)
    for var in ("EDITOR", "VISUAL"):
        if env.get(var, "").strip():
            return shlex.split(env[var])
    return list(DEFAULT)


def is_emacsclient(cmd: list[str]) -> bool:
    return bool(cmd) and Path(cmd[0]).name.startswith("emacsclient")


def _client(cfg: Config, cmd: list[str]) -> list[str]:
    """The emacsclient to use: the configured one if any, else CMD."""
    return list(cfg.emacsclient) if cfg.emacsclient != ["emacsclient"] else cmd


def run(cmd: list[str], path: Path) -> None:
    """Run editor CMD on PATH and wait."""
    try:
        code = subprocess.call([*cmd, str(path)])
    except OSError as err:
        raise EditorError(f"cannot run editor {shlex.join(cmd)}: {err}") from None
    if code:
        raise EditorError(f"editor {shlex.join(cmd)} exited {code}")


def open_live(cfg: Config, path: Path) -> tuple[bool, str]:
    """Open PATH for editing.  Return (live, note): live if it is in a
    running Emacs that re-exports on save, so this returns at once, else
    the editor has been run and exited.  NOTE says what went wrong, if
    anything, with emacsclient."""
    cmd = command(cfg)
    if is_emacsclient(cmd):
        live = replace(cfg, emacsclient=_client(cfg, cmd))
        what, why = emacs.edit(live, path)
        if not why:
            return True, "" if what != '"no ox-hugo"' else "no ox-hugo in that Emacs, saving does not re-export"
        return False, f"emacsclient failed ({why})"
    run(cmd, path)
    return False, ""


def wait_command(cfg: Config) -> list[str]:
    """An editor command that returns only when the editing is done."""
    cmd = command(cfg)
    if not is_emacsclient(cmd):
        return cmd
    client = _client(cfg, cmd)
    live = replace(cfg, emacsclient=client)
    has, err = emacs.run(live, emacs.HAS_FRAME)
    if err:
        raise EditorError(f"emacsclient failed ({err})")
    return client + ([] if has == "t" else ["-c"])


def edit_text(cfg: Config, text: str, suffix: str = ".txt") -> str | None:
    """Let the user edit TEXT.  Return the result, None if left unchanged."""
    with tempfile.TemporaryDirectory(prefix="myweb-") as tmp:
        path = Path(tmp) / f"edit{suffix}"
        path.write_text(text)
        run(wait_command(cfg), path)
        out = path.read_text()
    return None if out == text else out
