#!/usr/bin/env python3
"""phosphor broadcast -- CMD: one command on every fleet host, asking first.

    python3 tests/broadcast-check.py
"""
import io, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import broadcast

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

PROF = {"hosts": [
    {"name": "brain", "role": "brain", "local": True},
    {"name": "db-box", "role": "storage", "ssh": "db-box-alias", "user": "deploy"},
    {"name": "nimbus", "role": "work", "ssh": "nimbus"},
    {"name": "relay", "role": "node", "ssh": "relay", "fleet": False},
    {"name": "phone", "role": "viewer", "ssh": "phone"},
]}

# targets(): what fleet polls -- no viewers, no fleet = false
names = lambda hs: sorted(h["name"] for h in hs)
hs, unknown = broadcast.targets(PROF)
check("targets: the fleet, no viewer or fleet=false", names(hs) == ["brain", "db-box", "nimbus"] and not unknown)
hs, _ = broadcast.targets(PROF, role="storage")
check("targets: --role narrows", names(hs) == ["db-box"])
hs, unknown = broadcast.targets(PROF, ["nimbus", "relay"])
check("targets: a host off the fleet counts as unknown", names(hs) == ["nimbus"] and unknown == ["relay"])

# parse()
check("parse: -- then the command", broadcast.parse(["--", "df", "-h"]) == ([], None, 60, False, "df -h", False, 0))
check("parse: no -- works too", broadcast.parse(["uptime"]) == ([], None, 60, False, "uptime", False, 0))
check("parse: flags", broadcast.parse(["--host", "a", "--host", "b", "--role", "work", "--timeout", "5", "--yes",
                                       "--", "ls"]) == (["a", "b"], "work", 5, True, "ls", False, 0))
check("parse: no command is usage", broadcast.parse(["--yes", "--"]) is None)
check("parse: --rolling --pause", broadcast.parse(["--rolling", "--pause", "30", "--", "ls"])
      == ([], None, 60, False, "ls", True, 30))
check("parse: --pause without --rolling is usage", broadcast.parse(["--pause", "30", "--", "ls"]) is None)
check("parse: a bad timeout is usage", broadcast.parse(["--timeout", "x", "--", "ls"]) is None)

# run_one(): local runs sh -c, remote ssh BatchMode to the resolved target;
# ssh's own 255 is "never got there", not the command's exit code
real_run = broadcast.subprocess.run
calls = []
class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err
answers = {}
def fake_run(argv, **kw):
    calls.append((argv, kw.get("stdin")))
    return answers.get(argv[0], R(0, "ok\n"))
broadcast.subprocess.run = fake_run
try:
    name, rc, out, _ = broadcast.run_one(PROF["hosts"][0], "uptime", 5)
    check("local: sh -c, no ssh", calls[-1][0] == ["sh", "-c", "uptime"] and rc == 0 and out == "ok")
    name, rc, out, _ = broadcast.run_one(PROF["hosts"][1], "uptime", 5)
    argv = calls[-1][0]
    check("remote: ssh BatchMode to user@alias", argv[0] == "ssh" and "BatchMode=yes" in argv
          and argv[-2:] == ["deploy@db-box-alias", "uptime"])
    check("stdin is never the terminal", all(c[1] == broadcast.subprocess.DEVNULL for c in calls))
    answers["ssh"] = R(255, "", "ssh: connect to host nimbus port 22: No route to host\n")
    name, rc, out, _ = broadcast.run_one(PROF["hosts"][2], "uptime", 5)
    check("ssh 255: unreachable, with ssh's reason", rc is None and "No route" in out)
    answers["ssh"] = R(3, "", "inactive\n")
    name, rc, out, _ = broadcast.run_one(PROF["hosts"][2], "systemctl is-active x", 5)
    check("a remote non-zero exit is the command's", rc == 3 and out == "inactive")
finally:
    broadcast.subprocess.run = real_run

# main(): asks on a terminal, refuses unattended without --yes
class FakeStdin:
    def __init__(self, tty): self._tty = tty
    def isatty(self): return self._tty
