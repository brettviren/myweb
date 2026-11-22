Decisions from questions in proposal.md

First, one general decision.  I want to go "all in" on datalad / git-annex.  I pick `~/keep/` as the top level dataset into which I will import/copy or begin a new sub-dataset for each of:

- current `~/org/` to `~/keep/org/`
- current `~/sync/talks/` to `~/keep/talks/`
- new `~/keep/web/` to hold transformed version of current `~/pub/`

These areas will have peers across my accounts.  We leave existing `~/org/` and `~/sync/talks/` in place until we get this new paradigm working on this host (hokum) and then get the `~/keep/` top level dataset replicated across my other accounts, an in particular hierocles which is ultimately the server of my `public_html` directory.  In the interim we will publish to my local `~/public_html/` for testing on hokum.  And to start with, the top `~/keep/` dataset and its three sub-datasets will be local-only.  At some point I will look how to add at least the `web` dataset to gitea.

Individual answers to questions in the proposal.md file:

Q1. Accept recommendation (A, with B for notes).

Q2. All of `web` is one repo and audience filtering is used.  `talks` is separate due to its size.

Q3. The theme should be simple and plain and I'll likely want to change it from time to time.  In general web content should render nicely as plain HTML even when viewed in a browser without javascript support and/or in a terminal-based browser.  Some special cases may still use javascript, eg for interactive demos.

Q4. For now, let's develop a small Python CLI in this `myweb` directory.  We will keep it simple and I will later decide if/how we may combine with orgface.  I do have a few ideas to make that conceptually general to fit nicely into orgface by using configuration to associate a taxon to various things like source paths.  We should follow that idea in `myweb` and if it works out, migrate it into orgface while we also make orgface's existing commands more conceptually generic.  For example each taxon in a taxonomy may have a configuration section diving source directory and a deployment path.  A `myweb new` is then a taxon-parameterized version of `orgface log` and `orgface note`.  But for now, implement the subcommands to a new `myweb` as in proposal.md

Q5. Add drafts to org-agenda-files if a date is given.

Q6. As above, use datalad/git-annex for talks. We will need to map current `~/sync/talks/` patterns into the a new tree structure in the new `~/keep/talks/` sub-dataset.  I think an amalgamation of what we have in sync is best so we would have `~/keep/talks/<group>/<yyyy>/<mm>/<dd>/<topic>/<talk>/`.

Q7. I admin both the backend server (hierocles, my Debian desktop) and the frontend, reverse proxy (www.phy.bnl.gov).  Both `.htaccess` basic auth and unlisted/hash URLs are acceptable given the level of security needed.  The new `drop` command should be able to handle open index, adding an empty `index.html` to block directory listing, hash directory or file names, `.htaccess` for basic auth.  `drop` should also handle aging out of entries and auto removal after their time-to-live expires.

Q8. Standardize on systemd but also support cron.  A `drop setup [systemd|cron]` shoudl be provided.

Q9. A command from `myweb` should handle building into a given local target directory, eg `~/public_html` and optionally rsync'ing that target to a remote.  It should also support triggered building on a remote.  For example, via git hook or cron/systemd.  A `myweb setup [systemd|cron|git]` should also be provided to make those hooks.

Q10. We will leave current sources as-is and populate new ones as described in the general decision.

Q11. Let's defer this for now.

Q12. I don't know how best to do it but let's a versin using `git describe` run at an appropriate time to mark the state of the git repo, eg for the `~/keep/web` sub-dataset.  This version string can be kept in `version.txt` files though, of course adding/modifying them changes the next `git describe` output so some particular generation workflow is needed.  Once made, it should updated if and only if the content it represents changes.

This session should have write access to `~/keep/`, `~/dev/{drop,myweb}` and `~/.config/{drop,myweb}` and `~/public_html/` which is currently empty.  Develop `drop` and `myweb` and initialize datalad dataset and subdatasets under `~/keep` and configure myweb for the latest hugo and install hugo via uv and port current `~/pub/` to `~/keep/web` and get deployment to local `~/public_html` working.  After testing that we will come back and start working on migrating the talks.

