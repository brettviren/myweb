"""Integration: export with Emacs, build with hugo, deploy to a directory."""

import pytest

from conftest import add_post, have_hugo, have_ox_hugo
from myweb import authoring, check, deploy, export, hugo
from myweb.site import bundles, find

@pytest.mark.emacs
@pytest.mark.skipif(not have_ox_hugo(), reason="needs emacs with ox-hugo")
def test_export_bundle_relative(hugo_site):
    cfg = hugo_site
    path = add_post(cfg, "pic")
    (path / "fig.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    with open(path / "pic.org", "a") as fp:
        fp.write("\n[[file:fig.svg]]\n")
    done = export.export(cfg, bundles(cfg))
    assert [b.slug for b in done] == ["pic"]
    md = (path / "index.md").read_text()
    assert 'src="fig.svg"' in md
    assert not export.export(cfg, bundles(cfg))


@pytest.mark.emacs
@pytest.mark.hugo
@pytest.mark.skipif(not (have_hugo() and have_ox_hugo()), reason="needs hugo and ox-hugo")
def test_build_deploy_and_check(hugo_site, tmp_path):
    cfg = hugo_site
    add_post(cfg, "pub")
    add_post(cfg, "secret", visibility="protected")
    add_post(cfg, "work", audience="work")
    dest = tmp_path / "public_html"
    (dest / "drop").mkdir(parents=True)
    (dest / "drop" / "keepme").write_text("x")

    result = deploy.build(cfg, cfg.target("personal"), dest=dest)
    assert (dest / "posts" / "pub" / "index.html").exists()
    assert not (dest / "posts" / "secret").exists()
    assert not (dest / "posts" / "work").exists()
    assert (dest / "drop" / "keepme").exists()
    assert result.synced == [str(dest)]

    deploy.build(cfg, cfg.target("all"), dest=dest)
    htaccess = dest / "posts" / "secret" / ".htaccess"
    assert "AuthUserFile /srv/htpasswd" in htaccess.read_text()
    assert "secret" not in (dest / "posts" / "index.html").read_text()

    report = check.check(cfg, find(cfg, "pub"), cfg.target("all"))
    assert report.ok, report.text()


@pytest.mark.emacs
@pytest.mark.hugo
@pytest.mark.skipif(not (have_hugo() and have_ox_hugo()), reason="needs hugo and ox-hugo")
def test_sources_and_anchors(hugo_site, tmp_path):
    cfg = hugo_site
    path = add_post(cfg, "sec")
    with open(path / "sec.org", "a") as fp:
        fp.write("\n* First Part\nOne.\n* Private :noexport:\nsecret\n")
    note = cfg.taxa["notes"].source / "n1"
    note.mkdir()
    (note / "index.org").write_text("#+title: N1\n#+date: 2026-01-03\n\n* A Note Part\nTwo.\n")
    for bundle in bundles(cfg):
        authoring.ensure_ids(bundle)
    assert ":CUSTOM_ID: first-part" in (path / "sec.org").read_text()

    dest = tmp_path / "public_html"
    deploy.build(cfg, cfg.target("personal"), dest=dest)
    assert 'id="first-part"' in (dest / "posts" / "sec" / "index.html").read_text()
    assert 'id="a-note-part"' in (dest / "notes" / "n1" / "index.html").read_text()
    published = (dest / "posts" / "sec" / "sec.org").read_text()
    assert "First Part" in published and "secret" not in published
    assert (dest / "notes" / "n1" / "n1.org").exists()
    assert "AddType" in (dest / ".htaccess").read_text()
    assert 'source = "sec.org"' in hugo.config_text(hugo.plan(cfg, cfg.target("personal")))


@pytest.mark.emacs
@pytest.mark.skipif(not have_ox_hugo(), reason="needs emacs with ox-hugo")
def test_publish(hugo_site, site):
    from conftest import git
    from myweb import authoring

    cfg = hugo_site
    cfg.agenda = "none"
    add_post(cfg, "wip", draft="true")
    done = authoring.publish(cfg, find(cfg, "wip"), deploy_it=False)
    bundle = find(cfg, "wip")
    assert not bundle.meta().draft
    assert (bundle.path / "index.md").exists()
    assert done.tag == "posts/wip/v1"
    assert (bundle.path / "version.txt").exists()
    assert git(site, "status", "--porcelain", "--", "content") == ""
    again = authoring.publish(cfg, bundle, deploy_it=False)
    assert again.tag == "posts/wip/v2"
