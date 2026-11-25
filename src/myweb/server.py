"""A hugo server running in the background for previews."""

from __future__ import annotations

import socket
import subprocess

from . import hugo
from .config import Config, xdg_dir


def running(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ensure(cfg: Config, target_name: str = "local") -> str:
    """Start a drafts-included hugo server if none answers, return its URL."""
    port = cfg.server_port
    url = f"http://localhost:{port}/"
    if running(port):
        return url
    plan = hugo.plan(cfg, cfg.target(target_name), drafts=True, use="server")
    logfile = xdg_dir("state") / "server.log"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with open(logfile, "ab") as log:
        subprocess.Popen(
            hugo.server_args(cfg, plan, port),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return url
