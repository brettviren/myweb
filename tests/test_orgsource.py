from myweb.orgsource import ensure_ids, heading_slug, missing_ids, publishable

TEXT = """\
#+title: T

* Intro
Body.
* TODO [#A] See [[https://x.org][The X]] [1/2]  :tag:
DEADLINE: <2026-01-01 Thu>
** Kept
   :PROPERTIES:
   :CUSTOM_ID: my-own
   :END:
** Generated
   :PROPERTIES:
   :ORDERED: t
   :CUSTOM_ID: org1a2b3c4
   :END:
** Drawer
   :PROPERTIES:
   :ORDERED: t
   :END:
* Intro
#+begin_src org
* Not a heading
#+end_src
* Last"""


def test_heading_slug():
    assert heading_slug("TODO-free C++ and GNUS/BBDB") == "todo-free-cpp-and-gnus-bbdb"
    assert heading_slug("[[file:a.org][A file]] [50%]") == "a-file"
    assert heading_slug("COMMENT ???") == "section"


def test_ensure_ids():
    ids = ensure_ids(TEXT)
    assert [i for _, i in ids.made] == ["intro", "see-the-x", "generated", "drawer", "intro-2", "last"]
    text = ids.text
    # Existing drawers are indented so new ones are too, after planning.
    assert "DEADLINE: <2026-01-01 Thu>\n  :PROPERTIES:\n  :CUSTOM_ID: see-the-x\n  :END:\n** Kept" in text
    assert ":CUSTOM_ID: my-own" in text and "org1a2b3c4" not in text
    assert "   :PROPERTIES:\n   :CUSTOM_ID: drawer\n   :ORDERED: t" in text
    assert "* Not a heading\n#+end_src" in text
    assert text.endswith("* Last\n  :PROPERTIES:\n  :CUSTOM_ID: last\n  :END:\n")
    # Idempotent.
    assert ensure_ids(text).made == [] and missing_ids(text) == []


def test_publishable():
    text = "#+title: T\n* A\na\n* Notes :noexport:\nsecret\n** Sub\nsecret\n* COMMENT c\nx\n* B\nb\n"
    assert publishable(text) == "#+title: T\n* A\na\n* B\nb\n"
