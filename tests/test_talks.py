import json
import os
import shutil
import subprocess

import pytest

from myweb import talks

ORG = "#+title: {title}\n#+setupfile: ~/sync/talks/setup.org\n{extra}\n* Slide\nText.\n"
TEX = "\\documentclass{{beamer}}\n\\title{{{title}}}\n\\date{{{date}}}\n\\begin{{document}}\nx\n\\end{{document}}\n"


def test_compact_date():
    assert talks.compact_date("090401-upgrades") == ((2009, 4, 1), "day", "upgrades")
    assert talks.compact_date("201405-sc-review") == ((2014, 5, 1), "month", "sc-review")
    assert talks.compact_date("0910-nnn09") == ((2009, 10, 1), "month", "nnn09")
    assert talks.compact_date("20131003-sc") == ((2013, 10, 3), "day", "sc")
    assert talks.compact_date("0704xx") == ((2007, 4, 1), "month", "")
    assert talks.compact_date("120420-pool") == ((2012, 4, 20), "day", "pool")
    assert talks.compact_date("nnn09") is None


def test_path_info():
    i = talks.path_info(["2023", "06", "06", "framework"], "fw")
    assert (i.ymd, i.precision, i.topic) == ((2023, 6, 6), "day", "framework")
    i = talks.path_info(["2021", "02", "10"], "daq-multiproc")
    assert i.precision == "day" and i.topic == ""
    i = talks.path_info(["2019", "01", "daq-ws"], "newbold-20190129")
    assert (i.ymd, i.source, i.topic) == ((2019, 1, 29), "filename", "daq-ws")
    i = talks.path_info(["topics", "interpolation"], "refresher")
    assert i.ymd is None and i.series == "interpolation"
    assert talks.path_info(["kick-off"], "kom").topic == "kick-off"


def test_parse_loose_date():
    assert talks.parse_loose_date("<2021-02-10 Wed>") == "2021-02-10"
    assert talks.parse_loose_date("February 10, 2021") == "2021-02-10"
    assert talks.parse_loose_date("10 Feb 2021") == "2021-02-10"
    assert talks.parse_loose_date("\\today") == ""


def have_pdf_tools():
    return shutil.which("pdfinfo") and shutil.which("pdftotext")


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "old"
    def put(rel, text=""):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    put("dune/2023/06/06/framework.org", ORG.format(title="Frameworks", extra=""))
    put("dune/2023/06/06/striped.org", ORG.format(title="Striped", extra="#+date: 2023-06-06"))
    put("dune/2023/06/06/fig.dot", "digraph{}")
    put("dune/2023/06/06/framework.aux", "junk")
    put("dune/2023/06/06/auto/framework.el", "junk")
    put("dune/2023/06/06/notes.org", "* just notes\n")
    put("wire-cell/topics/config/config.org", ORG.format(title="Config", extra="#+date: <2020-03-04 Wed>"))
    put("wire-cell/topics/config/figs/a.dot", "x")
    put("dayabay/090401-upgrades/upgrades.tex", TEX.format(title="Upgrades", date="April 1, 2009"))
    put("dayabay/2009/04/01/upgrades/upgrades.tex", TEX.format(title="Upgrades", date="April 1, 2009"))
    put("dayabay/2009/04/01/upgrades/others/theirs.odp", "x")
    put("setup.org", ORG.format(title="Setup", extra=""))
    return root


def test_scan_and_place(tree):
    found = talks.scan(tree).candidates
    assert set(found) == {"dune/2023/06/06/framework", "dune/2023/06/06/striped",
                          "wire-cell/topics/config/config", "dayabay/090401-upgrades/upgrades",
                          "dayabay/2009/04/01/upgrades/upgrades", "setup"}
    fw = found["dune/2023/06/06/framework"]
    assert (fw.date, fw.date_source, fw.kind) == ("2023-06-06", "path", "org-beamer")
    assert fw.dest == "dune/2023/06/06/framework" and "shared-dir" in fw.flags
    cfg = found["wire-cell/topics/config/config"]
    assert (cfg.date, cfg.date_source, cfg.series) == ("2020-03-04", "source", "config")
    assert cfg.dest == "wire-cell/2020/03/04/config"
    # The date tree copy wins over the old compact directory.
    assert found["dayabay/090401-upgrades/upgrades"].duplicate_of == "dayabay/2009/04/01/upgrades/upgrades"
    assert "template" in found["setup"].flags


def test_copy_set(tree):
    found = talks.scan(tree).candidates
    live = [c for c in found.values() if not c.duplicate_of]
    files = talks.copy_set(tree, found["dune/2023/06/06/framework"], live)
    assert sorted(files) == ["fig.dot", "framework.org", "notes.org"]
    files = talks.copy_set(tree, found["dayabay/2009/04/01/upgrades/upgrades"], live)
    assert sorted(files) == ["others/theirs.odp", "upgrades.tex"]


def test_migrate_and_rescan(tree, tmp_path):
    dest = tmp_path / "keep"
    dest.mkdir()
    state = talks.State(dest)
    inv, new, changed = talks.update(state, tree)
    assert len(new) == 6 and not changed
    todo = talks.needs_review(state, inv)
    assert "setup" not in todo and "dayabay/090401-upgrades/upgrades" not in todo
    talks.write_digests(state, tree, inv, todo)
    assert "title: Frameworks" in state.digest_path("dune/2023/06/06/framework").read_text() or \
        "#+title: Frameworks" in state.digest_path("dune/2023/06/06/framework").read_text()

    def review(cid, **kw):
        data = {"id": cid, "is_talk": True, "owner_is_author": True, "title": cid, "summary": "S.",
                "keywords": [], "problems": [], **kw}
        state.review_path(cid).parent.mkdir(parents=True, exist_ok=True)
        state.review_path(cid).write_text(json.dumps(data))
    review("dune/2023/06/06/framework", venue="FW workshop")
    review("dune/2023/06/06/striped", problems=["maybe a draft"])
    review("wire-cell/topics/config/config", topic_slug="wct-configuration")
    review("dayabay/2009/04/01/upgrades/upgrades", is_talk=False)
    talks.stamp_reviews(state, inv)
    done = {cid: (status, d) for cid, status, d in talks.migrate(state, tree, inv)}
    assert done["dune/2023/06/06/framework"] == ("migrated", "dune/2023/06/06/framework")
    assert done["dune/2023/06/06/striped"][0] == "ambiguous"
    assert done["wire-cell/topics/config/config"] == ("migrated", "wire-cell/2020/03/04/wct-configuration")
    assert done["dayabay/2009/04/01/upgrades/upgrades"][0] == "not-a-talk"
    meta = json.loads((dest / "dune/2023/06/06/framework/talk.json").read_text())
    assert meta["venue"] == "FW workshop" and meta["origin"] == "dune/2023/06/06/framework"
    assert not (dest / "dune/2023/06/06/framework/framework.aux").exists()
    assert not (dest / "dune/2023/06/06/framework/striped.org").exists()

    report = talks.report(state, inv)
    assert "maybe a draft" in report and "[X] ~dune/2023/06/06/framework~" in report

    # A changed source shows up on the next scan and its review goes stale.
    (tree / "dune/2023/06/06/framework.org").write_text(ORG.format(title="Frameworks 2", extra="x"))
    os.utime(tree / "dune/2023/06/06/framework.org", (1e9, 1e9))
    inv, new, changed = talks.update(state, tree)
    assert changed == ["dune/2023/06/06/framework"]
    assert inv["talks"]["dune/2023/06/06/framework"]["status"] == "changed"
    assert "dune/2023/06/06/framework" in talks.needs_review(state, inv)
