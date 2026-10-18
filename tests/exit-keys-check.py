#!/usr/bin/env python3
"""Esc and q mean the same on every screen of the deck's own.

    python3 tests/exit-keys-check.py

The rule is keys.md's "Esc and q" (zoom.esc): Esc goes back a step and,
with none left, closes a screen opened over something (a shell, a card,
a menu) but never a pane of the tab; q closes what you look at. Each
screen runs for real in a pseudo-terminal against a throwaway HOME and
profile, twice: as if typed in a shell, where Esc ends it, and as a pane
of the tab (PHOSPHOR_RUN names its parent, as phosphor run does), where
Esc leaves it up and q ends it; ? lists its keys, and q there goes back
to the screen. Nothing of the real deck.
"""
import os, pty, select, signal, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOSPHOR = os.path.join(ROOT, "phosphor")
sys.path.insert(0, os.path.join(ROOT, "lib"))

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, ".config", "phosphor"))
PROFILE = os.path.join(tmp, ".config", "phosphor", "deck.toml")
open(PROFILE, "w").write('[deck]\nsession = "exit-probe"\n\n'
                         '[[hosts]]\nname = "probe-brain"\nrole = "brain"\nlocal = true\n')
NOTES = os.path.join(tmp, "notes.md")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR", "SSH_"))}
ENV.update(HOME=tmp, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=os.path.join(tmp, "cache"), PHOSPHOR_NOTES=NOTES,
           XDG_RUNTIME_DIR=tmp, TERM="xterm-256color", COLUMNS="80", LINES="24")

fails = []

# ── zoom.esc itself: outside zellij nothing is zoomed, so only who opened it counts
import zoom
def esc_with(run, card=""):
    old = dict(os.environ)
    try:
        os.environ.pop("PHOSPHOR_RUN", None); os.environ.pop("PHOSPHOR_CARD", None)
        if run: os.environ["PHOSPHOR_RUN"] = run
        if card: os.environ["PHOSPHOR_CARD"] = card
        return zoom.own_pane(), zoom.esc(), zoom.esc(opened=True)
    finally:
        os.environ.clear(); os.environ.update(old)
me = str(os.getppid())
for run, card, want, why in (
        ("", "", (False, True, True), "typed in a shell"),
        (me + " SERVICES", "", (True, False, True), "a pane of the tab"),
        ("1 SERVICES", "", (False, True, True), "a shell inside a pane (run isn't its parent)"),
        ("1 DASH", me + " fleet", (False, True, True), "a card's tap")):
    got = esc_with(run, card)
    if got != want:
        fails.append("zoom (%s): own_pane, esc, esc(opened) = %s, want %s" % (why, got, want))

# ── the screens, for real
def read_for(fd, secs):
    out, end = b"", time.time() + secs
    while time.time() < end:
        if select.select([fd], [], [], 0.05)[0]:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
    return out

def ended(p, secs):
    try:
        p.wait(timeout=secs); return True
    except subprocess.TimeoutExpired:
        return False

def drive(argv, keys, pane):
    """Run `phosphor argv`, send keys one by one; True when it ended."""
    env = dict(ENV)
    if pane:
        env["PHOSPHOR_RUN"] = "%d PROBE" % os.getpid()      # its parent is us: a pane of the tab
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, PHOSPHOR] + argv, stdin=slave, stdout=slave,
                         stderr=slave, env=env, cwd=tmp, start_new_session=True)
    os.close(slave)
    first = read_for(master, 2.5)
    done, seen = False, b""
    for k in keys:
        os.write(master, k)
        seen += read_for(master, 0.6)
        if p.poll() is not None:
            done = True; break
    done = done or ended(p, 1.5)
    if not done:
        os.killpg(p.pid, signal.SIGKILL); p.wait()
    os.close(master)
    return done, first + seen

subprocess.run([sys.executable, PHOSPHOR, "note", "a note to pick"], env=ENV, cwd=tmp,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
SCREENS = [("tabs", ["tabs"]), ("notes", ["notes"]), ("mem", ["mem"]),
           ("fleet", ["fleet"]), ("dash", ["dash", "version", "screens"])]
for name, argv in SCREENS:
    done, first = drive(argv, [b"\x1b"], pane=False)
    if b"\x1b[?1049h" not in first:
        fails.append("%s: never drew a screen: %r" % (name, first[-200:])); continue
    if not done:
        fails.append("%s, typed in a shell: Esc didn't close it" % name)
    done, _ = drive(argv, [b"\x1b"], pane=True)
    if done:
        fails.append("%s, a pane of the tab: Esc closed it (only q may)" % name)
    done, _ = drive(argv, [b"\x1b", b"q"], pane=True)
    if not done:
        fails.append("%s, a pane of the tab: q didn't close it" % name)
    done, out = drive(argv, [b"?"], pane=True)
    if b"its keys" not in out:
        fails.append("%s: ? didn't list its keys" % name)
    done, _ = drive(argv, [b"?", b"q"], pane=True)
    if done:
        fails.append("%s: q after ? closed the screen, not the list of keys" % name)

# a step back first: Esc drops the pick, the next one leaves
done, _ = drive(["notes"], [b"j", b"\x1b"], pane=False)
if done:
    fails.append("notes: Esc over a picked note left instead of dropping the pick")

if fails:
    print("FAIL\n  " + "\n  ".join(fails)); sys.exit(1)
print("ok: Esc steps back and never closes a pane of the tab, q closes, ? lists the keys, on %d screens"
      % len(SCREENS))
