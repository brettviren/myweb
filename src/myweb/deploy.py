"""From a staged build to a target's destination."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import access, export, hugo, orgsource, siteindex, talkpages, version as versioning
from .config import Config, Target, xdg_dir
from .site import bundles


class DeployError(Exception):
    pass


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
    warnings: list[str] = field(default_factory=list)


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
        path.write_text(access.htaccess(target, plan.realm[bundle.name], f"page {bundle.name}"))
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


def talk_files(cfg: Config, plan: hugo.Plan, stage: Path) -> list[str]:
    """Copy each included talk's PDF beside its page.  Return warnings for
    talks whose PDF content is not on this host."""
    warnings = []
    for talk in plan.talks:
        page = stage / talk.url_path
        if not page.is_dir():
            raise DeployError(f"talk page {talk.name} not found in {stage}")
        src = talkpages.pdf_path(cfg.talks_dest, talk)
        if src is None:
            if talk.data.get("pdf"):
                warnings.append(f"{talk.name}: {talk.data['pdf']} content not present (git annex get?)")
            continue
        dest = page / src.name
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copyfile(src, dest)
    return warnings


def verify(cfg: Config, target: Target, plan: hugo.Plan, stage: Path) -> None:
    """Fail if anything excluded from this target nevertheless got built."""
    leaks = [b.name for b, _ in [*plan.excluded, *plan.talks_excluded] if (stage / b.url_path).exists()]
    if leaks:
        raise DeployError(f"excluded pages leaked into {target.name}: {', '.join(leaks)}")
    if plan.protected and not target.auth:
        names = ", ".join(b.name for b in plan.protected)
        raise DeployError(f"protected {names} built for {target.name} which lacks auth")
    problems = siteindex.check(target, plan, stage)
    if problems:
        raise DeployError("search: " + "; ".join(problems))


def extra_files(target: Target, stage: Path) -> list[Path]:
    """Write the target's extra files, eg .nojekyll, at the top of STAGE."""
    out = []
    for name, text in target.files.items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        out.append(path)
    return out


def rsync(src: Path, dest: str, keep: list[str], exclude: list[str] = (), checksum: bool = False) -> str:
    if not shutil.which("rsync"):
        raise DeployError("rsync is not installed")
    args = ["rsync", "-a", "--delete", *(["--checksum"] if checksum else [])]
    for path in keep:
        args += ["--filter", f"protect /{path.lstrip('/')}"]
    for path in exclude:
        args += ["--exclude", f"/{path.lstrip('/')}"]
    args += [f"{src}/", dest if dest.endswith("/") else dest + "/"]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode:
        raise DeployError(f"rsync to {dest}: {proc.stderr.strip()}")
    return dest


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and proc.returncode:
        raise DeployError(f"git {args[0]}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def repo_dir(target: Target) -> Path:
    return xdg_dir("cache") / "deploy" / target.name


def git_push(src: Path, target: Target, message: str) -> str:
    """Commit SRC as the tip of the target's git branch and push it.

    A plain git working tree in the cache follows the remote branch: the
    built files are real files (talk PDFs copied out of the annex), so
    the receiving repository needs neither git-annex nor datalad.  Return
    "url branch", with " (unchanged)" when there was nothing to commit.
    """
    repo = repo_dir(target)
    if not (repo / ".git").is_dir():
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q")
        _git(repo, "remote", "add", "origin", target.git)
    else:
        _git(repo, "remote", "set-url", "origin", target.git)
    where = f"{target.git} {target.branch}"
    heads = _git(repo, "ls-remote", "--heads", "origin", target.branch).stdout
    if heads.strip():
        _git(repo, "fetch", "-q", "--depth", "1", "origin", target.branch)
        _git(repo, "checkout", "-q", "-B", target.branch, "FETCH_HEAD")
        _git(repo, "reset", "-q", "--hard", "FETCH_HEAD")
    else:
        _git(repo, "checkout", "-q", "--orphan", target.branch)
    # Checkout stamps files with the current time, so compare content.
    rsync(src, str(repo), target.keep, exclude=[".git"], checksum=True)
    _git(repo, "add", "-A")
    if not _git(repo, "diff", "--cached", "--quiet", check=False).returncode:
        return where + " (unchanged)"
    _git(repo, "commit", "-q", "-m", message)
    _git(repo, "push", "-q", "origin", f"HEAD:refs/heads/{target.branch}")
    return where


def build(cfg: Config, target: Target, drafts: bool = False, do_export: bool = True) -> Result:
    """Export stale items, build the target to its stage and check it."""
    exported = export.export(cfg, bundles(cfg)) if do_export else []
    plan = hugo.plan(cfg, target, drafts=drafts)
    stage = stage_dir(target)
    log = hugo.build(cfg, plan, stage, drafts=drafts)
    sources(target, plan, stage)
    warnings = talk_files(cfg, plan, stage)
    protect(target, plan, stage)
    siteindex.write(target, plan, stage)
    extra_files(target, stage)
    verify(cfg, target, plan, stage)
    return Result(target, stage, plan, exported=exported, log=log, warnings=warnings)


def ship(cfg: Config, result: Result, dest: Path | None = None, remote: str | None = None) -> Result:
    """Send a built stage by each of the target's methods, in order: copy to
    the local dest, rsync (from dest, else the stage) to the remote, and
    commit and push the stage to the git branch.  DEST and REMOTE override
    the target's dest and rsync."""
    target, stage = result.target, result.stage
    dest = dest or target.dest
    remote = target.rsync if remote is None else remote
    if not (dest or remote or target.git):
        raise DeployError(f"target {target.name} has no dest, rsync or git to deploy to")
    if dest:
        dest.mkdir(parents=True, exist_ok=True)
        result.synced.append(rsync(stage, str(dest), target.keep))
    if remote:
        result.synced.append(rsync(dest or stage, remote, target.keep))
    if target.git:
        stamp = versioning.compute(cfg.site, cfg.site).split("\n", 1)[0] or "uncommitted"
        message = f"myweb deploy {target.name} from {cfg.site.name} {stamp}"
        result.synced.append(git_push(stage, target, message))
    return result


def deploy(
    cfg: Config,
    target: Target,
    dest: Path | None = None,
    remote: str | None = None,
    drafts: bool = False,
    do_export: bool = True,
) -> Result:
    """Build TARGET and ship it."""
    return ship(cfg, build(cfg, target, drafts, do_export), dest, remote)
