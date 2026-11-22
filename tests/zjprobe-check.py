#!/usr/bin/env python3
"""The probe never talks to its zellij before the session exists (#123).

zellij 0.45's server panics (lib.rs:1462) when a client connects and leaves
before the attaching client has made the session: list-sessions or an
action sent that early killed a random probe test now and then under
check.sh's load, with "zellij didn't start" and no output. Every zellij
command the probe runs while it starts is recorded here, with whether a
pane of the session was already running: none may come before one.
"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import zjprobe

PROFILE = '''
[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name  = "A"
panes = [ { cmd = "sleep", args = ["651"] } ]
'''

def pane_running(home):
    """A process with this probe's HOME runs in a pane: its own /proc scan,
    so the check doesn't lean on the harness it checks."""
    want = ("HOME=%s" % home).encode()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            env = open("/proc/%s/environ" % d, "rb").read().split(b"\0")
        except OSError:
            continue
        if want in env and any(e.startswith(b"ZELLIJ_PANE_ID=") for e in env):
            return True
    return False

class Recorded(zjprobe.Probe):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = []

    def run(self, *args):
        self.calls.append((args[:3], pane_running(self.home)))
        return super().run(*args)

def main():
    if not zjprobe.zellij():
        print("no zellij here: skipped"); return 0
    fails = []
    for i in range(3):
        z = Recorded(PROFILE, session="zjprobeck%d" % i)
        try:
            with z:
                pass
        except RuntimeError as e:
            fails.append("round %d: %s" % (i, str(e)[:200]))
            continue
        early = [c for c, up in z.calls if not up]
        if not z.calls:
            fails.append("round %d: the probe asked zellij nothing (is it ready at all?)" % i)
        if early:
            fails.append("round %d: zellij asked before any pane ran: %s" % (i, early[:3]))
    if fails:
        print("zjprobe-check FAILED:\n  " + "\n  ".join(fails)); return 1
    print("zjprobe-check ok")
    return 0

if __name__ == "__main__":
    sys.exit(main())
