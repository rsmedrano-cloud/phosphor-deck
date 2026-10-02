#!/usr/bin/env python3
"""phosphor mem checks: which pane a process belongs to, and the sums.

    python3 tests/mem-check.py

Verifies:
- group() puts a process and the child it started in the pane named by
  their environment, only for the sessions asked for, and finds each
  session's zellij server by its command line
- a real process tree marked like a pane is found by procs() + group()
- footprint() reads this process's own memory
- tally() sums panes into tabs, heaviest first, names another kind's tab
  after its session, strips tabmark's unread count, and keeps a pane zellij
  doesn't list as "pane N" under "unlisted"
- human() and frame(), including a deck that isn't running
"""
import os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp()
import mem
from ui import vlen

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

E = lambda s, p: [b"HOME=/x", ("ZELLIJ_SESSION_NAME=%s" % s).encode(), ("ZELLIJ_PANE_ID=%d" % p).encode()]
ps = [(10, E("deck", 1), "bash"), (11, E("deck", 1), "claude"), (12, E("deck", 2), "phosphor fleet"),
      (13, E("deck-phone", 1), "phosphor notes"), (14, E("other", 1), "vim"),
      (15, [b"HOME=/x"], "zellij --server /run/user/1/zellij/0.45.1/deck"),
      (16, [b"HOME=/x"], "zellij --server /run/user/1/zellij/0.45.1/deck-phone"),
      (17, [b"HOME=/x"], "zellij --server /run/user/1/zellij/0.45.1/decky")]
panes, servers = mem.group(["deck", "deck-phone"], ps)
check("pane 1 has both its processes", sorted(panes.get(("deck", 1), [])) == [10, 11])
check("another kind's pane under its own session", panes.get(("deck-phone", 1)) == [13])
check("a session not asked for is left out", ("other", 1) not in panes)
check("servers found by name, not by prefix", servers == {"deck": [15], "deck-phone": [16]})

# a real tree: a shell marked as pane 7 of a made-up session, and its child
env = dict(os.environ, ZELLIJ_SESSION_NAME="probe-mem-%d" % os.getpid(), ZELLIJ_PANE_ID="7")
top = subprocess.Popen(["sh", "-c", "sleep 30 & wait"], env=env)
try:
    time.sleep(0.3)
    got, _ = mem.group([env["ZELLIJ_SESSION_NAME"]], mem.procs())
    pids = got.get((env["ZELLIJ_SESSION_NAME"], 7), [])
    check("a real pane's shell and its child are found (%s)" % pids, top.pid in pids and len(pids) == 2)
finally:
    top.kill(); top.wait()

check("footprint of this process", mem.footprint(os.getpid()) > 1 << 20)
check("footprint of a gone pid is 0", mem.footprint(999999999) == 0)

sizes = {10: 300 << 20, 11: 100 << 20, 12: 20 << 20, 13: 50 << 20, 15: 80 << 20, 16: 10 << 20}
names = {"deck": {1: (3, "AI", "CLAUDE"), 2: (0, "SYS", "FLEET")},
         "deck-phone": {1: (1, "NOTES", "NOTES")}}
names["deck"][2] = (0, mem.MARK.sub("", "SYS ●3"), "FLEET")
tabs, z = mem.tally("deck", ["deck", "deck-phone"], {**panes, ("deck", 9): [12]}, servers, names,
                    size=lambda p: sizes.get(p, 0))
check("heaviest tab first", [t[0] for t in tabs][:2] == ["AI", "NOTES · phone"])
check("a tab sums its panes", tabs[0][1] == 400 << 20 and tabs[0][2] == [("CLAUDE", 400 << 20, 2)])
sys_ = dict((t[0], t) for t in tabs)["SYS"]
check("tabmark's count stripped", [p[0] for p in sys_[2]] == ["FLEET"])
check("a pane zellij doesn't list is kept, as pane 9",
      dict((t[0], t) for t in tabs).get("unlisted", (0, 0, []))[2] == [("pane 9", 20 << 20, 1)])
check("zellij itself sums every server", z == 90 << 20)

check("human", (mem.human(940 << 10), mem.human(312 << 20), mem.human(3 << 29)) == ("940 KB", "312 MB", "1.5 GB"))
data = {"base": "deck", "tabs": tabs, "zellij": z, "machine": (8 << 30, 2 << 30)}
out = "\n".join(mem.frame(data, 80))
check("frame shows tabs, panes, zellij and the machine",
      all(s in out for s in ("AI", "CLAUDE", "NOTES · phone", "zellij itself", "the machine")))
check("frame fits the width", all(vlen(l) <= 80 for l in mem.frame(data, 80)))
check("frame fits a phone", all(vlen(l) <= 32 for l in mem.frame(data, 32)))
idle = "\n".join(mem.frame({"base": "deck", "tabs": [], "zellij": 0, "machine": (0, 0)}, 60))
check("a deck that isn't running says so", "isn't running" in idle)

if fails:
    print("mem-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("mem-check ok")
