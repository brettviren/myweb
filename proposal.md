# My web page: proposal

Status: draft for discussion, 2026-11-22.
Source notes: `~/org/roam/20261122081355-my_web_page.org`.

## 1. Where things stand (what I could see)

- **Personal blog** `~/pub` (GitHub `brettviren/pub`, public). Last commit 2022-06-25.
  It holds about 10 real entries in `org/{posts,articles,notes,about}/<slug>/<slug>.org`, which ox-hugo exports to `content/*.md`.
  The theme is `meathead`, a modified `archie`, and four other themes sit unused in `themes/`.
  `deploy.sh` builds into the `github/` submodule (`brettviren.github.io`) and pushes it.
  Hugo is **not installed** on this host, so the old Hugo version, and how much the theme has drifted from current Hugo, is unknown.
  Images are partly in post directories and partly in `static/`, which is the indirection your notes complain about.
- **Work site** `https://www.phy.bnl.gov/~bviren/`. The top page is an `index.org` export: a list of links, mostly into `tmp/<topic>/`.
  `tmp/`, `talks/`, `eggs/` and `wcwc/docs/` all answer 200. From here I can't inventory the tree behind them.
- **Talks** `~/sync/talks`: 2.0 GB, about 577 directories within 3 levels, about 181 `.org` files, and a mix of beamer `.tex`/`.pdf` and tarballs.
  The layout mixes `<project>/<YYYY>/...` and `<project>/topics/<topic>/`, and the oldest material uses `dayabay/YYMMDD-slug`.
  The README says a `.git` exists but is not synced and lives on `hokum`.
  There is an old waf + `memeb` scheme that dumps per-talk JSON metadata from `.tex` files, which is worth reviving as an idea.
- **orgface** already has `render` (Jinja2 template or Emacs org-export), `search` (full-text and semantic), `store`, `serve` and `commit`/`note`.
  That is a large part of the CLI-side infrastructure this plan needs.
- **see** (`~/scripts/see`) is a working "personal 0x0": md5-prefix name, strips EXIF, scp to `sobrieti.bot.nu/see/`. It has no expiry and no manifest.

## 2. Target picture

One **private source repo** (on gitea) produces **several deployment targets**. Every item carries two independent attributes:

| attribute    | values                                                                                                                  |
|--------------|-------------------------------------------------------------------------------------------------------------------------|
| `audience`   | `personal`, `work`, `both`: which site(s) it appears on                                                                  |
| `visibility` | `public` (listed and indexable), `unlisted` (built and reachable, not in indices, `noindex`), `protected` (password), `draft` (local only) |

Each target is a Hugo environment (`hugo --environment personal|work`). Its config filters on those two attributes and sets the base URL and deploy method:

- `personal` → GitHub Pages (static only, no auth, so it never receives `protected` items).
- `work` → BNL `public_html` (Apache: `.htaccess` for `protected` areas and `noindex`).
- *(optional)* `sobrieti.bot.nu` → protected or personal material that shouldn't live at BNL, plus the drop service (§3.5).

The **taxonomy** becomes a small set of Hugo *sections* (content types), each with its own archetype and layout. Everything else is cross-cutting *tags/topics*.

| section     | what                                                       | notes                                                           |
|-------------|------------------------------------------------------------|-----------------------------------------------------------------|
| `posts`     | timely blog entry                                          | as now                                                          |
| `articles`  | revised long-form; babel, figures                          | git revision history rendered on the page                       |
| `notes`     | TIL-sized                                                  | lowest-friction capture, can be created from a single `-m`      |
| `talks`     | one talk = one bundle with metadata and a list of venues   | sub-taxonomy (§3.4)                                             |
| `artifacts` | LLM-generated HTML/PDF                                     | mandatory provenance banner and endorsement status (§3.6)       |
| `docs`      | long-lived topic pages (e.g. `wcwc/docs`)                  | replaces ad-hoc `<topic>/` dirs                                 |
| `about`     | site and me                                                | as now                                                          |

