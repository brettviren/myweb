"""Working on talks in the talks dataset: start, refresh, pull.

A talk is a directory ``<group>/<YYYY>/<MM>/<DD>/<topic>/`` of the talks
dataset (default ~/keep/talks) holding its sources, its PDF and a
``talk.json`` the web build reads (see talkpages.py).

- ``new`` starts one: an org-beamer source and a draft talk.json.
- ``refresh`` updates talk.json from the talk's org title and PDF, after
  the PDF is (re)built, and with ``publish`` clears its draft flag.
- ``describe`` sets its summary, title and such, in talk.json and, for a
  migrated talk, in its review, which migrating again writes from.
- ``pull`` brings in a migrated talk's changes made since in the old
  talks tree, even if it moved there: it is migrated again (see talks.py)
  into its place, which follows a change of group.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import talks as talking
from .config import expand

TALK = "talk.json"
ORG_TITLE = re.compile(r"^#\+title:\s*(.+)$", re.I | re.M)
ORG_AUTHOR = re.compile(r"^#\+author:\s*(.+)$", re.I | re.M)
SETUPFILE = "~/sync/talks/setup.org"

SKELETON = """\
#+title: {title}
#+setupfile: {setupfile}

* {title}

- A first slide.

# Local Variables:
# eval: (fix-latex-previews)
# End:
"""


class TalkWorkError(Exception):
    pass


def talk_dirs(dest: Path) -> list[Path]:
    return sorted(p.parent for p in dest.glob(f"*/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*/{TALK}"))


def find(dest: Path, spec: str) -> Path:
    """A talk by its place (group/YYYY/MM/DD/topic), its topic or a path."""
    path = Path(spec).expanduser()
    if path.is_file():
        path = path.parent
    if path.is_dir() and (path / TALK).exists():
        return path.resolve()
    if (dest / spec / TALK).exists():
        return dest / spec
    hits = [d for d in talk_dirs(dest) if d.name == spec or d.relative_to(dest).as_posix().endswith("/" + spec)]
    if not hits:
        raise TalkWorkError(f"no talk {spec!r} in {dest}")
    if len(hits) > 1:
        raise TalkWorkError(f"{spec!r} is ambiguous: " + ", ".join(d.relative_to(dest).as_posix() for d in hits))
    return hits[0]


def read(talk: Path) -> dict:
    try:
        return json.loads((talk / TALK).read_text())
    except (OSError, json.JSONDecodeError) as err:
        raise TalkWorkError(f"{talk / TALK}: {err}") from None


def write(talk: Path, data: dict) -> None:
    (talk / TALK).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def source(talk: Path, data: dict | None = None) -> Path:
    """The talk's org (else first) source file."""
    data = data or read(talk)
    srcs = data.get("sources") or {}
    name = srcs.get("org") or next(iter(srcs.values()), "")
    if not name:
        raise TalkWorkError(f"{talk}: talk.json names no source")
    return talk / name


def new(dest: Path, group: str, title: str, topic: str = "", when: date | None = None,
        setupfile: str = SETUPFILE) -> Path:
    """Start a talk: a draft talk.json and an org-beamer source."""
    group, topic = talking.slug(group), talking.slug(topic or title)
    if not group or not topic:
        raise TalkWorkError("a talk needs a group and a title or topic")
    when = when or date.today()
    talk = dest / group / f"{when:%Y/%m/%d}" / topic
    if talk.exists():
        raise TalkWorkError(f"{talk} exists")
    setup = expand(setupfile)
    author = ORG_AUTHOR.search(setup.read_text()) if setup.is_file() else None
    talk.mkdir(parents=True)
    org = f"{topic}.org"
    (talk / org).write_text(SKELETON.format(title=title, setupfile=setupfile))
    write(talk, {
        "group": group, "date": when.isoformat(), "date_source": "owner", "topic": topic,
        "title": title, "authors": [author[1].strip()] if author else [], "summary": "",
        "keywords": [], "kind": "org-beamer", "pdf": f"{topic}.pdf", "pages": 0,
        "sources": {"org": org}, "files": [org], "draft": True,
    })
    return talk


