---
title: Install
sidebar:
  order: 2
---


On the machine that will be the brain:

    sh install.sh            # from a copy of the repo, or:
    curl -fsSL https://raw.githubusercontent.com/rsmedrano-cloud/phosphor-deck/main/install.sh | sh

It downloads zellij, yazi, btop, gping, ctop and rclone into `~/.local/bin`
(static binaries; no root), puts the code in `~/.phosphor` (an install that
already exists keeps its folder), writes the `deck` command, and asks
"set it up now?". Yes runs the wizard, which ends with "build the deck and
start it now?" and "get in now?": you finish inside the deck.

The same steps by hand:

    phosphor doctor     # optional: can this machine run it? warnings are fine
    phosphor init       # the wizard: writes the profile
    phosphor gen        # profile -> layouts, units, mounts
    phosphor up         # starts the deck, and at every boot
    deck                # you're in (the same as phosphor attach)

If `phosphor` isn't found, `~/.local/bin` isn't in your PATH yet: the
installer prints the line to add (`~/.bashrc` or `~/.zshrc`).

## What the wizard asks

- **how your machines reach each other**: tailscale, headscale, or none
  (plain ssh). Only matters with more than one machine.
- **is this the brain**: yes on the machine that stays on.
- **disks**: which of this machine's disks to show in `~/fleet`.
- **machines**: it tries ssh on every candidate (tailscale peers,
  `~/.ssh/config`) and only offers those that really run a shell; git servers
  never do. For each: watch it or not, its role, which disk to show. Tailscale
  peers are yours, so Enter means yes; hosts only in `~/.ssh/config` are often
  someone else's servers, so Enter means no.
- **tunnels**: only for the hosts you said yes to — a host you turned down is
  never asked about again.
- **which shape fits how you'll use it**: `homelab` (the default: fleet panel,
  file browser, monitoring), `revived` (one lean machine, no CLOUD tab), or
  `dev` (a two-assistant tab up front). More later with `phosphor recipe`.
- **editor** and **shell**: among the ones installed, yours first; files
  open with that editor and every shell pane runs that shell.
- **color**, **a chat app** for a COMMS tab, **browser access** (tailscale
  only, default no), **a phone or tablet** (prints the phone kit).
- **where the notebook lives**: private by default, or a folder you already
  sync (it offers ones with `.obsidian/`). `phosphor setup` changes it later.

## A run, start to finish

A real one, on a single machine with a few `~/.ssh/config` aliases lying
around (declined here -- they're not this machine's fleet) and `revived`
picked on purpose (see patterns for why): `phosphor init`, then Enter to
accept whatever default fits, typing a number where a different answer is
worth showing.

    ── network ─────────────────────────────────────────────────────────
      ? how do your machines reach each other? (only matters if you have more than one)
           1 tailscale  (tailscale.com)
           2 headscale  (your own control server)
         › 3 none       (plain ssh: ~/.ssh/config, LAN — or just this machine)

`none` was already the default here: no tailscale client installed, so
there was nothing else to detect.

    ── discovering ─────────────────────────────────────────────────────
      ✓ this machine              archlinux                              local
      · db-box                    ~/.ssh/config
      · nimbus                    ~/.ssh/config
      · relay                     ~/.ssh/config
      · voyager                   ~/.ssh/config

Every `Host` alias in `~/.ssh/config` shows up here too, not just tailscale
peers -- these four happened to already answer ssh (they were set up for a
tunnel and a fleet demo, not real machines), so the wizard offers them
next:

    ── this machine ────────────────────────────────────────────────────
      ? is this the brain? (it stays on and keeps the deck running) (Y/n)

    ── the fleet ───────────────────────────────────────────────────────
        trying ssh on 4 candidates at once...
      ? watch db-box as a machine of your fleet? (ssh in to read CPU, RAM, disks) (y/N)
      ? watch nimbus as a machine of your fleet? (ssh in to read CPU, RAM, disks) (y/N)
      ? watch relay as a machine of your fleet? (ssh in to read CPU, RAM, disks) (y/N)
      ? watch voyager as a machine of your fleet? (ssh in to read CPU, RAM, disks) (y/N)

