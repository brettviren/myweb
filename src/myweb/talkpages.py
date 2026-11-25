"""Talks from the talks dataset as Hugo pages.

Every ``talk.json`` under the talks dataset (see talks.py) becomes a page
at ``talks/<group>/<YYYY>/<MM>/<DD>/<topic>/``.  For each build myweb
writes the pages a target gets as leaf bundles under its cache and mounts
them as ``content/talks``, so the site dataset holds no generated files
and a newly migrated talk appears on the next build.  The talk's PDF is
copied beside its page by the deploy, not by hugo.

A talk's audience, visibility and access realm come from its talk.json
("audience", "visibility", "access") if set, else from the site's
``[talks]`` defaults, per group under ``[talks.group.<name>]``.  They are
handled exactly as an article's: protected talks get the realm's
.htaccess, are never listed and are searchable only in the realm's index.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .access import defaults
from .orgmeta import Meta

SECTION = "talks"
#: talk.json fields the web build reads and talks.migrate keeps on --redo.
ACCESS_FIELDS = ("audience", "visibility", "access", "draft")
DEFAULTS = {"audience": "work", "visibility": "public", "access": ""}


class TalkError(Exception):
    pass


@dataclass
class Talk:
    dest: str  # group/YYYY/MM/DD/topic, relative to the talks dataset
    data: dict
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
    def topics(self) -> list[str]:
        out = [self.data.get("topic", "")]
        if self.data.get("series") and self.data["series"] not in out:
            out.append(self.data["series"])
        return [t for t in out if t]

    def facets(self) -> dict:
        """Extra fields for listings and search."""
        d = self.data
        return {"group": d.get("group", ""), "topics": self.topics, "venue": d.get("venue", ""),
                "authors": d.get("authors") or [], "summary": d.get("summary", "")}


def load(dest: Path, settings: dict | None = None) -> list[Talk]:
    """Every talk.json in the talks dataset DEST, sorted by date."""
    settings = settings or {}
    out = []
    if not dest.is_dir():
        return out
    for path in sorted(dest.glob("*/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*/talk.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as err:
            raise TalkError(f"{path}: {err}") from None
        rel = str(path.parent.relative_to(dest))
        access = defaults(settings, data.get("group", ""), DEFAULTS)
        access.update({k: data[k] for k in ACCESS_FIELDS if data.get(k) not in (None, "")})
        keywords = {
            "title": data.get("title") or rel,
            "date": data.get("date", ""),
            "audience": str(access["audience"]),
            "visibility": str(access["visibility"]),
            "draft": "true" if access.get("draft") in (True, "true") else "false",
        }
        if access.get("access"):
            keywords["access"] = str(access["access"])
        out.append(Talk(rel, data, Meta(keywords=keywords)))
    out.sort(key=lambda t: (t.data.get("date", ""), t.dest))
    return out


def front_matter(talk: Talk, visibility: str) -> dict:
    d = talk.data
    fm = {
        "title": d.get("title") or talk.dest,
        "date": d.get("date"),
        "groups": [d["group"]] if d.get("group") else [],
        "topics": talk.topics,
        "tags": d.get("keywords") or [],
        "summary": d.get("summary", ""),
        "params": {
            "talk": True,
            "subtitle": d.get("subtitle", ""),
            "authors": d.get("authors") or [],
            "venue": d.get("venue", ""),
            "event_url": d.get("event_url", ""),
            "group": d.get("group", ""),
            "topic": d.get("topic", ""),
            "series": d.get("series", ""),
            "pdf": d.get("pdf", ""),
            "pages": d.get("pages", 0),
            "kind": d.get("kind", ""),
            "notes": d.get("notes") or [],
            "origin": d.get("origin", ""),
        },
    }
    if visibility != "public":
        fm["build"] = {"list": "never"}
        fm["params"]["visibility"] = visibility
        # Unlisted and protected talks are in no taxonomy listing either.
        fm["groups"] = fm["topics"] = fm["tags"] = []
    return fm


SECTION_PAGE = {"title": "Talks", "params": {"talklist": True}}


def write(talks: list[Talk], where: Path) -> Path:
    """Write the talks as Hugo leaf bundles under WHERE, replacing it."""
    if where.exists():
        shutil.rmtree(where)
    where.mkdir(parents=True)
    (where / "_index.md").write_text(json.dumps(SECTION_PAGE) + "\n")
    for talk in talks:
        page = where / talk.dest
        page.mkdir(parents=True, exist_ok=True)
        fm = front_matter(talk, talk.meta.visibility)
        (page / "index.md").write_text(json.dumps(fm, indent=1, ensure_ascii=False) + "\n\n"
                                       + (talk.data.get("summary") or "") + "\n")
    return where


def pdf_path(dest: Path, talk: Talk) -> Path | None:
    """The talk's PDF in the talks dataset, None if it has none or the
    annexed content is not present on this host."""
    name = talk.data.get("pdf")
    if not name:
        return None
    path = dest / talk.dest / name
    return path if path.exists() else None
