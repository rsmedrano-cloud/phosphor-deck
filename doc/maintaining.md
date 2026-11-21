# Maintaining Phosphor

How the maintainer and the assistants working with them change Phosphor
itself. Read it before changing anything in this repository, whichever
assistant you are. A pull request from outside only needs CONTRIBUTING.md.
Releases: doc/releasing.md.

The state of the work lives in GitLab issues, the repo and the deck's
notebook, never in one assistant's memory: anyone starting a session rebuilds
the context from them, so keep them current.

## Session protocol

- **Start:** `readlink -f ~/.local/bin/phosphor` (is the live deck running
  this checkout?), `git fetch gitlab`, `phosphor notes | head -40` (the
  latest entries: what was done, what's next), `glab issue list` (`-l p1`
  first). Don't run `phosphor doctor` or `tests/check.sh` just to start.
- **Work on an open issue is pre-approved:** start, don't ask. Ask first only
  for: anything that touches the live deck (a real `gen`, `up`, `update`,
  `restart`, the profile, mounts), a new kind of outward step (announcing,
  a new public service), or a decision the issue leaves open for the
  maintainer.
- **One topic per session, then stop.** Once it's closed (pushed, CI green,
  issue resolved, a `phosphor note --kind done`), say so and suggest a fresh
  session. Don't pull a second topic in.
- **Read by section:** `grep -n`, then a line range. Never paste whole files,
  diffs or logs into the conversation.
- **Answer what they asked.** A change to the shipped defaults
  (`lib/init.py`'s shapes, `profiles/*.toml`) never reaches an existing
  profile by itself: a new element gets an offer in `lib/migrate.py`
  (`tests/shapes-check.py` fails until it has one), a change of format a
  step. The deck runs the code it started with until it restarts. When the
  maintainer asked for something on their own deck, say so plainly and offer
  the matching profile edit (a `deck.toml.bak` first) in the reply itself.
  A topic isn't closed while one of their questions is unanswered.

## Issues are the queue

- **No issue, no work.** Every feature, fix or task has a GitLab issue first:
  goal, scope, acceptance criteria, open questions. Each open issue has one
  priority label: `p1` (the live deck is broken, data leaks, or it blocks a
  release), `p2` (planned for its milestone), `p3` (nice to have; the
  default). Each belongs to a milestone.
- **Comment as it moves:** one comment at the start (plan), one per
  decision, dead end or scope change, and a **Resolution** on close
  (version or commit, what changed, how it was verified, follow-ups). Never
  close an issue silently. Commits say `#n` in the subject or body.
- **Decisions are issues** labelled `decision`: context, options, choice,
  why, consequences. Closed once decided; undecided ones stay open for the
  maintainer.
- **Unverified parts are visible:** what CI can't prove (a real phone, an
  e-ink panel, a real screen) gets `needs-verify` on its issue with exactly
  what to try. The maintainer or a tester removes it.
- **Follow-ups found while working** become new issues, linked from the
  current one. Plans, roadmaps and proposals are issues and milestones,
  never a file in the repo.
- **The notebook** (`phosphor note`) is the log of what happened: a `done`
  note when a topic closes (what changed, what's pending). Assistant memory
  holds only personal preferences, never project state or lessons: a
  lesson goes in "Hard-won rules" below, or better, into a test.

## Who does what

Spend the big model on judgment, not on reading or prose.

- **A script** when one exists: `phosphor docs`, `tests/ci.py`, a grep.
- **A small model** (a subagent, Haiku) for mechanical reading and writing,
  with one precise question: what still describes the old behavior
  (`sweeper`), why a long log failed (`log-reader`), the doc prose for a
  change (`scribe`: CHANGELOG, README, the manual page, from a short
  summary). It answers with `file:line`; you check its diff before
  committing it.
- **A mid model** (Sonnet, in a worktree) for mechanical code changes a test
  covers: a new `share/commands.json` entry, a test, a rename.
- **You** for design, reviews, and anything that kills processes, touches
  the live deck, the profile and its migrations, or privacy.

## Branches and the live deck

- `main` is what people run (stable); `dev` is where work happens
  (nightly). Commit straight to `dev`; push named refs only (`dev`, `main`,
  `vX.Y.Z`) to the `gitlab` remote, never `--all`, `--mirror` or every tag.
- If the live deck runs this checkout, your edits *are* its code: keep the
  tree runnable at every step and end with a commit. Never run a real
  `phosphor gen`, `up`, `update` or `restart` yourself: gen points the live
  deck at the code it ran from, and when the deck takes a change is the
  maintainer's call. `--dry-run` and read-only commands are fine.
- Anything that restarts the deck, rewrites the profile or touches mounts
  gets checked before and after.

## Verify through CI

- `sh tests/check.sh` locally (about two minutes), push `dev`, then
  `python3 tests/ci.py`: one line per job, plus the end of a failed job's
  log. Run long things in the background and wait for the notice; don't
  poll.
- Don't click through the deck or drive screens to check a change: write
  the check into `tests/` (a throwaway zellij, like `tests/edit-check.py`).
  Trying it on real screens is the tester's part; what they find becomes a
  failing test first, then the fix.
- A test that fails now and then goes into `tests/flaky.json` with why
  (`python3 tests/flaky.py` shows the saves, `--tail TEST` how its last
  saved run failed). Never rerun a job by hand to get past one.

## Every change updates, in the same commit

CHANGELOG.md (under `## Unreleased`, written for users), README.md, the
manual page in doc/manual it touches, and AGENTS.md (`phosphor docs`);
`python3 doc/site/build.py` after a manual edit. English only. Before
closing a topic, sweep the docs for the old names and behavior. The
pipeline's docs job fails code changed without CHANGELOG.md
(`[no-changelog]` for a refactor users never see).

## Hard-won rules

Each of these cost a broken release or the maintainer's live deck.

- **Never run zellij, `phosphor gen` or a smoke test from a shell inside the
  deck:** its `ZELLIJ*` variables point every action at the live session
  (tabs leaked into it, 2026-10-01). Tests use their own probe harness
  (`tests/zjprobe.py`) with a socket dir of their own.
- **A temp HOME doesn't isolate /proc.** `restart`/`down`'s reaper and any
  test that kills processes must only touch pids it started (the live tabs
  closed 2026-10-02; the web daemon killed 2026-11-19).
- **Never run a list of tests grepped out of `tests/check.sh`:** its comments
  name `tests/audit.py`, which launches a real agy audit.
- **Wait on a pid** (`while kill -0 PID`), never `pgrep -f pattern`: the
  waiter's own command line matches.
- **Examples and fixtures use made-up names** (`db-box`, `nimbus`, `relay`;
  RFC 5737 addresses like 203.0.113.x), never a real host, user or the
  maintainer's name. The privacy hook scans what's staged: `git add` again
  after fixing a flagged file.
- **The zellij server has no `~/.local/bin` in PATH:** whatever a pane or yazi
  runs needs an absolute path (`gen.PHOSPHOR`). yazi `shell` bindings get no
  `$1`; use its `%s`, unquoted.
- **In tests, never mix `Popen.communicate()` with earlier `readline()`** on
  the same pipe: it split a UTF-8 glyph, in CI only.
- **The repo is the product.** The maintainer's own tooling (recordings,
  scripts for them, roadmaps, proposals) stays outside it
  (`.git/info/exclude`) or in issues; ask before committing anything that
  isn't the deck.
