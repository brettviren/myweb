"""Arrange for "myweb build" to run unattended: systemd, cron or git hook.

Each method makes text from the running myweb's own command so the
installed job runs the same program.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Config

MARK = "# myweb-managed"


@dataclass
class Unit:
    path: Path
    text: str


def myweb_command() -> list[str]:
    exe = shutil.which("myweb")
    return [exe] if exe else [sys.executable, "-m", "myweb"]


def build_command(target: str) -> str:
    return shlex.join([*myweb_command(), "build", target])


def systemd(cfg: Config, target: str, when: str, unitdir: Path) -> list[Unit]:
    """A service, a timer and a path unit watching the site's branch head."""
    name = f"myweb-build-{target}"
    head = cfg.site / ".git" / "HEAD"
    ref = (cfg.site / ".git" / head.read_text().split(":", 1)[1].strip()
           if head.exists() and head.read_text().startswith("ref:") else head)
    service = f"""\
{MARK}
[Unit]
Description=Build and deploy the {target} web site from {cfg.site}

[Service]
Type=oneshot
WorkingDirectory={cfg.site}
# Unattended jobs need to find hugo (uvx), emacs and rsync as you do.
Environment=PATH={os.environ.get("PATH", "")}
ExecStart={build_command(target)}
"""
    timer = f"""\
{MARK}
[Unit]
Description=Periodically build the {target} web site

[Timer]
OnCalendar={when}
Persistent=true

[Install]
WantedBy=timers.target
"""
    path = f"""\
{MARK}
[Unit]
Description=Build the {target} web site when its git branch moves

[Path]
PathChanged={ref}
Unit={name}.service

[Install]
WantedBy=default.target
"""
    return [
        Unit(unitdir / f"{name}.service", service),
        Unit(unitdir / f"{name}.timer", timer),
        Unit(unitdir / f"{name}.path", path),
    ]


def cron_line(target: str, when: str) -> str:
    path = shlex.quote(os.environ.get("PATH", ""))
    return f"{when} PATH={path} {build_command(target)} >/dev/null 2>&1 {MARK} {target}"


def install_cron(line: str, target: str) -> str:
    """Replace any myweb line for TARGET in the user's crontab with LINE."""
    proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    old = proc.stdout if proc.returncode == 0 else ""
    keep = [l for l in old.splitlines() if not l.endswith(f"{MARK} {target}")]
    new = "\n".join([*keep, line]) + "\n"
    subprocess.run(["crontab", "-"], input=new, text=True, check=True)
    return new


def git_hooks(cfg: Config, target: str) -> list[Unit]:
    """Hooks that build after a commit, a merge (pull) or a push received."""
    hooks = cfg.site / ".git" / "hooks"
    body = f"""\
#!/bin/sh
{MARK}
# Build the {target} site in the background so git is not held up.
unset GIT_DIR GIT_WORK_TREE
cd {shlex.quote(str(cfg.site))} || exit 0
nohup flock -n .git/myweb-build.lock {build_command(target)} >> .git/myweb-build.log 2>&1 &
"""
    return [Unit(hooks / name, body) for name in ("post-commit", "post-merge", "post-receive")]


def write(units: list[Unit], force: bool = False) -> list[Path]:
    out = []
    for unit in units:
        if unit.path.exists() and MARK not in unit.path.read_text() and not force:
            raise FileExistsError(f"{unit.path} exists and is not managed by myweb")
        unit.path.parent.mkdir(parents=True, exist_ok=True)
        unit.path.write_text(unit.text)
        if unit.path.parent.name == "hooks":
            unit.path.chmod(0o755)
        out.append(unit.path)
    return out
