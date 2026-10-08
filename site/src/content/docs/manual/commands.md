---
title: Commands
sidebar:
  order: 5
---


## Getting started
- `phosphor doctor` — check this machine: systemd, FUSE, locales, binaries, fleet reach, and
  profile keys it doesn't know (a typo, a key in the wrong table).
- `phosphor security [--local] [--json]` — how exposed the deck is, where doctor says whether it works. Read-only:
  each finding says what to run, nothing is changed. The profile and its backups (writable by
  anyone else, or readable while they hold a token or a public ntfy topic), `~/.ssh` and its
  private keys, the folders that decide what the deck runs; every fleet host's ssh server, the
  brain's included (root or password logins, empty passwords, StrictModes off: `sshd -T` where it
  answers without a password, else its config files, and a host where only root reads them says
  so instead of guessing); a tunnel forward or zellij's web server listening beyond 127.0.0.1, and
  anything `tailscale funnel` puts on the internet; zellij's and FLEET's socket folders. A folder
  others can't enter (a 0700 home) counts, and so does a group that's only you. `--local` skips
  the fleet. Exits 2 with something to fix, 1 with something worth a look.
- `phosphor init` — the wizard; writes the profile.
- `phosphor setup` — add/remove machines, color, editor and shell, phone (sharing this deck or a deck of its own), browser access, tunnels, notebook
  (also: `m` in the DECK tab).
- `phosphor panel` — the DECK tab: the deck's state, the next steps while you set up, and every
  action one key or tap away (add a screen, machines, theme, web, tunnels, tools, keep a tab, triage
  a host, tail logs, services, workspaces, review, notices & traces, tabs, shortcuts, a shell here, doctor,
  memory, logs, update, restart, manual, and `?` for the keys of every installed tool). Laid out as cards that
  follow the pane's width: one column on a phone (arrows or two fingers scroll it), more on a
  wider screen, with a line about each action once there's room. A profile of an older shape
  gets **P** in the deck card ("profile: N to migrate"): it runs `phosphor migrate`. `n` (notices & traces) opens `phosphor push`, `phosphor tts` or
  `phosphor trace` on their own screen: what's on, and on or off one key away. Actions
  run in the same pane and come back the same way from every one: q, Esc or Enter (the ones
  that print and wait say "q · Enter: back", the TUIs take q) -- `tail`'s stream is the one
  exception: it takes over the pane until you Ctrl-C, the same way "a shell here" does.
  After a hand edit of the profile, its status line says "profile changed: f applies it":
  `f` asks, then runs `phosphor gen` and `phosphor restart`. If gen went through and the deck
  didn't restart, the line says "applied, the deck hasn't restarted yet: f restarts it" until it
  does, and `f` offers the restart alone; `phosphor logs panel` shows what each step answered.
- `phosphor commands` — every phosphor command, browsable by category (also: `e` in the DECK
  tab). Pick a category, then a command: a read-only one runs right there when you pick it, and
  so does one that asks for what it needs (see "Commands that ask" below); anything else shows its usage and copies the invocation to every screen's clipboard instead
  of guessing at missing arguments (a file, a host, a message) for you. `/` searches every
  command at once, by name or by a word from its description (`/logs`, `/tailnet`): the name
  matching comes first.
- **Commands that ask.** Run with nothing at all on a terminal, these open a small screen for
  what they need instead of printing their usage line -- by key or by tap, `q`/Esc or
  "< back" to leave without doing anything; piped, or with their arguments, they behave as always:
  `ask` (a box for the question, whether the notebook goes along, the answer in a pager),
  `broadcast` (the hosts to tick, or a whole role with `g`, then the command, then its usual
  confirmation), `send`, `clip` and `face` (the file, walked to by folders: `~` and `~/fleet` one
  key away; `face` only lists images), `receive` (the QR on its own screen, and `y` opens the
  file that landed in yazi), `triage` (with nothing flagged, any host of the profile), `push`,
  `tts` and `trace` (their status, and on or off one key away), `read` (an address or words to
  search for). A line of text takes a paste whole.
- `phosphor phone` — how to add a screen (phone, another computer, anything with ssh), with the
  phone's line as a QR; piped (`ssh … phosphor phone | sh`) it is the Termux kit. `--qr` prints only the code.
- `phosphor screen [--as KIND]` — the same kit for a computer without Termux: a key and a `deck` in ~/.local/bin.
  `--as eink` (or any kind with a `[screens.KIND]` block) makes that `deck` come into the kind's own
  deck; the phone kit says `phone` by itself (see phones).
- `phosphor gen [--dry-run]` — profile → layouts, zellij theme, units, mounts, links, and the color
  of yazi, btop, gping and ctop (see `theme` in profile).
