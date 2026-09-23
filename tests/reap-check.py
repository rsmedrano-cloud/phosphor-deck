#!/usr/bin/env python3
"""What `phosphor restart` is allowed to kill.

    python3 tests/reap-check.py

The panes of the session, its server and its clients — and nothing else that
happens to have "phosphor" in its command line (that was a real bug: a test
run or an editor could be killed along with the deck).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import reap

HOME = "/home/x"
MINE = [b"ZELLIJ_SESSION_NAME=deck", b"TERM=xterm"]
OTHER = [b"ZELLIJ_SESSION_NAME=probe"]

CASES = [
    # pid, command line, environment, should it be stopped
    (100, "python3 %s/phosphor-deck/phosphor run --name FLEET -- %s/phosphor-deck/phosphor fleet" % (HOME, HOME), MINE, True),
    (101, "python3 %s/phosphor-deck/phosphor run --name LUCIUS --reconnect -- ssh -t lucius" % HOME, MINE, True),
    (102, "%s/.local/bin/zellij --server /run/user/1000/zellij/contract_version_1/deck" % HOME, [], True),
    (103, "zellij attach deck", [], True),
    (104, "python3 %s/phosphor-deck/phosphor attach" % HOME, [], False),          # a screen waiting to come back
    (105, "bash /builds/x/phosphor-deck/tests/from-zero.sh", [], False),          # a CI job on the brain
    (106, "nvim %s/phosphor-deck/lib/gen.py" % HOME, [], False),                  # an editor
    (107, "python3 %s/phosphor-deck/phosphor restart" % HOME, [], False),         # the restart itself (protected)
    (108, "zellij attach probe", OTHER, False),                                   # another session
    (109, "python3 %s/phosphor-deck/phosphor run --name X -- sleep 1" % HOME, OTHER, False),
    (110, "%s/.local/bin/zellij --server /run/user/1000/zellij/contract_version_1/probe" % HOME, [], False),
]

def main():
    procs = [(pid, args) for pid, args, _e, _w in CASES]
    envs = {pid: e for pid, _a, e, _w in CASES}
    got = {pid for pid, _a in reap.targets(procs, "deck", protect=(107,), environ=lambda p: envs.get(p, []))}
    want = {pid for pid, _a, _e, w in CASES if w}
    bad = 0
    for pid, args, _e, w in CASES:
        hit = pid in got
        if hit != w:
            bad += 1
        print("  %s  %-5s %s" % ("ok  " if hit == w else "FAIL",
                                 "stop" if hit else "spare", args[:78]))
    print("\n%s" % ("PASS: only the deck's own processes" if not bad else "FAIL: %d wrong" % bad))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