Things that are **not content**, so the site generator does not manage them: data areas (Spack build cache, conda channel) and ephemeral drops. They get stable, documented paths that the site links to, and nothing more.

**Every item is a directory** (a Hugo *page bundle*): `content/<section>/<slug>/index.org` plus its images and files. Hugo serves bundle resources next to the page, so relative org links work in Emacs and in HTML alike. Truly shared assets (logo, CSS) go in `static/`. This is native Hugo behavior. It only needs the existing posts moved and ox-hugo set to bundle mode (or bypassed, see Q1).

## 3. Major code development

### 3.1 Site foundation (Hugo upgrade)
- Install the current Hugo extended. Start a fresh site rather than upgrading `~/pub` in place, and copy content over (a clean sweep is allowed).
- Pick or write a minimal theme. My recommendation is a small own layout set: Hugo's stock templates have changed a lot since 2022, and a 4-theme pile is the friction you're describing.
- Templates for each section; a "source" link to the published `.org` file; a revisions block; a talk venue table; an artifact banner.
- Per-target environment configs with audience/visibility filtering. A build-time check fails if a `protected` item would reach a target without auth.

### 3.2 Org → HTML path (decision needed, Q1)
- **A. ox-hugo, bundle mode.** Proven, keeps Hugo shortcodes. It needs an Emacs export step, which is the main source of past friction. `org-hugo-auto-export-mode` plus `hugo server` gives the save → browser-reload loop.
- **B. Hugo reads `.org` directly** (go-org). No Emacs step and instant reloads, but org support is partial (babel results only, limited LaTeX, no ox options).
- **C. `orgface render -m emacs`** produces body HTML, and Hugo (or a small DIY assembler) wraps it.

My recommendation is **A to start**, with orgface driving the Emacs export so the CLI and Emacs paths are the same. Revisit B per section: `notes` would likely be fine with B.

