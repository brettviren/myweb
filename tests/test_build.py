"""Integration: export with Emacs, build with hugo, deploy to a directory."""

import shutil
import subprocess

import pytest

from conftest import add_post
from myweb import check, deploy, export
from myweb.site import bundles, find
from myweb.config import DEFAULT_HUGO, DEFAULT_EMACS_LOAD_PATH, expand

LAYOUTS = {
    "baseof.html": '<html><body>{{ block "main" . }}{{ end }}</body></html>',
    "home.html": '{{ define "main" }}{{ range site.RegularPages }}<a href="{{ .RelPermalink }}">{{ .Title }}</a>{{ end }}{{ end }}',
    "section.html": '{{ define "main" }}{{ range .Pages }}<a href="{{ .RelPermalink }}">{{ .Title }}</a>{{ end }}{{ end }}',
    "page.html": '{{ define "main" }}{{ .Content }}<a href="{{ site.Home.RelPermalink }}">home</a>{{ end }}',
}
HUGO_TOML = 'baseURL = "http://example.org/~me/"\ndisableKinds = ["taxonomy", "term"]\n[security]\nallowContent = ["! ^text/html$"]\n'


def have_hugo():
    try:
        return subprocess.run([*DEFAULT_HUGO, "version"], capture_output=True).returncode == 0
    except OSError:
        return False


def have_ox_hugo():
    return shutil.which("emacs") and all(expand(p).is_dir() for p in DEFAULT_EMACS_LOAD_PATH)


@pytest.fixture
def hugo_site(cfg, site):
    (site / "layouts").mkdir()
    for name, text in LAYOUTS.items():
        (site / "layouts" / name).write_text(text)
    (site / "config" / "_default").mkdir(parents=True)
    (site / "config" / "_default" / "hugo.toml").write_text(HUGO_TOML)
    cfg.emacs_load_path = [expand(p) for p in DEFAULT_EMACS_LOAD_PATH]
    return cfg


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
