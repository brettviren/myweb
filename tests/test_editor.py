import json
import os
import stat
from datetime import date

import pytest
from click.testing import CliRunner

from myweb import editor, talkwork
from myweb.cli import cli
from myweb.config import Config


def test_command_precedence(tmp_path):
    cfg = Config(site=tmp_path)
    assert editor.command(cfg, {}) == ["vi"]
    assert editor.command(cfg, {"VISUAL": "code -w"}) == ["code", "-w"]
    assert editor.command(cfg, {"VISUAL": "code -w", "EDITOR": "nano"}) == ["nano"]
    cfg.editor = ["emacsclient", "-c"]
    assert editor.command(cfg, {"EDITOR": "nano"}) == ["emacsclient", "-c"]
    assert editor.is_emacsclient(cfg.editor) and not editor.is_emacsclient(["nano"])


def test_description_round_trip(tmp_path):
    talk = talkwork.new(tmp_path, "dune", "A Talk", when=date(2026, 1, 2), setupfile=str(tmp_path / "x"))
    talkwork.describe(tmp_path, talk, keywords=["GDML", "Phlex"], summary="One.")
    text = talkwork.description_text(talk, tmp_path)
    assert "venue:\n" in text and "keywords: GDML, Phlex" in text and "dune/2026/01/02/a-talk" in text
    assert talkwork.changes(talk, talkwork.parse_description(text)) == {}
    edited = (text.replace("venue:", "venue: CM").replace("keywords: GDML, Phlex", "keywords:")
              .replace("One.", "First\nline.\n\nSecond."))
    assert talkwork.changes(talk, talkwork.parse_description(edited)) == {
        "venue": "CM", "keywords": [], "summary": "First line.\n\nSecond."}
    with pytest.raises(talkwork.TalkWorkError):
        talkwork.parse_description("color: blue\n")


def fake_editor(tmp_path, script):
    path = tmp_path / "ed.sh"
    path.write_text("#!/bin/sh\n" + script + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_describe_edit(site, tmp_path, monkeypatch):
    keep = tmp_path / "keep"
    talk = talkwork.new(keep, "dune", "A Talk", when=date(2026, 1, 2), setupfile=str(tmp_path / "x"))
    conf = tmp_path / "config.toml"
    conf.write_text(f'site = "{site}"\n[talks]\ndest = "{keep}"\n')
    monkeypatch.setenv("EDITOR", fake_editor(tmp_path, r"""sed -i 's/^venue:.*/venue: CM/; s/^summary:$/summary: Edited./' "$1" """))
    out = CliRunner().invoke(cli, ["-c", str(conf), "talks", "describe", "-e", "a-talk"])
    assert out.exit_code == 0, out.output
    assert "setting summary, venue" in out.output
    data = talkwork.read(talk)
    assert data["venue"] == "CM" and data["summary"] == "Edited."

    monkeypatch.setenv("EDITOR", "true")  # saves nothing
    out = CliRunner().invoke(cli, ["-c", str(conf), "talks", "describe", "-e", "a-talk"])
    assert out.exit_code == 0 and "unchanged" in out.output


def test_open_live_runs_plain_editor(tmp_path, monkeypatch):
    seen = tmp_path / "seen"
    cfg = Config(site=tmp_path, editor=[fake_editor(tmp_path, f'echo "$1" > {seen}')])
    target = tmp_path / "a.org"
    target.write_text("x")
    assert editor.open_live(cfg, target) == (False, "")
    assert seen.read_text().strip() == str(target)