### 3.3 Authoring CLI (`orgface web …` or a standalone `myweb`, Q4)
| command                            | does                                                                                                                                                                                    |
|------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `new <section> "Title" [-t tag…] [--deadline]` | slugify, create the bundle from an archetype, add a `TODO` with `DEADLINE` that org-agenda sees (the repo's `content/` added to `org-agenda-files`, or a pointer entry in `~/org`) |
| `edit <slug>`                      | open in Emacs, ensure `hugo server` (with drafts) runs, open the browser at the page                                                                                                     |
| `status [-t tag] [--section]`      | list open drafts: word count, figure count, TODO state, deadline, last-modified                                                                                                          |
| `check <slug>`                     | final render to a staging dir; link check; babel-results-present check; optional LLM review (spelling, clarity, leaked private info, consistency); the report saved next to the bundle   |
| `publish <slug> [--target]`        | flip `draft`, commit, tag if it's an article/talk revision, build the target(s) **from the checked staging output**, deploy                                                               |
| `search …`                         | delegate to `orgface search` over the site source (index the repo as an orgface store)                                                                                                   |

There is also a thin Emacs layer (a transient menu calling the same CLI) and an `orgface`-style one-shot `note -m` for TILs.

### 3.4 Talks subsystem
- Per-talk metadata file (`talk.org` with properties, or front matter in `index.org`): title, slug, created, topics/projects, **venues** (date, event, Indico URL, recording URL), visibility, source format, PDF(s).
- Generated indices by year, project, topic and venue. Because browsing comes from metadata, the physical layout stops mattering, and a single scheme can be imposed (Q6).
- Protected talks: built only for the `work` (or `sobrieti`) target, under an `.htaccess`-protected path.
- Git: `~/sync/talks` gets a repo whose `.git` is excluded via `.stignore` (already the de facto setup on hokum). Revisions use tags `talk/<slug>/vN`, and the page lists them.
- Later: experiment with HTML slides (reveal.js via `ox-reveal`, or a Hugo slide layout) from the same org source.

### 3.5 Drop service (formalized `see` + `eggs`)
- `drop put FILE [--ttl 7d] [--target bnl|sobrieti] [--note …]` → content-hash name in a non-listable dir, a URL printed or copied, and an entry in a local manifest (who/why/expiry).
- `drop ls`, `drop rm`, `drop gc`. `gc` runs from cron/systemd on the host if allowed, otherwise from your machine over ssh (Q8).
- Kept separate from the site generator. The site only links to it.

### 3.6 Artifacts
- Front matter: `generator` (model), `date`, `prompt` (summary or full), `status` (`unreviewed | read | endorsed | disputed`), `commentary` (your voice, rendered distinctly), `responds_to` (links, possibly to others' artifacts), visibility.
- The layout always shows an "LLM-generated" banner. HTML artifacts are embedded as bundle resources, not re-themed.
- `myweb artifact add FILE` ingests a file Claude produced, prompting for the fields above.

### 3.7 Babel policy (convention plus a small amount of code)
- Export **never evaluates** (`org-export-use-babel nil`, or `:eval never-export` in the setupfile). Results are committed in the `.org`, so they stay as they were when you authored them.
- An explicit `myweb rerun <slug>` evaluates in a recorded per-bundle environment (`pixi.toml`/`pyproject.toml` in the bundle) for reproducibility checks.
- `check` warns if a source block has no results, or if its body hash changed since the results were made (`:cache yes` gives this almost for free).

### 3.8 Search
- Online: **Pagefind** (a static index built after Hugo, works on GitHub Pages). This removes search as a reason to go DIY.
- CLI: orgface over the source repo (full-text and semantic).

## 4. Content transformation and migration

| what                 | size            | how                                                                                                  | who                                     |
|----------------------|-----------------|------------------------------------------------------------------------------------------------------|-----------------------------------------|
| `~/pub` entries      | about 10        | move to bundles, fix links and front matter, drop `static/` indirection, re-export                    | LLM; you review                         |
| `~/pub/org/abort/`   | 1 (interpolation) | decide: drop, or revive as a draft article                                                          | you                                     |
| GitHub `pub` repo    | n/a             | push history to gitea (private); archive or delete on GitHub                                         | you                                     |
| Work `public_html`   | unknown         | **inventory first**: a script you run at BNL writes a manifest (path, size, mtime, symlink target, has index/.htaccess, top-level file types) | LLM writes the script; you run it |
| `tmp/<topic>` areas  | unknown, ~15+ visible | classify each into docs / talks / artifacts / data / drop / delete, using the manifest          | LLM proposes; you decide                |
| Hash-named shares in `tmp/`/`eggs/` | unknown | re-issue as drops with TTL, or let them die (URLs may break)                           | you                                     |
| Talks                | about 180 org, 2 GB, many pre-org talks with tex/PDF only | an LLM pass extracts title/date/venue from org/tex/PDF and dir names into draft metadata; you review venues and visibility; optional relayout | LLM drafts; **you review, the biggest manual chunk** |
| LLM artifacts        | unknown         | collect, add provenance front matter                                                                 | LLM; you set status/commentary          |

Clean sweep: the new work site replaces `~/bviren/` wholesale. Data areas and anything external tools consume (Spack/conda) must keep **their** paths or have those tools reconfigured. That is the one place where breaking URLs matters (Q9).

## 5. Questions to answer before implementation

1. **Org → HTML path**: ox-hugo (A), Hugo-native org (B), or orgface-render (C)? (Recommendation: A, with B for notes.)
2. **One source repo, or two** (personal vs work)? (Recommendation: one, with `audience` filtering.) Can the work site's source live on your personal gitea, or does BNL policy want it elsewhere?
3. **Theme/look**: keep the archie/meathead feel, or start minimal? Are there any sites you'd like it to resemble?
4. **Where the CLI lives**: subcommands of `orgface` (shares its daemon, store and search) or a separate tool that orgface calls? Is orgface's repo/package the right home for site-specific logic?
5. **Agenda integration**: should drafts live in the site repo and be added to `org-agenda-files`, or get a pointer TODO in `~/org`?
6. **Talks layout**: keep the current physical layout and let metadata drive everything, or relayout to one scheme (e.g. `talks/<YYYY>/<YYYY-MM-DD>-<slug>/`)? Should git cover all 2 GB (consider git-annex/LFS for PDFs and tarballs) or only sources?
7. **Protection mechanism**: does BNL allow `.htaccess` Basic auth (and with which user database)? Is `sobrieti.bot.nu` an acceptable home for protected/personal material? Is hash-URL "unlisted" sufficient for most semi-private things?
8. **Drops**: can you run cron/systemd timers on the BNL web host, or must `gc` run remotely? Which host is the default?
9. **Build/deploy location**: does the work site build on the workstation and rsync into `public_html`, or build there directly? Which `tmp/`/data paths are consumed by tools and must keep their URLs?
10. **Git for `~/org`**: in scope now, or deferred? (This plan only needs git for the site repo and `~/sync/talks`, with `.git` stignored and commits from one host.)
11. **LLM review in `check`**: what should it look for? Which model/API (local or Claude), and is sending drafts to an API acceptable for work content?
12. **Revision display for articles**: a full git log per bundle, only tagged versions, or tags plus diffs between them?

## 6. Timeline

The effort figures are rough guesses at focused sessions, not calendar time. "LLM" means work Claude can do in this sandbox. "You" means decisions, review, and anything on the BNL workstation or needing credentials.

| phase | content                                                                                     | LLM                                                                         | you                                                              | effort |
|-------|---------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|------------------------------------------------------------------|--------|
| 0     | Answer §5; create gitea repo; install Hugo                                                  | refine this proposal                                                        | answers, gitea repo, `hugo` on hosts                             | 1      |
| 1     | **Foundation**: new Hugo site, layouts, bundles, port ~10 posts, `personal` target deploys to GitHub Pages | scaffold, layouts, port content, deploy script                    | look/feel review, check ported posts, first push                 | 2–3    |
| 2     | **Authoring loop**: `new/edit/status/check/publish`, Emacs transient, agenda hook, babel policy | CLI, elisp, archetypes, tests                                          | daily-use trial: write one real post through the whole flow      | 2–3    |
| 3     | **Work target**: visibility model, `.htaccess` generation, Pagefind, `docs` section; BNL inventory script | env configs, filters, inventory script                          | run inventory at BNL, confirm protection works                   | 2      |
| 4     | **Drops**: `drop` tool replacing `see`/`eggs`                                               | tool, manifest, gc                                                          | host setup (dir, cron/ssh key)                                   | 1      |
| 5     | **tmp/ migration**: classify manifest, move items into sections/data/drops, cut over the work site | classification proposal, bulk moves, index pages                     | decisions per item, the actual cutover at BNL                    | 2–4    |
| 6     | **Talks**: metadata schema, extraction pass, generated indices, git and tags, protected path | extractor, layouts, draft metadata for all talks                           | **review venues/visibility for about 180+ talks** (spread over time), optional relayout | 3–5 |
| 7     | **Artifacts + revisions**: artifact section/ingest, article revision rendering              | layouts, ingest command, git-history data generator                         | status/commentary on existing artifacts                          | 1–2    |
| 8     | Later: HTML slides experiment, `~/org` git question, semantic site search                    | prototypes                                                                  | judge whether worth it                                           | open   |

Phases 1 and 2 are the critical path: they restore a working, low-friction blog, which is the stated reason the blog stalled. Phases 3–7 are mostly independent after that and can be ordered by what bothers you most. Phase 4 (drops) is small and could jump ahead.

## 7. Risks and notes

- **Old Hugo templates**: Hugo has removed or renamed many template features since 2022 (for example `.Site.Author` and the RSS/pagination internals), so porting `meathead` may cost more than writing a fresh minimal layout.
- **The syncthing + git split** (`.git` on one host only) means commits happen on hokum. That's fine as long as it's deliberate, but a commit from another host would need care.
- **Publishing the `.org` source** exposes comments, `:noexport:` subtrees and private drawers. `check` should strip them or warn before a source file is copied into the output.
- **The 2 GB of talks** shouldn't be duplicated into every build: link or rsync the PDFs separately from the HTML build.
