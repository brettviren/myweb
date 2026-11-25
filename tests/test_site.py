from datetime import date

import pytest

from conftest import add_post, git
from myweb import authoring, hugo, setup, version
from myweb.config import ConfigError
from myweb.site import bundles, find, slugify


def test_slugify():
    assert slugify("Héllo, World!  Again") == "hello-world-again"


def test_config(cfg):
    assert cfg.taxa["posts"].section == "posts"
    assert cfg.taxa["notes"].render == "hugo"
    assert cfg.target("personal").auth is False
    with pytest.raises(ConfigError):
        cfg.target("nope")


def test_find(cfg):
    path = add_post(cfg, "alpha")
    assert find(cfg, "alpha").path == path
    assert find(cfg, "posts/alpha").path == path
    assert find(cfg, str(path / "alpha.org")).path == path
    with pytest.raises(ConfigError):
        find(cfg, "beta")


def test_new(cfg):
    made = authoring.new(
        cfg, "posts", "My New Post", tags=["x"], deadline=date(2026, 3, 4),
        body="Hello.", today=date(2026, 3, 1),
    )
    text = made.bundle.source.read_text()
    assert made.bundle.name == "posts/my-new-post"
    assert "#+hugo_bundle: my-new-post" in text
    assert "#+date: 2026-03-01" in text
    assert "DEADLINE: <2026-03-04 Wed>" in text
    assert made.bundle.meta().draft
    with pytest.raises(ConfigError):
        authoring.new(cfg, "posts", "My New Post")


def test_plan_and_config(cfg):
    add_post(cfg, "pub")
    add_post(cfg, "work", audience="work")
    add_post(cfg, "hidden", visibility="unlisted")
    add_post(cfg, "secret", visibility="protected")
    add_post(cfg, "wip", draft="true")

    plan = hugo.plan(cfg, cfg.target("personal"))
    excluded = {b.slug: why for b, why in plan.excluded}
    assert set(excluded) == {"work", "secret", "wip"}
    assert [b.slug for b, _ in plan.hidden] == ["hidden"]
    text = hugo.config_text(plan)
    assert '"! posts/secret/**"' in text
    assert 'path = "/posts/hidden"' in text

    plan = hugo.plan(cfg, cfg.target("all"), drafts=True)
    assert plan.excluded == []
    assert {b.slug for b in plan.protected} == {"secret"}


def test_version_stamp(cfg, site):
    one = add_post(cfg, "one")
    two = add_post(cfg, "two")
    git(site, "add", ".")
    git(site, "commit", "-q", "-m", "c1")
    s1 = version.stamp(site, one)
    assert s1.changed and s1.new
    version.stamp(site, two)
    git(site, "add", ".")
    git(site, "commit", "-q", "-m", "stamps")
    # Committing stamps changes nothing they cover.
    assert not version.stamp(site, one, write=False).changed

    (two / "two.org").write_text("#+title: Two changed\n")
    assert version.stamp(site, two, write=False).new.split("\n")[0].endswith("-dirty")
    git(site, "commit", "-q", "-am", "c2")
    assert not version.stamp(site, one, write=False).changed
    assert version.stamp(site, two, write=False).changed


def test_setup_text(cfg):
    units = setup.systemd(cfg, "all", "hourly", cfg.site / "units")
    assert [u.path.suffix for u in units] == [".service", ".timer", ".path"]
    assert "deploy all" in units[0].text
    assert "PathChanged=" in units[2].text
    hooks = setup.git_hooks(cfg, "all")
    paths = setup.write(hooks)
    assert all(p.stat().st_mode & 0o100 for p in paths)
    assert setup.cron_line("all", "@hourly").startswith("@hourly ")


def test_bundles_skips_dirs_without_source(cfg):
    add_post(cfg, "ok")
    (cfg.taxa["posts"].source / "empty").mkdir()
    assert [b.slug for b in bundles(cfg)] == ["ok"]


def test_plan_uses_own_config(cfg):
    from myweb import hugo
    tgt = cfg.target("personal")
    paths = {use: hugo.write_config(hugo.plan(cfg, tgt, use=use)) for use in ("build", "check", "server")}
    assert len(set(paths.values())) == 3
    assert paths["build"].name == "personal.toml"
