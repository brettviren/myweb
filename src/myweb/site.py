"""The site: its taxa and the bundles (items) within them.

Every item is a directory, a Hugo leaf bundle, holding its org source and
its resources.  A taxon rendered by ox-hugo holds ``<slug>/<slug>.org``
which Emacs exports to ``<slug>/index.md``.  A taxon rendered by hugo holds
``<slug>/index.org`` which Hugo reads directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import orgmeta
from .orgsource import slugify  # noqa: F401  (re-exported)
from .config import Config, ConfigError, Taxon


@dataclass
class Bundle:
    taxon: Taxon
    path: Path

    @property
    def slug(self) -> str:
        return self.path.name

    @property
    def name(self) -> str:
        return f"{self.taxon.name}/{self.slug}"

    @property
    def source(self) -> Path:
        if self.taxon.render == "hugo":
            return self.path / "index.org"
        return self.path / f"{self.slug}.org"

    @property
    def section(self) -> str:
        return self.taxon.section

    @property
    def source_name(self) -> str:
        """The name the org source is published under, beside index.html."""
        return f"{self.slug}.org"

    @property
    def output(self) -> Path | None:
        """The file ox-hugo writes, None for Hugo-native bundles."""
        if self.taxon.render == "hugo":
            return None
        return self.path / "index.md"

    @property
    def content_rel(self) -> str:
        """Path relative to the content directory, eg posts/slug."""
        return f"{self.taxon.section}/{self.slug}"

    @property
    def url_path(self) -> str:
        """The page path below the site base URL, eg posts/slug/."""
        return f"{self.content_rel}/"

    def meta(self) -> orgmeta.Meta:
        return orgmeta.read(self.source)

    def stale(self) -> bool:
        """True if the ox-hugo export is missing or older than its source."""
        out = self.output
        if out is None:
            return False
        return not out.exists() or out.stat().st_mtime < self.source.stat().st_mtime


def bundles(cfg: Config, taxa: list[str] | None = None) -> list[Bundle]:
    out = []
    for name, taxon in cfg.taxa.items():
        if taxa and name not in taxa:
            continue
        if not taxon.source.is_dir():
            continue
        for path in sorted(p for p in taxon.source.iterdir() if p.is_dir()):
            bundle = Bundle(taxon, path)
            if bundle.source.exists():
                out.append(bundle)
    return out


def find(cfg: Config, spec: str) -> Bundle:
    """Find one bundle by "slug", "taxon/slug" or a path in or of the bundle."""
    path = Path(spec).expanduser()
    if path.exists():
        path = path.resolve()
        if path.is_file():
            path = path.parent
        for taxon in cfg.taxa.values():
            if path.parent == taxon.source.resolve():
                bundle = Bundle(taxon, path)
                if bundle.source.exists():
                    return bundle
        raise ConfigError(f"{spec} is not a bundle of any taxon")
    taxon_name, _, slug = spec.rpartition("/")
    hits = [
        b
        for b in bundles(cfg, [taxon_name] if taxon_name else None)
        if b.slug == slug
    ]
    if not hits:
        raise ConfigError(f"no item {spec!r}")
    if len(hits) > 1:
        raise ConfigError(
            f"{spec!r} is ambiguous: {', '.join(b.name for b in hits)}"
        )
    return hits[0]
