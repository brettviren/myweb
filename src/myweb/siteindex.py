"""Search indexes of a built site, one per access realm.

Search runs in the reader's browser over static JSON, so what a reader
can search is exactly what the web server lets them fetch.  The public
index is ``search/index.json``.  Each other realm gets ``search/<realm>/``
holding its own ``index.json``, the realm's ``.htaccess`` (the same text
that guards its pages, see access.py) and a copy of the search page that
loads both the public index and the realm's.  No index holds pages of
two realms, and unlisted pages are in none.

The theme's search page marks where myweb edits its copies:
``data-indexes="index.json"`` on the element the script reads, and a
an empty ``<div id="search-realms"></div>`` where links to realm searches
go.  (Not a comment: Go templates drop comments.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from . import access
from .config import Target
from .hugo import Plan

SEARCH = "search"
INDEX = "index.json"
INDEXES_MARK = 'data-indexes="index.json"'
REALMS_MARK = '<div id="search-realms"></div>'
SKIP_TAGS = {"header", "script", "style", "nav", "math", "svg", "form"}
SKIP_CLASSES = {"anchor", "notice", "meta", "toc"}


class SearchError(Exception):
    pass


class _Text(HTMLParser):
    """Text of a page's <article>, less its header and decorations."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0  # inside <article>
        self.skip_tag = ""  # the element being skipped, and its nesting
        self.skip_n = 0
        self.in_h1 = False
        self.title: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.depth += 1
        if not self.depth:
            return
        if tag == "h1" and not self.title:
            self.in_h1 = True
        if self.skip_tag:
            self.skip_n += tag == self.skip_tag
            return
        classes = set((dict(attrs).get("class") or "").split())
        if tag in SKIP_TAGS or classes & SKIP_CLASSES:
            self.skip_tag, self.skip_n = tag, 1

    def handle_endtag(self, tag):
        if self.skip_tag and tag == self.skip_tag:
            self.skip_n -= 1
            if not self.skip_n:
                self.skip_tag = ""
        if tag == "h1":
            self.in_h1 = False
        if tag == "article" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.in_h1:
            self.title.append(data)
        if self.depth and not self.skip_tag:
            self.parts.append(data)


def page_text(html: str) -> tuple[str, str]:
    """(title, text) of a built page."""
    parser = _Text()
    parser.feed(html)
    return " ".join("".join(parser.title).split()), " ".join(" ".join(parser.parts).split())


@dataclass
class Index:
    realm: access.Realm
    pages: list[dict] = field(default_factory=list)

    def json(self) -> str:
        return json.dumps({"realm": self.realm.name, "pages": self.pages}, ensure_ascii=False)


def indexes(target: Target, plan: Plan, stage: Path) -> dict[str, Index]:
    """The index of each realm with pages on this plan, public always."""
    out = {access.PUBLIC: Index(access.Realm(access.PUBLIC))}
    for bundle in plan.included:
        realm = access.index_realm(target, plan.meta[bundle.name])
        if realm is None:
            continue
        page = stage / bundle.url_path / "index.html"
        if not page.exists():
            continue
        title, text = page_text(page.read_text(errors="replace"))
        meta = plan.meta[bundle.name]
        out.setdefault(realm.name, Index(realm)).pages.append({
            "url": bundle.url_path,  # relative to the site root
            "title": title or meta.title,
            "date": meta.date,
            "section": bundle.taxon.section,
            "tags": meta.tags,
            "text": text,
        })
    return out


def write(target: Target, plan: Plan, stage: Path) -> list[Path]:
    """Write the search indexes and realm search pages, return their paths."""
    found = indexes(target, plan, stage)
    top = stage / SEARCH
    top.mkdir(parents=True, exist_ok=True)
    page = top / "index.html"
    html = page.read_text() if page.exists() else ""
    realms = [i for name, i in found.items() if name != access.PUBLIC]
    out = []
    for index in [found[access.PUBLIC], *realms]:
        where = top if index.realm.public else top / index.realm.name
        where.mkdir(exist_ok=True)
        (where / INDEX).write_text(index.json())
        out.append(where / INDEX)
        if index.realm.public:
            continue
        try:
            text = access.htaccess(target, index.realm, "search")
        except ValueError as err:
            raise SearchError(str(err)) from None
        (where / ".htaccess").write_text(text)
        out.append(where / ".htaccess")
        if html:
            copy = html.replace(INDEXES_MARK, f'data-indexes="../{INDEX} {INDEX}"')
            copy = copy.replace(REALMS_MARK, f'<div id="search-realms"><p class="notice">Searching public pages and those of realm "{index.realm.name}".</p></div>')
            (where / "index.html").write_text(copy)
    if html:
        links = "".join(f'<li><a href="{i.realm.name}/">{i.realm.name}</a></li>' for i in realms)
        if links:
            links = f'<div id="search-realms"><p>Readers with access may also search:</p><ul>{links}</ul></div>'
        page.write_text(html.replace(REALMS_MARK, links))
    return out


def check(target: Target, plan: Plan, stage: Path) -> list[str]:
    """Problems with the written indexes: a page in the wrong realm's index,
    or a realm index not guarded as its pages are."""
    want = {}
    for bundle in plan.included:
        realm = access.index_realm(target, plan.meta[bundle.name])
        want[bundle.url_path] = realm.name if realm else None
    problems = []
    for path in sorted((stage / SEARCH).rglob(INDEX)):
        data = json.loads(path.read_text())
        name = data["realm"]
        for entry in data["pages"]:
            if want.get(entry["url"]) != name:
                problems.append(f"{entry['url']} must not be in search index of realm {name}")
        if name != access.PUBLIC:
            guard = path.parent / ".htaccess"
            realm = access.Realm(name, target.realms.get(name, ""))
            if realm.public or not guard.exists() or guard.read_text() != access.htaccess(target, realm, "search"):
                problems.append(f"{path.relative_to(stage)} is not guarded by realm {name}")
        elif path.parent != stage / SEARCH:
            problems.append(f"public index misplaced at {path.relative_to(stage)}")
    return problems
