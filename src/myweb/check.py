"""Pre-publication checks of one item.

The item is exported and the site is built, drafts included, to a check
stage.  The item's pages are then examined.  The report is written to
``.check.txt`` in the bundle, which hugo and git ignore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import export, hugo
from .config import Config, Target, xdg_dir
from .site import Bundle

REPORT = ".check.txt"


@dataclass
class Report:
    bundle: Bundle
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def text(self) -> str:
        lines = [f"myweb check {self.bundle.name} at {datetime.now():%Y-%m-%d %H:%M}"]
        for kind, items in (("error", self.errors), ("warning", self.warnings), ("note", self.notes)):
            lines += [f"{kind}: {item}" for item in items]
        lines.append("result: " + ("ok" if self.ok else "FAILED"))
        return "\n".join(lines) + "\n"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        for key, val in attrs:
            if val and key in ("href", "src") and tag in ("a", "img", "link", "script", "source", "iframe"):
                self.links.append(val)


def links(html: str) -> list[str]:
    parser = _Links()
    parser.feed(html)
    return parser.links


def resolve(stage: Path, page: Path, base_path: str, link: str) -> Path | None:
    """Return the stage file a local link names, None for external links."""
    parts = urlsplit(link)
    if parts.scheme or parts.netloc or link.startswith(("#", "mailto:")):
        return None
    path = unquote(parts.path)
    if not path:
        return None
    if path.startswith("/"):
        if not path.startswith(base_path):
            return stage / "__outside_base__" / path.lstrip("/")
        target = stage / path[len(base_path):]
    else:
        target = page.parent / path
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target


def check(cfg: Config, bundle: Bundle, target: Target) -> Report:
    report = Report(bundle)
    meta = bundle.meta()
    report.errors += meta.problems()
    for line in meta.missing_results:
        report.warnings.append(f"source block at line {line} exports results but has none")
    if meta.draft:
        report.notes.append("is a draft")
    if meta.audience not in target.audience:
        report.warnings.append(f"audience {meta.audience} is not served by target {target.name}")

    try:
        export.export(cfg, [bundle], force=True)
    except export.ExportError as err:
        report.errors.append(f"export failed: {err}")
        return report

    plan = hugo.plan(cfg, target, drafts=True)
    stage = xdg_dir("cache") / "check" / target.name
    try:
        log = hugo.build(cfg, plan, stage, drafts=True)
    except hugo.HugoError as err:
        report.errors.append(f"hugo failed: {err}")
        return report
    report.warnings += [l for l in log.splitlines() if l.startswith("WARN")]

    pagedir = stage / bundle.url_path
    if not pagedir.is_dir():
        report.errors.append(f"no page built at {bundle.url_path} for target {target.name}")
        return report
    base_path = urlsplit(hugo.base_url(cfg, plan)).path or "/"
    for page in sorted(pagedir.rglob("*.html")):
        for link in links(page.read_text(errors="replace")):
            path = resolve(stage, page, base_path, link)
            if path is not None and not path.exists():
                report.errors.append(f"broken link in {page.relative_to(stage)}: {link}")
    report.notes.append(f"built to {pagedir}")
    return report


def save(report: Report) -> Path:
    path = report.bundle.path / REPORT
    path.write_text(report.text())
    return path
