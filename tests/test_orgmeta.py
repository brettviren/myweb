from datetime import date

from myweb import orgmeta

TEXT = """\
#+title: A Title
#+date: 2026-01-02
#+hugo_tags: one two
#+hugo_draft: true
#+audience: work

Some words here.  [[file:fig.svg]]

#+begin_src python :exports both
print(1)
#+end_src

#+begin_src python :exports both
print(2)
#+end_src

#+RESULTS:
: 2

* TODO Write it        :noexport:
DEADLINE: <2026-02-03 Tue>
"""


def test_parse_keywords():
    meta = orgmeta.parse(TEXT)
    assert meta.title == "A Title"
    assert meta.draft is True
    assert meta.tags == ["one", "two"]
    assert meta.audience == "work"
    assert meta.visibility == "public"
    assert meta.problems() == []


def test_parse_body():
    meta = orgmeta.parse(TEXT)
    assert meta.figures == 1
    assert meta.words >= 4
    assert meta.missing_results == [9]


def test_parse_todo():
    meta = orgmeta.parse(TEXT)
    assert meta.todo == "TODO"
    assert meta.deadline == date(2026, 2, 3)
    assert meta.todos[0].noexport


def test_hugo_native_keywords():
    meta = orgmeta.parse("#+title: N\n#+tags[]: a b\n#+draft: false\n")
    assert meta.tags == ["a", "b"]
    assert meta.draft is False


def test_problems():
    meta = orgmeta.parse("#+audience: everyone\n#+visibility: secret\n")
    assert len(meta.problems()) == 3


def test_set_keyword_replace_and_add():
    text = orgmeta.set_keyword(TEXT, "hugo_draft", "false")
    assert "#+hugo_draft: false\n" in text
    assert "#+hugo_draft: true" not in text
    text = orgmeta.set_keyword("#+title: X\n\nbody\n", "draft", "false")
    assert text == "#+title: X\n#+draft: false\n\nbody\n"


def test_close_todos():
    text = orgmeta.close_todos(TEXT, today=date(2026, 2, 1))
    assert "* DONE Write it" in text
    assert "CLOSED: [2026-02-01 Sun] DEADLINE: <2026-02-03 Tue>" in text
    assert orgmeta.parse(text).deadline is None