All four declined here (Enter takes the default, `N`, since these came
from `~/.ssh/config` rather than tailscale) -- a real fleet member gets a
role and a disk to mount right after saying yes to it, which none of these
did.

    ── taste ───────────────────────────────────────────────────────────
      ? which shape fits how you'll use it? (phosphor recipe adds more later)
           1 homelab   fleet panel, file browser, monitoring -- the default
         › 2 revived   one lean machine: a shell, monitoring, notes -- no CLOUD tab
           3 dev       a two-assistant tab up front, the rest stays

Typed `2` here on purpose: no other machine answered, so this box is
exactly the case `revived` describes. Color, editor, shell, chat app and
where the notebook lives all followed with their defaults (Enter each
time), then:

    ── summary ─────────────────────────────────────────────────────────
      ✓ shape                     revived
      ✓ archlinux                 brain                                  local
      ✓ network                   none
      ✓ color                     p31
      ✓ editor                    nano
      ✓ shell                     bash
      ✓ chat                      none
      ✓ notebook                  private

      write the profile? (Y/n)
      ✓ profile                   ~/.config/phosphor/deck.toml

      next: phosphor gen && phosphor up && deck

That last line is the only thing left to do by hand outside the wizard's
own "build the deck and start it now?" (which runs those same three steps,
and only asks when it's actually attached to a terminal).

## Updating

    phosphor update              # the code is a git clone: pull, install, restart
    phosphor update FOLDER       # you copied a newer version into FOLDER

An install that came from a folder remembers it: the next time, a plain
`phosphor update` goes back there (and pulls it first if it's a git clone),
and `phosphor version` checks that clone for news.

It updates the installed copy in place, fetches only the binaries you're
missing, and gets the panes onto the new code (`--no-restart` to do that
yourself later with `phosphor restart`). Not always a real restart: a pull
that only touched one tool's own module (say, `lib/fleet.py`) refreshes
just the panes running that tool, in place, live -- everything else in the
deck, and every other tab, is left alone. Anything shared (the layout
generator, a shortcut zellij itself needs to reread, anything outside
`lib/`) still gets a real `phosphor restart`, same as always -- that
judgement call is conservative on purpose: `--full` skips it and always
restarts, if you'd rather not think about it.

A real restart only starts the new deck once the old one is proven gone:
zellij no longer lists the session, its service has stopped, and none of its
processes outlived the reaper. If anything is still alive, it stops right
there, says what, and leaves the watchdog off instead of starting new code
next to old panes; once those are gone, `phosphor restart` again. `phosphor
update` exits non-zero when that happens, and when the install itself fails
(then it doesn't restart at all), so an unattended update (cron, a timer)
knows it didn't land. Run from a pane inside the deck, the restart detaches
itself, so there the exit status only covers the install.

Two channels: **stable** follows main, which only moves when a minor version
is done (0.3.0, 0.4.0...), and the notice shows up only for a new version;
**nightly** follows dev, every patch release and what's done but not released
yet, and the notice shows every new commit with the Unreleased notes. While a
minor is being built (0.2.x), what's new is on nightly. Pick one with
`phosphor update --channel nightly` or `--channel stable`.

Which version you run: `phosphor version`. In a git clone it also checks for a
newer one, and the DECK tab shows "new version: u" when there is (u updates).

## If a download fails

GitHub sometimes answers 5xx. The installer retries; if something is still
missing it says so, and running it again fetches only what's missing. Without
zellij it stops: the deck can't run without it.

## Remove it

    phosphor down
    systemctl --user disable deck.timer deck.service
    rm -rf ~/.phosphor ~/phosphor-deck ~/.config/phosphor ~/.local/share/phosphor ~/.cache/phosphor ~/fleet
    rm -f ~/.config/systemd/user/deck.* ~/.config/systemd/user/fleet-*.service \
          ~/.config/systemd/user/tunnel-*.service ~/.local/bin/phosphor ~/.local/bin/deck

`~/.config/zellij` and the binaries in `~/.local/bin` only if you didn't have
them before.
