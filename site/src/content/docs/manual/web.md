---
title: The deck in a browser
sidebar:
  order: 10
---


Optional, off by default, and only inside your tailnet — never the internet.

    phosphor web on [--yes]   # publish, show the address (and a QR) and a login token
    phosphor web off         # unpublish and stop the web server, checking each step
    phosphor web status      # what really runs, not just what the profile says
    phosphor web token       # a new login token (shown once)

Or `w` in the DECK tab: when it's on, `t` makes a new login token right there
and `o` turns it off; when it's off, turning it on needs a `y` (the deck
restarts, after you've copied the token). On a machine that only looks at the
deck, `phosphor web ...` runs on the brain over ssh: that's where the web server
and its tokens live.

`on` restarts the deck so the browser can share its session: with a tty (you,
or the DECK tab) it pauses for Enter first, so you can copy the token. Without
one -- a script, a cron, a policy tool driving phosphor -- it publishes and
prints the token but does **not** restart on its own; `--yes` is the explicit
opt-in for an unattended restart.

zellij's own web client listens on 127.0.0.1:8082 and asks for a login token;
`tailscale serve` publishes it over HTTPS at `https://<brain>.<tailnet>.ts.net:8443`
to your tailscale devices only, on its own port so whatever you serve on 443
is untouched. `serve` is the tailnet; `funnel` would be the internet, and the
deck never uses it (`tailscale funnel status` shows "tailnet only" for each).
Two locks: the tailnet and the token (revoke with `zellij web --revoke-token NAME`).

**Colors:** `phosphor gen` writes the deck's palette into zellij's config.kdl
(between the PHOSPHOR WEB markers, only where the deck keeps its keys; a
`web_client` of your own is left alone), so the page and the terminal in it
follow `theme`. The web server reads it when it starts: after changing the
color, `phosphor web off` and `on`. The login box (SECURITY TOKEN REQUIRED)
keeps zellij's own colors: zellij 0.45 builds them into the page.

The same block also sets `web_sharing "on"`: zellij 0.45 refuses a web
client on any session that hasn't opted in, so without it `phosphor web on`
publishes an address the browser can never actually attach to ("This
session exists and web clients cannot attach to it"). A config.kdl of your
own needs that line by hand if it sets `web_sharing` (or nothing web-related
at all) itself; `phosphor gen` leaves a `web_sharing` you already wrote alone,
same as a `web_client` of your own.

**Keys in a browser:** the browser keeps some for itself (Alt-1..9 and
Alt-arrows switch its tabs and pages, Ctrl-w and Ctrl-t never reach a page).
Tabs, panes, the + menu and Alt-r's screens all work by click, so there the
mouse is the way; `phosphor shortcuts` moves a deck key the browser takes.

**From a phone:** the phone's Tailscale app must be connected, and the address
must be the whole thing, `https://` included — the short name (`homelab`) or a
missing `https://` never gets there. Scan the QR that `on` and `status` print
instead of typing it. The token lands on the clipboard of every screen looking
at the deck, so on the phone it's just paste.

**Without tailscale** (headscale, or `mesh = "none"`) it runs for this
machine only: `phosphor web on` starts the web client on 127.0.0.1 with a
login token, and you open http://127.0.0.1:8082 in a browser here — no tunnel
needed. From another machine it takes an ssh server on the brain:
`ssh -L 8082:127.0.0.1:8082 you@brain`, then http://localhost:8082 there. The
DECK tab shows it as "web local". Across the tailnet it needs tailscale with
HTTPS certificates enabled.
