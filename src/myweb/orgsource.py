"""Edits of an org source made for publishing it.

- Every headline gets a ``CUSTOM_ID`` property, a slug of its heading,
  which ox-hugo and go-org both use as the HTML anchor.  Ids that org
  generated (``org`` and seven hex digits) are replaced by slugs too.
- The copy published beside the HTML loses its ``:noexport:`` and
  ``COMMENT`` subtrees, as the HTML does.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .orgmeta import HEADING

BLOCK_BEGIN = re.compile(r"^\s*#\+begin_(\w+)", re.I)
PLANNING = re.compile(r"^\s*(SCHEDULED|DEADLINE|CLOSED):")
DRAWER_BEGIN = re.compile(r"^(?P<indent>\s*):PROPERTIES:\s*$", re.I)
DRAWER_END = re.compile(r"^\s*:END:\s*$", re.I)
CUSTOM_ID = re.compile(r"^(?P<indent>\s*):CUSTOM_ID:[ \t]*(?P<id>\S*)\s*$", re.I)
ORG_ID = re.compile(r"^org[0-9a-f]{7}$")
LINK = re.compile(r"\[\[([^]]+)\](?:\[([^]]*)\])?\]")
COOKIE = re.compile(r"\[(?:#[A-Z]|\d*/\d*|\d*%)\]")


def slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")


def heading_slug(title: str) -> str:
    """A slug of an org heading's title, without links, cookies or markup."""
    title = re.sub(r"^COMMENT\s+", "", title)
    title = LINK.sub(lambda m: m[2] or m[1], title)
    title = COOKIE.sub("", title).replace("/", " ").replace("+", "p")
    return slugify(title) or "section"


def _headings(lines: list[str]):
    """Yield (index, match) of each heading line, skipping #+begin blocks."""
    block = None
    for i, line in enumerate(lines):
        if block:
            if re.match(rf"^\s*#\+end_{block}\b", line, re.I):
                block = None
            continue
        if mb := BLOCK_BEGIN.match(line):
            block = re.escape(mb[1])
            continue
        if line.startswith("*") and (mh := HEADING.match(line)):
            yield i, mh


@dataclass
class Ids:
    text: str
    #: (heading title, id) of each id added or replaced.
    made: list[tuple[str, str]] = field(default_factory=list)


def ensure_ids(text: str) -> Ids:
    """Give every headline a CUSTOM_ID slug, replacing org's generated ids."""
    lines = text.splitlines(keepends=True)
    heads = list(_headings(lines))
    # (heading index, drawer begin index or None, custom id line index or None)
    found = []
    for i, mh in heads:
        j = i + 1
        while j < len(lines) and PLANNING.match(lines[j]):
            j += 1
        drawer = cid = None
        if j < len(lines) and DRAWER_BEGIN.match(lines[j]):
            drawer = j
            for k in range(j + 1, len(lines)):
                if DRAWER_END.match(lines[k]):
                    break
                if CUSTOM_ID.match(lines[k]):
                    cid = k
                    break
        found.append((i, mh, j, drawer, cid))

    taken = {CUSTOM_ID.match(lines[c])["id"] for *_, c in found if c is not None}
    taken = {t for t in taken if t and not ORG_ID.match(t)}
    indented = any(lines[d][:1].isspace() for *_, d, _ in found if d is not None)
    out = Ids(text)
    inserts: list[tuple[int, list[str]]] = []
    for i, mh, after, drawer, cid in found:
        old = CUSTOM_ID.match(lines[cid])["id"] if cid is not None else ""
        if old and not ORG_ID.match(old):
            continue
        base = heading_slug(mh["title"])
        new, n = base, 1
        while new in taken:
            n += 1
            new = f"{base}-{n}"
        taken.add(new)
        out.made.append((mh["title"], new))
        nl = "\n" if not lines[i].endswith("\n") else ""
        if cid is not None:
            indent = CUSTOM_ID.match(lines[cid])["indent"]
            lines[cid] = f"{indent}:CUSTOM_ID: {new}\n"
        elif drawer is not None:
            indent = DRAWER_BEGIN.match(lines[drawer])["indent"]
            inserts.append((drawer + 1, [f"{indent}:CUSTOM_ID: {new}\n"]))
        else:
            indent = " " * (len(mh["stars"]) + 1) if indented else ""
            if nl:
                lines[i] += nl
            inserts.append((after, [f"{indent}:PROPERTIES:\n", f"{indent}:CUSTOM_ID: {new}\n", f"{indent}:END:\n"]))
    for at, new_lines in reversed(inserts):
        lines[at:at] = new_lines
    out.text = "".join(lines)
    return out


def missing_ids(text: str) -> list[str]:
    """Titles of headlines that ensure_ids would change."""
    return [title for title, _ in ensure_ids(text).made]


def publishable(text: str) -> str:
    """TEXT without its :noexport: and COMMENT subtrees."""
    lines = text.splitlines(keepends=True)
    drop = []
    heads = list(_headings(lines))
    for n, (i, mh) in enumerate(heads):
        if ":noexport:" in (mh["tags"] or "") or mh["title"].startswith("COMMENT"):
            level = len(mh["stars"])
            end = next((k for k, m in heads[n + 1:] if len(m["stars"]) <= level), len(lines))
            drop.append((i, end))
    keep = [True] * len(lines)
    for begin, end in drop:
        keep[begin:end] = [False] * (end - begin)
    return "".join(line for line, k in zip(lines, keep) if k)
