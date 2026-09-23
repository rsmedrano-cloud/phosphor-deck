#!/usr/bin/env python3
"""An investigation, not a regression test: trying to reproduce the zellij
0.45 floating-pane freeze in isolation (issue #14). Not wired into CI --
a clean run here proves nothing (it's a timing race that resisted every
recipe tried), so it would only ever be red noise, not a real signal.

    python3 tests/float-check.py

The one live diagnosis on record (commit f5799ac): the "screen" thread spun
at 99% CPU, `list-tabs` stopped answering, right after `phosphor notify`'s
hider hid floating panes of the NON-active tabs by id (hide-floating-panes
-t, looping every tab) -- and the author had just switched tabs. That loop
is gone now (see the notifier entry in doc/manual/profile.md and the
Unreleased entry it came with): lower risk, but not a proof the underlying
zellij race is gone, since it was never isolated to begin with.

What this throws at a throwaway session, in order: repeated and overlapping
`phosphor notify` calls; SGR mouse-wheel bursts and a real touch-drag
(press, motion run, release); a garbled multi-touch-like byte stream; the
pty resizing small and back while a float is visible (#3926 upstream); and,
closest to the live diagnosis, tab switches timed into the exact window
where the hider used to walk every tab (round 6) and into deck-up.sh's own
startup hide-loop (round 7). None of it wedged a session in dozens of runs.

If it happens again for real: `phosphor logs`, and whether the "screen"
thread specifically is spinning (`top -H -p $(pgrep -f 'zellij.*--server')`)
is the detail the one prior diagnosis actually used -- everything else
(clients, panes, CPU by pid) came up empty.

Needs zellij; without it, it says so and passes (same as edit-check.py).
"""
import fcntl, os, signal, struct, subprocess, sys, termios, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zjprobe

PROFILE = '''
[deck]
session = "float-probe"
notifier = true
notify_seconds = 1

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name = "A"
panes = [ { cmd = "" } ]

[[tabs]]
name = "B"
panes = [ { cmd = "" } ]
'''

# The one live diagnosis on record (commit f5799ac): the "screen" thread spun
# at 99%, list-tabs stopped answering, right after notify's hider hid floating
# panes of the NON-active tabs by id (hide-floating-panes -t, looping every
# tab) -- and the author had just switched tabs. More tabs widen that loop's
# window; this profile is for timing a tab switch into it on purpose.
MANY_TABS = '''
[deck]
session = "{SESSION}"
notifier = true
notify_seconds = 1

[[hosts]]
name = "box"
role = "brain"
local = true
''' + "\n".join('[[tabs]]\nname = "T%d"\npanes = [ { cmd = "" } ]\n' % i for i in range(6))

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)
    return ok

def scroll_burst(z, n=40):
    """SGR mouse-wheel events at a fixed spot: what a finger drag sends."""
    seq = b""
    for i in range(n):
        code = 65 if i % 2 else 64          # 64 up, 65 down: alternate, like a shove
        seq += b"\x1b[<%d;40;12M" % code
    z.keys(seq, settle=0)

