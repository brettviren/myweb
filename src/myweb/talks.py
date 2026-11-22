"""Finding talks in an old talks tree and migrating them to a new one.

The old tree (eg ~/sync/talks) is only read.  Each talk found there is a
*candidate*, identified by its directory and file stem, eg
``dune/2023/06/06/framework``.  Its group, date and topic are derived
from its path, its sources and its PDF.  A *review* of each candidate,
made separately (by reading a digest of it), says whether it is really a
talk and gives its title, venue, summary and such.  Migration copies a
reviewed talk to ``<group>/<YYYY>/<MM>/<DD>/<topic>/`` in the new tree
with a ``talk.json`` describing it.

State lives in the new tree under ``migration/``:

- ``inventory.json`` :: every candidate ever found, and its status
- ``reviews/<id>.json`` :: one review per candidate, kept across scans
- ``digests/<id>.txt`` :: what a reviewer reads (not kept in git)

and ``MIGRATION.org`` reports it all for a person to read.  Scanning
again finds new or changed talks; migrating again rewrites talk.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

#: Bumped when what migrate writes changes, so old migrations show as stale.
VERSION = 1

SLIDE_SOURCES = {".org": "org-beamer", ".tex": "latex-beamer", ".odp": "impress", ".sxi": "impress",
                 ".ppt": "powerpoint", ".pptx": "powerpoint", ".key": "keynote"}
OFFICE = {".odp", ".sxi", ".ppt", ".pptx", ".key"}
#: Directories never scanned or copied: generated or tool state.
GENERATED_DIRS = {"auto", "latexmk-out", "ltximg", "svg-inkscape", ".git", "__pycache__", "_region_"}
GENERATED_EXT = {".aux", ".log", ".nav", ".snm", ".toc", ".out", ".vrb", ".fls", ".fdb_latexmk",
                 ".bbl", ".blg", ".synctex.gz", ".dvi", ".bak", ".pyc"}
#: Directories holding other people's material, copied with a talk but
#: never themselves holding a talk of the owner.
OTHERS_DIRS = {"other", "others"}
#: File stems that do not name a topic.
GENERIC = {"notes", "talk", "slides", "presentation", "main", "index", "cut", "test", "short",
           "junk", "junk2", "readme", "draft", "new", "old", "tmp"}
#: Top level files that are templates, not talks.
TEMPLATES = re.compile(r"^(setup.*|empty-talk|skel|test|readme)$", re.I)
PLOTTERS = ("matplotlib", "cairo", "root", "gnuplot", "graphviz", "inkscape", "pyx")
BEAMER = re.compile(r"\\documentclass(\[[^]]*\])?\{beamer\}|^#\+(setupfile:.*talks/setup|beamer_|startup:.*beamer|latex_class:\s*beamer)", re.I | re.M)
ORG_DATE = re.compile(r"^#\+date:\s*(.+)$", re.I | re.M)
TEX_DATE = re.compile(r"\\date(?:\[[^]]*\])?\{([^}]*)\}")


@dataclass
class Pdf:
    path: str
    pages: int = 0
    width: float = 0.0
    height: float = 0.0
    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    creator: str = ""
    producer: str = ""
    created: str = ""  # ISO date from CreationDate
    mtime: str = ""  # ISO date of the file's modification
    md5: str = ""

    @property
    def slides(self) -> bool:
        """Looks like a slide deck on its own: several landscape pages not
        made by a plotting tool."""
        made = f"{self.creator} {self.producer}".lower()
        if any(tool in made for tool in PLOTTERS):
            return False
        return self.pages >= 5 and self.width > 1.15 * self.height


@dataclass
class Candidate:
    id: str
    group: str = ""
    dir: str = ""
    stem: str = ""
    kind: str = "pdf"
    #: Relative paths of the talk's own files by role: pdf, org, tex, office.
    files: dict[str, str] = field(default_factory=dict)
    pdf: Pdf | None = None
    date: str = ""  # YYYY-MM-DD
    date_source: str = ""  # path, filename, source, pdfinfo, mtime
    date_precision: str = ""  # of the path or name: day, month, year, none
    topic: str = ""
    series: str = ""  # eg the topics/<series>/ a talk is in
    dest: str = ""
    flags: list[str] = field(default_factory=list)
    duplicate_of: str = ""
    fingerprint: str = ""
    source_date: str = ""  # #+date or \date{} text, as written

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        d = dict(d)
        if d.get("pdf"):
            d["pdf"] = Pdf(**d["pdf"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---- reading files

def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pdfdate(text: str) -> str:
    """ISO date of pdfinfo's CreationDate, eg 'Tue Sep 10 09:03:26 2024 EDT'."""
    m = re.search(r"(\w{3}) +(\d{1,2}) +[\d:]+ +(\d{4})", text)
    if not m:
        return ""
    try:
        return datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%b %d %Y").date().isoformat()
    except ValueError:
        return ""