real_load, real_example, real_stdin = broadcast.deckconf.load, broadcast.deckconf.example, broadcast.sys.stdin
real_one = broadcast.run_one
broadcast.deckconf.load = lambda: (PROF, "t")
broadcast.deckconf.example = lambda: False
ran = []
broadcast.run_one = lambda h, c, t: ran.append(h["name"]) or (h["name"], 0, "", 0.1)
def main(argv):
    saved, out = sys.argv, sys.stdout
    sys.argv, sys.stdout = ["phosphor-broadcast"] + argv, io.StringIO()
    try:
        return broadcast.main()
    finally:
        sys.argv, sys.stdout = saved, out
try:
    broadcast.sys.stdin = FakeStdin(False)
    rc = main(["--", "uptime"])
    check("not a tty, no --yes: refuses, runs nothing", rc == 1 and not ran)
    rc = main(["--yes", "--", "uptime"])
    check("--yes: runs on the whole fleet", rc == 0 and sorted(ran) == ["brain", "db-box", "nimbus"])
    ran.clear()
    rc = main(["--yes", "--host", "ghost", "--", "uptime"])
    check("unknown host: exits 1, runs nothing", rc == 1 and not ran)

    import init
    real_yes = init.yes
    broadcast.sys.stdin = FakeStdin(True)
    init.yes = lambda q, d=True: False
    rc = main(["--", "uptime"])
    check("a tty, answered no: runs nothing", rc == 1 and not ran)
    init.yes = lambda q, d=True: True
    rc = main(["--role", "work", "--", "uptime"])
    check("a tty, answered yes: runs", rc == 0 and ran == ["nimbus"])
    init.yes = real_yes

    broadcast.run_one = lambda h, c, t: (h["name"], None if h["name"] == "db-box" else 0, "", 0.1)
    rc = main(["--yes", "--", "uptime"])
    check("one host unreachable: exits 1", rc == 1)

    # --rolling: one at a time in the fleet's order, the brain last, stops at the first failure
    ran.clear()
    fail = set()
    broadcast.run_one = lambda h, c, t: ran.append(h["name"]) or (h["name"], 3 if h["name"] in fail else 0, "", 0.1)
    rc = main(["--yes", "--rolling", "--", "uptime"])
    check("rolling: every host, the brain last", rc == 0 and ran == ["nimbus", "db-box", "brain"])
    ran.clear(); fail.add("nimbus")
    rc = main(["--yes", "--rolling", "--", "uptime"])
    check("rolling: stops at the first failure", rc == 1 and ran == ["nimbus"])
    fail.clear(); ran.clear()
    broadcast.sys.stdin = FakeStdin(True)
    asked = []
    init.yes = lambda q, d=True: asked.append(q) or not q.startswith("next: db-box")
    rc = main(["--rolling", "--", "uptime"])
    check("rolling on a tty: asks before each next host, a no stops it",
          rc == 1 and ran == ["nimbus"] and asked[-1].startswith("next: db-box"))
    init.yes = real_yes
    ran.clear()
    slept = []
    real_sleep = broadcast.time.sleep
    broadcast.time.sleep = slept.append
    broadcast.run_one = lambda h, c, t: ran.append((h["name"], c)) or \
        (h["name"], None if (h["name"], c) == ("nimbus", "true") else 0, "", 0.1)
    rc = main(["--yes", "--rolling", "--pause", "20", "--", "reboot"])
    check("rolling --pause: waits, and a host that stops answering stops it",
          rc == 1 and slept == [20] and ran == [("nimbus", "reboot"), ("nimbus", "true")])
    broadcast.time.sleep = real_sleep
    broadcast.sys.stdin = FakeStdin(False)

    broadcast.deckconf.example = lambda: True
    ran.clear()
    broadcast.run_one = lambda h, c, t: ran.append(h["name"]) or (h["name"], 0, "", 0.1)
    rc = main(["--yes", "--", "uptime"])
    check("no profile yet: never runs on the example's machines", rc == 1 and not ran)
finally:
    broadcast.deckconf.load, broadcast.deckconf.example = real_load, real_example
    broadcast.sys.stdin, broadcast.run_one = real_stdin, real_one

if fails:
    print("broadcast-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("broadcast-check ok")
