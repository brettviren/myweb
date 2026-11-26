"""Configuration.

Two layers describe a site.  The site dataset carries ``myweb.toml`` with
its taxa and deployment targets, so that every clone of the dataset builds
the same way.  The user's ``~/.config/myweb/config.toml`` says where the
site is on this host, how to run hugo and Emacs, and may override any
taxon or target field.  Environment variables override both.
"""

from __future__ import annotations

import os
import re
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HUGO = ["uvx", "--from", "hugo==0.170.1", "hugo"]
DEFAULT_EMACS_LOAD_PATH = [
    "~/.config/emacs/straight/build/org",
    "~/.config/emacs/straight/build/tomelr",
    "~/.config/emacs/straight/build/ox-hugo",
]
SITE_CONFIG = "myweb.toml"
RENDERS = ("ox-hugo", "hugo")
#: Access realms when a target names none: protected pages admit any user.
DEFAULT_REALMS = {"protected": "valid-user"}
REALM_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ConfigError(Exception):
    pass


def xdg_dir(kind: str) -> Path:
    """Return the myweb XDG directory of kind config, state or cache."""
    var, default = {
        "config": ("XDG_CONFIG_HOME", "~/.config"),
        "state": ("XDG_STATE_HOME", "~/.local/state"),
        "cache": ("XDG_CACHE_HOME", "~/.cache"),
    }[kind]
    return Path(os.environ.get(var) or default).expanduser() / "myweb"


def expand(path: str | Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


@dataclass
class Taxon:
    name: str
    source: Path
    render: str = "ox-hugo"
    #: Tag published revisions as <taxon>/<slug>/vN.
    tag: bool = False

    @property
    def section(self) -> str:
        """The Hugo section path, relative to content/."""
        parts = self.source.parts
        if "content" in parts:
            return "/".join(parts[parts.index("content") + 1 :])
        return self.name


@dataclass
class Target:
    name: str
    environment: str
    audience: list[str] = field(default_factory=lambda: ["personal", "work", "both"])
    auth: bool = False
    #: The AuthUserFile path as seen by the web server.
    htpasswd: str = ""
    #: Local directory receiving the build.
    dest: Path | None = None
    #: Optional rsync destination ("host:path/") receiving dest, else the stage.
    rsync: str = ""
    #: Optional git repository URL whose branch receives the stage as a commit.
    git: str = ""
    branch: str = "gh-pages"
    #: Extra files written at the top of the build, path to text, eg
    #: {".nojekyll" = "", CNAME = "example.org"} for GitHub Pages.
    files: dict[str, str] = field(default_factory=dict)
    #: Whether the target gets talks at all (then by audience as pages).
    talks: bool = True
    #: Paths in dest (and rsync) that a build must not delete.
    keep: list[str] = field(default_factory=lambda: ["drop/"])
    base_url: str = ""
    #: Media type for published org sources, set by a top .htaccess
    #: (needs AllowOverride FileInfo).  Empty to write none.
    org_type: str = "text/plain; charset=utf-8"
    #: Grant, by a top .htaccess, every file type in the build, for a
    #: server that denies all but some types (eg .html) by default.
    allow_files: bool = False
    #: Access realm name to its Apache "Require" argument.  A protected
    #: page is in the realm its #+access names, default "protected".
    realms: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_REALMS))


@dataclass
class Config:
    site: Path
    hugo: list[str] = field(default_factory=lambda: list(DEFAULT_HUGO))
    emacs: str = "emacs"
    emacs_load_path: list[Path] = field(default_factory=list)
    #: The editor command, else $EDITOR, else $VISUAL (see editor.py).
    editor: list[str] = field(default_factory=list)
    #: The emacsclient command, eg ["emacsclient", "-s", "/tmp/emacs1001/sticky"].
    emacsclient: list[str] = field(default_factory=lambda: ["emacsclient"])
    #: How drafts with a deadline reach org-agenda: "emacsclient" or "none".
    agenda: str = "emacsclient"
    search: list[str] = field(default_factory=lambda: ["orgface", "search"])
    browser: str = "xdg-open"
    server_port: int = 1313
    #: The old talks tree, only ever read, and the talks dataset.
    talks_source: Path = field(default_factory=lambda: expand("~/sync/talks"))
    talks_dest: Path = field(default_factory=lambda: expand("~/keep/talks"))
    #: The [talks] settings of the site, then the user: audience,
    #: visibility, access defaults, also per [talks.group.<name>].
    talks: dict = field(default_factory=dict)
    #: The [artifacts] settings of the site, then the user: source, and
    #: audience, visibility, access defaults, also per [artifacts.group.<name>].
    artifacts: dict = field(default_factory=dict)
    publish_targets: list[str] = field(default_factory=lambda: ["local"])
    taxa: dict[str, Taxon] = field(default_factory=dict)
    targets: dict[str, Target] = field(default_factory=dict)

    @property
    def content(self) -> Path:
        return self.site / "content"

    def taxon(self, name: str) -> Taxon:
        try:
            return self.taxa[name]
        except KeyError:
            raise ConfigError(
                f"unknown taxon {name!r}, known: {', '.join(self.taxa)}"
            ) from None

    def target(self, name: str) -> Target:
        try:
            return self.targets[name]
        except KeyError:
            raise ConfigError(
                f"unknown target {name!r}, known: {', '.join(self.targets)}"
            ) from None


