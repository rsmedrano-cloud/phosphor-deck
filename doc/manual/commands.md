# Commands

## Getting started
- `phosphor doctor` — check this machine: systemd, FUSE, locales, binaries, fleet reach.
- `phosphor init` — the wizard; writes the profile.
- `phosphor setup` — add/remove machines, color, editor and shell, phone, browser access, tunnels, notebook
  (also: `m` in the DECK tab).
- `phosphor panel` — the DECK tab: the deck's state, the next steps while you set up, and every
  action one key or tap away (add a screen, machines, web, tunnels, tools, keep a tab, tabs, shortcuts,
  a shell here, doctor, logs, update, restart, manual). Actions run in the same pane and come back.
- `phosphor phone` — how to add a screen (phone, another computer, anything with ssh), with the
  phone's line as a QR; piped (`ssh … phosphor phone | sh`) it is the Termux kit. `--qr` prints only the code.
- `phosphor screen` — the same kit for a computer without Termux: a key and a `deck` in ~/.local/bin.
- `phosphor gen [--dry-run]` — profile → layouts, zellij theme, units, mounts, links, and the color
  of yazi, btop, gping and ctop (see `theme` in profile).
- `phosphor up` — start the deck and enable it at boot (with the fleet mounts).
- `phosphor attach` (alias `phosphor deck`, or just `deck`) — get in from the brain.
- `phosphor update [FOLDER]` — newer version: git pull or copy from FOLDER, run the installer, then
  get the panes onto the new code -- a real `phosphor restart` only when the pull touched shared
  code; a pull that only touched one tool's own module refreshes just that tool's panes, live, in
  place (`lib/hotswap.py`; `--full` always restarts, skipping that judgement call).
  A copy remembers FOLDER, so next time plain `phosphor update` goes back there.
  `--channel nightly` follows dev (what's done, not yet released); `--channel stable` goes back to
  releases. `phosphor version` and the DECK tab say which one you're on.
- `phosphor version` (or `--version`) — this version and commit, and whether a newer one exists;
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
- `phosphor workspace new|open|list` — a tab per idea with its own folder and assistants; see workspaces.

## Notes
- `phosphor note [--kind note|idea|decision|todo|summary] [--by NAME] [--book NAME] [--tab TAB] TEXT` (`-` reads stdin).
  `--tab` says which tab it came from; `--here` asks for it on screen and takes the tab you're in
  (what Alt-j runs: pick note, todo or idea, write it, and the screen closes over your pane).
- `phosphor notes [--book NAME | --file PATH] [--tab TAB] [--archive]` — read a notebook (`--tab`: only the notes taken there); `--book work` is WORK NOTES,
  `--file` any notebook (a workspace's NOTES.md). `phosphor note` takes `--file` too.
  In the tab itself: `a` writes a note, `t` a todo, `i` an idea (first line the title, an empty
  line saves). Tap a note or move with `j`/`k` to pick it: `e` edits it in `$EDITOR` (someone
  else's note gets "edited by you" on its author), `d` archives it, `x` marks a todo done,
  `c` opens a CHAT tab where an assistant (claude, gemini, codex or opencode) starts from it,
  `w` opens a workspace from it (see workspaces).
  A note taken from a tab says so (`from SYS`); `f` goes through those tabs, showing one tab's notes at a time.
  `u` brings back the last archived note. `/` searches title, body, author and tab at once (case-insensitive);
  Enter applies it, Esc cancels, an empty query clears it. Every key shows at the bottom from the start (dimmed
  until it applies), and tapping one works.
- Archived notes live in `notes-archive.md` next to the notebook; `phosphor notes --archive`
  shows them: `r` restores one, `D` deletes it for good (asks first).
- The notebook lives at `~/.local/share/phosphor/notes.md` unless `[notes] folder` in the
  profile points it at a folder you already sync (Obsidian, Syncthing, git) -- see profile.

## In the deck
- `phosphor fleet`, `phosphor pulse`, `phosphor adjutant`, `phosphor prom`, `phosphor ci`, `phosphor services` — the SYS panels; prom draws your Prometheus queries, ci draws your GitLab/GitHub pipeline statuses,
  services lists systemd units and their state (see `[prometheus]`, `[ci]` and `[services]` in profile; `--once` prints one frame).
  `fleet` also calls `phosphor notify` itself when a host's ok/not-ok flips (down, or back) -- at most once a minute per host even if the link flaps.
- `phosphor glance [--once]` — read-only: the fleet's problem hosts (or "all N ok"), unread
  mentions, open todos, and any workspace with uncommitted changes or commits ahead/behind its
  upstream ("one device, then another" makes those easy to forget). For a small screen:
  `ssh -t you@brain ~/.local/bin/phosphor glance` needs no zellij attach at all (see screens);
  refreshes every 5s, Ctrl-C to leave.
- `phosphor notify [--tab TAB] [--voice VOICE] [--tts|--no-tts] [--push|--no-push] MESSAGE` — the adjutant announces it, speaks it if TTS is enabled, and pushes it to your phone if `[push]` is on. The tab it names (or SYS with no `--tab`) also reads "`<TAB> ●N`" until you look, whether or not `[deck] notifier` is on (see profile).
- `phosphor tts [MESSAGE]` — speak a message aloud with selectable voices (glados, adjutant, hal, synth, system); `phosphor tts install glados` assists with installing GLaDOS-TTS.
- `phosphor push [--qr]` — `[push]`'s status (on/off, server, topic); `--qr` prints the subscribe
  link as a QR (also onto every screen's clipboard) so the phone's ntfy app can scan it instead of
  you typing the server and topic in by hand.
- `phosphor review` — open merge/pull requests, from the deck: detects GitLab or GitHub from this
  repo's remote and drives `glab`/`gh`. Per request: CI status (reusing `phosphor ci`'s own fetchers),
  whether it has conflicts, `d` for the diff (through `delta` if you have it, else `less`), `t` checks
  the branch out into its own worktree under `~/.cache/phosphor/review/` and opens a tab there if
  you're inside the deck -- your working copy is never touched, same spirit as `tests/mrs-check.py`;
  `x` drops that worktree. `r` refreshes the list.
- `phosphor screens` — who's attached (phone, tablet, another computer): where each is from and
  how long it's been idle, `x` (twice) kicks one loose, `r` refreshes. A kick just ends that one
  ssh connection -- its own `deck` wrapper (see screens) notices and reconnects in a few seconds by
  itself, so this is for the one squeezing everyone's pane down (zellij ties a tab's size to its
  smallest attached client, with no setting to change that), not for banning a device. Also `v` in
  the DECK tab. `--list` prints it once, no picker.
- `phosphor keys` — the key guide; `phosphor store` — install TUIs, no sudo; `d` removes one (only from ~/.local/bin).
  Enter on an installed app opens it in a new tab; `i` shows only what's installed. Your own apps
  (`apps.toml`, see profile) come first, as "yours".
- `phosphor new` — the new-tab menu (what + and Alt-n open). **layout** in it: pick a shape (2 columns,
  2 rows, 2 × 2, 3 columns), then what goes in each pane, or "the same in the rest"; all by tap too.
- `phosphor keep [TAB]` — read the tab as it is now (splits, sizes, what runs in each pane)
  and write it into your profile; `--pick` chooses the tab, `--dry-run` only shows it.
  Also `k` in the DECK tab.
- `phosphor tabs [--list]` — the tabs your profile brings back after a restart, and which are open now:
  forget one (out of the profile), move it, or open a closed one again. Also `b` in the DECK tab.
  Lists tabs.d's tabs too: `K`/`J` place one (a name-only stub in your profile marks where,
  its content stays in the file), and `f` on a placed one un-places it instead of deleting it.
- `phosphor recipe [NAME]` — starter tab bundles: `homelab` (prom and ci dashboards), `dev` (a
  two-assistant tab), `bubble` (mail, RSS, Mastodon, Matrix in one tab), `workbench` (four AI CLIs
  side by side). No `NAME` lists them, and what's already added. Drops `recipes/NAME.toml` into
  `~/.config/phosphor/tabs.d/` (see profile) and regenerates: the same file, editable by hand
  afterwards, same as any tabs.d tab. `phosphor init`'s "which shape" question builds `homelab`,
  `revived` (leaner: no CLOUD tab) or `dev` right into the profile from the start.
- `phosphor shortcuts [--kdl]` — the deck's keys, yours to change (also `c` in the DECK tab); `--kdl` prints the block
  for a zellij config of your own.
- `phosphor edit` — what Alt-r runs: unlock the tab you're in, change it, then save it or put it back (see keys).
- `phosphor mentions [--setup]` — the chat feed; `--setup` hooks matterhorn.
- `phosphor clip FILE` | `cmd | phosphor clip` | `phosphor clip --save FILE [--force]`.
- `phosphor send FILE [--timeout SECONDS]` — one real file (any size or type), as a one-time
  link and QR on your tailnet (or LAN without one). Gone the moment it's downloaded, or after
  the timeout (default 180s) if nobody comes for it. See clipboard.
- `phosphor web on|off|status|token` — browser access, tailnet only.
- `phosphor path PATH` — `~/fleet/x/y` → `host:/y`.
- `phosphor tunnel [on|off HOST]` — keep your ssh config's LocalForward tunnels up.
- `phosphor face IMAGE [--name N] [--w 24] [--h 13] [--half] [--mode thr|dither|edge]`.
- `phosphor run [--name N] [--reconnect] [--wait S] [--alt] -- CMD` — the watcher every pane uses:
  a crash, a hang or a non-zero exit goes into the deck's log; `l` on an "ended" pane reads it back.
- `phosphor logs [TOOL] [-f]` — the deck's own log (`~/.cache/phosphor/deck.log`): crashes with their
  traceback, hangs, exits, restarts. `TOOL` narrows to it (its trace file if `phosphor trace` turned
  one on, else its lines from the base log); `-f` follows, like `tail -f`. Also `l` in the DECK tab.
- `phosphor trace TOOL` — verbose logging for that tool alone, into `trace-TOOL.log`; turns itself
  off after about 30 minutes. No `TOOL`: lists whatever is tracing right now.

## Before you push a fork
- `phosphor demo` — a throwaway session over made-up machines and a made-up notebook, for a
  screenshot or a recording: never your real profile, session or ssh. `phosphor demo --stop`
  kills it. `Ctrl-c` or a normal exit from a pane leaves the session running in the background,
  same as any zellij session. It reads and writes nothing of the machine's own: the notebook,
  the chat feed, the adjutant's events, the fleet's readings and the log live in
  `~/.cache/phosphor/demo-state` (`--stop` removes it). What it can't hide is where it runs: the
  machine's user and host name still show in paths and prompts, so for a public screenshot run
  it on a machine whose user name you're happy to show.
- `phosphor privacy [--install]` — finds your own data (IPs, users, servers) in what git would publish.

## Shell
- `phosphor completion bash|zsh` — tab completion (the installer adds it to your rc file).

## Help
- `phosphor help [TOPIC]` — this manual. `phosphor docs [--check]` — rebuild AGENTS.md.