def resize(z, rows, cols):
    """A touchscreen rotating, or a terminal app resized mid-scroll: the pty
    changes size and the child gets SIGWINCH -- issue #3926 upstream crashed
    zellij resizing a tiled pane very small with a floating one visible."""
    fcntl.ioctl(z.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    try:
        os.kill(z.pid, signal.SIGWINCH)
    except OSError:
        pass

def touch_drag(z, n=25):
    """SGR press + a run of motion events + release: a finger dragging to
    scroll, as opposed to a mouse's discrete wheel clicks."""
    seq = b"\x1b[<0;40;20M"                          # press
    y = 20
    for i in range(n):
        y += 1 if i % 2 else -1
        seq += b"\x1b[<32;40;%dM" % y                # motion, button held
    seq += b"\x1b[<0;40;%dm" % y                      # release
    z.keys(seq, settle=0)

def touch_garble(z):
    """Two fingers at once, or a terminal app under load: interleaved and
    truncated SGR sequences -- a state a single finger's clean stream never
    produces, but a real touchscreen's driver sometimes does."""
    seq = (b"\x1b[<0;10;5M\x1b[<0;60;15M"             # two presses, no release
           b"\x1b[<32;12;6M\x1b[<32;58;1" +           # one motion cut off mid-number
           b"\x1b[<3;10;5m" +                          # a release for a button never reported this way
           b"4;16M\x1b[<32;13;7M")                     # the rest of the cut sequence lands as garbage
    z.keys(seq, settle=0)

def notify(z, msg):
    return subprocess.Popen([os.path.join(z.env["HOME"], ".local/bin/phosphor"), "notify", "--no-tts", "--no-push", msg],
                            env=z.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def responsive(z, timeout=8):
    try:
        r = subprocess.run([z.zj, "--session", z.session, "action", "list-tabs"],
                           env=z.env, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0 and "A" in r.stdout
    except subprocess.TimeoutExpired:
        return False

if not zjprobe.zellij():
    print("ok — zellij isn't installed, skipping"); sys.exit(0)

with zjprobe.Probe(PROFILE, session="float-probe") as z:
    need("session starts with notifier=true", responsive(z))

    # Round 1: notify, then immediately scroll while its floating pane is up
    # and its hider (notify_seconds=1) is about to fire.
    for _ in range(6):
        notify(z, "tick")
        scroll_burst(z, 15)
        z.pump(0.2)
    time.sleep(1.5)   # let every hider run

    # Round 2: overlapping notifies (a second one before the first's hider
    # fires) plus scroll and a tab switch mid-flight -- closer to real use
    # (an alert lands while you're mid-scroll and you flip tabs to look).
    procs = [notify(z, "a"), notify(z, "b")]
    scroll_burst(z, 30)
    z.keys("\x1b2", settle=0.1)      # Alt-2: switch tab while floats are moving
    z.keys("\x1b1", settle=0.1)
    scroll_burst(z, 30)
    for p in procs: p.wait(timeout=10)
    time.sleep(1.5)

    need("still answers after overlapping notify + scroll", responsive(z))

    # Round 3: hammer show/hide directly (skip phosphor notify's own pacing)
    # back to back, the tightest loop the code path allows.
    for _ in range(20):
        subprocess.run([z.zj, "-s", z.session, "action", "show-floating-panes"],
                       env=z.env, capture_output=True, timeout=5)
        subprocess.run([z.zj, "-s", z.session, "action", "hide-floating-panes"],
                       env=z.env, capture_output=True, timeout=5)
        scroll_burst(z, 5)

    need("still answers after a show/hide hammer", responsive(z, timeout=12))
    need("the pty is still drawing (not a blank/stuck screen)", len(z.text()) > 0)

    # Round 4: a floating pane visible while the pty resizes small and back
    # (a phone rotating, or the terminal app resizing mid-scroll) -- #3926
    # upstream crashed zellij resizing very small with a floating pane up.
    subprocess.run([z.zj, "-s", z.session, "action", "show-floating-panes"],
                   env=z.env, capture_output=True, timeout=5)
    for _ in range(10):
        resize(z, 6, 20)
        scroll_burst(z, 5)
        z.pump(0.05)
        resize(z, 40, 140)
        scroll_burst(z, 5)
        z.pump(0.05)
    time.sleep(0.5)
    need("still answers after resize-while-floating", responsive(z, timeout=12))

    # Round 5: a real touch drag (press, motion run, release) and a garbled
    # multi-touch-like stream, both while floats show/hide keep firing.
    for _ in range(8):
        notify(z, "tick")
        touch_drag(z, 20)
        touch_garble(z)
        z.pump(0.1)
    time.sleep(1.5)
    need("still answers after touch-drag + garbled multitouch", responsive(z, timeout=12))

    print("  rounds 1-5: no wedge yet, trying the live-diagnosed timing (round 6)")

# Round 6: the literal sequence from the one live diagnosis (commit
# f5799ac) -- notify, then switch tabs right as the hider is hiding every
# OTHER tab's floating pane by id. Repeated, since it's a timing window,
# not a guaranteed hit.
hit = False
for attempt in range(15):
    with zjprobe.Probe(MANY_TABS.replace("{SESSION}", "float-probe-many"), session="float-probe-many") as z:
        if not responsive(z):
            need("many-tab session starts", False)
            break
        notify(z, "tick")
        # notify_seconds=1: the hider starts ~1s from now and walks 6 tabs.
        # Land a burst of tab switches across that whole window.
        t0 = time.time()
        while time.time() - t0 < 1.6:
            for n in range(1, 7):
                z.keys("\x1b%d" % n, settle=0)
            time.sleep(0.02)
        time.sleep(0.3)
        if not responsive(z, timeout=6):
            hit = True
            print("  REPRODUCED on attempt %d: unresponsive after notify + tab-switch during hide-floating-panes -t"
                  % (attempt + 1))
            break
print("  round 6: %s after 15 attempts" % ("reproduced" if hit else "no wedge"))
need("round 6 (notify + tab-switch timing) never wedged the session", not hit)

# Round 7: floating panes start VISIBLE on every tab (the layout's own
# default) until deck-up.sh's own startup routine hides them -- two passes
# of hide-floating-panes -t across every tab id, a couple of seconds apart
# (lib/gen.py's DECK_UP script). zjprobe attaches straight to zellij and
# skips deck-up.sh, so replay its exact loop here, in a background thread,
# while switching tabs through that whole window -- attaching and going
# straight to work is the ordinary case, not an edge case.
import threading

def deck_up_hide_loop(z):
    for _ in range(2):
        time.sleep(2)
        out = subprocess.run([z.zj, "-s", z.session, "action", "list-tabs"],
                             env=z.env, capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines()[1:]:
            tid = line.split()[0]
            subprocess.run([z.zj, "-s", z.session, "action", "hide-floating-panes", "-t", tid],
                           env=z.env, capture_output=True, timeout=10)

hit2 = False
for attempt in range(10):
    with zjprobe.Probe(MANY_TABS.replace("{SESSION}", "float-probe-startup"), session="float-probe-startup") as z:
        if not responsive(z):
            continue
        th = threading.Thread(target=deck_up_hide_loop, args=(z,), daemon=True)
        th.start()
        t0 = time.time()
        while time.time() - t0 < 4.5:              # covers both hide passes
            for n in range(1, 7):
                z.keys("\x1b%d" % n, settle=0)
            scroll_burst(z, 5)
            time.sleep(0.03)
        th.join(timeout=5)
        if not responsive(z, timeout=6):
            hit2 = True
            print("  REPRODUCED on attempt %d: unresponsive during startup's own hide-floating-panes -t loop"
                  % (attempt + 1))
            break
print("  round 7: %s after 10 attempts" % ("reproduced" if hit2 else "no wedge"))
need("round 7 (deck-up.sh's own startup hide loop + tab switching) never wedged the session", not hit2)

if fails:
    print("FAILED (repro found or the harness broke):\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok — no wedge in this run (doesn't clear zellij: only says this recipe didn't hit it)")
