---
layout: default
title: Screens
permalink: /phones/
---

[Home](/) · [Concepts](/concepts/) · [Install](/install/) · [Patterns](/patterns/) · [The profile](/profile/) · [Commands](/commands/) · [Keys](/keys/) · **Screens** · [Workspaces](/workspaces/) · [Mentions](/mentions/) · [The deck in a browser](/web/) · [Tunnels](/tunnels/) · [Clipboard](/clipboard/) · [Privacy](/privacy/) · [Troubleshooting](/troubleshooting/)

---


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

## Managing screens from the deck

zellij ties a tab's whole grid to the smallest attached client's viewport,
with no setting to change that -- so a phone looking at the same tab as
your PC squeezes everyone's pane down to phone size. `phosphor screens`
(also `v` in the DECK tab) lists every screen actually attached (where
it's from, how long it's been idle) and lets you kick one loose with `x`
(twice, on purpose): it just ends that one ssh connection, and the `deck`
wrapper above notices the drop and reconnects on its own in a few seconds.
Not a way to ban a device -- a way to force one reconnect without walking
over to whichever screen is in the way.

## Notifications when you're not attached

A screen only shows what's happening while you're looking at it. For when
you're not: install the [ntfy](https://ntfy.sh) app (Play Store, F-Droid, or
`pkg install ntfy` in Termux), turn on `[push]` in the profile (see profile),
then

    phosphor push --qr

and scan the code in the ntfy app (its own "+" → scan a QR, not the phone's
camera app) to subscribe -- no typing the server or topic in by hand. From
then on `phosphor notify --push`, a fleet host going down or coming back, and
a chat mention all ring and vibrate the phone, Termux open or not.

## A glance instead of the whole deck

Some screens are too small for a full attach: a Pi with a small display
sitting on a shelf, an old e-reader, anything you'd rather glance at than
drive. `ssh -t you@brain ~/.local/bin/phosphor glance` skips zellij entirely and prints a
read-only summary that refreshes on its own -- the fleet's problem hosts (or
"all N ok"), unread mentions, open todos -- until Ctrl-C. Nothing to attach,
nothing to detach: it's just a command, so any cron job or kiosk script that
can run one over ssh can drive that little screen.
