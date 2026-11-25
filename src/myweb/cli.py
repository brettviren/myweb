"""Command line entry point.

Argument parsing, output and exit only.  The work is in the other modules.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import click

from . import (
    __version__,
    agenda,
    authoring,
    check as checking,
    deploy,
    export as exporting,
    hugo,
    server,
    setup as setting,
    site as sites,
    siteindex,
    status as statusing,
    talkpages,
    talks as talking,
    vcs,
    version as versioning,
)
from .config import Config, ConfigError, load, xdg_dir

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 96}
ERRORS = (
    ConfigError,
    exporting.ExportError,
    hugo.HugoError,
    deploy.DeployError,
    siteindex.SearchError,
    talking.TalksError,
    talkpages.TalkError,
    vcs.VcsError,
    FileExistsError,
)

pass_config = click.make_pass_decorator(Config)


def fail(err: Exception) -> None:
    click.secho(f"myweb: {err}", fg="red", err=True)
    sys.exit(1)


@click.group(context_settings=CONTEXT_SETTINGS, no_args_is_help=True)
@click.option(
    "-c", "--config", "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="User configuration file instead of ~/.config/myweb/config.toml.",
)
@click.option(
    "-s", "--site",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="The site dataset, overriding MYWEB_SITE and the config.",
)
@click.version_option(__version__, "-V", "--version")
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None, site: Path | None) -> None:
    """Author, build and deploy web sites from org sources.

    Items are page bundles in taxa (posts, articles, notes, ...) of the site
    dataset.  Taxa and deployment targets are configured in the site's
    myweb.toml.
    """
    try:
        ctx.obj = load(config_path, site)
    except ConfigError as err:
        fail(err)


def _date(ctx, param, value):
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise click.BadParameter("give a date as YYYY-MM-DD") from None


@cli.command(no_args_is_help=True)
@click.argument("taxon")
@click.argument("title")
@click.option("-t", "--tag", "tags", multiple=True, help="A tag, may repeat.")
@click.option("-d", "--deadline", callback=_date, help="YYYY-MM-DD, adds a TODO and puts the item in org-agenda.")
@click.option("-m", "--message", default="", help="Initial body text, eg a whole note.")
@click.option("--slug", help="Use this slug instead of one made from the title.")
@pass_config
def new(cfg: Config, taxon, title, tags, deadline, message, slug):
    """Create a new draft item in TAXON titled TITLE."""
    try:
        made = authoring.new(cfg, taxon, title, list(tags), deadline, message, slug)
    except ERRORS as err:
        fail(err)
    click.echo(made.bundle.source)
    if deadline and not made.in_agenda:
        click.echo("note: Emacs did not answer, " + agenda.instructions(made.bundle.source), err=True)


@cli.command(no_args_is_help=True)
@click.argument("item")
@click.option("--no-browser", is_flag=True, help="Do not open a browser.")
@pass_config
def edit(cfg: Config, item, no_browser):
    """Open ITEM in Emacs with a drafts-included hugo server previewing it.

    ITEM is a slug, taxon/slug or a path.  In Emacs, ox-hugo items are
    re-exported on each save by org-hugo-auto-export-mode.
    """
    try:
        bundle = sites.find(cfg, item)
        url = server.ensure(cfg) + bundle.url_path
    except ERRORS as err:
        fail(err)
    elisp = exporting.elisp_file()
    form = (
        f'(progn (find-file "{bundle.source}") (when (require \'ox-hugo nil t)'
        f' (load "{elisp}" nil t) (when (fboundp \'org-hugo-auto-export-mode)'
        " (org-hugo-auto-export-mode 1))) t)"
    )
    proc = subprocess.run([cfg.emacsclient, "-n", "--eval", form], capture_output=True)
    if proc.returncode:
        click.echo(f"emacsclient failed, edit {bundle.source} yourself", err=True)
    click.echo(url)
    if not no_browser:
        subprocess.Popen([cfg.browser, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@cli.command()
@click.option("-t", "--tag", help="Only items with this tag.")
@click.option("-x", "--taxon", "taxa", multiple=True, help="Only items of this taxon, may repeat.")
@click.option("-a", "--all", "every", is_flag=True, help="All items, not only drafts.")
@pass_config
def status(cfg: Config, tag, taxa, every):
    """List draft items with their deadline, size and state."""
    rows = statusing.rows(cfg, list(taxa) or None, tag, drafts_only=not every)
    for r in rows:
        flags = ("D" if r.draft else "-") + ("S" if r.stale else "-")
        due = r.deadline.isoformat() if r.deadline else "-"
        vis = "" if r.visibility == "public" else f" [{r.visibility}]"
        click.echo(
            f"{flags} {due:10} {r.todo or '-':5} {r.words:6}w {r.figures:2}f "
            f"{r.modified:%Y-%m-%d} {r.audience:8} {r.bundle.name}{vis}  {r.title}"
        )
    if not rows:
        click.echo("no drafts" if not every else "no items", err=True)


@cli.command()
@click.argument("items", nargs=-1)
@click.option("-f", "--force", is_flag=True, help="Export even if index.md is newer than the org.")
@pass_config
def export(cfg: Config, items, force):
    """Export ox-hugo ITEMS (default all stale) from org to markdown."""
    try:
        todo = [sites.find(cfg, i) for i in items] if items else sites.bundles(cfg)
        done = exporting.export(cfg, todo, force=force or bool(items))
    except ERRORS as err:
        fail(err)
    for bundle in done:
        click.echo(f"exported {bundle.name}")


@cli.command(no_args_is_help=True)
@click.argument("item")
@click.option("-T", "--target", "target_name", default="local", show_default=True)
@pass_config
def check(cfg: Config, item, target_name):
    """Export and build ITEM to a check stage, then check it for problems.

    The report is also saved as .check.txt in the item's bundle.
    """
    try:
        bundle = sites.find(cfg, item)
        report = checking.check(cfg, bundle, cfg.target(target_name))
    except ERRORS as err:
        fail(err)
    checking.save(report)
    click.echo(report.text(), nl=False)
    sys.exit(0 if report.ok else 1)


@cli.command(no_args_is_help=True)
@click.argument("items", nargs=-1)
@click.option("-a", "--all", "every", is_flag=True, help="All items.")
@click.option("-n", "--dry-run", is_flag=True, help="Only say what would change.")
@click.option("--commit", is_flag=True, help="Save the changed sources with git.")
@pass_config
def ids(cfg: Config, items, every, dry_run, commit):
    """Give every headline of ITEMS a CUSTOM_ID, a slug of its heading.

    These become the HTML anchors of sections.  Existing ids are kept
    except org's generated "org1234abc" ones, which are replaced.
    "publish" does this itself.
    """
    try:
        todo = sites.bundles(cfg) if every else [sites.find(cfg, i) for i in items]
        changed = []
        for bundle in todo:
            made = authoring.ensure_ids(bundle, dry_run=dry_run)
            for title, ident in made:
                click.echo(f"{bundle.name}: #{ident}  {title}")
            if made:
                changed.append(bundle.source)
        if commit and changed and not dry_run:
            vcs.save(cfg.site, "headline CUSTOM_IDs", changed)
    except ERRORS as err:
        fail(err)


@cli.command(no_args_is_help=True)
@click.argument("item")
@click.option("-T", "--target", "targets", multiple=True, help="Deploy to this target, may repeat.  Default from config.")
@click.option("--no-commit", is_flag=True, help="Do not save, stamp or tag.")
@click.option("--no-deploy", is_flag=True, help="Do not build and deploy.")
@pass_config
def publish(cfg: Config, item, targets, no_commit, no_deploy):
    """Make ITEM no longer a draft, record it, then build and deploy."""
    try:
        bundle = sites.find(cfg, item)
        done = authoring.publish(cfg, bundle, list(targets), not no_commit, not no_deploy)
    except ERRORS as err:
        fail(err)
    click.echo(f"published {bundle.name}")
    if done.tag:
        click.echo(f"tagged {done.tag}")
    for result in done.results:
        click.echo(f"deployed {result.target.name}: {', '.join(result.synced) or result.stage}")


def _report(result: deploy.Result, quiet: bool) -> None:
    for line in result.warnings:
        click.echo(f"warning: {line}", err=True)
    if quiet:
        return
    for bundle in result.exported:
        click.echo(f"exported {bundle.name}")
    for bundle, why in result.plan.excluded:
        click.echo(f"excluded {bundle.name}: {why}")
    for bundle, vis in result.plan.hidden:
        click.echo(f"{vis} {bundle.name}")
    for talk, why in result.plan.talks_excluded:
        click.echo(f"excluded {talk.name}: {why}")
    for line in result.log.splitlines():
        if line.startswith(("WARN", "ERROR")):
            click.echo(line, err=True)
    click.echo(f"built {result.target.name}: {len(result.plan.included)} items "
               f"and {len(result.plan.talks)} talks to {result.stage}")


@cli.command()
@click.argument("target_name", default="local")
@click.option("--drafts", is_flag=True, help="Include drafts.")
@click.option("--no-export", is_flag=True, help="Do not export stale ox-hugo items first.")
@click.option("-q", "--quiet", is_flag=True)
@pass_config
def build(cfg: Config, target_name, drafts, no_export, quiet):
    """Build TARGET (default local) to its stage and check it, deploying nothing."""
    try:
        result = deploy.build(cfg, cfg.target(target_name), drafts=drafts, do_export=not no_export)
    except ERRORS as err:
        fail(err)
    _report(result, quiet)


@cli.command("deploy", no_args_is_help=True)
@click.argument("target_names", nargs=-1)
@click.option("-a", "--all", "every", is_flag=True, help="Deploy the configured publish_targets.")
@click.option("-d", "--dest", type=click.Path(file_okay=False, path_type=Path), help="Local directory instead of the target's dest.")
@click.option("-r", "--rsync", "remote", help="rsync destination (host:path) instead of the target's.")
@click.option("--drafts", is_flag=True, help="Include drafts.")
@click.option("--no-export", is_flag=True, help="Do not export stale ox-hugo items first.")
@click.option("-q", "--quiet", is_flag=True)
@pass_config
def deploy_(cfg: Config, target_names, every, dest, remote, drafts, no_export, quiet):
    """Build each TARGET and deploy it by its configured methods.

    A target deploys by each of its settings, in order: "dest", a local
    directory; "rsync", a host:path receiving dest (else the build); "git",
    a repository URL whose "branch" receives the build as a new commit.
    """
    names = list(target_names) or (cfg.publish_targets if every else [])
    if not names:
        fail("name a TARGET or give --all")
    try:
        targets = [cfg.target(n) for n in names]
        for target in targets:
            result = deploy.build(cfg, target, drafts=drafts, do_export=not no_export)
            _report(result, quiet)
            deploy.ship(cfg, result, dest, remote)
            for where in result.synced:
                click.echo(f"deployed {target.name} to {where}")
    except ERRORS as err:
        fail(err)


@cli.command()
@click.argument("items", nargs=-1)
@click.option("-u", "--update", is_flag=True, help="Write version.txt files that are out of date.")
@pass_config
def version(cfg: Config, items, update):
    """Show (or update) the version stamps of ITEMS and of the site."""
    try:
        todo = [sites.find(cfg, i) for i in items] if items else sites.bundles(cfg)
        paths = [b.path for b in todo] + ([] if items else [cfg.site])
        for path in paths:
            st = versioning.stamp(cfg.site, path, write=update)
            name = path.relative_to(cfg.site) if path != cfg.site else "(site)"
            first = st.new.split("\n", 1)[0] or "(uncommitted)"
            mark = ("updated" if update else "stale") if st.changed else "ok"
            click.echo(f"{mark:7} {first:30} {name}")
    except ERRORS as err:
        fail(err)


@cli.command(context_settings={"ignore_unknown_options": True}, no_args_is_help=True)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@pass_config
def search(cfg: Config, args):
    """Search the site source, passing ARGS to the configured search command."""
    sys.exit(subprocess.call([*cfg.search, *args]))


@cli.command(no_args_is_help=True)
@click.argument("method", type=click.Choice(["systemd", "cron", "git"]))
@click.option("-T", "--target", "target_name", default="local", show_default=True)
@click.option("-w", "--when", help="systemd OnCalendar or cron schedule.  Default hourly.")
@click.option("-p", "--print", "just_print", is_flag=True, help="Print what would be installed.")
@click.option("-f", "--force", is_flag=True, help="Overwrite files not made by myweb.")
@click.option("--unitdir", type=click.Path(file_okay=False, path_type=Path), default=Path("~/.config/systemd/user").expanduser(), show_default=True)
@pass_config
def setup(cfg: Config, method, target_name, when, just_print, force, unitdir):
    """Arrange for "myweb deploy TARGET" to run by systemd, cron or git hook.

    systemd: a user service, a timer and a path unit that fires when the
    site's branch moves.  cron: a crontab line.  git: post-commit,
    post-merge and post-receive hooks in the site repository.
    """
    try:
        cfg.target(target_name)
        if method == "cron":
            line = setting.cron_line(target_name, when or "@hourly")
            if just_print:
                click.echo(line)
            else:
                setting.install_cron(line, target_name)
                click.echo(f"installed in crontab: {line}")
            return
        if method == "systemd":
            units = setting.systemd(cfg, target_name, when or "hourly", unitdir)
        else:
            units = setting.git_hooks(cfg, target_name)
        if just_print:
            for unit in units:
                click.echo(f"### {unit.path}\n{unit.text}")
            return
        for path in setting.write(units, force=force):
            click.echo(f"wrote {path}")
        if method == "systemd":
            name = f"myweb-deploy-{target_name}"
            click.echo(f"enable with: systemctl --user daemon-reload && "
                       f"systemctl --user enable --now {name}.timer {name}.path")
    except ERRORS as err:
        fail(err)
    except OSError as err:
        fail(f"{err} (use --print to see what to install)")


@cli.group(no_args_is_help=True)
def talks():
    """Migrate talks from the old talks tree to the talks dataset.

    "scan" finds talk candidates and writes a digest of each needing a
    review.  A review, migration/reviews/<id>.json, is written by reading
    the digest (fields: "myweb talks fields").  "migrate" copies reviewed
    talks to <group>/<YYYY>/<MM>/<DD>/<topic>/ with a talk.json.  Every
    command rewrites MIGRATION.org.  The old tree is only read.
    """


def _talks_state(cfg: Config) -> talking.State:
    if not cfg.talks_dest.is_dir():
        raise ConfigError(f"no talks dataset at {cfg.talks_dest}")
    return talking.State(cfg.talks_dest)


def _talks_load(state: talking.State) -> dict:
    """The inventory with new reviews stamped and the owner's guidance
    taken from MIGRATION.org before anything rewrites it."""
    inv = state.load()
    talking.stamp_reviews(state, inv)
    if talking.harvest(state, inv):
        state.save(inv)
    return inv


def _talks_report(state: talking.State, inv: dict) -> None:
    talking.write_report(state, inv)


@talks.command("scan")
@pass_config
def talks_scan(cfg: Config):
    """Find new and changed talks, write digests of those needing review."""
    try:
        state = _talks_state(cfg)
        _talks_load(state)
        inv, new, changed = talking.update(state, cfg.talks_source)
        talking.stamp_reviews(state, inv)
        todo = talking.needs_review(state, inv)
        talking.write_digests(state, cfg.talks_source, inv, todo)
        _talks_report(state, inv)
    except ERRORS as err:
        fail(err)
    click.echo(f"{len(inv['talks'])} candidates, {len(new)} new, {len(changed)} changed, "
               f"{len(todo)} need review (digests in {state.dir / 'digests'})")


@talks.command("todo")
@click.option("-p", "--paths", is_flag=True, help="Print digest paths instead of ids.")
@pass_config
def talks_todo(cfg: Config, paths):
    """List talks needing a review."""
    try:
        state = _talks_state(cfg)
        inv = _talks_load(state)
        for cid in talking.needs_review(state, inv):
            click.echo(state.digest_path(cid) if paths else cid)
    except ERRORS as err:
        fail(err)


@talks.command("fields")
def talks_fields():
    """Describe the fields of a review."""
    click.echo(json.dumps(talking.REVIEW_FIELDS, indent=1))


@talks.command("migrate")
@click.argument("ids", nargs=-1)
@click.option("--redo", is_flag=True, help="Migrate again talks already migrated.")
@click.option("-n", "--dry-run", is_flag=True)
@click.option("--save", is_flag=True, help="datalad save the talks dataset afterwards.")
@pass_config
def talks_migrate(cfg: Config, ids, redo, dry_run, save):
    """Copy reviewed talks (IDS, default all) to the talks dataset."""
    try:
        state = _talks_state(cfg)
        inv = _talks_load(state)
        done = talking.migrate(state, cfg.talks_source, inv, list(ids) or None, redo=redo, dry_run=dry_run)
        _talks_report(state, inv)
        counts: dict[str, int] = {}
        for cid, status, dest in done:
            counts[status] = counts.get(status, 0) + 1
            if status in ("migrated", "would migrate") and dest and (ids or redo or dry_run):
                click.echo(f"{status} {cid} -> {dest}")
        click.echo(", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
        if save and not dry_run:
            vcs.save(state.dest, "talks: migrate from " + str(cfg.talks_source).replace(str(Path.home()), "~"))
    except ERRORS as err:
        fail(err)


@talks.command("resolve", no_args_is_help=True)
@click.argument("ids", nargs=-1, required=True)
@click.option("-a", "--accept", "action", flag_value="accept", help="Migrate despite the problems.")
@click.option("-r", "--reject", "action", flag_value="reject", help="Never migrate.")
@click.option("--material", "action", flag_value="material", help="Not a talk, but copy it with the talks beside it.")
@click.option("--clear", "action", flag_value="clear", help="Forget an earlier accept or reject.")
@click.option("-m", "--note", default="", help="Why, kept in the review.")
@click.option("-d", "--date", "date_", default="", help="Date to use, YYYY-MM-DD.")
@click.option("-t", "--topic", default="", help="Topic directory name to use.")
@click.option("--remove", is_flag=True, help="With --reject or --material, remove a talk already migrated.")
@click.option("--access", "realm", default="", help="Protect it in this access realm.")
@click.option("--migrate/--no-migrate", default=True, show_default=True, help="Migrate what this makes ready.")
@pass_config
def talks_resolve(cfg: Config, ids, action, note, date_, topic, remove, realm, migrate):
    """Decide on talks listed in MIGRATION.org: IDS are their ~id~s."""
    if not action and not (date_ or topic or realm):
        fail(ConfigError("give --accept, --reject, --material, --clear, --date, --topic or --access"))
    try:
        state = _talks_state(cfg)
        inv = _talks_load(state)
        for cid in ids:
            talking.resolve(state, inv, cid, action, note=note, date_=date_, topic=topic, remove=remove, realm=realm)
        if migrate:
            for cid, status, dest in talking.migrate(state, cfg.talks_source, inv, list(ids)):
                click.echo(f"{cid}: {status}" + (f" -> {dest}" if dest else ""))
        state.save(inv)
        _talks_report(state, inv)
    except ERRORS as err:
        fail(err)


@talks.command("report")
@pass_config
def talks_report(cfg: Config):
    """Rewrite MIGRATION.org."""
    try:
        state = _talks_state(cfg)
        inv = _talks_load(state)
        _talks_report(state, inv)
    except ERRORS as err:
        fail(err)
    click.echo(state.dest / "MIGRATION.org")


def main() -> None:
    cli()
