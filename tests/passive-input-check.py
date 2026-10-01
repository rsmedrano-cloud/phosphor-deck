#!/usr/bin/env python3
"""The panels that only draw (ci, prom, usage, glance, pulse) never print
what reaches their pane.

    python3 tests/passive-input-check.py

zellij hands a pane a mouse wheel as arrow keys, and a stray key or a
hover can land there too; with the terminal left echoing, each one was
printed over the frame until the next redraw ("moving the mouse over the
CI panel erases characters"). Each panel runs for real in a
pseudo-terminal against a throwaway HOME and profile: an up arrow and an
SGR mouse move go in, and neither may come back out. Nothing of the real
deck.
"""
import os, pty, select, signal, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOSPHOR = os.path.join(ROOT, "phosphor")

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, ".config", "phosphor"))
PROFILE = os.path.join(tmp, ".config", "phosphor", "deck.toml")
open(PROFILE, "w").write('[deck]\nsession = "passive-probe"\n\n'
                         '[[hosts]]\nname = "probe-brain"\nrole = "brain"\nlocal = true\n')
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR", "SSH_"))}
ENV.update(HOME=tmp, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=os.path.join(tmp, "cache"), PHOSPHOR_NOTES=os.path.join(tmp, "notes.md"),
           XDG_RUNTIME_DIR=tmp, TERM="xterm-256color", COLUMNS="80", LINES="24")

def read_for(fd, secs):
    out, end = b"", time.time() + secs
    while time.time() < end:
        if select.select([fd], [], [], 0.05)[0]:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
    return out

fails = []
for tool in ("ci", "prom", "usage", "glance", "pulse"):
    master, slave = pty.openpty()
    p = subprocess.Popen([sys.executable, PHOSPHOR, tool], stdin=slave, stdout=slave,
                         stderr=slave, env=ENV, cwd=tmp, start_new_session=True)
    os.close(slave)
    first = read_for(master, 2.0)
    if b"\x1b[?1049h" not in first:
        fails.append("%s: never drew a frame: %r" % (tool, first[-200:]))
    os.write(master, b"\x1b[A\x1b[<35;5;5M")
    after = read_for(master, 1.0)
    os.killpg(p.pid, signal.SIGINT)
    read_for(master, 0.5)
    try:
        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL); p.wait()
        fails.append("%s: Ctrl-C didn't stop it" % tool)
    os.close(master)
    for seen in (b"^[[A", b"\x1b[A", b"[<35;5;5M"):
        if seen in after:
            fails.append("%s: echoed %r back onto its frame" % (tool, seen))
            break

if fails:
    print("\n".join(fails))
    sys.exit(1)
print("ok")