def pdfinfo(root: Path, rel: str) -> Pdf:
    path = root / rel
    pdf = Pdf(rel, mtime=date.fromtimestamp(path.stat().st_mtime).isoformat())
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60,
                             errors="replace").stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    info = {}
    for line in out.splitlines():
        key, sep, val = line.partition(":")
        if sep:
            info[key.strip()] = val.strip()
    pdf.pages = int(info.get("Pages", "0") or 0)
    if m := re.match(r"([\d.]+) x ([\d.]+)", info.get("Page size", "")):
        pdf.width, pdf.height = float(m[1]), float(m[2])
        if info.get("Page rot", "0") in ("90", "270"):
            pdf.width, pdf.height = pdf.height, pdf.width
    for key in ("title", "author", "subject", "keywords", "creator", "producer"):
        setattr(pdf, key, info.get(key.capitalize(), ""))
    pdf.created = _pdfdate(info.get("CreationDate", ""))
    pdf.md5 = _md5(path)
    return pdf


def _head(path: Path, size: int = 20000) -> str:
    try:
        with open(path, errors="replace") as fp:
            return fp.read(size)
    except OSError:
        return ""


# ---- dates and topics from paths

def _valid(y: int, m: int, d: int = 1) -> bool:
    try:
        date(y, m, d)
    except ValueError:
        return False
    return 1990 <= y <= 2100


def _yy(yy: str) -> int:
    return 2000 + int(yy) if int(yy) < 90 else 1900 + int(yy)


def compact_date(name: str) -> tuple[tuple[int, int, int], str, str] | None:
    """Parse a name like 090401-upgrades, 201405-sc, 0910-nnn09,
    20131003-sc, 0704xx.  Return ((y, m, d), precision, rest)."""
    m = re.match(r"^(\d{4,8}|\d{4}xx)(?:[-_.](.*))?$", name)
    if not m:
        return None
    digits, rest = m[1], m[2] or ""
    if digits.endswith("xx"):
        y, mo = _yy(digits[:2]), int(digits[2:4])
        return ((y, mo, 1), "month", rest) if _valid(y, mo) else None
    if len(digits) == 8:
        y, mo, d = int(digits[:4]), int(digits[4:6]), int(digits[6:])
        return ((y, mo, d), "day", rest) if _valid(y, mo, d) else None
    if len(digits) == 6:
        # 201405 is May 2014; 090401 is 2009-04-01.
        y4, m2 = int(digits[:4]), int(digits[4:])
        if 1995 <= y4 <= 2035 and 1 <= m2 <= 12:
            return (y4, m2, 1), "month", rest
        y, mo, d = _yy(digits[:2]), int(digits[2:4]), int(digits[4:])
        return ((y, mo, d), "day", rest) if _valid(y, mo, d) else None
    if len(digits) == 4:
        y, mo = _yy(digits[:2]), int(digits[2:])
        return ((y, mo, 1), "month", rest) if _valid(y, mo) else None
    return None


@dataclass
class PathInfo:
    ymd: tuple[int, int, int] | None = None
    precision: str = "none"
    source: str = ""  # path or filename
    topic: str = ""  # from the path, "" if none
    series: str = ""
    extra: list[str] = field(default_factory=list)  # deeper dirs