def _files(talk: Path) -> list[str]:
    out = []
    for path in sorted(talk.rglob("*")):
        rel = path.relative_to(talk)
        if rel.as_posix() == TALK or not (path.is_file() or path.is_symlink()):
            continue
        if any(talking._skip_dir(p) for p in rel.parts[:-1]) or talking._generated(path.name):
            continue
        out.append(rel.as_posix())
    return out


def refresh(talk: Path, publish: bool = False) -> tuple[dict, list[str]]:
    """Update talk.json from the org title and the PDF.  Return it and warnings."""
    data, warnings = read(talk), []
    org = source(talk, data)
    if org.suffix == ".org" and org.exists():
        if m := ORG_TITLE.search(org.read_text()):
            data["title"] = m[1].strip()
    pdf = talk / data["pdf"] if data.get("pdf") else None
    if pdf and pdf.exists():
        info = talking.pdfinfo(talk, data["pdf"])
        data["pages"] = info.pages
        data["aspect"] = round(info.width / info.height, 3) if info.height else 0
        data["pdf_meta"] = {k: getattr(info, k) for k in ("title", "author", "subject", "keywords", "creator",
                                                          "producer", "created", "mtime", "md5")}
    else:
        warnings.append(f"no PDF {data.get('pdf') or '(none named)'} yet: build it from {org.name}")
    data["files"] = _files(talk)
    if publish:
        if not (pdf and pdf.exists()):
            raise TalkWorkError(f"{talk}: will not publish a talk without its PDF")
        data.pop("draft", None)
    write(talk, data)
    return data, warnings


def pull(state: talking.State, root: Path, talk: Path, src: Path | None = None) -> tuple[str, str]:
    """Migrate TALK again from the old tree, from SRC if it moved there.

    The old tree is scanned first.  The candidate at SRC (else the talk's
    origin) is taken as the talk's, accepted by the owner as it is now,
    with the talk's review and place, so it is neither reviewed again nor
    migrated a second time elsewhere.  Return (candidate id, place).
    """
    inv, _, _ = talking.update(state, root)
    top = state.dest.resolve()
    talk = talk.resolve()
    place = talk.relative_to(top).as_posix()
    old = [cid for cid, e in inv["talks"].items() if e.get("dest") == place]
    if not old:
        raise TalkWorkError(f"{place} was not migrated, nothing to pull")
    old_id = old[0]
    if src is None:
        new_id = old_id
        if inv["talks"][old_id].get("gone"):
            raise TalkWorkError(f"{old_id} is gone from {root}; give where it is now")
    else:
        rel = src.expanduser().resolve().relative_to(root.resolve()).as_posix()
        here = [cid for cid, e in inv["talks"].items() if not e.get("gone")
                and talking.Candidate.from_dict(e["candidate"]).dir == rel]
        slides = [cid for cid in here if talking.Candidate.from_dict(inv["talks"][cid]["candidate"]).pdf]
        here = slides or here
        if len(here) != 1:
            raise TalkWorkError(f"{len(here)} talk candidates in {rel}: " + (", ".join(here) or "none"))
        new_id = here[0]
    cand = talking.Candidate.from_dict(inv["talks"][new_id]["candidate"])
    review = dict(state.review(old_id) or {})
    review.update(id=new_id, fingerprint=cand.fingerprint, resolution="accept",
                  resolution_note=f"pulled into {place}")
    data = read(talk)
    review.setdefault("date", data.get("date", ""))
    review.setdefault("topic_slug", data.get("topic", ""))
    path = state.review_path(new_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review, indent=1, ensure_ascii=False) + "\n")
    # The place keeps its date and topic; a new group moves it.
    y, m, d = (review.get("date") or data["date"]).split("-")
    new_place = f"{cand.group or data['group']}/{y}/{m}/{d}/{data['topic']}"
    if new_place != place:
        target = top / new_place
        if target.exists():
            raise TalkWorkError(f"{new_place} exists, will not move {place} there")
        target.parent.mkdir(parents=True, exist_ok=True)
        talk.rename(target)
        for parent in talk.parents:
            if parent == top or any(parent.iterdir()):
                break
            parent.rmdir()
    entry = inv["talks"][new_id]
    entry.update(dest=new_place, status="changed")
    if old_id != new_id:
        inv["talks"][old_id].update(moved_to=new_id)
        inv["talks"][old_id].pop("dest", None)
    done = talking.migrate(state, root, inv, [new_id], redo=True)
    if not done or done[0][1] != "migrated":
        raise TalkWorkError(f"{new_id}: {done[0][1] if done else 'not migrated'}")
    return new_id, new_place


