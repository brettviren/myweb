"""Summaries of items, for the status command."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .config import Config
from .site import Bundle, bundles


@dataclass
class Row:
    bundle: Bundle
    title: str
    draft: bool
    todo: str
    deadline: date | None
    words: int
    figures: int
    audience: str
    visibility: str
    modified: datetime
    stale: bool


def rows(
    cfg: Config,
    taxa: list[str] | None = None,
    tag: str | None = None,
    drafts_only: bool = True,
) -> list[Row]:
    out = []
    for bundle in bundles(cfg, taxa):
        meta = bundle.meta()
        if drafts_only and not meta.draft:
            continue
        if tag and tag not in meta.tags:
            continue
        mtime = max(p.stat().st_mtime for p in bundle.path.iterdir() if p.is_file())
        out.append(
            Row(
                bundle=bundle,
                title=meta.title,
                draft=meta.draft,
                todo=meta.todo,
                deadline=meta.deadline,
                words=meta.words,
                figures=meta.figures,
                audience=meta.audience,
                visibility=meta.visibility,
                modified=datetime.fromtimestamp(mtime),
                stale=bundle.stale(),
            )
        )
    out.sort(key=lambda r: (r.deadline or date.max, r.modified))
    return out
