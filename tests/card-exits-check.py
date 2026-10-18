#!/usr/bin/env python3
"""Every card's tap comes back: on its own, or on the first Esc.

    python3 tests/card-exits-check.py [CARD...]

A tester filled a tab with every card, and many of the screens they open
kept them there: the panels that only draw (ci, prom, usage) took no key at
all, glance only q, setup's menu only Ctrl-C -- and Ctrl-C took the cards
down with it. Each card runs here as card.tap runs it (PHOSPHOR_CARD names
its parent), in a pseudo-terminal of its own, against a throwaway HOME and
profile, with no zellij on PATH: it must end by itself, or on one Esc (a
screen of its own, a question it asks). Left out, and why: toggles and the cards that
change things (they ask first, and would), and the ones that ask for a
value before they run (card.asked's own line, where Esc goes back).

Then: Ctrl-C in the screen a card opened ends that screen, not whatever
opened it (the cards, the DECK tab); and Esc at a y/n is no.
"""
import os, pty, select, signal, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import cli, dash

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, ".config", "phosphor"))
PROFILE = os.path.join(tmp, ".config", "phosphor", "deck.toml")
TEXT = '[deck]\nsession = "card-exits"\n\n[[hosts]]\nname = "probe-brain"\nrole = "brain"\nlocal = true\n'
open(PROFILE, "w").write(TEXT)
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR", "SSH_"))}
ENV.update(HOME=tmp, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=os.path.join(tmp, "cache"), PHOSPHOR_NOTES=os.path.join(tmp, "notes.md"),
           XDG_RUNTIME_DIR=tmp, TERM="xterm-256color", COLUMNS="100", LINES="30",
           PATH=os.pathsep.join(p for p in ("/usr/local/bin", "/usr/bin", "/bin")))   # no zellij

fails = []

def read(fd, secs, until=lambda out: False):
    out, end = b"", time.time() + secs
    while time.time() < end and not until(out):
        if select.select([fd], [], [], 0.05)[0]:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
    return out

def spawn(argv, env):
    """argv in a pty that is its controlling terminal: Ctrl-C is a signal."""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(tmp)
        os.execve(sys.executable, [sys.executable] + argv, env)
    return pid, fd

def ended(pid, secs):
    end = time.time() + secs
    while time.time() < end:
        if os.waitpid(pid, os.WNOHANG)[0]:
            return True
        time.sleep(0.05)
    return False

def tap(name):
    """How a tap on name ends: "itself", "Esc", or "never"."""
    c = cli.entries()[name]["card"]
    env = dict(ENV, PHOSPHOR_CARD="%d %s" % (os.getpid(), name))
    pid, fd = spawn([os.path.join(ROOT, "phosphor"), name] + c.get("args", []), env)
    how = None
    try:
        if ended(pid, 0.3):
            return "itself"
        read(fd, 8, lambda out: b"\x1b[?1049h" in out and out.endswith((b"\x1b[J", b"\x1b[K")))
        if ended(pid, 0.5 if c.get("tui") else 8):
            return "itself"
        os.write(fd, b"\x1b")
        read(fd, 0.2)
        how = "Esc" if ended(pid, 4) else "never"
        return how
    finally:
        if how == "never":
            try: os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
            except OSError: pass
        os.close(fd)

E = cli.entries()
safe = [n for n in dash.gallery_names()
        if E[n]["card"]["kind"] != "toggle" and not E[n]["card"].get("ask")
        and (not E[n].get("mutates") or n == "fleet")]     # fleet: changes things only on a key, behind a y/n
safe = [n for n in safe if n in sys.argv[1:]] or safe
with ThreadPoolExecutor(8) as ex:
    got = dict(zip(safe, ex.map(tap, safe)))
for n, how in sorted(got.items()):           # a question it asks (a y/n) ends on Esc too
    if how == "never":
        fails.append("%s: a tap opens it and neither it ends nor Esc ends it: the cards are out of reach" % n)

# Ctrl-C in the screen a card opened ends that screen, never the cards behind it
code = ("import sys; sys.path.insert(0, %r); import card; card.tap('ci'); print('BACK-ON-THE-CARDS')"
        % os.path.join(ROOT, "lib"))
pid, fd = spawn(["-c", code], ENV)
out = read(fd, 8, lambda o: b"\x1b[?1049h" in o)
os.write(fd, b"\x03")
out += read(fd, 4, lambda o: b"BACK-ON-THE-CARDS" in o)
if b"BACK-ON-THE-CARDS" not in out:
    fails.append("Ctrl-C in a screen a card opened took the cards down with it")
if not ended(pid, 3):
    os.kill(pid, signal.SIGKILL)
os.close(fd)

# Esc at a y/n is no, and nothing is written (migrate asks before it writes)
open(PROFILE, "w").write('[deck]\nsession = "card-exits"\n')
pid, fd = spawn([os.path.join(ROOT, "phosphor"), "migrate"], ENV)
read(fd, 8, lambda o: b"(Y/n)" in o or b"(y/N)" in o)
os.write(fd, b"\x1b")
if not ended(pid, 4):
    fails.append("migrate: Esc at its y/n didn't answer it")
    os.kill(pid, signal.SIGKILL)
if open(PROFILE).read() != '[deck]\nsession = "card-exits"\n':
    fails.append("migrate: Esc at its y/n wrote the profile anyway")
os.close(fd)

if fails:
    print("card-exits-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("card-exits-check ok (%d cards come back: %d on Esc, the rest by themselves)"
      % (len(got), sum(h == "Esc" for h in got.values())))