def path_info(parts: list[str], stem: str) -> PathInfo:
    """Date and topic from a talk's directory parts below its group."""
    info = PathInfo()
    i = 0
    if len(parts) > 0 and re.fullmatch(r"\d{4}", parts[0]) and 1990 <= int(parts[0]) <= 2100:
        y, mo, d, prec = int(parts[0]), 1, 1, "year"
        i = 1
        if len(parts) > 1 and re.fullmatch(r"\d{2}", parts[1]) and 1 <= int(parts[1]) <= 12:
            mo, prec, i = int(parts[1]), "month", 2
            if len(parts) > 2 and re.fullmatch(r"\d{2}", parts[2]) and _valid(y, mo, int(parts[2])):
                d, prec, i = int(parts[2]), "day", 3
        info.ymd, info.precision, info.source = (y, mo, d), prec, "path"
    elif parts and (c := compact_date(parts[0])):
        info.ymd, info.precision, info.source = c[0], c[1], "path"
        info.topic = c[2]
        i = 1
    elif parts and parts[0] == "topics":
        info.series = parts[1] if len(parts) > 1 else ""
        info.topic = info.series
        i = 2
    rest = parts[i:]
    if rest and not info.topic:
        info.topic = rest[0]
        rest = rest[1:]
    elif not info.topic and parts and info.ymd is None and parts[0] != "topics":
        info.topic = parts[0]
    info.extra = rest
    if info.ymd is None or info.precision != "day":
        c = compact_date(stem)
        if not c and (m := re.search(r"(?:^|[-_])(\d{8})(?:$|[-_])", stem)):
            c = compact_date(m[1])
        if c and (info.ymd is None or c[0][:2] == info.ymd[:2] or info.precision == "none"):
            info.ymd, info.precision, info.source = c[0], c[1], "filename"
    return info


def parse_loose_date(text: str) -> str:
    """ISO date from free text like '2021-02-10', 'Feb 10, 2021', '10 February 2021'."""
    text = re.sub(r"<|>|\[|\]|\\today", " ", text)
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", text):
        y, mo, d = map(int, m.groups())
        return date(y, mo, d).isoformat() if _valid(y, mo, d) else ""
    for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        m = re.search(r"([A-Za-z]+\.? +\d{1,2},? +\d{4}|\d{1,2} +[A-Za-z]+\.? +\d{4})", text)
        if not m:
            return ""
        try:
            return datetime.strptime(m[1].replace(",", "").replace(".", ""), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def slug(text: str) -> str:
    from .orgsource import slugify
    return slugify(text.replace("+", "p").replace("/", " ").replace(".", " "))


# ---- scanning

@dataclass
class Scan:
    root: Path
    candidates: dict[str, Candidate] = field(default_factory=dict)


def _skip_dir(name: str) -> bool:
    return name in GENERATED_DIRS or name.startswith("_minted") or name.startswith(".")


def _generated(name: str) -> bool:
    return (any(name.endswith(e) for e in GENERATED_EXT) or name.endswith("~")
            or name.startswith(".#") or name.startswith("#") or ".sync-conflict-" in name)


def _walk(root: Path):
    """Yield (reldir, filenames) below root, skipping generated dirs and dir symlinks."""
    for top, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not _skip_dir(d) and not os.path.islink(os.path.join(top, d)))
        yield os.path.relpath(top, root), sorted(files)


def _is_slide_source(path: Path, ext: str) -> bool:
    if ext in OFFICE:
        return True
    if ext in (".org", ".tex"):
        return bool(BEAMER.search(_head(path)))
    return False


def scan(root: Path, known: dict[str, Candidate] | None = None) -> Scan:
    """Find talk candidates under ROOT.  Unchanged PDFs reuse KNOWN's pdfinfo."""
    known = known or {}
    result = Scan(root)
    for reldir, files in _walk(root):
        reldir = "" if reldir == "." else reldir
        parts = reldir.split("/") if reldir else []
        if any(p in OTHERS_DIRS for p in parts):
            continue
        by_stem: dict[str, dict[str, str]] = {}
        for name in files:
            if _generated(name):
                continue
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if ext == ".pdf" or ext in SLIDE_SOURCES:
                path = root / reldir / name
                if not path.exists():  # dangling symlink
                    continue
                by_stem.setdefault(stem, {})[ext] = f"{reldir}/{name}" if reldir else name
        for stem, exts in by_stem.items():
            cand = _candidate(root, reldir, parts, stem, exts, known)
            if cand:
                result.candidates[cand.id] = cand
    _place(result)
    return result


