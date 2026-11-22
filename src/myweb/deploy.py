"""From a staged build to a target's destination."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import export, hugo, orgsource
from .config import Config, Target, xdg_dir
from .site import bundles


class DeployError(Exception):
    pass


HTACCESS = """\
# Written by myweb: this page is protected.
AuthType Basic
AuthName "{name}"
AuthUserFile {htpasswd}
Require valid-user
"""


ORG_TYPE = """\
# Written by myweb: show org sources as text.
AddType "{type}" .org
"""


@dataclass
class Result:
    target: Target
    stage: Path
    plan: hugo.Plan
    exported: list = field(default_factory=list)
    synced: list[str] = field(default_factory=list)
    log: str = ""


def stage_dir(target: Target) -> Path:
    return xdg_dir("cache") / "stage" / target.name


def protect(target: Target, plan: hugo.Plan, stage: Path) -> list[Path]:
    """Write an .htaccess into the output of each protected page."""
    if plan.protected and not target.htpasswd:
        raise DeployError(f"target {target.name} has protected pages but no htpasswd")
    out = []
    for bundle in plan.protected:
        page = stage / bundle.url_path
        if not page.is_dir():
            raise DeployError(f"protected page {bundle.name} not found in {stage}")
        path = page / ".htaccess"
        path.write_text(HTACCESS.format(name=bundle.name, htpasswd=Path(target.htpasswd).expanduser()))
        out.append(path)
    return out


def sources(target: Target, plan: hugo.Plan, stage: Path) -> list[Path]:
    """Put each page's org source, less :noexport: subtrees, beside it."""
    out = []
    for bundle in plan.included:
        page = stage / bundle.url_path
        if not page.is_dir():
            raise DeployError(f"page {bundle.name} not found in {stage}")
        path = page / bundle.source_name
        path.write_text(orgsource.publishable(bundle.source.read_text()))
        out.append(path)
    if target.org_type:
        (stage / ".htaccess").write_text(ORG_TYPE.format(type=target.org_type))
    return out


def verify(cfg: Config, target: Target, plan: hugo.Plan, stage: Path) -> None:
    """Fail if anything excluded from this target nevertheless got built."""
    leaks = [b.name for b, _ in plan.excluded if (stage / b.url_path).exists()]
    if leaks:
        raise DeployError(f"excluded pages leaked into {target.name}: {', '.join(leaks)}")
    if plan.protected and not target.auth:
        names = ", ".join(b.name for b in plan.protected)
        raise DeployError(f"protected {names} built for {target.name} which lacks auth")


def rsync(src: Path, dest: str, keep: list[str]) -> str:
    if not shutil.which("rsync"):
        raise DeployError("rsync is not installed")
    args = ["rsync", "-a", "--delete"]
    for path in keep:
        args += ["--filter", f"protect /{path.lstrip('/')}"]
    args += [f"{src}/", dest if dest.endswith("/") else dest + "/"]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode:
        raise DeployError(f"rsync to {dest}: {proc.stderr.strip()}")
    return dest


def build(
    cfg: Config,
    target: Target,
    dest: Path | None = None,
    remote: str | None = None,
    drafts: bool = False,
    do_export: bool = True,
    sync: bool = True,
) -> Result:
    """Export stale items, build the target to its stage, check, then sync.

    DEST and REMOTE override the target's dest and rsync.
    """
    exported = export.export(cfg, bundles(cfg)) if do_export else []
    plan = hugo.plan(cfg, target, drafts=drafts)
    stage = stage_dir(target)
    log = hugo.build(cfg, plan, stage, drafts=drafts)
    sources(target, plan, stage)
    protect(target, plan, stage)
    verify(cfg, target, plan, stage)
    result = Result(target, stage, plan, exported=exported, log=log)
    if not sync:
        return result
    dest = dest or target.dest
    if dest:
        dest.mkdir(parents=True, exist_ok=True)
        result.synced.append(rsync(stage, str(dest), target.keep))
    remote = target.rsync if remote is None else remote
    if remote:
        result.synced.append(rsync(dest or stage, remote, target.keep))
    return result
