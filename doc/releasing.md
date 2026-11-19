# Releasing Phosphor

When and how a version goes out. The everyday workflow is in
doc/maintaining.md.

## When

Releases come as topics close, without waiting to be asked: a patch
(1.0.1, 1.0.2...) for each closed topic or batch of fixes, the next minor or
major when its milestone is covered and its bugs are checked. Patches stay
on `dev` (the nightly channel); `main`, the stable channel, only moves at a
minor or major, so users on stable never get half a milestone. A bug that
hurts stable users before then is cherry-picked onto `main` by hand and
released as a patch of that minor.

## Before

- **Open merge requests:** `python3 tests/mrs-check.py`. The pipeline only
  runs on protected refs (main, dev, tags), on purpose: a merge request's
  own branch never gets one, so nobody's code runs on the runner before
  it's looked at. This is the stand-in: a real merge into a throwaway
  worktree, nothing pushed, then the fast checks against the result.
- **Open GitHub issues and PRs:** `python3 tests/github-check.py`. Nothing
  else polls the public mirror; a bug report there only gets looked at
  here. A PR there can't be merged as-is (GitHub's history is squashed
  releases): point the author at an issue instead.
- **Before a minor, an outside audit:** `python3 tests/audit.py` has agy
  (`-p --dangerously-skip-permissions`) audit a throwaway clone of dev with
  no remote, the deck's zellij variables stripped, a zellij socket dir of
  its own and copies of phosphor's profile and data; the report goes into
  the notebook (`--by agy`, "audit VERSION (SHA)"), never the repo. It's a
  second opinion, not a verdict: check each finding against the code, fix
  what holds, then cut the minor.

`tests/release.py` runs the first two and warns about the third, as
heads-ups, not blockers.

## Cutting it

`python3 tests/release.py X.Y.Z "title"` does a dev release from a dev
checkout, stopping at the first problem: checks, VERSION and CHANGELOG,
dev's pipeline, the tag, its pipeline; the pipeline's release job publishes
the notes. Add `--main` for a minor: main is fast-forwarded on the remote
first. Run it in the background with no `timeout`: it waits on two
pipelines, and a run killed after the version commit can't be rerun (finish
by hand: `tests/ci.py dev`, tag and push it, `tests/ci.py vX.Y.Z`,
`glab release view`, then the GitHub sync below).

It never touches the live deck's checkout: the brain takes the release with
`phosphor update` (`--channel nightly` for a dev one), when the maintainer
says so.

## The GitHub mirror

`tests/release.py` also syncs github.com/rsmedrano-cloud/phosphor-deck as
its last step: a squashed commit onto GitHub's own `dev` at every release,
building on dev's previous sync there, never GitLab's granular history. At
a minor, GitHub's `main` is then fast-forwarded to that same commit, so
main is always an ancestor of dev there and GitHub never shows them as
diverged to an outside contributor. Titled after the release, authored as
the maintainer, no AI co-author. Best-effort on purpose: a GitHub hiccup is
printed, not fatal, and never undoes a GitLab release that already
shipped; `sync_github()`, called standalone, does it again.

At a minor only, also a GitHub Release for that tag with the cross-compiled
Rust binaries (`rust/fleet-poll`, `rust/run`; the tag's `rust-release` CI
job builds them for x86_64 and aarch64) attached. `install.sh`'s `fetch()`
reads `releases/latest` there and always installs from `main`, so shipping
binaries at every dev patch would make `releases/latest` drift ahead of
main. Same best-effort spirit (`sync_github_binaries()`, same standalone
rerun).

Announcing it anywhere beyond the repo (Hacker News, Reddit...) stays the
maintainer's call.