def _candidate(root, reldir, parts, stem, exts, known) -> Candidate | None:
    sources = {e: p for e, p in exts.items() if e != ".pdf" and _is_slide_source(root / p, e)}
    pdf = None
    empty = ".pdf" in exts and (root / exts[".pdf"]).stat().st_size == 0
    if ".pdf" in exts and not empty:
        rel = exts[".pdf"]
        old = known.get(f"{reldir}/{stem}" if reldir else stem)
        mtime = date.fromtimestamp((root / rel).stat().st_mtime).isoformat()
        if old and old.pdf and old.pdf.path == rel and old.pdf.mtime == mtime:
            pdf = old.pdf
        else:
            pdf = pdfinfo(root, rel)
    if not sources and not (pdf and pdf.slides):
        return None
    cid = f"{reldir}/{stem}" if reldir else stem
    cand = Candidate(id=cid, dir=reldir, stem=stem, pdf=pdf)
    if empty:
        cand.flags.append("empty-pdf")
    if pdf:
        cand.files["pdf"] = pdf.path
    for ext, path in sources.items():
        role = "office" if ext in OFFICE else ext[1:]
        cand.files[role] = path
    if ".org" in sources:
        cand.kind = "org-beamer"
        if ".tex" in exts:
            cand.files["tex"] = exts[".tex"]
    elif ".tex" in sources:
        cand.kind = "latex-beamer"
    elif sources:
        cand.kind = SLIDE_SOURCES[next(iter(sources))]
    if ".org" in exts and "org" not in cand.files:
        cand.files["org"] = exts[".org"]  # an org next to a PDF, eg notes for it
    h = hashlib.md5()
    for role in sorted(cand.files):
        p = root / cand.files[role]
        h.update(f"{role}:{p.stat().st_size}:{int(p.stat().st_mtime)}".encode())
    cand.fingerprint = h.hexdigest()

    if not parts:
        cand.flags.append("top-level" if not TEMPLATES.match(stem) else "template")
        return cand
    cand.group = parts[0]
    info = path_info(parts[1:], stem)
    srcdate = ""
    for role in ("org", "tex"):
        if role in cand.files:
            text = _head(root / cand.files[role])
            m = (ORG_DATE if role == "org" else TEX_DATE).search(text)
            if m and m[1].strip():
                cand.source_date = m[1].strip()
                srcdate = parse_loose_date(cand.source_date)
                break
    _date(cand, info, srcdate)
    cand.series = info.series
    cand.topic = info.topic
    if info.extra:
        cand.flags.append("nested")
        cand.topic = info.extra[-1]
    if not cand.topic or slug(cand.topic) in GENERIC:
        cand.topic = stem if slug(stem) not in GENERIC else (cand.topic or stem)
    return cand


def _date(cand: Candidate, info: PathInfo, srcdate: str) -> None:
    """Date from the path or name, else the source, pdfinfo, file mtime.
    A partial path date (no day) is completed by a fallback that agrees
    with it, else the 1st with a flag."""
    pdf = cand.pdf
    fallbacks = [(srcdate, "source"), (pdf.created if pdf else "", "pdfinfo"),
                 (pdf.mtime if pdf else "", "mtime")]
    cand.date_precision = info.precision
    if info.ymd and info.precision == "day":
        cand.date, cand.date_source = date(*info.ymd).isoformat(), info.source
        return
    if info.ymd:
        y, mo, _ = info.ymd
        prefix = f"{y:04d}-{mo:02d}" if info.precision == "month" else f"{y:04d}"
        for value, how in fallbacks:
            if value and value.startswith(prefix):
                cand.date, cand.date_source = value, f"{info.source}+{how}"
                return
        cand.date = f"{y:04d}-{mo:02d}-01"
        cand.date_source = info.source
        cand.flags.append("day-unknown" if info.precision == "month" else "month-unknown")
        return
    for value, how in fallbacks:
        if value:
            cand.date, cand.date_source = value, how
            return
    if cand.files:
        cand.flags.append("no-date")


def _rank(c: Candidate) -> tuple:
    """Prefer, among duplicates: a full path date in a date tree, sources,
    a short path."""
    return (c.date_precision != "day", not re.match(r"^[^/]+/\d{4}/", c.id), "org" not in c.files and "tex" not in c.files
            and "office" not in c.files, len(c.id))


