import json

import pytest

from conftest import add_post, have_hugo, have_ox_hugo
from myweb import deploy, hugo, talkpages


def add_talk(root, dest, **kw):
    path = root / dest
    path.mkdir(parents=True)
    group = dest.split("/")[0]
    data = {"group": group, "date": "-".join(dest.split("/")[1:4]), "topic": dest.split("/")[-1],
            "title": f"Talk {dest}", "summary": f"About {dest}.", "keywords": ["k"], "pdf": "t.pdf", **kw}
    (path / "talk.json").write_text(json.dumps(data))
    (path / "t.pdf").write_bytes(b"%PDF-1.4 " + dest.encode())
    return path


def test_load_defaults(tmp_path):
    add_talk(tmp_path, "dune/2023/06/06/fw")
    add_talk(tmp_path, "edg/2020/01/02/x", visibility="protected", access="edg")
    add_talk(tmp_path, "llm/2025/01/01/y")
    settings = {"audience": "both", "group": {"llm": {"visibility": "unlisted"}}}
    talks = {t.dest: t for t in talkpages.load(tmp_path, settings)}
    assert talks["dune/2023/06/06/fw"].meta.audience == "both"
    assert talks["dune/2023/06/06/fw"].meta.visibility == "public"
    assert talks["edg/2020/01/02/x"].meta.access == "edg"
    assert talks["llm/2025/01/01/y"].meta.visibility == "unlisted"
    fm = talkpages.front_matter(talks["llm/2025/01/01/y"], "unlisted")
    assert fm["build"] == {"list": "never"} and fm["groups"] == []


@pytest.mark.emacs
@pytest.mark.hugo
@pytest.mark.skipif(not (have_hugo() and have_ox_hugo()), reason="needs hugo and ox-hugo")
def test_build_talks(hugo_site, tmp_path):
    cfg = hugo_site
    conf = cfg.site / "config" / "_default" / "hugo.toml"
    conf.write_text(conf.read_text().replace('disableKinds = ["taxonomy", "term"]\n', "")
                    + '[taxonomies]\ngroup = "groups"\n')
    (cfg.site / "layouts" / "term.html").write_text(
        '{{ define "main" }}{{ range .Pages }}<a href="{{ .RelPermalink }}">{{ .Title }}</a>{{ end }}{{ end }}')
    (cfg.site / "layouts" / "taxonomy.html").write_text('{{ define "main" }}terms{{ end }}')
    cfg.talks = {"audience": "both"}
    root = cfg.talks_dest
    add_talk(root, "dune/2023/06/06/fw")
    add_talk(root, "dune/2023/07/01/secret", visibility="protected")
    add_talk(root, "edg/2020/01/02/mine", audience="personal")
    add_post(cfg, "pub")
    dest = tmp_path / "www"

    deploy.deploy(cfg, cfg.target("all"), dest=dest)
    assert (dest / "talks/dune/2023/06/06/fw/t.pdf").read_bytes().endswith(b"fw")
    assert "Require valid-user" in (dest / "talks/dune/2023/07/01/secret/.htaccess").read_text()
    listing = (dest / "talks/index.html").read_text()
    assert "fw/" in listing and "secret" not in listing
    assert "secret" not in (dest / "groups/dune/index.html").read_text()
    public = json.loads((dest / "search/index.json").read_text())["pages"]
    assert "talks/dune/2023/06/06/fw/" in [p["url"] for p in public]
    assert all("secret" not in p["url"] for p in public)
    assert [p["url"] for p in json.loads((dest / "search/protected/index.json").read_text())["pages"]] \
        == ["talks/dune/2023/07/01/secret/"]
    fw = next(p for p in public if p["url"].endswith("fw/"))
    assert fw["group"] == "dune" and fw["summary"] == "About dune/2023/06/06/fw."

    # The work audience target gets neither the personal talk nor, lacking
    # auth, the protected one.
    plan = hugo.plan(cfg, cfg.target("personal"))
    assert [t.dest for t in plan.talks] == ["edg/2020/01/02/mine", "dune/2023/06/06/fw"] or \
        sorted(t.dest for t in plan.talks) == ["dune/2023/06/06/fw", "edg/2020/01/02/mine"]
    deploy.deploy(cfg, cfg.target("personal"), dest=tmp_path / "p")
    assert not (tmp_path / "p/talks/dune/2023/07/01/secret").exists()

    # A newly migrated talk appears on the next build.
    add_talk(root, "dune/2024/01/01/new")
    deploy.deploy(cfg, cfg.target("all"), dest=dest)
    assert (dest / "talks/dune/2024/01/01/new/index.html").exists()


def test_plan_without_talks(cfg):
    add_talk(cfg.talks_dest, "dune/2023/06/06/fw")
    cfg.talks = {"audience": "both"}
    tgt = cfg.target("personal")
    assert [t.dest for t in hugo.plan(cfg, tgt).talks] == ["dune/2023/06/06/fw"]
    tgt.talks = False
    assert hugo.plan(cfg, tgt).talks == []
