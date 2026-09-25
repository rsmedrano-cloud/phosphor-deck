# Release notes

What each version brings, newest first. `phosphor version` shows the part
you don't have yet when a newer one is out, and so does `u` in the DECK tab
before it updates.

## Unreleased

## 1.0.3 — rust/python parity restored, cargo test now in CI

- Fixed: the two Rust rewrites (`rust/fleet-poll`, `rust/run`) had quietly fallen out of parity
  with their Python originals -- caught by an independent audit, not by CI: `rust/fleet-poll`
  still sent fleet alerts with `--tab FLEET` (the bug 1.0.1 fixed in `lib/fleet.py`), and
  `rust/run` still retried `--reconnect` on a flat 3s timer with no backoff (the bug 1.0.2 fixed
  in `lib/run.py`). Both now match their Python side exactly.
- New: `cargo test` for both Rust crates now runs in CI, on every push, as its own `rust-test`
  job -- it never ran there before, which is exactly how the divergence above went unnoticed.
- Fixed: `tests/hang-check.py` didn't isolate `PHOSPHOR_CACHE`, so every local `sh
  tests/check.sh` run wrote a real "PROBE hung" line into the actual `~/.cache/phosphor/deck.log`
  -- 265 of them, found while tracking down the fleet/reconnect bugs above. Existing entries are
  harmless leftovers (deck.log carries no personal data), but the test is isolated now, same
  pattern `tests/run-rust-check.py` already used correctly.

## 1.0.2 — reconnect backs off instead of hammering a dead link

- Fixed: `phosphor run --reconnect` (every ssh pane) retried a dropped link every 3 seconds,
  forever, with no backoff -- fine for a blip, but a real outage hammered the remote host the
  whole time it was down (one incident in the wild: 6 hours, 2055 attempts, found going through
  deck.log). Now doubles the wait each consecutive failure, capped at 60s, and drops straight
  back to a plain 3s the moment a connection actually holds for 30 seconds or more.

## 1.0.1 — fleet alerts mark the real tab, docs catch up to 1.0

- Fixed: a fleet host going down or coming back marked a tab named "FLEET" -- which never
  existed (the fleet card lives inside the SYS tab, alongside pulse and the adjutant), so the
  "SYS ●N" mark it should have set never got there for a new alert, and worse, once one was
  already showing there was nothing left tracking it to ever clear it, however many times you
  looked at the tab. Fleet alerts now correctly mark SYS, the same tab the doc always said they
  did. If yours is stuck: `phosphor restart` -- `phosphor gen` won't touch it, this is live
  session state, and a restart reloads the tab names fresh from your profile.
- Docs: README's "## Status" line still said 0.3.0 (this project's first public version) three
  releases after it stopped being true. Fixed, along with a few version examples elsewhere
  (CONTRIBUTING.md, doc/manual/install.md, `phosphor docs`'s own release-policy rules) that were
  still anchored to the 0.2.x/0.3.0 era.

## 1.0.0 — phosphor commands, and the other direction: phosphor receive

- New: `phosphor commands` (also `e` in the DECK tab) -- a categorized, drill-down index of
  every phosphor subcommand: pick a category, then a command, the same categories the manual
  and README already use. A read-only one (`share/commands.json` says `mutates: false`) runs
  right there when you pick it; anything else shows its usage and copies the invocation to
  every screen's clipboard instead of guessing at missing arguments (a file, a host, a message)
  for you.
- New: `phosphor receive [--dir FOLDER] [--timeout SECONDS]` -- the upload-direction mirror of
  `phosphor send`: a one-time link and QR, same tailnet-or-LAN reach, but a form to send a file
  in instead of a link to download one. It lands in `~/received` (or `--dir`), never overwriting
  one that's already there. For getting a real file (a photo, a screenshot) from whatever
  device you're actually holding onto this machine -- an AI assistant running in a pane here
  can then read it directly, no detour through copying it by hand and typing "I left it in ~/x".

## 0.4.4 — ask reads a pipe, README finds its categories

- Docs: README's command table was one long undifferentiated list of ~45 rows -- split into
  the same categories the manual already uses (Getting started, Session, Workspaces, Notes, In
  the deck...), so skimming it for the first time doesn't read as a wall.
- New: `phosphor ask` reads a pipe. `git diff | phosphor ask "what changed here"` sends the
  diff and the question together (the pipe first, as context); with no question at all, the
  piped text alone is the prompt.

## 0.4.3 — middle-click paste, documented not built

- Docs: why middle-click paste (X11/Wayland primary selection) doesn't come from a plain
  drag-select in the deck, and the fix that needs no code -- hold Shift (Option in iTerm2)
  while selecting to bypass zellij's `mouse_mode` and use your terminal's own selection, which
  does feed the primary selection. No behavior changed; see doc/manual/clipboard.md. (#24)

## 0.4.2 — don't act unattended without a real client

- Fixed: `phosphor web on` used to restart the live deck unconditionally once its own
  confirmation pause was skipped -- which happens automatically without a tty (a script, a
  cron, a policy tool), not just when a human presses Enter. It now only restarts on its own
  with a tty, or with the new explicit `--yes` flag; without either, it still publishes and
  prints the token, but leaves the restart to you. (#38)
- Fixed: `phosphor new --here` (what Alt-n and the tab bar's + actually run) called `zellij
  action new-tab` with no check that a client was attached to the session -- exactly the
  pattern AGENTS.md warns assistants never to do by hand. A real keypress always has a client
  attached by construction, so this only ever mattered for something driving the deck out of
  band; it now refuses instead of adding a tab when `zellij action list-clients` names none.
  It also now requires an actual pane context (`$ZELLIJ`) before even asking that: with none at
  all, zellij falls back to "the only session running" on its own, which on a real box is
  someone's live deck -- caught this the hard way while testing the fix itself. (#39)

## 0.4.1 — phosphor ask, and a manifest of what's safe to automate

- New: `share/commands.json` -- a machine-readable manifest of every `phosphor` subcommand,
  saying whether it mutates live state (the session, a systemd unit, the profile, or a
  generated file) and whether it needs the deck already running, with a note where a flag or
  an interactive key changes the plain answer. For a CI job, a cron, an external policy/guard
  tool, or another assistant working in this repo -- the classification AGENTS.md's own rules
  already implied, now written down instead of left to prose and judgment calls. (#37)
- New: `phosphor ask "question"` -- a one-shot question, no tab. Shells out to whichever
  assistant CLI is already installed (claude, gemini, codex, opencode, aider -- the same list
  `phosphor workspace` knows) in its own headless, single-answer mode and prints the reply.
  `--assistant NAME` picks one instead of the first installed. (#35)

## 0.4.0 — the deck that tells you: tab marks, dirty workspaces, self-healing mounts

- `phosphor glance` and the DECK tab's status line now call out a workspace with uncommitted
  changes, or commits ahead/behind its upstream -- "one device, then another" makes those easy to
  forget which machine has. A fresh workspace's own scaffold (`AGENTS.md`, `NOTES.md`...) gets
  committed when it's created, so a brand new workspace starts clean instead of showing up dirty
  from day one.

## 0.3.5 — self-healing fleet mounts, real Rust binaries, and aider

- Fixed: a `~/fleet/<host>` mount (rclone sftp) whose transport died -- a remote sleeping or
  changing IP over Tailscale, most often -- used to stay broken forever: the kernel still lists
  it as mounted, so nothing noticed, and a fresh rclone can't mount over a mountpoint it still
  considers busy from the dead one. `phosphor fleet` now sweeps for it in the background (every
  20s) and self-heals it (`fusermount -uz` then a unit restart); `phosphor doctor` calls out a
  zombie mount by name instead of reporting it as healthy.

- `install.sh` now fetches the optional Rust rewrites (`rust/fleet-poll`, `rust/run`) on
  x86_64/aarch64, same as zellij/yazi/btop: a new `rust-release` CI job cross-compiles both for
  both architectures at every tag, and a minor release (`tests/release.py --main`) attaches them
  to a real GitHub Release for `install.sh`'s fetch to find. Still entirely optional -- missing,
  or on 32-bit ARM, both tools fall back to Python exactly as before.

- `phosphor workspace` (and the notebook's `c`) can now start a workspace with **aider**, alongside
  claude, gemini, codex and opencode. It resumes across restarts like claude does
  (`--restore-chat-history`), and gets its own onboarding message on first launch too, even though
  aider's `--message` normally answers once and exits: it answers that one message non-interactively,
  then hands off to a normal interactive aider that reloads the exchange from its chat history.

- A workspace's tab now marks itself (`<TAB> ●N`, same mechanism as a chat mention) the moment its
  `NOTES.md` changes -- the only channel a workspace's assistants have to hand off work, and until
  now nothing signalled a new entry landed there short of polling it by hand.

## 0.3.4 — ssh multiplexing, and a real undo depth for the profile

- A profile write (`phosphor setup`, `keep`, `tabs`, `shortcuts`, a new tab from `+`, a tunnel,
  `web on/off`, `init` over an existing one) now keeps up to three backups (`deck.toml.bak`,
  `.bak.2`, `.bak.3`), rotating the oldest out, instead of one slot every write overwrote --
  `phosphor setup` then a recipe, back to back, used to lose the setup-time backup.

- Fleet: ssh multiplexing (`ControlMaster=auto`, `ControlPersist=60s`) -- a full handshake on the
  first poll of each host, every poll after that rides the same connection instead of opening a
  fresh one every 15s. Cuts both the CPU cost of repeated key exchange and the login-every-15s
  noise a polled host's own auth log used to get.

- Fixed: `phosphor restart`/`down`'s new duplicate-process check (0.3.3) counted matterhorn,
  yazi, btop, ctop and gping by name alone, machine-wide -- on the same machine the tests were
  run from (the brain itself, running a real deck) it always found the live deck's own panes
  too and called them duplicates. Scoped to the session just restarted, the same
  `ZELLIJ_SESSION_NAME` mark `reap.targets()` already uses.

## 0.3.3 — notes search, and a restart that waits for proof

- `phosphor notes`: `/` searches title, body, author and tab at once (case-insensitive) over
  what's already loaded -- no new file reads. Enter applies it, Esc cancels, an empty query
  clears it; the header shows the active search and the entry count updates as you'd expect.

- `phosphor restart` (and so `phosphor update`) no longer starts the new deck until the old one
  is proven gone: zellij no longer lists the session, `deck.service` isn't still active, and no
  process of it survived the reaper. If any of that fails it stops there, names what's still
  alive, leaves the watchdog off and exits non-zero -- before, it only printed how many processes
  were left over and started the new deck anyway, so new code on disk could run next to old
  panes. `phosphor down` checks the same and exits non-zero too. Reads `/proc` directly for
  this, not `ps` -- not every minimal install has `procps`, CI's own slim image included.
- `phosphor update` now exits non-zero when the install fails (and then doesn't restart the
  deck at all) or when the restart doesn't finish cleanly, instead of always reporting success:
  an unattended update (cron, a timer) can tell. Run from a pane inside the deck, the restart
  still detaches, so there the exit status only covers the install.

## 0.3.2 — phosphor notify marks the tab it came from

- `phosphor notify` now marks the tab it came from (`--tab`, or SYS with none) with "`<TAB> ●N`"
  even with `[deck] notifier = false` (the default, no floating panes) -- the same mechanism
  mentions.py already used for "COMMS ●2", generalized so a notification never leaves you with
  nothing on screen. Cleared the moment you actually look at that tab.

## 0.3.1 — install.sh finishes the job on a clean machine

- Fixed: `install.sh` on a genuinely clean machine (`curl -fsSL .../install.sh | sh`,
  nothing cloned yet, no `PHOSPHOR_REPO` set) used to download every deck binary and then quietly
  give up on getting the actual code, leaving `~/.local/bin` full of zellij/yazi/btop and no
  `phosphor` command. It now falls back to cloning the public repo in that case. The README and
  manual show the real, working curl command instead of a `…/install.sh` placeholder.

- README: links to the manual's own GitHub Pages site (next to the logo, and again in "The
  manual"), a "Built on" section crediting zellij/yazi/btop/gping/ctop/rclone by name, and a
  "Status" section that actually says 0.3.0 and public instead of the stale "not published yet".

- A mark: `doc/img/logo/logo.svg` (and rasters at a few sizes) -- the deck's own tab layout, one
  pane lit, in p31 green. In the README header, and as the manual site's own favicon and nav logo.

- The manual is now also a website, rebuilt: `site/` (Astro + Starlight) replaces the earlier
  Jekyll `docs/` -- full-text search, a real sidebar and next/previous links, and code blocks
  framed like a terminal, all from the exact same doc/manual/*.md `phosphor help` and
  `phosphor docs` (AGENTS.md) already read. `doc/site/build.py` turns each manual page into
  `site/src/content/docs/manual/*.md` (never edited by hand: `tests/site-check.py` fails the
  same way `phosphor docs --check` does when someone edits the manual and forgets to rebuild
  it) and copies doc/img into `site/src/assets/img`. `.github/workflows/pages.yml` builds and
  publishes it on every push to main that touches the manual, the images or the site itself;
  CI's own `site` job (`.gitlab-ci.yml`) runs that same build on every push, so a broken one
  is caught before it ever reaches that workflow. Needs Node 22+ to build (`cd site && npm
  install && npm run build`) -- nothing else in Phosphor does, and the deck itself still
  doesn't. The site itself picks up Phosphor's own screen colors: a select in the nav (gear
  icon) switches between p31 green, p3 amber, p4 white and paper, the same four the profile's
  `theme` key offers, remembered per visitor. Content also stretches to a real monitor's width
  instead of a phone-width column, and the page leans into the CRT it's named after -- faint
  scanlines, a soft vignette, and a phosphor glow on the site title, the hero and the current
  page in the sidebar (paper skips all of it: paper doesn't glow).

## 0.3.0 — screens, faster updates, and Rust underneath

- Fleet: a host that's missed a couple of polls in a row (still gets the full 6s connect / 25s
  poll window the first two times -- a real blip deserves the benefit of the doubt) now gets a
  short 2s/5s probe on every round after that, instead of dragging the whole fleet's refresh time
  by the full window forever. Same change in both the Python poller and the optional Rust one.

- `phosphor restart`/`down`/`up`, and a screen's own `deck` waiting for either: several fixed
  waits (`sleep(2)`, `sleep(1)`...) between kill-session and delete-session, between a SIGTERM and
  a SIGKILL round, and while polling for the session to come back are now `poll_until()` --
  checking every 150ms instead of blindly waiting the full amount, same worst-case timeout as
  before. The common case (already dead, already back up well before the deadline) resolves in a
  fraction of the time instead of always paying the full fixed cost.

- `phosphor update` no longer always restarts the whole deck. Every pane is already its own
  process, so a pull that only touched one tool's own module (`lib/fleet.py`, say) now refreshes
  just the panes running that tool, in place, live -- other tabs, other panes, the session itself,
  none of it touched (`lib/hotswap.py`, reusing the exact `zellij new-pane --in-place` primitive
  `phosphor edit`'s own "swap the program" already uses). Anything shared -- the layout generator,
  a zellij config change, anything outside `lib/` -- still gets a real `phosphor restart`, same as
  always; that judgement call stays conservative on purpose. `--full` skips it and always restarts.

- `rust/fleet-poll`: `phosphor fleet` now supervises the optional Rust poller instead of just
  launching it once. A crash relaunches it; a rebuild (its mtime changes on disk) hot-reloads it
  within a second, live, no restart of the pane or the deck; a real crash loop gives up on Rust
  for that pane and falls back to the Python poller, so the panel keeps updating either way.

- `phosphor tabs --forget NAME` and `--closing`: the same forget (out of your profile, comments
  and `deck.toml.bak` kept) and the same "is this pane a kept tab's last program?" check, without
  the picker -- for scripting, and now also for `rust/run` (next entry) to call into instead of
  reimplementing profile edits itself.

- `lib/run.py` (every pane's watcher: spawn, close it if it froze, banner and Enter/x/l when it
  ends, ssh reconnect) has an optional Rust rewrite, `rust/run`, its own README. Not wired into
  any pane by default -- point one tab's `cmd` at the built binary to try it. The one thing it
  doesn't reimplement on purpose: a kept tab's `f` (forget it) still shells out to `phosphor tabs
  --forget`, the previous entry, rather than editing deck.toml itself. Verified in a real pty,
  the same frozen/healthy/busy shapes `tests/hang-check.py` already uses against the Python one.

- Fleet: an optional Rust poller (`rust/fleet-poll`, its own README). Not built or fetched by
  `install.sh` -- put a hand-built `phosphor-fleet-poll` in `~/.local/bin` and `phosphor fleet`
  uses it instead of its own Python thread; remove it to go back, nothing else to undo. Same
  ssh, same `fleet.json`, same host-name-free logging. Second step of the "use Rust where it
  pays off" effort from the previous entry; `phosphor run` is the bigger one, still ahead.

- Fleet: the FLEET card now draws from `fleet.json` (the same file `glance` and the adjutant
  already read) instead of the poller's own in-memory state -- no visible change, but whatever
  writes that file next doesn't have to be this same Python process anymore. First step of a
  standing "use Rust where it pays off" effort; the poller itself is next.

- Fleet: every poll is now tagged with how long it took. `phosphor logs fleet` always logs the
  first poll round's total time (what "polling..." actually waits on) and flags any later round
  over 3s -- without naming which host, since deck.log is meant to be safe to paste into an
  issue. A slow or unreachable host's own FLEET card says so directly instead ("slow poll: Ns",
  or the seconds it took to fail).

- `phosphor screens` (also `v` in the DECK tab): who's attached to the deck right now --
  where each screen is from, how idle it's been -- and `x` (twice) to kick one loose. zellij
  ties a tab's whole size to its smallest attached client with no setting to change that, so
  this is for the phone squeezing your pane down without having to walk over and detach it
  yourself. A kick just ends that one ssh connection; its own `deck` wrapper reconnects on its
  own in a few seconds.

- README: a "Footprint" table under Requirements — RSS and CPU at rest, measured
  (`tests/bench.py`, a new throwaway-session benchmark, never the live deck) on
  homelab's own hardware, one shape at a time; plus a first phone battery number
  (Android's own battery screen, a real phone, mixed use over 3h).

## 0.2.28 — notifications that reach you, not just the deck

- Fleet health and chat notifications now reach your phone too. A host going down or coming back,
  and a chat mention or DM, call `phosphor notify` themselves -- push if `[push]` is on, spoken if
  `[tts]` is on (a fleet blip only speaks with the new `[tts] fleet_alerts` also on, so a machine
  nobody's looking at doesn't talk over you), the floating toast if `notifier` is on. A flapping
  link alerts at most once a minute per host, never for a host that was already down before this
  session started watching it. `phosphor notify`'s own events file now honors `PHOSPHOR_CACHE`
  like everything else `phosphor demo` isolates -- it used to hardcode `~/.cache/phosphor`.

- `phosphor push [--qr]`: `[push]`'s status (on/off, server, topic), or a QR (and clipboard link)
  that subscribes in the phone's ntfy app without typing the server and topic in by hand. The
  manual's `[push]` section also has a recipe for a self-hosted ntfy server (one binary, no
  Firebase, plain HTTP over a tailnet) instead of the public ntfy.sh.

## 0.2.27 — CI history, an isolated demo, a mitigation for #14

- `phosphor update` no longer breaks half way when the new version changes a helper the old one had
  already loaded (it reloads them after the pull).
- The manual's `phosphor glance` example over ssh was missing the full path (`~/.local/bin/phosphor`):
  a plain ssh command gets no login shell, so a bare `phosphor` isn't found, same as `deck`.
- `phosphor notify`'s floating toast (`notifier = true`) only touches the tab it actually showed on
  now, both to show it and to hide it again, instead of looping `hide-floating-panes -t` across every
  tab whether it needed it or not -- that loop was the only clue behind a real zellij 0.45 freeze (issue
  #14), so doing less of it is lower-risk even without an isolated repro. Along the way: showing the
  toast with no tab named could itself fail ("Tab not found") when called from outside the client; it
  now names the tab explicitly, the same fix.

- `phosphor demo` no longer touches the machine's own data. It read the real chat feed (mentions), the
  adjutant's events and the fleet cache of whatever machine it ran on, so a demo could show a real
  sender's name and message, and it overwrote the real fleet cache. Everything it reads or writes now
  lives in `~/.cache/phosphor/demo-state` (PHOSPHOR_DATA and PHOSPHOR_CACHE point the tools there).
  What it can't hide is the machine's user and host name: run it, for a public screenshot, on a
  machine whose user name you'd show.

- `phosphor ci` (the CI card in SYS): shows a history of the last five pipelines under the latest one, so
  an idle repo still says what happened; lists every job of a pipeline (it dropped some before, and
  showed a retried job twice); a failed refresh keeps the last card marked "stale" instead of turning it
  red; a 404, 401 or 403 says what it means (private project: `glab auth login` or `GITLAB_TOKEN`); and
  one broken pipeline no longer takes the whole panel down.
- The CI card showed "Not Found" for a private GitLab project: a pane runs with systemd's PATH, which
  lacks `~/.local/bin`, so it never found `glab` and had no token. It (and `phosphor review`) now look
  there too.

## 0.2.26 — Distro tests, release policy, templates

- The install from zero is now tested on Ubuntu 24.04, Fedora and Arch as the brain, in a systemd
  container on every push (Debian 12 already was). `DISTRO=ubuntu sh tests/from-zero.sh` runs one.

- Release policy: while a minor version is being built (0.2.x) every patch release stays on dev, the
  nightly channel; main, the stable one, only moves when a minor is done (0.3.0). Stable users no
  longer get half a milestone.

- The repository has issue and merge request templates (GitLab and GitHub) and ignores `.env`, logs and editor folders.

## 0.2.25 — README that shows the deck

- README: a Quick start at the top (try `phosphor demo` first) and a requirements table, and a screenshot of the paper (e-ink) theme, and the other screenshots redone without missing-glyph boxes.

## 0.2.24 — Push notifications to your phone

- Push notifications: `phosphor notify` can now reach your phone even when nothing is attached to the
  deck -- the ntfy app rings, vibrates and shows it, Termux open or not. The brain often lives in a
  rack where a spoken notice (`[tts]`) has nobody to hear it. Off by default: add a `[push]` section
  (see the profile page) with a topic; `phosphor notify --push "hi"` tests it, `--no-push` skips it.

## 0.2.23 — phosphor send: the link on every clipboard, and clickable

- `phosphor send`: the link is now also a clickable hyperlink (OSC 8) and lands on the clipboard
  of every screen looking at the deck, so on a phone it's one paste into the browser -- no QR
  scan, no copying it out of the next column. The QR stays for when there's no second device.

## 0.2.22 — yazi c s / c t pass the file

- Fix: yazi's `c` `t` / `c` `s` got no file at all ("exited with status code 1"): yazi's `shell`
  action passes no `$1`/`$@`, only its own `%s` placeholder, which it escapes for you (spaces and
  quotes in names included). `phosphor gen` writes that now; run it again to pick it up.

## 0.2.21 — yazi's c s / c t work inside the deck

- Fix: yazi's `c` `t` / `c` `s` failed with "exited with status code 127" inside the deck (the zellij
  server has no `~/.local/bin` in its PATH, so a bare `phosphor` isn't found). `phosphor gen` now
  writes the absolute path into `keymap.toml`; run `phosphor gen` again to pick it up.

## 0.2.20 — a real file to your phone: phosphor send, and yazi's c t / c s

- `phosphor send FILE`: a real file (any size or type), not just text -- a
  one-time link and QR on your tailnet (or LAN without one), gone the
  moment it's downloaded or after a timeout (default 180s) if nobody comes
  for it. The deck-native version of the "open a port, send the file,
  close it" script.
- yazi, on the hovered file, no shell tab needed: `c` then `t` copies its
  contents onto every screen's clipboard (`phosphor clip`), `c` then `s`
  sends the file itself (`phosphor send`) -- next to yazi's own
  `c`-path/`c`-url copies. `phosphor gen` writes both into yazi's
  `keymap.toml`; a `keymap.toml` of your own is left alone.

## 0.2.19 — the update cache never lies about being behind

- Fix: `phosphor version` (and the DECK tab's "new version: u") could
  announce an *older* version than the one you're already running --
  `git merge --ff-only` a clone straight to a newer commit (as `main`
  needs after a dev release) left the update cache pointing at whatever
  was newest at the last check, and it was never compared against your
  current version, only checked for a difference. It's now compared
  properly, and a commit that moves under the cache marks it stale so the
  next check refreshes it well before its normal 6-hour interval.

## 0.2.18 — glance and review: a small-screen panel, and MRs/PRs from the deck

- `phosphor glance`: a read-only summary for a small screen -- the fleet's
  problem hosts (or "all N ok"), unread mentions, open todos -- that
  refreshes on its own without a zellij attach. Meant for `ssh -t
  you@brain phosphor glance` from a Pi with a small display, or anything
  too narrow for the full deck. Supersedes the earlier plan (2026-09-12
  notes) to build this as a separate Rust panel on a Pi: no such project
  ever got started, and reusing the fleet/mentions/notes caches this way
  needed no second codebase. Closes #12.
- `phosphor review`: open merge/pull requests from the deck. Detects GitLab
  or GitHub from this repo's remote and drives `glab`/`gh` -- CI status
  (reusing `phosphor ci`'s own fetchers), conflicts, the diff (through
  `delta` if you have it), and `t` to check the branch out into its own
  worktree and try it, never touching your working copy (same spirit as
  `tests/mrs-check.py`). Closes #11.

## 0.2.17 — services in SYS: phosphor's own systemd units, and any you add

- Services in SYS (`phosphor services`): a new SYS panel listing systemd
  units and their state -- Phosphor's own (the deck's service and watchdog
  timer, one `fleet-*.service` per mounted host, one per tunnel) always
  show up, straight from what `phosphor gen` writes; `[services] extra`
  adds your own homelab units (system scope by default, `"user:"` prefix
  for one of yours). `failed` and a unit that doesn't exist are the only
  loud colors -- `inactive` isn't treated as a problem. New installs get it
  in the default SYS layout; existing profiles add it by hand (`phosphor
  keep` after adding the pane, or edit the profile directly). Closes #13.

## 0.2.16 — pane titles, and real screenshots

- README screenshots now come from `phosphor demo`: real captures of the
  SYS and DECK tabs, plus a new one showing the SYS tab narrowed to a
  phone. Fix: every pane's zellij title used to be its full command line --
  `/home/you/.phosphor/phosphor run --name PULSE -- ...`, your install path
  and username, framed at the top of every pane and in every screenshot
  (the two README images this replaces had been showing it since they were
  first added). `phosphor gen` now gives each pane the same short name
  `phosphor run --name` already uses (PULSE, FLEET, SHELL...) as its zellij
  title too, on the real deck as well as `phosphor demo`.

## 0.2.15 — every tool follows theme

- Every tool follows `theme`, not just zellij and the web client. `phosphor
  gen` now recolors yazi (`theme.toml`), btop (its own `phosphor` theme,
  wired up as `color_theme` in `btop.conf`), and passes gping and ctop
  their color on the command line -- ctop only tells light from dark, so
  paper is the one theme that inverts it. A theme you set yourself on any
  of them, gen leaves alone. Closes #21.

## 0.2.14 — phosphor demo: session isolation, actually

- Fix: `phosphor demo`, run from a pane inside your real deck, could land
  its made-up tabs in that live session instead of a throwaway one --
  ZELLIJ_SESSION_NAME (and friends) leaked in from the shell and zellij read
  it as "the session you're already in". Stripped before building the
  background session.

## 0.2.13 — demo mode: made-up machines, for a screenshot

- `phosphor demo`: a throwaway session over made-up machines and a made-up
  notebook, so a screenshot or a recording never shows a real IP, hostname
  or note. Fleet fakes plausible, drifting readings instead of polling ssh;
  its own profile and notebook, never your real ones. `phosphor demo --stop`
  tears it down. Closes #9.

## 0.2.12 — phosphor premium: TTS notifications, courtesy of GLaDOS

- Text-to-Speech (TTS) notifications module (`phosphor tts`). Notifications
  sent with `phosphor notify` can now be announced aloud with selectable voice
  profiles (`glados`, `adjutant`, `hal`, `synth`, `system`). Supports GLaDOS
  neural TTS via the `nimaid/GLaDOS-TTS` project with an automated installation
  assistant (`phosphor tts install glados`).

## 0.2.11 — the manual gets its images organized, and prometheus its screenshot

- `doc/img/` split into one subfolder per manual page (`mentions/`,
  `workspaces/`, `profile/`, `readme/`) now that screenshots are piling
  up -- a flat folder stopped being navigable.
- profile.md's `[prometheus]` section gets a screenshot: `phosphor prom`
  with no gauges configured, "Prometheus watching itself" against a fake
  server standing in for a real install.

## 0.2.10 — the manual, hyper-loaded: mentions, workspaces, install

- `phosphor help TOPIC` shows a manual page's screenshot as a dimmed
  caption instead of the raw `![]()` markdown -- there's no way to draw
  the image itself in a terminal, but the raw syntax was worse than
  nothing. AGENTS.md keeps the real markdown (an AI assistant can read
  that fine).
- mentions.md, expanded: the full path a notification takes from your
  chat client to the COMMS tab's unread count, with two screenshots.
- workspaces.md, expanded: opening one from a note start to finish, that
  only claude resumes its last conversation across a restart (gemini,
  codex and opencode start over), and the two notebooks that are easy to
  mix up -- Alt-j's is yours, the workspace's own NOTES.md is only written
  on purpose, by an assistant or by you.
- install.md: a real `phosphor init` run, start to finish, including the
  part the summary table leaves out -- every `~/.ssh/config` alias is
  offered too, not just tailscale peers.

## 0.2.9 — screenshots, a privacy fix, and patterns

- The manual's new patterns page: which shape to pick and why, the three
  ways to add a tab (recipe, tabs.d, `phosphor keep`) from least to most
  committed, moving a whole deck to a new brain, sharing one tab, and
  backing out of a change. `phosphor help patterns`.

## 0.2.8 — phosphor web, actually reachable

- Fix: `phosphor web on` published an address the browser could never
  attach to. zellij 0.45 refuses a web client on a session that hasn't
  opted in (`web_sharing`, off by default); `phosphor gen` now sets
  `web_sharing "on"` in the same block it already writes the browser's
  colors into, so a fresh config gets it for free and an existing one
  picks it up on the next `gen`. A `web_sharing` of your own is left
  alone, same as a `web_client` of your own.

## 0.2.7 — tabs.d tabs can be placed

- tabs.d tabs can be placed. `phosphor tabs`' `K`/`J` now work on a shared
  or recipe tab too: the first time, it writes a name-only stub into your
  profile marking where it goes -- its content still comes from tabs.d,
  never copied in. `f` on a placed one un-places it (back to the end, in
  file-name order) instead of deleting it; the file it came from is never
  touched either way.

## 0.2.6 — recipes, and a shape for the wizard

- Recipes: starter tab bundles, built on tabs.d. `phosphor recipe` adds
  `homelab` (prom and ci dashboards), `dev` (a two-assistant tab), `bubble`
  (mail, RSS, Mastodon and Matrix in one tab) or `workbench` (four AI CLIs
  side by side) -- picked interactively, or by name; no argument lists
  what's there and what's already added. Also in the DECK tab (`a`).
  `phosphor init` now asks which shape fits how you'll use it: today's
  default (`homelab`), a leaner `revived` for one machine with no fleet
  (skips the CLOUD tab), or `dev` (a two-assistant tab up front). Closes #7.

## 0.2.5 — tabs you can share

- tabs.d: tabs you can share. Drop a `[[tabs]]` file into
  `~/.config/phosphor/tabs.d/*.toml` and it shows up in the deck,
  `phosphor gen` away, without touching your own profile -- pass someone
  a file, they drop it in. They come after your own tabs; a name your
  profile already uses wins. Read-only from the tools that edit your
  profile: Alt-r's save, `phosphor keep` and `phosphor tabs` (forget,
  reorder) name the file instead of touching it. Closes #8.

## 0.2.4 — an invitation, and your own vault

- The first-attach message no longer lists five keys to remember. It says
  the one thing that matters and lets you feel it yourself: type something,
  leave with Ctrl-q, come back with your deck's own command -- even from
  another screen -- and it's still there. Tabs, the + menu and every key
  are in the DECK tab, which already keeps itself current. Closes #6.
- Notes in your own vault: `[notes] folder` in the profile puts the
  notebook inside a folder you already sync (Obsidian, Syncthing, git) --
  `phosphor init` asks (offering folders with `.obsidian/`), `phosphor
  setup` changes it later, and either way an existing notebook moves into
  the new folder, never overwriting one that's already there. `phosphor
  doctor` checks the folder exists and is writable. Still one file
  (`notes.md`): it shows in Obsidian as a single long note, not one per
  entry -- the manual says what happens when it's edited from both sides
  at once. Closes #22.

## 0.2.3 — more of the deck's log, and a privacy fix

- Deck logs, third slice: about 20 more of lib/'s silent `except Exception`
  blocks now leave a line in `~/.cache/phosphor/deck.log` instead of
  throwing the reason away — the adjutant's face and fleet-alert reads, zellij
  calls from the adjutant, mentions and the + menu, `phosphor ci`'s job/commit
  detail fetches, `phosphor privacy`'s own scan, mesh detection, the manual's
  key table, the shell/editor probes in the profile, and a couple of
  redraw-loop failures (fleet's stuck-pane unfreezer, the DECK panel, an
  update check). Left alone on purpose: places that already show the user why
  (doctor, prom, ci's own pipeline fetch, a bad profile write) and one-off
  cleanup on exit. Some of these run in a redraw loop, so they're throttled
  like fleet's cache write already was. One privacy fix along the way: a
  broken profile check or matterhorn config could have put its own error text
  -- which can quote the very host/login it was reading -- into the log;
  those now log the bare fact instead. Also: `phosphor privacy` no longer
  crashes outright on a machine with no `git` on PATH; it just finds less.
  Rest of #23 for a later session.

## 0.2.2 — deck logs, and phosphor ci

- `phosphor ci`: status cards for GitLab and GitHub pipelines (`[ci]` in the
  profile, `[[ci.pipelines]]` per one; "ci" in the + menu once it's there).
  Colored by state, with the failing job and the commit that broke it.
  Contributed by the tester (leandrofus); the token auto-detected from
  `glab`/`gh` now goes through those tools themselves instead of parsing
  their config files by hand, so a token kept in the OS keyring (common on
  a desktop) is found too.
- Deck logs: `phosphor run` now writes a crash (with its traceback), a hang
  or a non-zero exit to `~/.cache/phosphor/deck.log`, size-capped and never
  holding note text or host names. `phosphor logs [TOOL] [-f]` reads it back
  (also `l` on an "ended" pane, and `l` in the DECK tab); `phosphor trace
  TOOL` turns on a verbose one for about 30 minutes, then off by itself.
  `phosphor restart`/`up`/`down` log their outcome too. Also logged now: a
  mention-hook that fails (it has to print nothing, so this was the only
  way to ever find out), a `phosphor web off` step that didn't, a
  `phosphor store` install that failed, and fleet's cache write (throttled,
  so a stuck failure doesn't fill the log). First slice of #23; the rest of
  lib/'s silent `except Exception` blocks adds up over time.

## 0.2.1 — prometheus gauges

- Prometheus gauges: `phosphor prom` draws your PromQL queries as bars, arcs
  and sparklines that turn amber and red past their thresholds, from
  `[prometheus]` in your profile. A query that fails says why under its
  card. It shows in the + menu once the profile has `[prometheus]`.

## 0.2.0 — your deck, your way

**Your deck, your way.** Everything 0.1.7 to 0.1.10 brought, in one place:

- Tabs you shape: Alt-r unlocks a tab to resize, split, close or swap what a
  pane runs, then saves it or puts it back; + → layout builds a tab of
  several panes by tap; `phosphor keep` saves a tab as it is.
- Tabs you keep or let go: `f` forgets a kept tab when it closes, and
  `phosphor tabs` forgets, moves and reopens them.
- Your keys: every deck key is yours to change (`phosphor shortcuts`).
- Your tools: your own apps in `apps.toml`, the store showing what's
  installed, and workspaces, a tab per idea with its own assistants.
- Your notes, from anywhere: Alt-j in any tab, tagged with where it came
  from, and an editor that works on a phone.
- Your channel: stable follows releases, nightly follows dev.
- The deck in a browser in the deck's color, and a start that waits for a
  slow machine.

## 0.1.10 — notes you can write on a phone

- Writing a note on a phone works: words the keyboard sends at once keep
  every letter, a line wider than the screen is saved whole, backspace goes
  back across the wrap and to the line above, and a paste keeps its lines.
  The hint shows once at the top instead of on every line.

## 0.1.9 — notes from anywhere

- Jot a note from wherever you are. Alt-j, in any tab, asks note, todo or
  idea (a key or a tap), you write it, and it's saved in NOTES saying which
  tab it came from: SYS shows a disk filling up, Alt-j, t, "clean the
  backups", and NOTES reads `TODO · from SYS`. In NOTES, `f` shows one tab's
  notes at a time; `phosphor note --tab SYS` and `phosphor notes --tab SYS`
  do the same from a shell. Change the key with `phosphor shortcuts`.
- The deck in a browser takes the deck's color: the page and its terminal
  follow `theme` (amber, white, paper) instead of zellij's black. The login
  box keeps zellij's colors, which zellij doesn't let us change yet.
- Writing a note right after a tap no longer picks up stray characters
  (`[<0;5;6m`) at the start of the note.
- `phosphor notes | head` no longer ends in a Python error.

## 0.1.8 — a patient start

- A slow machine no longer trips the start. `phosphor up` waits until the
  deck has its tabs (up to a minute) instead of giving up after 24 seconds,
  and `deck` typed while the deck is still starting (right after boot or
  `phosphor up`) says "the deck is starting..." and waits for it, instead of
  zellij's "No session 'deck' found".

## 0.1.7 — tabs your way

**Tabs your way**

- Edit a tab on purpose. Tabs stay locked; Alt-r (EDIT on a phone) unlocks
  the one you're in, marked with a ✎. Resize, split, close panes, or swap
  what runs in one (ctop for lazydocker) without rebuilding the tab. Alt-r
  again shows what changed and asks: save it into your profile, or put it
  back as it was. Every step is a row you can tap, so it all works by touch.
  One thing zellij won't lock: dragging a border still resizes.
- Quick layouts. `+` → layout: pick a shape (2 columns, 2 rows, 2 × 2,
  3 columns), then what goes in each pane, or "the same in the rest": four
  assistants side by side in a few taps. "keep" saves it into your profile.
- Alt-n opens a new tab (the + menu) in the folder of the pane you're in, and
  Alt-← / Alt-→ past the last pane move to the tab next to it.
- The deck's keys are yours. `phosphor shortcuts` (c in the DECK tab): pick
  one, press the new key, and it works at once; it warns when another key or
  a tool (matterhorn, the shell) already uses it. They live in `[keys]` in
  your profile, so updates never reset them, and `phosphor gen` rewrites only
  a marked block of zellij's config.kdl: binds of your own elsewhere in that
  file stay untouched. A config.kdl Phosphor installed gets the block by
  itself; one of your own gets it from `phosphor shortcuts --kdl`.
- Tabs you kept but don't want back. Closing the last program of a tab kept in
  your profile offers a third choice, f: close it and forget it, so it won't
  come back after a restart. `phosphor tabs` (b in the DECK tab) lists every
  kept tab and which are open now, to forget, reorder or reopen them.
- Pick your editor and your shell. The wizard asks (yours come first) and
  `phosphor setup` → "editor and shell" changes them. Shell panes, + → shell
  and the panes zellij opens all run that shell, not bash.

**Apps**

- Your own apps. List the programs you use in `~/.config/phosphor/apps.toml`
  (a name, the command, its arguments) and they show first in the store as
  "yours" and in the `+` menu.
- The store opens what you have: Enter on an installed app opens it in a new
  tab, and `i` shows only what's installed.
- A program that froze no longer passes for alive. When the pane changes size
  and the program neither answers nor does anything for 20 seconds (btop once
  sat an hour on "Terminal size too small" in a pane that was plenty big),
  the deck closes it and says "stopped responding": Enter opens it again.

**Everything else**

- Mentions from anything. `phosphor mention-hook` takes a notification as
  JSON on stdin from a bot, a script or any chat client, not only matterhorn;
  a tab named COMMS, or running iamb or gomuks, is the chat tab too.
- In Konsole and other terminals that name the tab after the program, the
  deck's tab reads `deck` (your command) instead of `python3`.
- `phosphor privacy` stops repeating the examples you meant: list a host name
  in `.privacy-allow` with the files it may appear in. IPs, users, emails and
  servers can't be allowed.
- Tab completion knows `keep`, `workspace`, `edit`, `shortcuts`, every manual
  topic and the notebook's `--file` and `--archive`.
- Without a profile, commands say they're using the example's made-up
  machines, and nothing is ever saved into the example.
- The example profile no longer assumes a chat app, and the removal steps
  also clear `~/.cache/phosphor`.
- `phosphor gen --dry-run` says what it would do to zellij's config.kdl
  instead of claiming it updated it.
- After updating: run the phone kit again for the EDIT key.

## 0.1.6 — a tab per idea

- Notes you can act on. In the NOTES tab, tap a note (or move with j/k) and
  its actions show at the bottom: `e` edit it (in your editor; a note an
  assistant wrote is marked "edited by you"), `d` archive it, `x` mark a todo
  done, `c` talk it over with an assistant in a new tab. `u` brings back the
  last archived note. `phosphor notes --archive` shows the archive, where `r`
  restores a note and `D` deletes it for good.
- Workspaces: a tab per idea, with its own folder, git repository and one or
  two assistants. `+` → workspace, `phosphor workspace new`, or `w` on a note
  (it shows the note first, so you never open the wrong one; the note becomes
  BRIEF.md). Two assistants can share a tab, each in its own part (frontend,
  backend); every one gets an AGENTS.md saying what it owns, and they hand
  work to each other in the workspace's own NOTES.md. The tab comes back after
  a restart, with claude picking up its conversation.
- A login token for browser access without leaving the deck: `w` in the DECK
  tab, then `t`. Turning it on waits for you to copy the token before the
  deck restarts (it used to vanish with the restart).
- `phosphor web` on a machine that only looks at the deck asks the brain over
  ssh, where the web server lives (it used to fail with "compiled without web
  server support").

## 0.1.5 — the tab you arranged, kept

- Keep a tab the way you arranged it: split the panes by hand, open what you
  want in each, and `phosphor keep` (or `k` in the DECK tab) writes that tab
  into your profile — splits, sizes and all — so it comes back after a
  restart. No TOML by hand.
- `phosphor restart` stops the deck's panes and nothing else. It used to match
  any process with "phosphor" in its command line, so an editor or a test
  running at that moment could be killed too.
- Browser access without tailscale works on the brain itself: `phosphor web
  on` starts the web client for this machine only (127.0.0.1 and a token)
  instead of refusing, and says how other machines can reach it. It used to
  suggest an ssh tunnel to a server that was never started (thanks to the
  first tester).
- An update regenerates your deck's files even when the phosphor doing the
  update is older than the one it installs: 0.1.3 updating to 0.1.4 left
  the old mount settings in place, so a fleet folder could stay empty.
  If that happened to you: `phosphor gen`.
- `phosphor doctor` tests ssh from where the mounts run (a service): a key
  with a passphrase works in your terminal and not there, and now it says so.

## 0.1.4 — fleet folders that mount, and a nightly channel

- Fleet folders mount through your own ssh, so a machine that answers
  `ssh NAME` also mounts: ~/.ssh/config, keys and known_hosts all count. A
  machine added in the wizard used to show an empty folder (thanks to the
  first tester).
- `phosphor doctor` says which fleet folders are really mounted, and where to
  look when one isn't; `phosphor update` regenerates before it restarts.
- The "new version" notice only shows up when there is a new version, not
  for every commit on its way to one.
- Two channels: `phosphor update --channel nightly` follows what's done but
  not released yet, `--channel stable` goes back to releases. `phosphor
  version` and the DECK tab say which one you're on; on nightly the notice
  counts every new commit and shows the Unreleased notes.
- Checks run by themselves on GitLab for every push and merge request
  (`tests/check.sh`).
- The slow tests (a clean install, a first-time user) run by themselves
  too, on the maintainer's own runner, for main, dev and releases.

## 0.1.3 — the wizard takes no for an answer

- A machine you turn down in the wizard is never asked about again: no
  follow-up question about its tunnels (thanks to the first tester).
- Machines found only in your `~/.ssh/config` are often someone else's
  servers, so the wizard offers them with No as the default; your tailscale
  peers keep Yes.

## 0.1.2 — release notes

- Release notes: this file. `phosphor version` shows what a newer version
  brings before you update, and `u` in the DECK tab does too.

## 0.1.1 — browser access tells the truth

- Browser access is tailnet only, never the internet, and the screens now
  say it in those words.
- `w` in the DECK tab asks by what really runs: when it's on, Enter turns it
  off (it used to answer "no" and leave it on).
- The DECK tab says "web half on" in amber when the profile and what runs
  disagree; `phosphor web off` checks each step.
- The address comes as a QR to scan from a phone, and the login token lands
  on the clipboard of every screen looking at the deck.

## 0.1.0 — the first versioned release

- The DECK tab (it was HELP): the deck's state, the next steps while you set
  it up, and every action one key or tap away — add a screen, machines and
  color, browser access, tunnels, tools, a shell on the brain, doctor,
  update, restart, the manual.
- `phosphor restart` brings every screen back in by itself.
- Add a screen: the phone kit as a QR, `phosphor screen` for any computer,
  and one ssh line for anything else.
- NOTES: write from the tab itself — `a` a note, `t` a todo, `i` an idea, or
  tap the bottom line.
- `phosphor version`, and a "new version: u" notice in the DECK tab. A copy
  install remembers the clone it came from, so a plain `phosphor update`
  goes back there.
- `deck` is the one word to get in, from any machine; `phosphor update` is
  the one way to update.
