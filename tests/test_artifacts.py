import json

import pytest

from conftest import add_post, have_hugo, have_ox_hugo
from myweb import artifacts, deploy, hugo


def add_artifact(root, dest, files=None, **meta):
    path = root / dest
    path.mkdir(parents=True)
    meta.setdefault("title", f"Artifact {dest}")
    meta.setdefault("date", "2026-11-01")
    lines = [f"{k} = {json.dumps(v)}" for k, v in meta.items()]
    (path / artifacts.META).write_text("\n".join(lines) + "\n")
    for name, text in (files or {"index.html": f"<html><title>{dest}</title><body>{dest}</body></html>"}).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    return path


def test_load_defaults_and_groups(tmp_path):
    add_artifact(tmp_path, "pub", tags=["dune"])
    add_artifact(tmp_path, "review/a")
    add_artifact(tmp_path, "review/deep/b", entry="report.html", files={"report.html": "r"})
    settings = {"group": {"review": {"visibility": "protected", "access": "review"}}}
    arts = {a.dest: a for a in artifacts.load(tmp_path, settings)}
    assert arts["pub"].meta.visibility == "public" and arts["pub"].meta.tags == ["dune"]
    assert arts["pub"].group == "" and arts["review/deep/b"].group == "review"
    for dest in ("review/a", "review/deep/b"):
        assert arts[dest].meta.access == "review"
    assert arts["review/deep/b"].entry == "report.html"
    fm = artifacts.front_matter(arts["review/a"])
    assert fm["build"] == {"render": "link", "list": "never"}


def test_nested_artifacts_refused(tmp_path):
    add_artifact(tmp_path, "outer")
    add_artifact(tmp_path, "outer/inner")
    with pytest.raises(artifacts.ArtifactError):
        artifacts.load(tmp_path)


@pytest.mark.emacs
@pytest.mark.hugo
@pytest.mark.skipif(not (have_hugo() and have_ox_hugo()), reason="needs hugo and ox-hugo")
def test_build_artifacts(hugo_site, tmp_path):
    cfg = hugo_site
    root = artifacts.source_dir(cfg.site, cfg.artifacts)
    add_artifact(root, "pub", files={"index.html": "<html>pub</html>", "js/app.js": "1", "data/d.json": "{}"})
    add_artifact(root, "review/a")
    add_artifact(root, "review/deep/b")
    add_artifact(root, "mine", audience="personal")
    cfg.artifacts = {"group": {"review": {"visibility": "protected"}}}
    add_post(cfg, "p")
    dest = tmp_path / "www"

    deploy.deploy(cfg, cfg.target("all"), dest=dest)
    assert (dest / "artifacts/pub/index.html").read_text() == "<html>pub</html>"
    assert (dest / "artifacts/pub/js/app.js").exists() and (dest / "artifacts/pub/data/d.json").exists()
    assert not (dest / "artifacts/pub" / artifacts.META).exists()
    for d in ("review/a", "review/deep/b"):
        assert "Require valid-user" in (dest / "artifacts" / d / ".htaccess").read_text()
    listing = (dest / "artifacts/index.html").read_text()
    assert "/~me/artifacts/pub/" in listing and "review" not in listing

    # The personal target has no auth: no protected artifacts, no leaks.
    deploy.deploy(cfg, cfg.target("personal"), dest=tmp_path / "p")
    assert (tmp_path / "p/artifacts/mine/index.html").exists()
    assert not (tmp_path / "p/artifacts/review").exists()
    plan = hugo.plan(cfg, cfg.target("personal"))
    assert {a.dest for a, _ in plan.artifacts_excluded} == {"review/a", "review/deep/b"}
