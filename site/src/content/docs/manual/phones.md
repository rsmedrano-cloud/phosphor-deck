---
title: Screens
sidebar:
  order: 8
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

It also makes Termux a place to share files to: in any app (Files, the
gallery, a browser's download), Share, pick Termux, then **Edit**, and the
file goes over the same ssh into the brain's `~/received`, under a name of
plain characters, never over one already there. (Termux keeps its own copy
in `~/downloads`. A `~/bin/termux-file-editor` of your own is left alone.)

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
    skip   = ["phosphor adjutant"]          # panes it doesn't need, by their cmd

    [screens.eink]
    theme  = "paper"

Or let `phosphor setup` write it: "connect a phone or tablet" ends by
asking whether that screen shares this deck (nothing to change) or gets a
deck of its own -- the kind, which tabs -- and says what to run on the
screen after. It says the cost first: **a deck of its own starts every pane
it keeps a second time**, assistants included. The same step takes a
kind's block back out.

Then `phosphor gen` (no restart needed). The screen says which kind it is
when it comes in: the phone kit's `deck` already says `phone`; for another
computer, an e-ink reader or a Pi on a shelf, `phosphor screen --as eink`
writes a `deck` that says `eink` (`phosphor phone --as tablet` is the Termux
kit for a tablet that should say `tablet`), and on anything with only ssh it's
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
block, or a screen that says nothing, gets the deck as always. A kind's
session runs its own copy of every pane it keeps, so it costs memory of
its own: `phosphor mem` says how much, tab by tab (`SYS · phone`).

### A touch screen with no keyboard

A Pi with a 7" touch screen on a desk, a tablet on a stand: everything can
be reached by tap, as long as its kind has the tabs for it. Put `DECK` in
its `tabs` -- every phosphor action is a tap there -- and the tabs you
actually look at (`SYS`, `NOTES`). The tab bar's `+` menu, a pane that
ended (open it again, close it, its log) and the NOTES keys all take a tap.
Writing text (a note, a search) is the one thing that needs keys: use the
system's own on-screen keyboard, or skip it on that screen.

    [screens.tablet]
    tabs = ["SYS", "NOTES", "DECK"]
    land = "SYS"

## Managing screens from the deck

zellij ties a tab's whole grid to the smallest attached client's viewport,
with no setting to change that -- so a phone looking at the same tab as
your PC squeezes everyone's pane down to phone size. `phosphor screens`
(also `v` in the DECK tab) lists every screen actually attached (where
it's from, how long it's been idle, which deck it's in) and lets you kick one loose with `x`
(it asks y/n first, on purpose): it just ends that one ssh connection, and the `deck`
wrapper above notices the drop and reconnects on its own in a few seconds.
A terminal on the brain itself is no ssh login, so it has no row to kick, but it's
counted all the same ("1 attached here on the brain, none over ssh"), the way the
screens card and the header count it.
Not a way to ban a device -- a way to force one reconnect without walking
over to whichever screen is in the way.

`o` (asking too) changes which deck a kind of screen gets, from the screen
in front of you: on a tablet in a deck of its own, every tablet shares this
deck again (`[screens.tablet]` comes out of the profile and `deck-tablet`
closes, its panes with it); on a screen that says a kind (`deck (phone)` in
the list) but shares the deck, that kind gets a deck of its own with every
tab, which you can trim afterwards in its block. Before you say y it
says the cost. Either way the screens of that kind are kicked and come back
where they now belong, and the profile keeps a backup. It's per kind, not
per device: every screen saying that kind moves. A screen that says no kind
gets a hint instead -- it has to say one first (`phosphor screen --as KIND`
on it).

### A screen through a relay

A screen with no direct path to the brain reaches it through one of
tailscale's relay servers (DERP), a much thinner link: ten redraws a
second of the adjutant and the old pulse panel were enough to freeze a Pi
that came in that way, while the same Pi over the LAN was fine. So while a screen
attached to a deck comes through a relay, that deck's animations drop to
one frame a second -- every screen of that deck sees the slower pace, since
zellij sends the same panes to all of them, so give such a screen a kind of
its own (`[screens.KIND]`) if the others shouldn't share it. `phosphor
screens` marks it "relay"; `phosphor logs adjutant` says when the pace changed.
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
summary that refreshes on its own -- the fleet's problem hosts (or
"all N ok"), unread mentions, open todos, any workspace dirty or unpushed -- until `q` or Ctrl-C. Nothing to attach,
nothing to detach: it's just a command, so any cron job or kiosk script that
can run one over ssh can drive that little screen.

It's made for slow screens too, e-ink above all. It repaints only when what
it says changes (or every 10 minutes), so the time on its top line is when
it last changed, not a clock; `r` clears and repaints, for e-ink ghosting.
On a screen of 96 columns or more the four sections sit side by side, two by
two, so a 130x17 panel shows all of them whole. A terminal with no color
(`TERM` like `xterm-mono` or `vt100`, or `NO_COLOR` set; `--mono` forces it)
gets plain text, with what's wrong in bold and the light reversed when it's
red: some e-ink ssh clients read the numbers inside a 24-bit color as other
codes and turn on bold or reverse at random. A key that should only ever
show this can say so in `~/.ssh/authorized_keys`:
`command="~/.local/bin/phosphor glance" ssh-ed25519 ...`.

Up, down and Enter -- all an e-ink panel's wheel sends -- are enough to act
on it; with a keyboard, `j`/`k` move too and Esc goes back. The first up or
down puts a cursor (`▸`, reversed) on a host, a mention, a todo or a
workspace; Enter opens it whole on a page of its own, its actions on the
last line: `done` for a todo (it goes to the archive, like `x` in NOTES),
`all read` for the mentions, `snooze 24h` for a host you already know
about (`phosphor snooze`: it leaves glance, the light and every other
screen until tomorrow, or until it gets worse), and `back`, where the
cursor starts, so a stray Enter changes nothing. Two minutes without a key and the summary is
back on its own, so a panel left on a page still shows what's wrong. Only
the lines that change are sent, so moving the cursor redraws one line, not
the screen.

### A gadget that can't ssh

A microcontroller with a 2.9" e-paper (an ESP32), a Pi Zero with a tiny
OLED: these can make an HTTP request, not an ssh session. For them, on the
brain:

    phosphor glance --serve              # port 8484; --port N for another

It prints an address with a token (and a QR of it); the gadget asks it with
a plain GET -- `?token=` in the address, or an `Authorization: Bearer`
header -- and gets one JSON object back:

    {"status": "amber", "t": 1791287707,
     "fleet": {"ok": 3, "total": 3, "stale": false,
               "problems": [{"host": "db-box", "detail": "reboot pending", "down": false}]},
     "worst": {"host": "db-box", "detail": "reboot pending"},
     "mentions": 0, "todos": 2, "workspaces": 1}

`status` is the light to show: **red** when a host is down or the readings
stopped coming, **amber** for anything else worth a look (a host's problem,
an unread mention), **green** otherwise, **unknown** with no fleet data.
Open todos and dirty workspaces are counted but never change the color.
`phosphor glance --json` prints the same thing in a terminal.

It's read-only and listens only on the brain's tailnet address (the LAN's
without a tailnet, where the token crosses the network in the clear); any
other path, or a request without the token, gets nothing. A gadget on the
home Wi-Fi with no tailnet (most microcontrollers) can't reach the tailnet
address: `--lan` listens on the LAN's instead, with the token in the clear
there too. The token is kept
in `~/.local/share/phosphor/glance-token` (only you can read it) so a
flashed gadget keeps working across restarts; `--new-token` replaces it.
It runs in the foreground, Ctrl-C stops it. To keep it up, give it a tab of
its own -- `phosphor run` brings it back if it ends:

    [[tabs]]
    name  = "GLANCE"
    panes = [{ cmd = "phosphor glance", args = ["--serve"] }]

**A SolarOS panel** (an ESP32-S3 e-ink like the CrowPanel) has a whole
app of its own, built on this: see "A SolarOS panel" below.

## One pane instead of the whole deck

A screen that reads slower than zellij writes can't attach at all: zellij
drops a client that falls behind ("client too slow") and the screen
freezes. An e-ink panel takes a few KB a second; one busy tab, an
assistant redrawing its spinner, sends megabytes a minute, mostly colors a
mono screen can't show. `phosphor mirror` shows one pane without attaching:

    ssh -t you@brain ~/.local/bin/phosphor mirror --tab AI

It reads that pane's text from the deck's session -- a tab nobody is
looking at works too -- and sends only the lines that changed, with no
color, once a second at most. It reads the pane again only once the last
paint went through, so a slow link sets the pace and what changed
meanwhile arrives as one paint, never as a backlog. The pane keeps the
size the deck gave it: a line wider than the screen wraps (a rule of box
lines is cut instead) and the screen shows the bottom, where the prompt is.

What you type goes into that pane, so a BLE keyboard on the panel holds a
conversation with the assistant in AI. That's typing in the pane itself:
Ctrl-C and all reach the program there; only Ctrl-] stays with mirror, and
leaves it. `--view` only watches (no key reaches the pane; `q` and Ctrl-C
leave too), `--pane ID` picks one pane of a tab with several (`phosphor
mirror` alone lists them), and `--once` prints one frame, for a script.
A key that should only ever watch the AI tab can say so in
`~/.ssh/authorized_keys`: `command="~/.local/bin/phosphor mirror --tab AI
--view" ssh-ed25519 ...`.

The notebook works the same way, no zellij in between:
`ssh -t you@brain ~/.local/bin/phosphor notes`. On a terminal with no color
(`TERM` like `xterm-mono`, or `NO_COLOR`) it drops its colors and keeps
bold and reverse, as glance does.

## A SolarOS panel

A SolarOS panel (an ESP32-S3 e-ink like the CrowPanel) gets an app of its
own: a menu of the deck. It never attaches a zellij client, so the deck's
redraws can't flood it. One switch on the brain:

    phosphor solaros on

That keeps `phosphor glance --serve --lan` running as a user service
(`phosphor-glance.service`, `[glance] serve = "lan"` in the profile; it
comes back after a reboot), prints the two lines to type on the panel's
SolarOS prompt and puts them on the clipboard of every screen looking at
the deck (`E` in the DECK tab's actions does the same):

    curl -o /phosphor.py http://<brain>:8484/p/k7q2m
    python /phosphor.py

From a serial console instead, put it on the display with `session
create python display0 /phosphor.py`.

Those two lines are typed once. The code at the end of the first (five
letters and digits, none you could misread) works one time, for 10
minutes; `phosphor solaros on` again prints a new one. The first run adds `phosphor` to the
SolarOS shell (a line in `/.shell/alias`; one you already have for that
name is left alone), so later it's one word at the prompt, and, when
SolarOS's launcher has a free cell, asks once whether to put Phosphor
there (Enter yes, Esc no; `put Phosphor in the launcher` stays in the menu
for later). A cell named Phosphor that you made yourself counts: nothing
is added next to it, and a copy an older install put there goes. SolarOS's
launcher only takes its own icons, so the cell shows `terminal`; on a
launcher patched to take a file as an icon (one of its cells already
shows one), it shows `/icons/phosphor.pbm` when that file is there. And it updates itself: at every start the app asks the brain
which copy it hands out (the brain reads `share/solaros-app.py` on each
request, so a `phosphor update` there is enough) and, when it's another
one, fetches it, writes it over `/phosphor.py` and starts it, one line on
screen. A copy from before 2.0.9 can't do that: type the two lines once
more.

The app shows the glance's light and counts on top and, below, the menu:
**glance** (the hosts with a problem, the counts; read over HTTP, repainted
only when it changes), one entry per tab of the deck as it is now (AI,
AGY, a workspace you opened since; NOTES and FLEET at the end when no tab
has them) and **write a note**. Up, Down (the wheel) and Enter; `r` reads
the brain again; Esc, `q` or EXIT leave. On the CrowPanel 5.79" keep the
display's default refresh (`display mode display0 refresh=auto`): `fast`
and `full` left that panel black or frozen until a reboot.

A tab opens the panel's own deck, over ssh with the panel's key, on that
tab: the tab bar on top, the one you're on in inverse, and the tab below.
**Ctrl-Left** / **Ctrl-Right** go to the tab before or after, and
**Ctrl-Up** / **Ctrl-Down** to the pane before or after in a tab with
several (its name at the right of the bar). With a left Alt key,
**Alt-1** ... **Alt-9** (**Alt-0** the tenth) go straight to a tab, as in
the deck, and Alt-Up / Alt-Down and Alt-p work too. A keyboard with only
AltGr sends no Alt, and SolarOS keeps Alt-Left, Alt-Right and Alt-Tab for
its own sessions: those never reach the deck. Everything else you type goes to the tab: the wheel
scrolls its list, and in AI you talk to the assistant. **Ctrl-q**, as in
the deck, or the panel's EXIT closes the session (the bar says so when
there's room): you're back where you opened it, the launcher or the
SolarOS prompt, where `phosphor` opens the menu again.

phosphor's own screens (NOTES, DECK, FLEET, CI...) and viewers that keep
nothing of their own (yazi, btop, ctop, gping) run right there at the
panel's size. Anything else (a shell, an assistant, a chat) lives in its
pane of the deck and is mirrored (`phosphor mirror`), at the size the
last screen on the deck gave it: a long line wraps. Either way the panel
gets only the lines that changed, at most about three times a second,
however often the screen behind them redraws. FLEET lists each machine
with its pending updates and reboot, where `upgrade` and `reboot` run
`phosphor upkeep` right there: it shows the command and waits for you,
and sudo asks on the panel; `snooze 24h` quiets what's wrong on it for a
day (`wake` undoes it). A screen you leave keeps running (the last
four), so coming back to it is instant; one that ends says so, and Enter
starts it again.

What only reads comes over HTTP, behind the token. Everything that does
something goes over ssh with the panel's own key. On the LAN the token
crosses the network in the clear, so it can read, never type.

The key is paired once. On the brain:

    phosphor solaros pair

opens a window for 10 minutes. On the panel, `pair with the brain` makes
the panel's ssh key (the first time; it can take a minute) and sends it.
Both screens show its fingerprint: the same on both means nobody swapped
it on the way, and Enter on the brain lets it in. It lands in
`~/.ssh/authorized_keys` with a forced command (`restrict,pty`, no
forwarding): that key gets the panel's deck, whatever it asks to run,
not a login of its own. Still, pair only a panel you'd hand the deck to:
the menu opens the deck's tabs, and typing in one -- a shell, an
assistant -- is typing there. The old file stays as `authorized_keys.bak.solaros`; a line
that key already had (a panel set up by hand) is replaced.

SolarOS's ssh can't send a remote command (it always asks for a shell),
so the app tells the brain over HTTP which entry it's about to open, then
connects; the session takes that once, within a minute, and only if it's
on the menu. Without it, the session starts on the menu.

    phosphor solaros            the service, the address, the paired panels
    phosphor solaros off        stop serving (paired keys stay)
    phosphor solaros forget     take every paired panel's key out