def _place(result: Scan) -> None:
    """Find duplicates, flag shared directories, choose unique destinations."""
    cands = list(result.candidates.values())
    by_md5: dict[str, list[Candidate]] = {}
    for c in cands:
        if c.pdf:
            by_md5.setdefault(c.pdf.md5, []).append(c)
    by_key: dict[tuple, list[Candidate]] = {}
    for c in cands:
        by_key.setdefault((c.group, c.date, c.stem), []).append(c)
    for groups in (by_md5.values(), by_key.values()):
        for same in groups:
            if len(same) > 1:
                best = min(same, key=_rank)
                for c in same:
                    if c is not best and not c.duplicate_of:
                        c.duplicate_of = best.id
    by_dir: dict[str, list[Candidate]] = {}
    for c in cands:
        if not c.duplicate_of:
            by_dir.setdefault(c.dir, []).append(c)
    for same in by_dir.values():
        if len(same) > 1:
            for c in same:
                c.flags.append("shared-dir")
                if c.topic != c.stem and slug(c.stem) not in GENERIC:
                    c.series = c.series or c.topic
                    c.topic = c.stem
    taken: set[str] = set()
    for c in sorted(cands, key=lambda c: c.id):
        if c.duplicate_of or not c.group or not c.date:
            continue
        y, m, d = c.date.split("-")
        base = f"{c.group}/{y}/{m}/{d}/{slug(c.topic) or slug(c.stem) or 'talk'}"
        dest, n = base, 1
        while dest in taken:
            n += 1
            dest = f"{base}-{n}"
        taken.add(dest)
        c.dest = dest


# ---- digests for review

def digest(root: Path, cand: Candidate, pages: int = 4, chars: int = 6000) -> str:
    """What a reviewer reads to judge a candidate."""
    lines = [f"id: {cand.id}", f"group: {cand.group}", f"kind: {cand.kind}",
             f"derived date: {cand.date} (from {cand.date_source})", f"derived topic: {cand.topic}",
             f"files: {json.dumps(cand.files)}", f"flags: {', '.join(cand.flags) or '-'}"]
    if cand.source_date:
        lines.append(f"date written in source: {cand.source_date}")
    if cand.pdf:
        p = cand.pdf
        lines += [f"pdf: {p.pages} pages {p.width:.0f}x{p.height:.0f}pt, title={p.title!r}, "
                  f"author={p.author!r}, subject={p.subject!r}, creator={p.creator!r}, "
                  f"producer={p.producer!r}, created={p.created}"]
    folder = root / cand.dir
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    lines.append("directory: " + " ".join(n for n in names if not _generated(n))[:800])
    for role in ("org", "tex"):
        if role in cand.files:
            text = _head(root / cand.files[role], 200000)
            if role == "tex":
                macros = re.findall(r"^\s*\\(?:title|subtitle|author|date|institute|event)\b.*$", text, re.M)
                body = text.partition("\\begin{document}")[2] or text
                text = "\n".join(macros) + "\n...\n" + body[:2500]
            lines += [f"--- start of {cand.files[role]}", text[:4000], "---"]
            break
    if cand.pdf:
        try:
            text = subprocess.run(["pdftotext", "-l", str(pages), "-layout", str(root / cand.pdf.path), "-"],
                                  capture_output=True, text=True, timeout=60, errors="replace").stdout
        except (OSError, subprocess.TimeoutExpired):
            text = ""
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        lines += [f"--- text of first {pages} pages of {cand.pdf.path}", text[:chars], "---"]
    elif "office" in cand.files:
        lines.append("(no PDF; office source only)")
    return "\n".join(lines) + "\n"


REVIEW_FIELDS = {
    "is_talk": "true if this is a presentation (slides) given or prepared by the owner; false for figures, notes, posters, papers, templates",
    "owner_is_author": "true if Brett Viren is an author or presenter, false if it is someone else's talk, null if unknown",
    "title": "the talk title, plain text without LaTeX",
    "subtitle": "subtitle if one is used, else empty",
    "short_title": "short title if one is given, else empty",
    "authors": "list of author names as given",
    "venue": "meeting, workshop, conference, institution or event where given, if it can be determined, else empty",
    "event_url": "URL of the event (eg indico) if given, else empty",
    "slide_date": "date shown in the talk (title slide), ISO YYYY-MM-DD if possible, else empty",
    "summary": "2 to 4 plain sentences on what the talk is about and its main points, for a web listing and search",
    "keywords": "5 to 10 lower case keywords",
    "topic_slug": "a better short lower-case-hyphenated topic name if the derived topic is generic or wrong, else empty",
    "problems": "list of reasons this talk is ambiguous to migrate (eg unsure it is a talk, wrong date, someone else's), empty if none; these block migration",
    "notes": "list of non-blocking remarks, eg slide date differs from the path date, overlaps another talk",
}


