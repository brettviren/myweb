"""Search indexes never hold a page for readers who could not read it."""

import json

import pytest

from conftest import add_post, have_hugo, have_ox_hugo
from myweb import access, deploy, siteindex
from myweb.config import ConfigError, Target, _target
from myweb.orgmeta import parse

SEARCH = """{{ define "main" }}<article><h1>Search</h1>
<div id="search-results" data-indexes="index.json"></div><div id="search-realms"></div></article>{{ end }}"""


def test_realms():
    tgt = Target("t", "t", htpasswd="/pw", realms={"protected": "valid-user", "dune": "user alice bob"})
    meta = lambda kw: parse("#+title: x\n" + kw + "\n")
    assert access.page_realm(tgt, meta("")).public
    assert access.index_realm(tgt, meta("#+visibility: unlisted")) is None
    assert access.page_realm(tgt, meta("#+visibility: protected")).require == "valid-user"
    dune = access.page_realm(tgt, meta("#+visibility: protected\n#+access: dune"))
    assert dune == access.Realm("dune", "user alice bob")
    assert access.page_realm(tgt, meta("#+visibility: protected\n#+access: nope")) is None
    assert "Require user alice bob" in access.htaccess(tgt, dune, "x")
    # #+access means nothing on a public page.
    assert access.page_realm(tgt, meta("#+access: dune")).public
    with pytest.raises(ConfigError):
        _target("t", {"realms": {"public": "valid-user"}})


def test_page_text():
    html = ('<html><header class="site"><h1>Site</h1></header><article><header><h1>The '
            '<code>T</code></h1><p class="meta">2026</p></header><p class="notice">Draft.</p>'
            '<h2 id="a">A <a class="anchor" href="#a">#</a></h2><div class="toc">TOC</div>'
            '<p>Body &amp; <em>more</em>.</p><script>x()</script></article><footer>f</footer>')
    assert siteindex.page_text(html) == ("The T", "A Body & more .")


@pytest.mark.emacs
@pytest.mark.hugo
@pytest.mark.skipif(not (have_hugo() and have_ox_hugo()), reason="needs hugo and ox-hugo")
def test_indexes_by_realm(hugo_site, tmp_path):
    cfg = hugo_site
    (cfg.site / "layouts" / "search.html").write_text(SEARCH)
    (cfg.site / "content" / "search.md").write_text("---\ntitle: Search\nlayout: search\n---\n")
    tgt = cfg.target("all")
    tgt.realms["dune"] = "user alice"
    add_post(cfg, "pub")
    add_post(cfg, "hush", visibility="unlisted")
    add_post(cfg, "prot", visibility="protected")
    path = add_post(cfg, "duneonly", visibility="protected")
    text = (path / "duneonly.org").read_text().replace("#+visibility:", "#+access: dune\n#+visibility:")
    (path / "duneonly.org").write_text(text)

    dest = tmp_path / "www"
    deploy.deploy(cfg, tgt, dest=dest)
    load = lambda p: [e["url"] for e in json.loads((dest / p).read_text())["pages"]]
    assert load("search/index.json") == ["posts/pub/"]
    assert load("search/protected/index.json") == ["posts/prot/"]
    assert load("search/dune/index.json") == ["posts/duneonly/"]
    assert "Require valid-user" in (dest / "search/protected/.htaccess").read_text()
    assert "Require user alice" in (dest / "search/dune/.htaccess").read_text()
    assert "Require user alice" in (dest / "posts/duneonly/.htaccess").read_text()
    assert 'data-indexes="../index.json index.json"' in (dest / "search/dune/index.html").read_text()
    assert 'href="dune/"' in (dest / "search/index.html").read_text()

    # A target without the dune realm does not build the page at all.
    del tgt.realms["dune"]
    deploy.deploy(cfg, tgt, dest=dest)
    assert not (dest / "posts/duneonly").exists() and not (dest / "search/dune").exists()


def test_check_catches_leak(tmp_path):
    from myweb.hugo import Plan
    tgt = Target("t", "t", htpasswd="/pw")
    (tmp_path / "search" / "protected").mkdir(parents=True)
    (tmp_path / "search" / "index.json").write_text(json.dumps({"realm": "public", "pages": [{"url": "posts/x/"}]}))
    (tmp_path / "search" / "protected" / "index.json").write_text(json.dumps({"realm": "protected", "pages": []}))
    problems = siteindex.check(tgt, Plan(tgt), tmp_path)
    assert any("posts/x/ must not be in" in p for p in problems)
    assert any("not guarded" in p for p in problems)
