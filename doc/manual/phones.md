# Screens

A screen is anything with a terminal: a phone, another computer, an old
laptop, a pocket terminal. None of them hold state — the deck stays on the
brain — so adding one is one line, and removing one is deleting that line.

`phosphor phone` (also `p` in the DECK tab) prints all of this for your own
deck, with the phone's line as a QR to scan with the camera.

## A phone or tablet (Android + Termux)

    pkg install -y openssh
    ssh you@brain '~/.local/bin/phosphor phone' | sh

The brain answers with a script made for your deck: the phone's ssh key (your
password one last time), a `deck` command, a Termux:Widget icon, and extra keys
(KEYBOARD, EDIT, ZOOM, EXIT). Run it again any time; it only adds what's
missing, and a phone with the kit's older keys gets EDIT too.

## Another computer (Linux, macOS, WSL)

    ssh you@brain '~/.local/bin/phosphor screen' | sh

The same thing without Termux: a key, and a `deck` command in `~/.local/bin`
that reconnects by itself. Nothing else is installed: an old laptop makes a
fine screen.

## Anything that only has ssh

    ssh -t you@brain ~/.local/bin/deck

An old terminal, an ssh app on an iPad, a pocket terminal. The full path
matters: a plain ssh command gets no login shell, so a bare `deck` isn't
found. This is also what the kits above end up running.

## ssh, not mosh

mosh survives sleep and network changes but doesn't carry the mouse, so no
touch. The `deck` command uses ssh and reconnects by itself when the link
drops (every 3s until the network is back) and when the deck restarts;
leaving with EXIT or Ctrl-q ends it. If Android killed Termux, tap the icon.

Narrow screens: Alt-z (ZOOM) gives one pane the whole screen. With headscale,
the phone's Tailscale app must log into your headscale server; `phosphor
phone` prints which.

## A deck for each kind of screen

zellij sizes a tab to the smallest screen looking at it, so a phone and a
desktop in the same tabs squeeze each other. Give a kind of screen a block
in the profile and it gets a deck of its own, laid out for it:

    [screens.phone]
    tabs   = ["SYS", "NOTES", "COMMS"]   # which tabs, in this order (default: all)
    land   = "NOTES"                     # the tab you arrive on (default: the first)
    graphs = "blocks"                    # default: the deck's

    [screens.tablet]
    skip   = ["phosphor pulse"]          # panes it doesn't need, by their cmd

    [screens.eink]
    theme  = "paper"

Then `phosphor gen` (no restart needed). The screen says which kind it is
when it comes in: the phone kit's `deck` already says `phone`; for another
computer, an e-ink reader or a Pi on a shelf, `phosphor screen --as eink`
writes a `deck` that says `eink`, and on anything with only ssh it's
`ssh -t you@brain '~/.local/bin/deck --screen eink'`. A phone set up before
this: run its kit again.

Each kind is its own zellij session on the brain (`deck-phone`,
`deck-eink`), made the first time a screen of that kind comes in. The
notebook, the fleet, `~/fleet`, your workspaces and the profile are the
same everywhere; the panes aren't -- a shell on the phone isn't the one on
the desktop, and a tab you open on one doesn't show on the other. The
fleet is polled once, by the deck's own session, and every kind's FLEET
card reads that. `phosphor restart` and `down` take every kind's session
along, and each screen goes back into its own by itself. A kind with no
block, or a screen that says nothing, gets the deck as always.

## Managing screens from the deck

zellij ties a tab's whole grid to the smallest attached client's viewport,
with no setting to change that -- so a phone looking at the same tab as
your PC squeezes everyone's pane down to phone size. `phosphor screens`
(also `v` in the DECK tab) lists every screen actually attached (where
it's from, how long it's been idle, which deck it's in) and lets you kick one loose with `x`
(twice, on purpose): it just ends that one ssh connection, and the `deck`
wrapper above notices the drop and reconnects on its own in a few seconds.
Not a way to ban a device -- a way to force one reconnect without walking
over to whichever screen is in the way.

### A screen through a relay

A screen with no direct path to the brain reaches it through one of
tailscale's relay servers (DERP), a much thinner link: ten redraws a
second of pulse and the adjutant were enough to freeze a Pi that came in
that way, while the same Pi over the LAN was fine. So while a screen
attached to a deck comes through a relay, that deck's animations drop to
one frame a second -- every screen of that deck sees the slower pace, since
zellij sends the same panes to all of them, so give such a screen a kind of
its own (`[screens.KIND]`) if the others shouldn't share it. `phosphor
screens` marks it "relay"; `phosphor logs pulse` says when the pace changed.
`tailscale ping NAME` shows whether a direct path exists at all.

## Notifications when you're not attached

A screen only shows what's happening while you're looking at it. For when
you're not: install the [ntfy](https://ntfy.sh) app (Play Store, F-Droid, or
`pkg install ntfy` in Termux), turn on `[push]` in the profile (see profile),
then

    phosphor push --qr

and scan the code in the ntfy app (its own "+" → scan a QR, not the phone's
camera app) to subscribe -- no typing the server or topic in by hand. From
then on `phosphor notify --push`, a fleet host going down or coming back, and
a chat mention all ring and vibrate the phone, Termux open or not. With
browser access on (see web), tapping the notice -- or its "open the deck"
button -- opens the deck in the phone's browser.

## A glance instead of the whole deck

Some screens are too small for a full attach: a Pi with a small display
sitting on a shelf, an old e-reader, anything you'd rather glance at than
drive. `ssh -t you@brain ~/.local/bin/phosphor glance` skips zellij entirely and prints a
read-only summary that refreshes on its own -- the fleet's problem hosts (or
"all N ok"), unread mentions, open todos, any workspace dirty or unpushed -- until Ctrl-C. Nothing to attach,
nothing to detach: it's just a command, so any cron job or kiosk script that
can run one over ssh can drive that little screen.
