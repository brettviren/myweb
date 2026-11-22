"""Read and edit the bits of an org file that myweb cares about.

This is not an org parser.  It understands file keywords (``#+key:
value``) in the header, headings with TODO states and DEADLINE planning
lines, and enough of source blocks to tell if they carry results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

KEYWORD = re.compile(r"^#\+(?P<key>[A-Za-z_][\w\[\]-]*):[ \t]*(?P<val>.*?)\s*$")
HEADING = re.compile(
    r"^(?P<stars>\*+)\s+(?:(?P<todo>TODO|NEXT|WAIT|DONE|CANCELED)\s+)?(?P<title>.*?)"
    r"(?:\s+(?P<tags>:[\w@:]+:))?\s*$"
)
DEADLINE = re.compile(r"DEADLINE:\s*<(?P<date>\d{4}-\d{2}-\d{2})[^>]*>")
SRC_BEGIN = re.compile(r"^\s*#\+begin_src\b(?P<args>.*)$", re.I)
SRC_END = re.compile(r"^\s*#\+end_src\b", re.I)
RESULTS = re.compile(r"^\s*#\+results(\[.*\])?:", re.I)
FIGURE = re.compile(r"\[\[(?:file:)?[^]\s]+\.(?:png|jpe?g|svg|gif|webp|pdf)\]", re.I)

AUDIENCES = ("personal", "work", "both")
VISIBILITIES = ("public", "unlisted", "protected")


@dataclass
class Todo:
    state: str
    title: str
    deadline: date | None = None
    noexport: bool = False


@dataclass
class Meta:
    """What myweb knows of one item from its org source."""

    keywords: dict[str, str] = field(default_factory=dict)
    todos: list[Todo] = field(default_factory=list)
    words: int = 0
    figures: int = 0
    #: Source blocks that export results but have none.
    missing_results: list[int] = field(default_factory=list)

    @property
    def title(self) -> str:
        return self.keywords.get("title", "")

    @property
    def date(self) -> str:
        return self.keywords.get("date", "")

    @property
    def draft(self) -> bool:
        val = self.keywords.get("hugo_draft", self.keywords.get("draft", "false"))
        return val.strip().lower() in ("t", "true", "yes")

    @property
    def tags(self) -> list[str]:
        val = self.keywords.get("hugo_tags", self.keywords.get("tags[]", ""))
        return val.split()

    @property
    def audience(self) -> str:
        return self.keywords.get("audience", "both").strip() or "both"

    @property
    def visibility(self) -> str:
        return self.keywords.get("visibility", "public").strip() or "public"

    @property
    def deadline(self) -> date | None:
        dates = [t.deadline for t in self.todos if t.deadline and t.state != "DONE"]
        return min(dates) if dates else None

    @property
    def todo(self) -> str:
        """The state of the first open TODO, else of the first TODO, else ''."""
        for todo in self.todos:
            if todo.state not in ("DONE", "CANCELED"):
                return todo.state
        return self.todos[0].state if self.todos else ""

    def problems(self) -> list[str]:
        out = []
        if self.audience not in AUDIENCES:
            out.append(f"audience {self.audience!r} not one of {AUDIENCES}")
        if self.visibility not in VISIBILITIES:
            out.append(f"visibility {self.visibility!r} not one of {VISIBILITIES}")
        if not self.title:
            out.append("no #+title")
        return out


def parse(text: str) -> Meta:
    meta = Meta()
    in_header = True
    in_src: str | None = None
    src_line = 0
    pending: int | None = None  # source block line wanting results
    last: Todo | None = None
    for num, line in enumerate(text.splitlines(), 1):
        if in_src is not None:
            if SRC_END.match(line):
                if _exports_results(in_src):
                    pending = src_line
                in_src = None
            continue
        if pending is not None and line.strip():
            if not RESULTS.match(line):
                meta.missing_results.append(pending)
            pending = None
        if mk := KEYWORD.match(line):
            key = mk["key"].lower()
            if in_header and key not in meta.keywords:
                meta.keywords[key] = mk["val"]
            continue
        if ms := SRC_BEGIN.match(line):
            in_src, src_line = ms["args"], num
            continue
        if mh := HEADING.match(line):
            in_header = False
            last = None
            if mh["todo"]:
                last = Todo(
                    state=mh["todo"],
                    title=mh["title"],
                    noexport=":noexport:" in (mh["tags"] or ""),
                )
                meta.todos.append(last)
            continue
        if last is not None and (md := DEADLINE.search(line)):
            last.deadline = date.fromisoformat(md["date"])
            last = None
            continue
        if line.startswith(":") or line.startswith("#"):
            continue  # drawers, comments, other keywords
        if line.strip():
            in_header = False
        meta.words += len(line.split())
        meta.figures += len(FIGURE.findall(line))
    if pending is not None:
        meta.missing_results.append(pending)
    return meta


def _exports_results(args: str) -> bool:
    match = re.search(r":exports\s+(\S+)", args)
    exports = match[1] if match else "code"
    return exports in ("both", "results")


def read(path: Path) -> Meta:
    return parse(path.read_text(encoding="utf-8"))


def set_keyword(text: str, key: str, value: str) -> str:
    """Set the header keyword KEY to VALUE, adding it after #+title if absent."""
    lines = text.splitlines(keepends=True)
    want = key.lower()
    for i, line in enumerate(lines):
        if HEADING.match(line):
            break
        if (mk := KEYWORD.match(line)) and mk["key"].lower() == want:
            lines[i] = f"#+{key}: {value}\n"
            return "".join(lines)
    at = 0
    for i, line in enumerate(lines):
        if (mk := KEYWORD.match(line)) and mk["key"].lower() == "title":
            at = i + 1
            break
    lines.insert(at, f"#+{key}: {value}\n")
    return "".join(lines)


def close_todos(text: str, today: date | None = None) -> str:
    """Mark open :noexport: TODO headings DONE with a CLOSED stamp."""
    today = today or date.today()
    stamp = f"CLOSED: [{today.isoformat()} {today.strftime('%a')}]"
    out = []
    lines = text.splitlines(keepends=True)
    closing = False
    for line in lines:
        mh = HEADING.match(line)
        if mh and mh["todo"] in ("TODO", "NEXT", "WAIT") and ":noexport:" in (mh["tags"] or ""):
            line = line.replace(mh["todo"], "DONE", 1)
            closing = True
            out.append(line)
            continue
        if closing:
            closing = False
            if DEADLINE.search(line):
                out.append(f"{stamp} {line.lstrip()}")
                continue
            out.append(f"{stamp}\n")
        out.append(line)
    if closing:
        out.append(f"{stamp}\n")
    return "".join(out)