#: Text a person gives a talk, in talk.json and a migrated talk's review.
DESCRIBED = ("title", "subtitle", "summary", "keywords", "venue", "event_url")


def describe(dest: Path, talk: Path, **fields) -> list[str]:
    """Set FIELDS (of DESCRIBED, None to leave) of TALK.  Return where written."""
    fields = {k: v for k, v in fields.items() if v is not None}
    unknown = set(fields) - set(DESCRIBED)
    if unknown:
        raise TalkWorkError(f"cannot describe {', '.join(sorted(unknown))}")
    data = read(talk)
    data.update(fields)
    write(talk, data)
    out = [str(talk / TALK)]
    origin = data.get("origin")
    if origin:
        state = talking.State(dest)
        inv = state.load()
        place = talk.resolve().relative_to(dest.resolve()).as_posix()
        if inv["talks"].get(origin, {}).get("dest") == place:
            review = state.review(origin) or {"id": origin, "reviewed_by": "owner", "is_talk": True, "problems": []}
            review.update(fields)
            path = state.review_path(origin)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(review, indent=1, ensure_ascii=False) + "\n")
            out.append(str(path))
    return out


#: The one-line fields of a description text, by their label there.
TEXT_FIELDS = (("title", "title"), ("subtitle", "subtitle"), ("venue", "venue"),
               ("url", "event_url"), ("keywords", "keywords"))
TEXT_HELP = """\
# Describe the talk {place}.
# Edit the values after each "name:".  An empty value clears it.
# keywords are separated by commas.  The summary is every line after
# "summary:", a few sentences for listings and search.
# Lines starting with # are ignored.  Save and quit to apply.
"""


def description_text(talk: Path, dest: Path) -> str:
    """The talk's description as text to edit, every field shown."""
    data = read(talk)
    lines = [TEXT_HELP.format(place=talk.resolve().relative_to(dest.resolve()).as_posix())]
    for label, key in TEXT_FIELDS:
        val = data.get(key) or ""
        if key == "keywords":
            val = ", ".join(val)
        lines.append(f"{label}: {val}".rstrip())
    lines += ["", "summary:", (data.get("summary") or "").strip(), ""]
    return "\n".join(lines)


def parse_description(text: str) -> dict:
    """The fields of a description text, all of them, "" or [] if empty."""
    labels = dict(TEXT_FIELDS)
    out: dict = {}
    summary: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        if summary is not None:
            summary.append(line)
            continue
        if not line.strip():
            continue
        label, sep, val = line.partition(":")
        label = label.strip().lower()
        if not sep or (label not in labels and label != "summary"):
            raise TalkWorkError(f"not a field: {line!r}; expected one of "
                                + ", ".join([*labels, "summary"]))
        if label == "summary":
            summary = [val.strip()] if val.strip() else []
            continue
        key = labels[label]
        out[key] = [k.strip() for k in val.split(",") if k.strip()] if key == "keywords" else val.strip()
    for _, key in TEXT_FIELDS:
        out.setdefault(key, [] if key == "keywords" else "")
    # Paragraphs keep their breaks, lines within one are joined.
    paras = "\n".join(summary or []).strip().split("\n\n")
    out["summary"] = "\n\n".join(" ".join(p.split()) for p in paras if p.strip())
    return out


def changes(talk: Path, fields: dict) -> dict:
    """Those of FIELDS that differ from the talk's."""
    data = read(talk)
    return {k: v for k, v in fields.items() if (data.get(k) or type(v)()) != v}
