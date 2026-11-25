"""Who may read a page: its access realm.

A realm is a name and the Apache ``Require`` that admits its readers.
Public pages are in the "public" realm, which requires nothing.  A
protected page is in the realm its ``#+access:`` names (default
"protected") among the target's ``realms``, eg::

    [target.work.realms]
    protected = "valid-user"
    dune = "user alice bob"

Everything guarded is guarded by the one ``.htaccess`` text made here, so
a page and the search index holding it always admit the same readers.
Search keeps one index per realm and never mixes realms in a file, so a
reader admitted to one realm learns nothing of another.  Unlisted pages
are in the public realm but are in no index: being found only by their
URL is what unlisted means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import Target
from .orgmeta import Meta

PUBLIC = "public"

HTACCESS = """\
# Written by myweb: {what} is in access realm "{realm}".
AuthType Basic
AuthName "{realm}"
AuthUserFile {htpasswd}
Require {require}
# Files sections merge after directories, so a FilesMatch granting file
# types higher up (see grant) would otherwise override the Require above.
# A server's "Satisfy Any" would let a granted host admit without login.
<FilesMatch "">
  Require {require}
  <IfModule mod_access_compat.c>
    Satisfy All
  </IfModule>
</FilesMatch>
<IfModule mod_access_compat.c>
  Satisfy All
</IfModule>
"""

#: Both 2.4 Require and, for a server denying by the old Order/Deny of
#: mod_access_compat, which Require can not lift, an Allow.
GRANT = """\
# Written by myweb: the server admits only some file types; admit these,
# never dotfiles (.htaccess, .htpasswd, drop's .htdrop-*.json).
<FilesMatch "^[^.].*\\.({types})$">
  Require all granted
  <IfModule mod_access_compat.c>
    Order deny,allow
    Allow from all
  </IfModule>
</FilesMatch>
"""


@dataclass(frozen=True)
class Realm:
    name: str
    #: The Apache Require argument, "" for the public realm.
    require: str = ""

    @property
    def public(self) -> bool:
        return not self.require


def page_realm(target: Target, meta: Meta) -> Realm | None:
    """The realm of a page on TARGET, None if TARGET has no such realm."""
    if not meta.access:
        return Realm(PUBLIC)
    if meta.access not in target.realms:
        return None
    return Realm(meta.access, target.realms[meta.access])


def index_realm(target: Target, meta: Meta) -> Realm | None:
    """The realm whose search index holds a page, None for no index."""
    if meta.visibility == "unlisted":
        return None
    return page_realm(target, meta)


def htaccess(target: Target, realm: Realm, what: str) -> str:
    if realm.public:
        raise ValueError("the public realm needs no .htaccess")
    if not target.htpasswd:
        raise ValueError(f"target {target.name} has no htpasswd for realm {realm.name}")
    return HTACCESS.format(
        what=what, realm=realm.name, require=realm.require,
        htpasswd=Path(target.htpasswd).expanduser(),
    )


def grant(types: list[str]) -> str:
    """Top .htaccess text admitting files of the TYPES (extensions)."""
    return GRANT.format(types="|".join(re.escape(t) for t in sorted(set(types))))


def file_types(root: Path) -> list[str]:
    """The extensions of the non-hidden files under ROOT."""
    return sorted({p.suffix[1:] for p in root.rglob("*")
                   if p.is_file() and p.suffix and not p.name.startswith(".")})


def defaults(settings: dict, group: str, base: dict) -> dict:
    """Audience, visibility and access of a generated page (a talk, an
    artifact): BASE, then SETTINGS, then SETTINGS["group"][GROUP]."""
    out = dict(base)
    out.update({k: v for k, v in settings.items() if k in out})
    out.update({k: v for k, v in (settings.get("group", {}).get(group) or {}).items() if k in out})
    return out
