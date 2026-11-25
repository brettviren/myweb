import pytest

from conftest import git
from myweb import deploy
from myweb.config import ConfigError, Target, _target, methods


@pytest.fixture
def ident(monkeypatch):
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.com")


def stage(tmp_path, files):
    root = tmp_path / "stage"
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return root


def test_target_methods_and_fields():
    tgt = _target("gh", {"git": "git@example.org:me/me.github.io.git", "branch": "master",
                         "files": {".nojekyll": ""}, "talks": False, "keep": []})
    assert methods(tgt) == ["git"]
    assert tgt.branch == "master" and tgt.files == {".nojekyll": ""} and not tgt.talks
    assert methods(_target("w", {"rsync": "host:public_html/"})) == ["rsync"]
    with pytest.raises(ConfigError):
        _target("bad", {"files": {"../x": ""}})


def test_git_push(tmp_path, monkeypatch, ident):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    tgt = Target(name="gh", environment="gh", git=str(remote), branch="pages", keep=[])

    src = stage(tmp_path, {"index.html": "one", "posts/a/index.html": "a"})
    assert deploy.git_push(src, tgt, "first") == f"{remote} pages"
    assert git(remote, "show", "pages:index.html") == "one"

    (src / "posts" / "a" / "index.html").unlink()
    (src / "index.html").write_text("two")
    deploy.git_push(src, tgt, "second")
    assert git(remote, "show", "pages:index.html") == "two"
    assert "posts/a/index.html" not in git(remote, "ls-tree", "-r", "--name-only", "pages")
    assert git(remote, "log", "--format=%s", "pages").split() == ["second", "first"]

    assert deploy.git_push(src, tgt, "third").endswith("(unchanged)")

    # A fresh cache follows the existing remote branch.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache2"))
    (src / "new.html").write_text("n")
    deploy.git_push(src, tgt, "fourth")
    assert git(remote, "log", "--format=%s", "pages").split() == ["fourth", "second", "first"]


def test_extra_files(tmp_path):
    tgt = Target(name="gh", environment="gh", files={".nojekyll": "", "CNAME": "example.org"})
    deploy.extra_files(tgt, tmp_path)
    assert (tmp_path / ".nojekyll").read_text() == ""
    assert (tmp_path / "CNAME").read_text() == "example.org"


def test_ship_needs_somewhere(tmp_path):
    tgt = Target(name="x", environment="x")
    result = deploy.Result(tgt, tmp_path, plan=None)
    with pytest.raises(deploy.DeployError):
        deploy.ship(None, result)


def test_top_htaccess(tmp_path):
    files = stage(tmp_path, {"index.html": "", "css/s.css": "", "t/a.pdf": "", ".nojekyll": "", "x/.htaccess": ""})
    tgt = Target(name="w", environment="w", allow_files=True)
    text = deploy.top_htaccess(tgt, files).read_text()
    assert 'AddType "text/plain; charset=utf-8" .org' in text
    assert '<FilesMatch "\\.(css|html|pdf)$">' in text
    tgt.org_type, tgt.allow_files = "", False
    assert deploy.top_htaccess(tgt, files) is None and not (files / ".htaccess").exists()


def test_protected_htaccess_requires_files_too():
    from myweb import access
    tgt = Target(name="w", environment="w", htpasswd="/srv/pw")
    text = access.htaccess(tgt, access.Realm("edg", "user edg"), "page x")
    assert text.count("Require user edg") == 2
    assert '<FilesMatch "">' in text
