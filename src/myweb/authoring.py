"""Creating and publishing items."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from string import Template

from . import agenda, deploy, export, orgmeta, vcs, version
from .config import Config, ConfigError, Taxon
from .site import Bundle, slugify


@dataclass
class Created:
    bundle: Bundle
    in_agenda: bool = False


def archetype(cfg: Config, taxon: Taxon) -> Template:
    adir = cfg.site / "archetypes"
    for name in (f"{taxon.name}.org", f"default-{taxon.render}.org", "default.org"):
        if (adir / name).exists():
            return Template((adir / name).read_text())
    raise ConfigError(f"no archetype for {taxon.name} in {adir}")


def org_date(day: date, active: bool = True) -> str:
    stamp = f"{day.isoformat()} {day.strftime('%a')}"
    return f"<{stamp}>" if active else f"[{stamp}]"


def new(
    cfg: Config,
    taxon_name: str,
    title: str,
    tags: list[str] | None = None,
    deadline: date | None = None,
    body: str = "",
    slug: str | None = None,
    today: date | None = None,
) -> Created:
    taxon = cfg.taxon(taxon_name)
    slug = slug or slugify(title)
    if not slug:
        raise ConfigError(f"can not make a slug from {title!r}")
    bundle = Bundle(taxon, taxon.source / slug)
    if bundle.path.exists():
        raise ConfigError(f"{bundle.name} already exists: {bundle.path}")
    today = today or date.today()
    text = archetype(cfg, taxon).safe_substitute(
        title=title,
        date=today.isoformat(),
        slug=slug,
        section=taxon.section,
        tags=" ".join(tags or []),
        body=body,
    )
    if deadline:
        text = text.rstrip("\n") + (
            f'\n\n* TODO Write "{title}"{" " * 8}:noexport:\n'
            f"DEADLINE: {org_date(deadline)}\n"
        )
    bundle.path.mkdir(parents=True)
    bundle.source.write_text(text)
    created = Created(bundle)
    if deadline:
        created.in_agenda = agenda.add(cfg, bundle.source)
    return created


@dataclass
class Published:
    bundle: Bundle
    tag: str = ""
    stamps: list[version.Stamp] = field(default_factory=list)
    results: list[deploy.Result] = field(default_factory=list)


def _set_draft(bundle: Bundle, draft: bool) -> None:
    key = "draft" if bundle.taxon.render == "hugo" else "hugo_draft"
    text = bundle.source.read_text()
    text = orgmeta.set_keyword(text, key, "true" if draft else "false")
    if not draft:
        text = orgmeta.close_todos(text)
    bundle.source.write_text(text)


def publish(
    cfg: Config,
    bundle: Bundle,
    targets: list[str] | None = None,
    commit: bool = True,
    deploy_it: bool = True,
) -> Published:
    """Flip draft, export, commit, stamp, tag, build and deploy."""
    site = cfg.site
    result = Published(bundle)
    problems = bundle.meta().problems()
    if problems:
        raise ConfigError(f"{bundle.name}: " + "; ".join(problems))
    _set_draft(bundle, False)
    export.export(cfg, [bundle], force=True)
    agenda.remove(cfg, bundle.source)
    if commit:
        vcs.save(site, f"publish {bundle.name}", [bundle.path])
        result.stamps = [version.stamp(site, bundle.path), version.stamp(site, site)]
        changed = [s.path for s in result.stamps if s.changed]
        if changed:
            vcs.save(site, f"version stamps for {bundle.name}", changed)
        if bundle.taxon.tag:
            prefix = f"{bundle.name}/v"
            num = len(vcs.tags(site, prefix + "*")) + 1
            result.tag = f"{prefix}{num}"
            vcs.tag(site, result.tag, f"publish {bundle.name} revision {num}")
    if deploy_it:
        for name in targets or cfg.publish_targets:
            result.results.append(deploy.build(cfg, cfg.target(name)))
    return result
