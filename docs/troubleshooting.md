---
layout: default
title: Troubleshooting
permalink: /troubleshooting/
---

[Home](/) · [Concepts](/concepts/) · [Install](/install/) · [Patterns](/patterns/) · [The profile](/profile/) · [Commands](/commands/) · [Keys](/keys/) · [Screens](/phones/) · [Workspaces](/workspaces/) · [Mentions](/mentions/) · [The deck in a browser](/web/) · [Tunnels](/tunnels/) · [Clipboard](/clipboard/) · [Privacy](/privacy/) · **Troubleshooting**

---


- **Start with** `phosphor doctor`. Red is blocking, amber isn't.
- **A pane says "ended"**: its program exited. Enter reopens it, x closes the
  tab, l shows what phosphor logged for it (also `phosphor logs TOOL`). A tab
  you closed comes back with `phosphor restart`.
- **A tab I closed keeps coming back after a restart**: it's kept in your
  profile. `phosphor tabs` (b in the DECK tab) forgets it, or press f instead
  of x when its last program ends.
- **"isn't installed"**: run the installer again (`sh ~/.phosphor/install.sh`);
  it fetches only what's missing.
- **"the deck is starting..."**: `deck` found the session not up yet (right
  after boot or `phosphor up`) and waits for it, up to a minute and a half.
- **The deck is gone**: the watchdog brings it back within a minute; `phosphor
  up` if you ran `phosphor down`.
- **A change to the profile doesn't show**: `phosphor gen && phosphor restart`.
- **A new version doesn't show**: the panes run the code they started with.
  `phosphor update` restarts the deck for you; after updating any other way,
  `phosphor restart`.
- **A data file change doesn't show** (key guide, store): a copy in
  `~/.local/share/phosphor/` overrides the repo's. Remove it.
- **The deck takes a long time to load or refresh**: usually one slow or
  unreachable host in the fleet -- ssh has up to 25s to answer before a poll
  gives up. `phosphor logs fleet` says how long the *first* poll round took
  (always logged once) and flags any later round over 3s, without naming
  which host (deck.log is meant to be safe to paste into an issue). To see
  which one: its FLEET card says "slow poll: Ns" while it's ok, or the
  seconds it took to fail next to "unreachable". A host that's been down for
  a couple of polls in a row only gets a short 2s/5s probe on every round
  after that (the first two still get the full 6s/25s -- a real blip
  deserves the benefit of the doubt), so a chronically unreachable host
  stops dragging every refresh on its own.
- **A folder in `~/fleet` is empty** (yazi shows nothing, or won't go in):
  its mount isn't up. `phosphor doctor` says which ones are mounted;
  `journalctl --user -u fleet-NAME` says why. Mounts use your own ssh, so
  `ssh NAME` has to work first. The mounts run as a systemd service, not in your
  terminal: if your key has a passphrase, the service has no agent to ask.
  `phosphor doctor` checks that too; `systemctl --user import-environment
  SSH_AUTH_SOCK` (then `phosphor gen`) gives the service your agent, or use a
  key without a passphrase for the deck.
- **A frozen pane**: Ctrl-Z in a pane without a shell stops the program; the
  deck resumes it within seconds. A program stuck on its last frame (it
  doesn't redraw when you resize) is closed after 20 seconds and says
  "stopped responding"; Enter opens it again. It's in `phosphor logs TOOL` too.
- **A deck key does nothing** (Alt-r, Alt-n...): `phosphor gen` says what it
  did with config.kdl. "yours, without the deck's keys" means your own
  config has no PHOSPHOR KEYS block: `phosphor shortcuts --kdl` prints it to
  paste inside `keybinds { }`. A terminal or a browser may take the key
  before the deck sees it: move it with `phosphor shortcuts`.
- **"This session exists and web clients cannot attach to it"**: your
  config.kdl predates `web_sharing "on"` (see web) or defines its own and
  it's off. `phosphor gen` (a fresh one adds the line; an old one you edited
  by hand needs it added yourself), then `phosphor restart`.
- **Graphs look like boxes with a hex number**: your font has no Braille.
  Put `graphs = "blocks"` in `[deck]` (then `phosphor gen && phosphor restart`),
  or use a font like DejaVu Sans Mono.
- **Logs**: `phosphor logs` reads `~/.cache/phosphor/deck.log` (crashes with
  their traceback, hangs, exits, restarts; `-f` follows), and `phosphor trace
  TOOL` turns on a verbose one for ~30 minutes. Never note text or hosts, so
  it's safe to paste into an issue. Below that: `journalctl --user -u
  deck.service`, `/tmp/zellij-$(id -u)/zellij-log/zellij.log`,
  `~/.cache/phosphor/restart.log`.
- **Never** run `zellij action new-tab` against the deck with nobody attached,
  and don't test against the live session: use a throwaway one.
