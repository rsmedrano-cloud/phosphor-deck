# Contributing

**Everything you need. Nothing you don't.** (borrowed, gratefully, from
SolarOS)

A change belongs upstream when it serves anyone running a deck, measured
against the project's four tests:

- the screen doesn't invade the room;
- quick access to what matters;
- moving between devices without drama;
- what you left on one device is there on the next.

Things that are yours — your machines, your chat server, the assistant and
documents you prepare notes with — go in your profile, not in the code. A
feature existing in your fork is not, by itself, a reason to merge it.

Before a pull request:

- `sh tests/check.sh` passes: the fast checks, seconds, no docker;
- `python3 tests/edit-check.py` passes if you touched keys, tabs or the +
  menu: a throwaway zellij in its own HOME, driven by keys and taps (needs
  zellij; `tests/fetch-zellij.py` gets one);
- `sh tests/from-zero.sh` (also `DISTRO=ubuntu|fedora|arch`, files in
  tests/distros/) and `python3 tests/tester-sim.py` pass (docker: a
  clean install in a systemd container);
- `python3 tests/update-check.py` passes if you touched updates or channels
  (needs git).

GitLab (`.gitlab-ci.yml`) runs all of them on the brain's own runner, and
only for protected refs (main, dev, v* tags): nobody's code runs on the brain
without the maintainer pushing it, so a merge request is checked locally
first. After a push, `python3 tests/ci.py` waits for the pipeline and prints
only what matters: a line per job, and the end of a failed job's log. A bug
found by hand becomes a failing test before it's fixed. The rest of the list:

- `phosphor docs --check` passes: a change in behavior updates doc/manual/,
  and AGENTS.md is rebuilt with `phosphor docs`;
- CHANGELOG.md says what users get, under `## Unreleased` (the pipeline's docs
  job fails code without it; `[no-changelog]` in the commit for a refactor);
- `phosphor privacy` is clean;
- comments only where a choice isn't obvious.

## Python, POSIX sh, and where Rust pays off

Phosphor is Python + POSIX sh because it's glue around zellij/ssh/rclone/
systemd and the design keeps moving; that stays the default. Where a piece
is long-lived or multiplied across panes rather than one-shot, and rewriting
it in Rust pays off in memory or reliability, it can get one -- always
**optional and additive**: a Python fallback stays the only thing a plain
`sh install.sh` ever needs, and nothing breaks for a checkout without a Rust
toolchain. Two so far, each with its own README for how it's wired in
(or isn't yet) and how to build it: `rust/fleet-poll` (feeding `phosphor
fleet`'s `fleet.json`, picked up automatically when it's installed) and
`rust/run` (`lib/run.py`'s watcher, every pane -- not picked up automatically
yet; try it on one tab by pointing that pane's `cmd` at the built binary).
Neither's `cargo test` is in `tests/check.sh` yet -- CI's images
(`python:3.12-slim`, `alpine`) don't carry a Rust toolchain, and adding one
is its own topic, not bundled into a module's first pass. Run them by hand
from each crate's folder until that's sorted out.

## Branches

`dev` is where work happens; `main` is what stable users run. A topic is done
when its tests pass on `dev`, with a CHANGELOG.md entry written for the people
who use it, not for the code. Patch releases (0.2.x) stay on `dev`, the nightly
channel; `main` only moves when a minor version is done (0.3.0), so stable
users never get half a milestone.

What's done but not released goes under `## Unreleased` at the top of
CHANGELOG.md; a release turns that heading into the version. Not every merge
is a release: small things wait until there's something worth announcing,
and the "new version" notice only fires when VERSION changes.

A release is one command from a dev checkout: `python3 tests/release.py
0.2.0 "a short title"`. It checks where it stands, bumps VERSION, turns
`## Unreleased` into the version, waits for dev's pipeline, pushes the tag
and waits for its pipeline (`--main` for a minor: it fast-forwards main first);
a tag's pipeline publishes its release notes from CHANGELOG.md once every test passed.
