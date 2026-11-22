import subprocess
from pathlib import Path

import pytest

from myweb.config import load

MYWEB_TOML = """\
[taxon.posts]
render = "ox-hugo"
tag = true

[taxon.notes]
render = "hugo"

[target.all]
environment = "all"
audience = ["personal", "work", "both"]
auth = true
htpasswd = "/srv/htpasswd"

[target.personal]
environment = "personal"
audience = ["personal", "both"]
"""

POST = """\
#+title: {title}
#+date: 2026-01-02
#+hugo_base_dir: ../../..
#+hugo_section: posts
#+hugo_bundle: {slug}
#+export_file_name: index
#+hugo_draft: {draft}
#+audience: {audience}
#+visibility: {visibility}

Body of {title}.
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A minimal site, a git repo, with no user config."""
    root = tmp_path / "site"
    (root / "content" / "posts").mkdir(parents=True)
    (root / "content" / "notes").mkdir(parents=True)
    (root / "archetypes").mkdir()
    (root / "myweb.toml").write_text(MYWEB_TOML)
    (root / "archetypes" / "default.org").write_text(
        "#+title: $title\n#+date: $date\n#+hugo_section: $section\n"
        "#+hugo_bundle: $slug\n#+hugo_tags: $tags\n#+hugo_draft: true\n\n$body\n"
    )
    for var in ("XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(var, str(tmp_path / var.lower()))
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    return root


@pytest.fixture
def cfg(site, tmp_path):
    return load(path=tmp_path / "none.toml", site=site, env={})


def add_post(cfg, slug, title=None, draft="false", audience="both", visibility="public"):
    path = cfg.taxa["posts"].source / slug
    path.mkdir(parents=True)
    (path / f"{slug}.org").write_text(
        POST.format(
            title=title or slug.title(), slug=slug, draft=draft,
            audience=audience, visibility=visibility,
        )
    )
    return path