- `phosphor up` — start the deck and enable it at boot (with the fleet mounts).
- `phosphor attach [--screen KIND]` (alias `phosphor deck`, or just `deck`) — get in from the brain.
  `--screen KIND` goes into that kind's own deck when the profile has a `[screens.KIND]` block
  (made the first time one comes in), else into the deck.
- `phosphor update [FOLDER]` — newer version: git pull or copy from FOLDER, run the installer, then
  get the panes onto the new code -- a real `phosphor restart` only when the pull touched shared
  code; a pull that only touched one tool's own module refreshes just that tool's panes, live, in
  place (`lib/hotswap.py`; `--full` always restarts, skipping that judgement call).
  A copy remembers FOLDER, so next time plain `phosphor update` goes back there.
  `--channel nightly` follows dev (what's done, not yet released); `--channel stable` goes back to
  releases. `phosphor version` and the DECK tab say which one you're on.
- `phosphor version [--json]` (or `--version`) — this version and commit, and whether a newer one exists;
  `--check` asks now (a clone does `git fetch`; every few hours the DECK tab asks by itself
  and shows "new version: u").
  `--notes` shows what this version brought, `--new` what a newer one brings (from CHANGELOG.md).

## Session
- `phosphor restart` — down, reap leftover processes, up. Up only runs once down is proven clean
  (session gone from zellij, service stopped, nothing of it left alive); otherwise it names what's
  left, leaves the watchdog off and exits non-zero. From inside the deck it detaches itself.
  Every screen that came in with `deck` (this machine, other computers, phones) waits and goes back in by itself.
- `phosphor down` — bring it down and stop the watchdog timer (`phosphor up` to return); exits non-zero
  if anything of the old deck is still alive.

## Workspaces
- `phosphor workspace new|open|list|rm` — a tab per idea with its own folder and assistants; see workspaces.
  `rm NAME` takes its tab out and moves its folder into phosphor's trash (asks first).
  Bare, on a terminal (or `z` in the DECK tab): every workspace and its git state, Enter opens its tab,
  `d` its diff, `n` a new one, `x` asks y/n and removes it.
- `phosphor ask [--assistant NAME] [-c] QUESTION` — a one-shot question, no tab: shells out to whichever
  assistant CLI is already installed (claude, gemini, codex, opencode, aider, agy -- the same
  list `phosphor workspace` knows, tried in that order) with a headless, single-answer flag of
  its own (`claude -p`, `gemini -p`, `codex exec`, `opencode run`, `aider --message`, `agy -p`)
  and prints the answer. With no question and nothing piped, on a terminal, it asks for one (see
  "Commands that ask").
  `--assistant` picks one by name instead of the first installed. For "what was that command
  again" -- not a replacement for a workspace or a chat tab. Piped input is context, not a
  replacement for the question: `git diff | phosphor ask "what changed here"` sends both
  together (the pipe first); with no question at all, the piped text alone is the prompt.
  `-c` (`--notes`) sends your notebook's five latest decisions and summaries along, ahead of
  everything else, so "why did we drop X" has something to go on. Only when you ask for it:
  those notes go to the assistant's provider with the question.
- `phosphor read URL | WORDS... [--ask QUESTION] [--assistant NAME]` — a web page as plain text,
  for docs in the middle of an incident without a browser. An address (`http`/`https`) is
  fetched and boiled down to its own text: the article or main part of the page when it has
  one, headings as `#`, lists, quotes and code blocks kept, menus, cookie banners, sidebars and
  scripts left out; in the pager on a terminal, printed when piped. Words instead of an address
  search the web (DuckDuckGo's HTML page, no account): on a terminal, pick a result and it's
  read the same way, and q brings you back to the results; piped, the results are printed.
  `--ask` hands the page to whichever assistant `phosphor ask` would pick, fenced as data with
  no tools, and flags a dangerous command in the answer, as triage does. With nothing, on a
  terminal, it asks for an address or words (see "Commands that ask"). A page that builds its
  text with JavaScript has none to give: it says so. Standard library only, nothing to install.

## Notes
- `phosphor note [--kind note|idea|decision|todo|summary] [--by NAME] [--book NAME] [--tab TAB] TEXT` (`-` reads stdin).
  `--tab` says which tab it came from; `--here` asks for it on screen and takes the tab you're in
  (what Alt-j runs: pick note, todo or idea, write it, and the screen closes over your pane).
- `phosphor notes [--book NAME | --file PATH] [--tab TAB] [--archive]` — read a notebook (`--tab`: only the notes taken there); `--book work` is WORK NOTES,
  `--file` any notebook (a workspace's NOTES.md). `phosphor note` takes `--file` too.
  In the tab itself: `a` writes a note, `t` a todo, `i` an idea (first line the title, an empty
  line saves). Tap a note or move with `j`/`k` to pick it: `e` edits it in `$EDITOR` (someone
  else's note gets "edited by you" on its author), `d` archives it, `x` marks a todo done,
  `c` opens a CHAT tab where an assistant (claude, gemini, codex, opencode, aider or agy) starts from it,
  `w` opens a workspace from it (see workspaces).
  A note taken from a tab says so (`from SYS`); `f` goes through those tabs, showing one tab's notes at a time.
  `u` brings back the last archived note. `/` searches title, body, author and tab at once (case-insensitive);
  Enter applies it, Esc cancels, an empty query clears it. Every key shows at the bottom from the start (dimmed
  until it applies), and tapping one works.
- Archived notes live in `notes-archive.md` next to the notebook; `phosphor notes --archive`
  shows them: `r` restores one, `D` deletes it for good (asks first). A todo marked done ends
  with the moment it was (`done 2026-10-06 21:40`); `r` takes that line back out.
- `phosphor digest [--hours N] [--assistant NAME] [--print]` — the last day (or N hours, up to
  168) as one summary note, "digest YYYY-MM-DD", by `digest`: commits on any local branch of
  the repos in `[deck] projects` and which ones have uncommitted changes, what FLEET's history
  recorded (a host down, or a reading past its red line in `[alerts]`: CPU or RAM 90%, 85°C, a
  disk 90% unless you changed them), the notes taken,
  the todos done and the ones still open. It hands that to whichever assistant `phosphor ask`
  would pick and writes its answer; the next session, yours or an assistant's, starts from it.
  Commit messages and host errors are text others wrote, so it goes in the way triage's snapshot
  does: cleaned, fenced as data, the assistant with no tools. What it collects goes to that
  assistant's provider; `--print` only shows it and sends nothing, and a day with nothing in it
  writes no note. Nothing runs it on its own: for one every night, a cron line
  (`0 23 * * * PATH=$HOME/.local/bin:$PATH phosphor digest`, with the PATH your assistant CLI needs).
- The notebook lives at `~/.local/share/phosphor/notes.md` unless `[notes] folder` in the
  profile points it at a folder you already sync (Obsidian, Syncthing, git) -- see profile.

## In the deck
- `phosphor fleet`, `phosphor adjutant`, `phosphor prom`, `phosphor ci`, `phosphor services`, `phosphor pulse` — the SYS panels; adjutant watches the fleet's health alongside listening for events, prom draws your Prometheus queries, ci draws your GitLab/GitHub pipeline statuses,
  services lists systemd units and their state (see `[prometheus]`, `[ci]` and `[services]` in profile; `--once` prints one frame;
  `fleet --json` and `services --json` print their readings as JSON, see below).
  services also opens from the `+` menu and with `y` in the DECK tab; on a terminal, pick a unit: `l` its logs,
  `r` restart it, `s` start or stop it, each asking first (see `[services]` in profile).
  `fleet` also calls `phosphor notify` itself when a host's ok/not-ok flips (down, or back) -- at most once a minute per host even if the link flaps.
  A card also shows the CPU's temperature and a laptop's battery (from sysfs, when the kernel has
  them) and disks failing SMART: that needs `smartctl` there, answering without a password (root,
  or a sudoers line like `you ALL=(root) NOPASSWD: /usr/sbin/smartctl`; sudo is only tried by a
  user in sudo, wheel or admin). It's asked at most every 30 minutes, with `-n standby` so a
  sleeping disk stays asleep; the answer waits in `$XDG_RUNTIME_DIR/phosphor-smart` on that
  machine, and "not allowed" waits a day. A disk starting to fail alerts like a host going down.
  It also says how many updates the machine has pending -- amber when some are security
  updates, which `phosphor glance` calls out too. Counted from what the package manager already
  knows (apt and dnf from their own cache, apk's index, Arch's `checkupdates`, with `arch-audit`
  for the security ones), never with its lock, and in the background: a host's first poll has no
  count yet. Counted again once the package database changes (an upgrade, an `apt update`), or
  after 6 hours; the count waits in `$XDG_RUNTIME_DIR/phosphor-updates` on that machine.
  In `fleet`, pick a machine's card (arrows, Tab or a tap; Esc lets go) and open something on it in a tab of
  its own: `s` a shell there (ssh, or a plain shell for the brain), `l` its logs (what `phosphor tail HOST`
  runs), `t` a `phosphor triage` of it, `c` its containers (`phosphor containers HOST`, below). The keys
  show on the bottom line and tapping them works too; none of them changes anything on the host by
  itself. `h` stays in the pane and draws that machine's last 24 hours:
  CPU, RAM, temperature and its fullest disk, one sparkline each, with the day's peak and when it was,
  and a red `·` where it was down (arrows or Tab go to the next machine, Esc back to the cards). The
  deck's own fleet keeps it, from the readings it already has -- nothing new runs on the hosts: every
  5 minutes, each host's peaks of that window go into `~/.cache/phosphor/history.json`, a day's worth,
  and only while the deck runs (a gap where it didn't).
- `phosphor containers [HOST] [--once | --json]` — a host's containers (docker, or podman where docker isn't
  there or doesn't answer -- the engine its FLEET card counts), running first, an exit that wasn't 0
  in red; no `HOST` means this machine. Listed over ssh the same way FLEET reaches it (a key, never
  a password prompt). On a terminal, pick one (j/k or a tap): `l` reads its last 300 log lines, `r`
  restarts it and `s` starts or stops it, each asking first (`y`). No sudo: if listing them works
  without it, so does acting on them. Also `c` over a card in FLEET, in a tab of its own. In
  `phosphor demo` it lists made-up containers and touches nothing.
- `phosphor usage [--once]` — how much of your AI assistants' plans you've used, one card each:
  Claude Code (the 5-hour window and the week) and Antigravity (each quota pool -- Gemini, and the
  Claude/GPT models it also offers), each with a bar and the time until it refills. Only the ones
  signed in on this machine show. It reads the token each CLI already keeps
  (`~/.claude/.credentials.json`, `~/.gemini/antigravity-cli/antigravity-oauth-token`) and asks that
  same provider, every two minutes; it never refreshes a token, so an expired one says "open claude
  (or agy) once" until that CLI renews it. Antigravity has no separate weekly figure to show: its
  answer is one fraction per pool.
- `phosphor glance [--once | --json | --serve [--port N] [--new-token]]` — read-only: the fleet's problem hosts (or "all N ok"), unread
  mentions, open todos, and any workspace with uncommitted changes or commits ahead/behind its
  upstream ("one device, then another" makes those easy to forget). For a small screen:
  `ssh -t you@brain ~/.local/bin/phosphor glance` needs no zellij attach at all (see screens);
  refreshes every 5s, Ctrl-C to leave. `--json` prints the same answers once, as JSON, with a
  `status` to light up: red (a host down, or the readings stopped), amber (anything else to look
  at, an unread mention), green, or unknown with no fleet data. `--serve` answers that JSON over
  HTTP for a gadget that can't ssh (an ESP32 with e-paper, a Pi Zero with an OLED): see screens.
- `phosphor notify [--tab TAB] [--voice VOICE] [--tts|--no-tts] [--push|--no-push] MESSAGE` — the adjutant announces it, speaks it if TTS is enabled, and pushes it to your phone if `[push]` is on -- with what it said attached as audio when it spoke it (`[push] clip`). The tab it names (or SYS with no `--tab`) also reads "`<TAB> ●N`" until you look, whether or not `[deck] notifier` is on (see profile).
- `phosphor tts [MESSAGE]` — speak a message aloud with selectable voices (glados, adjutant, hal, synth, system); `phosphor tts install glados` assists with installing GLaDOS-TTS. `on`/`off` switch `[tts]`; with nothing, on a terminal, its status with on/off one key away.
- `phosphor push [--qr | on | off]` — `[push]`'s status (on/off, server, topic, the "open the deck" button); `on`/`off`
  switch it (`on` with no topic makes up a long random one); with nothing, on a terminal, the same status with
  on/off and the QR one key away. `--qr` prints the subscribe
  link as a QR (also onto every screen's clipboard) so the phone's ntfy app can scan it instead of
  you typing the server and topic in by hand.
- `phosphor review` — open merge/pull requests, from the deck: detects GitLab or GitHub from this
  repo's remote and drives `glab`/`gh`. Also in the `+` menu (with `glab` or `gh` installed) and `x`
  in the DECK tab: outside a GitLab or GitHub repo they ask which folder first. Per request: CI status (reusing `phosphor ci`'s own fetchers),
  whether it has conflicts, `d` for the diff (through `delta` if you have it, else `less`), `t` checks
  the branch out into its own worktree under `~/.cache/phosphor/review/` and opens a tab there if
  you're inside the deck -- your working copy is never touched, same spirit as `tests/mrs-check.py`;
  `x` drops that worktree (after a y/n: anything changed there is lost). `r` refreshes the
  list, which also refreshes on its own once a minute; rows and keys answer a tap.
- `phosphor screens [--list | --json]` — who's attached (phone, tablet, another computer): where each is from and
  how long it's been idle, `x` kicks one loose, `o` changes its kind's deck (see
  screens) -- both ask y/n first -- and `r` refreshes; a tap picks a row or presses a key. A kick just ends that one
  ssh connection -- its own `deck` wrapper (see screens) notices and reconnects in a few seconds by
  itself, so this is for the one squeezing everyone's pane down (zellij ties a tab's size to its
  smallest attached client, with no setting to change that), not for banning a device. Also `v` in
  the DECK tab. `--list` prints it once, no picker. A screen that reaches the brain through a
  tailscale relay is marked "relay": its deck's animations slow to one frame a second (see screens).
- `phosphor mem [--once | --json]` — how much memory each tab and pane of the deck takes, heaviest tab
  first, every 5s (j/k scroll, q leaves; also `M` in the DECK tab). A pane counts everything it
  started -- an assistant's workers, a shell's children -- since every process keeps the
  `ZELLIJ_PANE_ID` zellij gave its pane; each kind of screen's own deck shows under its name
  (`SYS · phone`), then zellij itself and the machine as a whole. PSS, so a library two processes
  share is split between them instead of counted twice. Read-only.
- `phosphor keys` — the key guide; `phosphor store` — install TUIs, no sudo: Enter installs (or opens what you have in a tab), `d` removes one (only from ~/.local/bin, asks y/n first), `i` shows only what's installed, `/` filters, Esc clears; rows and keys answer a tap.
  Enter on an installed app opens it in a new tab; `i` shows only what's installed. Your own apps
  (`apps.toml`, see profile) come first, as "yours".
- `phosphor new` — the new-tab menu (what + and Alt-n open). **layout** in it: pick a shape (2 columns,
  2 rows, 2 × 2, 3 columns), then what goes in each pane, or "the same in the rest"; all by tap too.
  An **assistant** in it asks which folder it starts in: here, a folder of `[deck] projects`
  (workspaces say so), one you typed before, or `/` to type another (`~` and relative paths
  work); the tab takes that folder's name.
  **`/`** in it (or tap "search everything...") searches, as you type, the tabs open now, the
  menu's own entries, your workspaces, the tools you've installed and every phosphor command:
  every word counts, in names and descriptions, the name matching first. Enter or a tap goes to
  that tab, opens the workspace or the tool, or runs the command in this tab -- a command that
  could change something shows its usage and copies it instead, as in `phosphor commands`.
  Whatever you type, the last row is always "search the web for it": a READ tab with
  `phosphor read` on those words.
  Its first twenty openings end with one line of the deck's own keys, as `[keys]` has them.
- `phosphor keep [TAB]` — read the tab as it is now (splits, sizes, what runs in each pane)
  and write it into your profile; `--pick` chooses the tab, `--dry-run` only shows it.
  Also `k` in the DECK tab.
- `phosphor tabs [--list]` — the tabs your profile brings back after a restart, and which are open now:
  `f` forgets one (out of the profile, after a y/n), `K`/`J` move it, `o` opens a closed one
  again; rows and keys answer a tap, and the list refreshes on its own. Also `b` in the DECK tab.
  Lists tabs.d's tabs too: `K`/`J` place one (a name-only stub in your profile marks where,
  its content stays in the file), and `f` on a placed one un-places it instead of deleting it.
- `phosphor migrate [--dry-run]` — bring a profile of an older shape up to date. A change to
  what phosphor ships never reaches a profile that already exists, so when a shape changes it
  becomes a step here: each pending one is shown as a diff (the DECK tab in one pane, `[deck] tts`
  into `[tts] enabled`), then one "write it?" writes them all, with `version` in `[deck]`, and
  keeps the old profile as `deck.toml.bak`; it shows after `phosphor gen && phosphor restart`
  (`f` in the DECK tab). `--dry-run` only shows. A profile written by a newer phosphor is left
  alone. `phosphor doctor`, `gen` and `update` say when there's something to migrate; `P` in
  the DECK tab runs it.
- `phosphor backup [FILE]` — the brain's own backup, one file (default
  `~/phosphor-backup-DATE.tar.gz`, 0600): your profile, `apps.toml`, `tabs.d`, the notebook
  (unless `[notes] folder` keeps it in a vault you already sync), the glance token, your adjutant
  faces and the folders "where?" remembers. Never ssh keys, nothing phosphor makes again by
  itself (gen's files, caches, logs). It won't overwrite a file that's already there.
- `phosphor restore FILE [--dry-run]` — put a backup back, on this brain or a new one. Each
  file is shown as new, replace or same; one "restore it?" writes them, the profile with its
  `deck.toml.bak` and anything else it replaces with a `.bak` next to it. It only takes the
  names a backup holds (no paths, no links from the archive), names any host with `local =
  true` (the old brain's own disks), and ends with `phosphor gen --dry-run`: the deck changes
  only when you run `phosphor gen && phosphor up` (or `restart`). `--dry-run` only shows.
- `phosphor recipe [NAME]` — starter tab bundles: `homelab` (prom and ci dashboards), `dev` (a
  two-assistant tab), `bubble` (mail, RSS, Mastodon, Matrix in one tab), `workbench` (four AI CLIs
  side by side). No `NAME` lists them, what's already added and which programs each still needs. Drops `recipes/NAME.toml` into
  `~/.config/phosphor/tabs.d/` (see profile) and regenerates: the same file, editable by hand
  afterwards, same as any tabs.d tab. `phosphor recipe --remove NAME` takes it back out (the
  file, and any place `phosphor tabs` gave its tabs; never the programs). Adding one checks
  what its panes run: what `phosphor store` carries it offers to install (no sudo, into
  `~/.local/bin`; it asks first, and only on a terminal), the rest it names with how to get it
  (`npm install -g ...`, your package manager). `phosphor init`'s "which shape" question builds `homelab`,
  `revived` (leaner: no CLOUD tab) or `dev` right into the profile from the start.
- `phosphor theme [NAME | --list]` — the deck's color. With no `NAME`, a picker: arrows, j/k,
  a number or a tap preview each theme as a small deck painted in it, on its own background,
  before anything is written; Enter keeps it (then `phosphor gen`, and it asks before a
  restart), q leaves it as it was. `NAME` (p31, p3, p4, ega, paper) writes it straight away and
  applies nothing: `phosphor gen && phosphor restart`, or `f` in the DECK tab. `o` in the DECK
  tab and `phosphor setup`'s "change the color" open the same picker.
- `phosphor shortcuts [--kdl]` — the deck's keys, yours to change (also `c` in the DECK tab); `--kdl` prints the block
  for a zellij config of your own.
- `phosphor edit` — what Alt-r runs: unlock the tab you're in, change it, then save it or put it back (see keys).
- `phosphor mentions [--setup]` — the chat feed; `--setup` hooks matterhorn.
- `phosphor clip FILE` | `cmd | phosphor clip` | `phosphor clip --save FILE [--force]`. With nothing, on a terminal, it asks which file.
- `phosphor send FILE [--timeout SECONDS]` — one real file (any size or type), as a one-time
  link and QR on your tailnet (or LAN without one). Gone the moment it's downloaded, or after
  the timeout (default 180s) if nobody comes for it. No `FILE`, on a terminal: it asks which. See clipboard.
- `phosphor receive [--dir FOLDER] [--timeout SECONDS]` — the other way: a one-time upload
  link and QR, same tailnet-or-LAN reach as `send`. The file lands in `~/received` (or `--dir`),
  never overwriting one that's already there, and the link is gone the moment it's used or
  after the timeout. For getting a real file (a photo, a screenshot) from whatever device
  you're actually holding onto this machine -- an AI assistant running in a pane here can then
  read it directly. Run bare on a terminal, the QR gets a screen of its own and, once the file
  lands, `y` opens it in yazi. See clipboard.
- `phosphor web on|off|status|token` — browser access, tailnet only.
- `phosphor path PATH` — `~/fleet/x/y` → `host:/y`.
- `phosphor tail HOST [SERVICE]` — stream a fleet host's logs: `journalctl -f` with no `SERVICE`,
  `journalctl -f -u SERVICE` for a bare name or `systemd/NAME`, `docker logs -f` or `podman logs
  -f` for `docker/NAME` or `podman/NAME`. Just a normal ssh tab (`ssh -t HOST ...`, through
  `phosphor run --reconnect`) with the command already filled in -- reconnects on a dropped link
  the same way any other ssh tab does, never touches anything on the host (also: `j` in the DECK
  tab, which asks for the host and service first). What it prints keeps its lines and colors and
  loses any other escape sequence (see privacy).
- `phosphor triage [--assistant NAME] [HOST]` — a deeper, one-off look at a host (uptime and load,
  failed systemd units, memory, disk, recent kernel messages) collected over ssh and piped
  straight into `phosphor ask`, which shells it to whichever assistant CLI is installed with a
  fixed question: what's actually wrong, and how to fix it. For when `phosphor fleet` or `phosphor
  doctor` already flagged something and you want a second look before digging by hand -- not
  something to run on a timer. With no `HOST` on a real terminal, it opens the same arrow-key
  picker `phosphor commands` uses, over whatever the fleet panel is currently flagging (the same
  hosts `phosphor glance` calls out) -- or, with nothing flagged, over every host of the profile; piped or scripted, it just lists them instead (also: `g` in
  the DECK tab). The snapshot is whatever the host says, so a log line can try to steer the
  assistant: it goes in cleaned and fenced as data, never instructions; the assistant runs with no
  tools (or its read-only mode); and a command in the answer that does real damage (a piped
  installer, `rm -rf /`, a new ssh key, a firewall off...) is listed at the end under "check
  before running anything". Triage never runs what the answer suggests.
- `phosphor broadcast [--host NAME]... [--role ROLE] [--timeout S] [--rolling [--pause S]] [--yes] -- COMMAND` — one
  command on every host `phosphor fleet` watches, at once: over ssh (BatchMode, a key, never a
  password prompt) and in parallel, the brain itself locally, viewers and `fleet = false` ones left
  out. Each host's output comes under its own header with its exit code (or "unreachable", when
  ssh never got there) and how long it took; it exits 0 only if every host answered 0. `--host`
  (repeatable) and `--role` narrow it down; `--timeout` (default 60s) is per host. It can change
  anything on those machines, so it shows the command and the hosts and asks first; without a
  terminal it refuses unless `--yes` says the run was meant to be unattended. `--rolling` goes one
  host at a time instead (the brain last) and stops at the first that doesn't answer 0, naming the
  hosts it never got to: a bad update breaks one machine, not the whole fleet. `--pause S` waits S
  seconds after each host and checks it still answers ssh before the next (a restarted service, a
  reboot). On a terminal it asks before each next host; with `--yes` it goes on by itself while
  they keep answering 0. With nothing at all, on a terminal, it asks: the hosts to tick, the
  command, all at once or one at a time, then the same confirmation.
- `phosphor tunnel [on|off HOST | --json]` — keep your ssh config's LocalForward tunnels up.
- `phosphor face IMAGE [--name N] [--w 24] [--h 13] [--half] [--mode thr|dither|edge]`. No `IMAGE`, on a
  terminal: it asks which, listing only images. Needs ImageMagick (`convert`).
  `phosphor face IMAGE --bitmap [--closed IMAGE] [--px 96] [--crop WxH+X+Y]` keeps the picture as a
  small grid of tones instead of characters, so the adjutant draws it at the size of its pane (up to 28 columns, centered in a bigger one), in half
  blocks and the colors of your theme (`phosphor adjutant --face NAME`). Warm bright spots (amber
  lights) become their own layer that pulses and turns red on an alert; `--closed` is the same picture
  with the eyes shut, for the blink. The adjutant's own face is one of these.
- `phosphor run [--name N] [--reconnect] [--wait S] [--alt] -- CMD` — the watcher every pane uses:
  a crash, a hang or a non-zero exit goes into the deck's log; `l` on an "ended" pane reads it back.
  `--reconnect` (ssh panes) retries a dropped link (ssh's own exit 255) starting at 3s, doubling
  up to a 60s cap while it stays down, back to 3s once a connection actually holds for 30s or
  more -- a real outage doesn't get hammered every 3s for hours.
- `phosphor logs [TOOL] [-f]` — the deck's own log (`~/.cache/phosphor/deck.log`): crashes with their
  traceback, hangs, exits, restarts. `TOOL` narrows to it (its trace file if `phosphor trace` turned
  one on, else its lines from the base log); `-f` follows, like `tail -f`. Also `l` in the DECK tab.
- `phosphor trace TOOL` — verbose logging for that tool alone, into `trace-TOOL.log`; turns itself
  off after about 30 minutes, or sooner with `phosphor trace off TOOL`. No `TOOL`: lists whatever is
  tracing right now, and on a terminal `t` starts one (the tools deck.log has lines for) and `x`
  stops one.

## For scripts: --json
Every read-only listing prints its data once as one JSON object with `--json`: no color, no
screen codes, the same answers the panel shows. Scripts, gadgets and the assistants in your panes
read that instead of scraping colored text. Nothing in it writes or restarts anything.

- `phosphor fleet --json` — every host's latest readings, from the fleet's own cache (it polls
  nothing): `t`, `age` and `stale` (no reading for 90s: the deck's fleet isn't running), and
  `hosts`, one per profile host (null before its first poll) with `ok`, `cpu`, `memory`, `load`,
  `uptime`, `disks`, `containers`, `gpus`, `failed_units`, `reboot`, `temp`, `battery`, `smart`
  and `updates`, or `ok: false` and its `error`.
- `phosphor glance --json` — the four questions with a `status` light (see above).
- `phosphor services --json` — `units`: `unit`, `scope`, `state` (the panel's word), `load`,
  `active`, `sub`, `memory` in bytes.
- `phosphor containers [HOST] --json` — `host`, `engine`, `problem` (null when the list is good;
  exit 1 otherwise) and `containers`: `name`, `state`, `tag`, `status`, `image`, `exit`.
- `phosphor screens --json` — `session` and `screens`: `tty`, `from`, `login`, `idle`, `pid`,
  `session`, `said` (the kind it came in as), `relay`.
- `phosphor mem --json` — `session`, `running`, `tabs` (each with its `panes`, in bytes),
  `zellij` and `machine` (`total`, `available`).
- `phosphor security [--local] --json` — `sections`, each a `title` and its `findings`: `level`
  (ok, warn, bad, skip), `label`, `value`, `fix`. Exits 2 or 1 like the audit itself.
- `phosphor tunnel --json` — `tunnels`: `host`, `state` (up, down, off) and its `forwards`.
- `phosphor version --json` — `version`, `commit`, `branch`, `channel`, `installed`, `news` and
  the last `check` (`--check` asks first).
- `phosphor workspace list --json` — `root` and `workspaces`: `name`, `path`, `git` (`dirty`,
  `ahead`, `behind`).

### For assistants: phosphor mcp
`phosphor mcp` is the same data for an assistant that speaks MCP (Model Context Protocol): a
server on stdin/stdout that the assistant starts itself and that ends when it closes the pipe.
Nothing listens on a port. Register it once, in the assistant you use:

    claude mcp add phosphor -- phosphor mcp

(or a `{"command": "phosphor", "args": ["mcp"]}` entry in another assistant's MCP config).
Its tools only read what's already on the brain, and none of them sends, restarts or writes:

- `glance` — what `glance --json` says.
- `fleet` — what `fleet --json` says, from the cache (no ssh); `host` narrows it to one.
- `notes` — the notebook, newest first: `when`, `kind`, `by`, `tab`, `title`, `body`, and the
  `total` of matches; `kind`, `tab`, `query` (title or body, any case), `limit` (20, up to 200)
  and `archive` narrow it.
- `workspaces` — what `workspace list --json` says.
- `logs` — the end of deck.log, or one tool's lines (`tool`, `lines`: 100, up to 400).

## Before you push a fork
- `phosphor demo` — a throwaway session over made-up machines and a made-up notebook, for a
  screenshot or a recording: never your real profile, session or ssh. `phosphor demo --stop`
  kills it. `Ctrl-c` or a normal exit from a pane leaves the session running in the background,
  same as any zellij session. It reads and writes nothing of the machine's own: the notebook,
  the chat feed, the adjutant's events, the fleet's readings, the log and its workspaces
  folder live in `~/.cache/phosphor/demo-state` (`--stop` removes it). What it can't hide is where it runs: the
  machine's user and host name still show in paths and prompts, so for a public screenshot run
  it on a machine whose user name you're happy to show. FLEET's `s` and `l` open nothing on a
  made-up machine, unless its name (forge, atlas, vault, relay) is also a `Host` alias in your
  `~/.ssh/config`: a recording can point one somewhere real.
  `phosphor demo --tour` is the same demo with a guide: a small floating pane on every tab that
  has you try each thing (switch tabs, Alt-j a note, Alt-n a tab, Alt-r to keep it) and moves on
  once it has seen you do it. Enter steps it aside so your keys reach the deck; it comes back by
  itself when the step is done. The demo's profile is a copy under `demo-state`: saving a tab
  there never touches the repo or your own profile, and `gen`, `up`, `restart` and `down` refuse
  to run on it (they'd write the demo over this machine's real deck).
- `phosphor privacy [--install]` — finds your own data (IPs, users, servers) in what git would publish.

## Shell
- `phosphor completion bash|zsh` — tab completion (the installer adds it to your rc file).

## Help
- `phosphor help [TOPIC]` — this manual. `phosphor docs [--check]` — rebuild AGENTS.md (the rules, concepts and an index of these pages).
- `phosphor CMD --help` (or `-h`) — what that command does and its usage; it never runs it.
- `share/commands.json` — a machine-readable manifest, one entry per command above, saying
  whether it mutates live state (the session, a systemd unit, the profile, or any file phosphor
  generates) and whether it needs the deck already running to do anything -- with a one-line
  note for the ones where a flag or an interactive key changes the plain answer. Not a command
  of its own: for a CI job, a cron/timer, an external policy tool, or another assistant working
  in this repo that wants to know what needs a human before it runs unattended, without parsing
  this page's prose. `tests/commands-manifest-check.py` keeps it matching the list above.
