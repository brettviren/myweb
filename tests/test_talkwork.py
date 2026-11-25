import json
import shutil
from datetime import date

import pytest

from myweb import talks, talkwork

ORG = "#+title: {title}\n#+setupfile: ~/sync/talks/setup.org\n#+date: 2026-11-20\n* Slide\n{text}\n"


def test_new_refresh_publish(tmp_path):
    setup = tmp_path / "setup.org"
    setup.write_text("#+author: Ann Author\n")
    talk = talkwork.new(tmp_path / "keep", "DUNE", "Geometry Plans", when=date(2026, 12, 1), setupfile=str(setup))
    assert talk == tmp_path / "keep/dune/2026/12/01/geometry-plans"
    data = talkwork.read(talk)
    assert data["draft"] is True and data["authors"] == ["Ann Author"] and data["pdf"] == "geometry-plans.pdf"
    assert f"#+setupfile: {setup}" in (talk / "geometry-plans.org").read_text()
    assert talkwork.find(tmp_path / "keep", "geometry-plans") == talk
    with pytest.raises(talkwork.TalkWorkError):
        talkwork.new(tmp_path / "keep", "dune", "Geometry Plans", when=date(2026, 12, 1))

    org = talk / "geometry-plans.org"
    org.write_text(org.read_text().replace("#+title: Geometry Plans", "#+title: Geometry, Planned"))
    data, warnings = talkwork.refresh(talk)
    assert data["title"] == "Geometry, Planned" and warnings and data["draft"]
    with pytest.raises(talkwork.TalkWorkError):
        talkwork.refresh(talk, publish=True)  # no PDF yet
    (talk / "geometry-plans.pdf").write_bytes(b"%PDF-1.4\n")
    (talk / "geometry-plans.aux").write_text("junk")
    data, _ = talkwork.refresh(talk, publish=True)
    assert "draft" not in data
    assert data["files"] == ["geometry-plans.org", "geometry-plans.pdf"]


def _migrated(tmp_path):
    old, keep = tmp_path / "old", tmp_path / "keep"
    src = old / "wire-cell/topics/phlex/geom"
    src.mkdir(parents=True)
    (src / "geom.org").write_text(ORG.format(title="Geometry", text="First."))
    (src / "fig.png").write_text("png")
    keep.mkdir()
    state = talks.State(keep)
    inv, _, _ = talks.update(state, old)
    cid = "wire-cell/topics/phlex/geom/geom"
    state.review_path(cid).parent.mkdir(parents=True)
    state.review_path(cid).write_text(json.dumps(
        {"id": cid, "is_talk": True, "owner_is_author": True, "title": "Geometry", "summary": "S.",
         "keywords": [], "problems": [], "topic_slug": "phlex-geometry"}))
    talks.stamp_reviews(state, inv)
    done = talks.migrate(state, old, inv, [cid])
    place = done[0][2]
    assert place == "wire-cell/2026/11/20/phlex-geometry"
    tj = keep / place / "talk.json"
    tj.write_text(tj.read_text().replace('"group": "wire-cell"', '"audience": "both", "group": "wire-cell"'))
    return old, keep, state, src, place


def test_pull_in_place(tmp_path):
    old, keep, state, src, place = _migrated(tmp_path)
    (src / "geom.org").write_text(ORG.format(title="Geometry", text="Second."))
    cid, where = talkwork.pull(state, old, keep / place)
    assert (cid, where) == ("wire-cell/topics/phlex/geom/geom", place)
    assert "Second." in (keep / place / "geom.org").read_text()
    assert talkwork.read(keep / place)["audience"] == "both"
    # Nothing is left to review or to migrate a second time.
    inv = state.load()
    assert cid not in talks.needs_review(state, inv)
    assert [d for _, s, d in talks.migrate(state, old, inv) if s == "migrated"] == [place]


def test_pull_moved(tmp_path):
    old, keep, state, src, place = _migrated(tmp_path)
    moved = old / "dune/topics/phlex/geom"
    moved.parent.mkdir(parents=True)
    shutil.move(src, moved)
    (moved / "geom.org").write_text(ORG.format(title="Geometry", text="Moved and changed."))
    (moved / "fig.png").unlink()
    (moved / "new.png").write_text("new")
    cid, where = talkwork.pull(state, old, keep / place, moved)
    assert cid == "dune/topics/phlex/geom/geom"
    assert where == "dune/2026/11/20/phlex-geometry"
    assert not (keep / "wire-cell").exists()
    talk = keep / where
    assert "Moved and changed." in (talk / "geom.org").read_text()
    assert (talk / "new.png").exists() and not (talk / "fig.png").exists()
    data = talkwork.read(talk)
    assert data["group"] == "dune" and data["audience"] == "both" and data["summary"] == "S."
    inv = state.load()
    assert inv["talks"]["wire-cell/topics/phlex/geom/geom"]["moved_to"] == cid
    assert cid not in talks.needs_review(state, inv)
    assert [d for _, s, d in talks.migrate(state, old, inv) if s == "migrated"] == [where]
