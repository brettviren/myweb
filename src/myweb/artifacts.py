"""Artifacts: trees of ready-made files, often HTML, served as they are.

An artifact is any directory under the site's artifacts source (default
``<site>/artifacts``) holding an ``artifact.toml``, eg::

    title = "Field response study"
    date = 2026-11-25
    summary = "Interactive plots of ..."
    tags = ["dune", "wire-cell"]
    entry = "index.html"      # the file the listing links, default
    # audience, visibility, access, draft as for any page

Everything in the directory but artifact.toml is copied verbatim to
``artifacts/<path>/`` of the build; hugo renders none of it.  For the
listings myweb writes, per build, a page for each artifact with
``build.render = "link"``: listed (with its tags in the taxonomies), never
rendered.

An artifact's group is the top directory of its path, when it is
nested.  Its audience, visibility and access realm come from its
artifact.toml, else ``[artifacts.group.<group>]``, else ``[artifacts]``
of myweb.toml.  So one realm on a group protects every artifact below it
with one password.  A protected artifact gets the realm's .htaccess at its
top, which Apache applies to the whole tree under it.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .access import defaults
from .orgmeta import Meta

SECTION = "artifacts"
META = "artifact.toml"
ENTRY = "index.html"
DEFAULTS = {"audience": "both", "visibility": "public", "access": "", "draft": False}


class ArtifactError(Exception):
    pass


@dataclass
class Artifact:
    dest: str  # path relative to the artifacts source
    data: dict
    source: Path
    meta: Meta = field(default_factory=Meta)

    @property
    def name(self) -> str:
        return f"{SECTION}/{self.dest}"

    @property
    def url_path(self) -> str:
        return f"{SECTION}/{self.dest}/"

    @property
    def section(self) -> str:
        return SECTION

    @property
    def entry(self) -> str:
        return str(self.data.get("entry") or ENTRY)

    @property
    def group(self) -> str:
        parts = self.dest.split("/")
        return parts[0] if len(parts) > 1 else ""


def source_dir(site: Path, settings: dict) -> Path:
    path = Path(settings.get("source", SECTION)).expanduser()
    return path if path.is_absolute() else site / path


def load(root: Path, settings: dict | None = None) -> list[Artifact]:
    """Every artifact under ROOT, newest first."""
    settings = settings or {}
    out = []
    if not root.is_dir():
        return out
    for path in sorted(root.rglob(META)):
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as err:
            raise ArtifactError(f"{path}: {err}") from None
        dest = path.parent.relative_to(root).as_posix()
        if dest == ".":
            raise ArtifactError(f"{path}: an artifact needs a directory of its own")
        art = Artifact(dest, data, path.parent)
        access = defaults(settings, art.group, DEFAULTS)
        access.update({k: data[k] for k in DEFAULTS if data.get(k) not in (None, "")})
        keywords = {
            "title": str(data.get("title") or dest),
            "date": str(data.get("date", "")),
            "hugo_tags": " ".join(data.get("tags") or []),
            "audience": str(access["audience"]),
            "visibility": str(access["visibility"]),
            "draft": "true" if access["draft"] in (True, "true") else "false",
        }
        if access["access"]:
            keywords["access"] = str(access["access"])
        art.meta = Meta(keywords=keywords)
        out.append(art)
    nested = [(a, b) for a in out for b in out if b is not a and b.dest.startswith(a.dest + "/")]
    if nested:
        inner, outer = nested[0][1], nested[0][0]
        raise ArtifactError(f"artifact {inner.dest} is inside artifact {outer.dest}")
    out.sort(key=lambda a: (a.meta.date, a.dest), reverse=True)
    return out


def front_matter(art: Artifact) -> dict:
    vis = art.meta.visibility
    fm = {
        "title": art.meta.title,
        "date": art.meta.date or None,
        "summary": str(art.data.get("summary", "")),
        "tags": art.meta.tags,
        "build": {"render": "link"},
        "params": {"artifact": True, "entry": art.entry},
    }
    if not fm["date"]:
        del fm["date"]
    if vis != "public":
        fm["build"]["list"] = "never"
        fm["params"]["visibility"] = vis
        fm["tags"] = []
    return fm


SECTION_PAGE = {"title": "Artifacts", "params": {"artifactlist": True}}


def write(arts: list[Artifact], where: Path) -> Path:
    """Write the artifacts' listing pages under WHERE, replacing it.  The
    section page is always written, so artifacts/ exists with none."""
    if where.exists():
        shutil.rmtree(where)
    where.mkdir(parents=True)
    (where / "_index.md").write_text(json.dumps(SECTION_PAGE) + "\n")
    for art in arts:
        page = where / art.dest
        page.mkdir(parents=True, exist_ok=True)
        (page / "index.md").write_text(json.dumps(front_matter(art), indent=1, ensure_ascii=False) + "\n")
    return where


def copy(art: Artifact, dest: Path) -> list[str]:
    """Copy the artifact's files, less artifact.toml, into DEST.  Annexed
    files whose content is not on this host are skipped: return warnings."""
    warnings = []
    for src in sorted(art.source.rglob("*")):
        rel = src.relative_to(art.source)
        if rel.as_posix() == META or src.is_dir():
            continue
        if not src.exists():  # a dangling annex symlink
            warnings.append(f"{art.name}: {rel} content not present (git annex get?)")
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists() or out.stat().st_size != src.stat().st_size or out.stat().st_mtime < src.stat().st_mtime:
            shutil.copyfile(src, out)
    if not (art.source / art.entry).exists():
        warnings.append(f"{art.name}: no {art.entry}, the listing links a missing page")
    return warnings