def user_config_path() -> Path:
    env = os.environ.get("MYWEB_CONFIG")
    if env:
        return expand(env)
    return xdg_dir("config") / "config.toml"


def _read_toml(path: Path) -> dict:
    try:
        with open(path, "rb") as fp:
            return tomllib.load(fp)
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{path}: {err}") from None


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def _command(val) -> list[str]:
    return shlex.split(val) if isinstance(val, str) else [str(v) for v in val]


def _taxon(name: str, cfg: dict, site: Path) -> Taxon:
    render = cfg.get("render", "ox-hugo")
    if render not in RENDERS:
        raise ConfigError(f"taxon {name}: render must be one of {RENDERS}")
    source = Path(cfg.get("source", f"content/{name}"))
    return Taxon(
        name=name,
        source=source if source.is_absolute() else site / source,
        render=render,
        tag=bool(cfg.get("tag", False)),
    )


def _target(name: str, cfg: dict) -> Target:
    tgt = Target(name=name, environment=cfg.get("environment", name))
    for key in ("audience", "keep"):
        if key in cfg:
            setattr(tgt, key, list(cfg[key]))
    tgt.auth = bool(cfg.get("auth", tgt.auth))
    tgt.htpasswd = str(cfg.get("htpasswd", ""))
    tgt.rsync = str(cfg.get("rsync", ""))
    tgt.git = str(cfg.get("git", ""))
    tgt.branch = str(cfg.get("branch", tgt.branch))
    tgt.talks = bool(cfg.get("talks", tgt.talks))
    if "files" in cfg:
        tgt.files = {str(k): str(v) for k, v in cfg["files"].items()}
    for path in tgt.files:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ConfigError(f"target {name}: file {path!r} must be relative to the site top")
    tgt.base_url = str(cfg.get("base_url", ""))
    tgt.org_type = str(cfg.get("org_type", tgt.org_type))
    tgt.allow_files = bool(cfg.get("allow_files", tgt.allow_files))
    if "realms" in cfg:
        tgt.realms = {str(k): str(v) for k, v in cfg["realms"].items()}
    for realm, require in tgt.realms.items():
        if realm == "public" or not REALM_NAME.match(realm) or not require.strip():
            raise ConfigError(f"target {name}: bad realm {realm!r} = {require!r}")
    if cfg.get("dest"):
        tgt.dest = expand(cfg["dest"])
    return tgt


def methods(target: Target) -> list[str]:
    """How TARGET is deployed, in order: "dest", "rsync", "git"."""
    return [m for m in ("dest", "rsync", "git") if getattr(target, m)]


def load(
    path: Path | None = None, site: Path | None = None, env: dict | None = None
) -> Config:
    """Load configuration from the layers, last wins: user file, site file, env, args."""
    env = os.environ if env is None else env
    path = path or user_config_path()
    user = _read_toml(path) if path.exists() else {}

    site = site or (expand(env["MYWEB_SITE"]) if env.get("MYWEB_SITE") else None)
    site = site or expand(user.get("site", "~/keep/web"))
    site = site.resolve()
    site_file = site / SITE_CONFIG
    if not site_file.exists():
        raise ConfigError(f"no {SITE_CONFIG} in site {site}")
    sitecfg = _read_toml(site_file)

    # The user file may override any taxon or target field of the site.
    merged = _merge(sitecfg, {k: user[k] for k in ("taxon", "target") if k in user})

    cfg = Config(site=site)
    if env.get("MYWEB_HUGO"):
        cfg.hugo = _command(env["MYWEB_HUGO"])
    elif "hugo" in user:
        cfg.hugo = _command(user["hugo"])
    emacs = user.get("emacs", {})
    cfg.emacs = emacs.get("command", cfg.emacs)
    if "client" in emacs:
        cfg.emacsclient = _command(emacs["client"])
    cfg.emacs_load_path = [
        expand(p) for p in emacs.get("load_path", DEFAULT_EMACS_LOAD_PATH)
    ]
    if "editor" in user:
        cfg.editor = _command(user["editor"])
    cfg.agenda = user.get("agenda", cfg.agenda)
    if "search" in user:
        cfg.search = _command(user["search"])
    cfg.browser = user.get("browser", cfg.browser)
    cfg.server_port = int(user.get("server_port", cfg.server_port))
    talks = user.get("talks", {})
    cfg.talks = _merge(sitecfg.get("talks", {}), talks)
    cfg.artifacts = _merge(sitecfg.get("artifacts", {}), user.get("artifacts", {}))
    cfg.talks_source = expand(env.get("MYWEB_TALKS_SOURCE") or talks.get("source", cfg.talks_source))
    cfg.talks_dest = expand(env.get("MYWEB_TALKS_DEST") or talks.get("dest", cfg.talks_dest))
    cfg.publish_targets = list(
        user.get("publish_targets", sitecfg.get("publish_targets", cfg.publish_targets))
    )
    cfg.taxa = {n: _taxon(n, c, site) for n, c in merged.get("taxon", {}).items()}
    cfg.targets = {n: _target(n, c) for n, c in merged.get("target", {}).items()}
    return cfg
