#!/usr/bin/env python3
"""phosphor triage HOST: a diagnostic snapshot piped into phosphor ask.

    python3 tests/triage-check.py
"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import triage

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

PROF = {"hosts": [
    {"name": "brain", "role": "brain", "local": True},
    {"name": "db-box", "role": "storage", "ssh": "db-box-alias", "user": "deploy"},
]}

# snapshot(): local host runs "sh -s" with no ssh in front, a remote one goes
# through ssh with the resolved target -- same delivery share/collect.sh uses.
real_run = triage.subprocess.run
calls = []
class FakeResult:
    def __init__(self, stdout="== uptime & load ==\nup 3 days\n", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr

def fake_run(cmd, **kw):
    calls.append((cmd, kw.get("input")))
    return FakeResult()

triage.subprocess.run = fake_run
try:
    calls.clear()
    text, err = triage.snapshot({"local": True})
    check("local snapshot: no ssh, plain sh -s", calls[0][0] == ["sh", "-s"])
    check("local snapshot: the collection script goes in on stdin", "uptime" in calls[0][1])
    check("local snapshot: returns the captured text", text and err is None)

    calls.clear()
    text, err = triage.snapshot({"ssh": "db-box-alias", "user": "deploy"})
    check("remote snapshot: ssh to the resolved target, command is sh -s",
          calls[0][0][-2:] == ["deploy@db-box-alias", "sh -s"])
    check("remote snapshot: BatchMode so it never waits on a password",
          "BatchMode=yes" in calls[0][0])

    calls.clear()
    def empty_run(cmd, **kw):
        return FakeResult(stdout="", stderr="Connection refused")
    triage.subprocess.run = empty_run
    text, err = triage.snapshot({"local": True})
    check("empty output surfaces stderr as the reason", text is None and "Connection refused" in err)
finally:
    triage.subprocess.run = real_run

# list_flagged(): reuses glance.fleet_state(), no host needed
home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.makedirs(os.path.join(home, ".cache/phosphor"))
json.dump({"t": __import__("time").time(), "hosts": {
    "atlas": {"ok": True, "mnt": [], "SVCFAIL": 1},
}}, open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))

import io
buf = io.StringIO()
real_stdout = sys.stdout
sys.stdout = buf
try:
    rc = triage.list_flagged()
finally:
    sys.stdout = real_stdout
out = buf.getvalue()
check("list_flagged: nonzero when something's flagged", rc == 1)
check("list_flagged: names the host and the reason", "atlas" in out and "service" in out)

# main(): unknown host never reaches ssh or ask
real_load = triage.deckconf.load
triage.deckconf.load = lambda: (PROF, "t")
def run(argv):
    saved = sys.argv
    sys.argv = ["phosphor-triage"] + argv
    try:
        return triage.main()
    finally:
        sys.argv = saved

try:
    rc = run(["nope-a-host"])
    check("unknown host: exits 1", rc == 1)

    # no HOST at all: falls through to list_flagged(), no crash
    buf = io.StringIO()
    sys.stdout = buf
    try:
        rc = run([])
    finally:
        sys.stdout = real_stdout
    check("no host given: exits through list_flagged, not a crash", rc in (0, 1))
finally:
    triage.deckconf.load = real_load

# --assistant with no name after it
rc_out = io.StringIO()
sys.stdout = rc_out
try:
    rc = run(["--assistant"])
finally:
    sys.stdout = real_stdout
check("--assistant with nothing after it: usage error, not a crash", rc == 1)

if fails:
    print("triage-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("triage-check ok")