# ---- state

class TalksError(Exception):
    pass


@dataclass
class State:
    dest: Path

    @property
    def dir(self) -> Path:
        return self.dest / "migration"

    @property
    def inventory_path(self) -> Path:
        return self.dir / "inventory.json"

    def review_path(self, cid: str) -> Path:
        return self.dir / "reviews" / (cid.replace("/", "__") + ".json")

    def digest_path(self, cid: str) -> Path:
        return self.dir / "digests" / (cid.replace("/", "__") + ".txt")

    def load(self) -> dict:
        if self.inventory_path.exists():
            return json.loads(self.inventory_path.read_text())
        return {"version": VERSION, "talks": {}}

    def save(self, inv: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.inventory_path.write_text(json.dumps(inv, indent=1, sort_keys=True) + "\n")

    def review(self, cid: str) -> dict | None:
        path = self.review_path(cid)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as err:
            raise TalksError(f"{path}: {err}") from None


def candidates(inv: dict) -> dict[str, Candidate]:
    return {cid: Candidate.from_dict(t["candidate"]) for cid, t in inv["talks"].items()}


def update(state: State, root: Path) -> tuple[dict, list[str], list[str]]:
    """Scan ROOT into the inventory.  Return it and the new and changed ids."""
    inv = state.load()
    known = candidates(inv)
    found = scan(root, known)
    new, changed = [], []
    for cid, cand in found.candidates.items():
        entry = inv["talks"].setdefault(cid, {"status": "found"})
        old = known.get(cid)
        if old is None:
            new.append(cid)
        elif old.fingerprint != cand.fingerprint:
            changed.append(cid)
            if entry.get("status") == "migrated":
                entry["status"] = "changed"
        entry["candidate"] = asdict(cand)
        entry.pop("gone", None)
    for cid, entry in inv["talks"].items():
        if cid not in found.candidates:
            entry["gone"] = True
    inv["scanned"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inv["source"] = str(root)
    state.save(inv)
    return inv, new, changed


def write_digests(state: State, root: Path, inv: dict, ids: list[str] | None = None) -> list[Path]:
    out = []
    for cid, cand in candidates(inv).items():
        if ids is not None and cid not in ids:
            continue
        path = state.digest_path(cid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(digest(root, cand))
        out.append(path)
    return out


def stamp_reviews(state: State, inv: dict) -> int:
    """Mark new reviews (those without one) with the fingerprint of the
    candidate they reviewed, so later changes to it make them stale."""
    n = 0
    for cid, entry in inv["talks"].items():
        rev = state.review(cid)
        if rev is not None and "fingerprint" not in rev:
            rev["fingerprint"] = entry["candidate"]["fingerprint"]
            state.review_path(cid).write_text(json.dumps(rev, indent=1, ensure_ascii=False) + "\n")
            n += 1
    return n


def needs_review(state: State, inv: dict) -> list[str]:
    """Ids lacking a review, or whose review predates a change."""
    out = []
    for cid, entry in inv["talks"].items():
        cand = Candidate.from_dict(entry["candidate"])
        if entry.get("gone") or cand.duplicate_of or "template" in cand.flags:
            continue
        rev = state.review(cid)
        if rev is None or rev.get("fingerprint") != cand.fingerprint:
            out.append(cid)
    return sorted(out)


# ---- migrating

def decide(cand: Candidate, review: dict | None) -> tuple[str, list[str]]:
    """Status a candidate should get and the problems blocking it."""
    if "template" in cand.flags:
        return "template", []
    if cand.duplicate_of:
        return "duplicate", []
    if review is None:
        return "unreviewed", []
    if review.get("is_talk") is False:
        return "not-a-talk", list(review.get("problems") or [])
    problems = list(review.get("problems") or [])
    if review.get("owner_is_author") is False:
        problems.append("someone else's talk")
    if not cand.group:
        problems.append("not in a group directory")
    if not cand.date:
        problems.append("no date found")
    if problems:
        return "ambiguous", problems
    return "ready", []


def copy_set(root: Path, cand: Candidate, others: list[Candidate]) -> list[str]:
    """Relative paths (under the candidate's dir) to copy for a talk: its
    directory less generated files, other talks' own files and any
    subdirectory holding another talk."""
    folder = root / cand.dir
    other_files = {Path(p).name for o in others if o.dir == cand.dir and o.id != cand.id
                   for p in o.files.values()}
    other_stems = {o.stem for o in others if o.dir == cand.dir and o.id != cand.id}
    other_dirs = {o.dir for o in others if o.dir != cand.dir and o.dir.startswith(cand.dir + "/" if cand.dir else "")}
    out = []
    for top, dirs, files in os.walk(folder):
        rel = os.path.relpath(top, folder)
        keep = []
        for d in sorted(dirs):
            sub = os.path.normpath(os.path.join(cand.dir, rel, d))
            if _skip_dir(d) or os.path.islink(os.path.join(top, d)):
                continue
            if any(od == sub or od.startswith(sub + "/") for od in other_dirs) and d not in OTHERS_DIRS:
                continue
            keep.append(d)
        dirs[:] = keep
        for name in sorted(files):
            if _generated(name):
                continue
            if rel == "." and (name in other_files or os.path.splitext(name)[0] in other_stems):
                continue
            path = Path(top) / name
            if not path.exists():
                continue
            out.append(os.path.normpath(os.path.join(rel, name)))
    return out


def talk_json(cand: Candidate, review: dict, copied: list[str]) -> dict:
    pdf = cand.pdf
    topic = review.get("topic_slug") or ""
    data = {
        "group": cand.group,
        "date": cand.date,
        "date_source": cand.date_source,
        "topic": slug(topic) if topic else slug(cand.topic),
        "series": cand.series,
        "title": review.get("title") or (pdf.title if pdf else "") or cand.stem,
        "subtitle": review.get("subtitle", ""),
        "short_title": review.get("short_title", ""),
        "authors": review.get("authors") or [],
        "venue": review.get("venue", ""),
        "event_url": review.get("event_url", ""),
        "slide_date": review.get("slide_date", ""),
        "summary": review.get("summary", ""),
        "notes": review.get("notes") or [],
        "keywords": review.get("keywords") or [],
        "kind": cand.kind,
        "pdf": Path(cand.files["pdf"]).name if "pdf" in cand.files else "",
        "pages": pdf.pages if pdf else 0,
        "aspect": round(pdf.width / pdf.height, 3) if pdf and pdf.height else 0,
        "sources": {r: Path(p).name for r, p in cand.files.items() if r != "pdf"},
        "origin": cand.id,
        "origin_dir": cand.dir,
        "origin_files": cand.files,
        "files": copied,
        "pdf_meta": {k: getattr(pdf, k) for k in ("title", "author", "subject", "keywords", "creator",
                                                  "producer", "created", "mtime", "md5")} if pdf else {},
        "source_date": cand.source_date,
        "flags": cand.flags,
        "migration": {"version": VERSION, "reviewed_by": review.get("reviewed_by", ""),
                      "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
    }
    return data


def migrate(state: State, root: Path, inv: dict, ids: list[str] | None = None,
            redo: bool = False, dry_run: bool = False) -> list[tuple[str, str, str]]:
    """Copy ready talks to their destination.  Return (id, status, dest)."""
    cands = candidates(inv)
    live = [c for cid, c in cands.items() if not inv["talks"][cid].get("gone") and not c.duplicate_of]
    out = []
    for cid, cand in sorted(cands.items()):
        entry = inv["talks"][cid]
        if ids is not None and cid not in ids:
            continue
        if entry.get("gone"):
            continue
        review = state.review(cid)
        if review and review.get("fingerprint") != cand.fingerprint:
            review = None  # stale
        status, problems = decide(cand, review)
        entry["problems"] = problems
        if status != "ready":
            if entry.get("status") != "migrated":
                entry["status"] = status
            out.append((cid, status, ""))
            continue
        if entry.get("status") == "migrated" and not redo and entry.get("version") == VERSION:
            out.append((cid, "migrated", entry.get("dest", "")))
            continue
        old_dest = entry.get("dest")
        dest = old_dest or cand.dest
        if review.get("topic_slug") and not old_dest:
            y, m, d = cand.date.split("-")
            base = f"{cand.group}/{y}/{m}/{d}/{slug(review['topic_slug'])}"
            used = {e.get("dest") for k, e in inv["talks"].items() if k != cid}
            used |= {c.dest for c in live if c.id != cid}
            dest, n = base, 1
            while dest in used:
                n += 1
                dest = f"{base}-{n}"
        copied = copy_set(root, cand, live)
        if not dry_run:
            target = state.dest / dest
            target.mkdir(parents=True, exist_ok=True)
            for rel in copied:
                src = root / cand.dir / rel
                to = target / rel
                to.parent.mkdir(parents=True, exist_ok=True)
                if to.is_symlink():
                    to.unlink()
                shutil.copy2(src, to)  # follows symlinks
            (target / "talk.json").write_text(json.dumps(talk_json(cand, review, copied), indent=1,
                                                         ensure_ascii=False) + "\n")
            entry.update(status="migrated", dest=dest, version=VERSION,
                         migrated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        out.append((cid, "would migrate" if dry_run else "migrated", dest))
    if not dry_run:
        state.save(inv)
    return out


# ---- report

def report(state: State, inv: dict) -> str:
    """MIGRATION.org: every candidate and its status, problems first."""
    rows = []
    for cid, entry in sorted(inv["talks"].items()):
        cand = Candidate.from_dict(entry["candidate"])
        review = state.review(cid) or {}
        status = "gone" if entry.get("gone") else entry.get("status", "found")
        rows.append((status, cid, cand, review, entry))
    counts: dict[str, int] = {}
    for status, *_ in rows:
        counts[status] = counts.get(status, 0) + 1
    out = ["#+title: Talks migration",
           f"#+date: {inv.get('scanned', '')}",
           "",
           f"Source: ~{inv.get('source', '').removeprefix(str(Path.home()))}/, "
           "written by ~myweb talks report~ from ~migration/inventory.json~ and ~migration/reviews/~.",
           "",
           "| status | count |", "|-"]
    out += [f"| {s} | {n} |" for s, n in sorted(counts.items())]
    sections = [
        ("ambiguous", "Ambiguous: guidance wanted",
         "Not migrated.  Say what to do with each; problems are from the scan and the review."),
        ("not-a-talk", "Judged not to be talks", "Not migrated.  Correct any that are talks."),
        ("unreviewed", "Not yet reviewed", ""),
        ("found", "Not yet reviewed", ""),
        ("changed", "Changed since migration", "Source changed; review and migrate again."),
        ("migrated", "Migrated", ""),
        ("duplicate", "Duplicates", "Same PDF (or same group, date and name) as another, not migrated."),
        ("template", "Templates", ""),
        ("gone", "Gone from the source", ""),
    ]
    done = set()
    for status, heading, note in sections:
        mine = [r for r in rows if r[0] == status]
        if not mine or heading in done:
            continue
        mine += [r for r in rows if r[0] != status and dict((s, h) for s, h, _ in sections).get(r[0]) == heading]
        done.add(heading)
        out += ["", f"* {heading} ({len(mine)})", ""]
        if note:
            out += [note, ""]
        for status_, cid, cand, review, entry in mine:
            title = review.get("title") or (cand.pdf.title if cand.pdf else "") or cand.stem
            if status_ == "migrated":
                out.append(f"- [X] ~{cid}~ → [[file:{entry.get('dest')}/talk.json][{entry.get('dest')}]] :: {title}")
                continue
            box = "- [ ]"
            out.append(f"{box} ~{cid}~ :: {title}")
            info = [f"{cand.kind}", f"date {cand.date or '?'} ({cand.date_source or '-'})",
                    f"would go to {cand.dest or '?'}"]
            if cand.duplicate_of:
                info = [f"duplicate of ~{cand.duplicate_of}~"]
            if cand.flags:
                info.append("flags: " + ", ".join(cand.flags))
            out.append("  " + "; ".join(info))
            for p in entry.get("problems") or []:
                out.append(f"  - {p}")
    return "\n".join(out) + "\n"
