#!/usr/bin/env python3
"""`phosphor notify`'s CLI: --no-event and --fleet-alert (used internally by
fleet and mentions, see fleet-alert-check.py and mentions-push-check.py),
and that its events file honors PHOSPHOR_CACHE like everything else phosphor
demo isolates -- it used to hardcode ~/.cache/phosphor.

    python3 tests/notify-check.py
"""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

td = tempfile.mkdtemp()
env = dict(os.environ)
env["PHOSPHOR_CACHE"] = os.path.join(td, "cache")
env["PHOSPHOR_DATA"] = os.path.join(td, "data")
env.pop("HOME_NEVER", None)

def notify(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "notify",
                           "--no-tts", "--no-push"] + list(args),
                          env=env, capture_output=True, text=True, timeout=15)

events = os.path.join(td, "cache", "events")

p = notify("hello there")
check("plain notify exits 0", p.returncode == 0)
check("events file lands under PHOSPHOR_CACHE, not the real machine's", os.path.exists(events))
check("the message is in it", "hello there" in open(events).read())
n = len(open(events).read().splitlines())

p = notify("--no-event", "should not appear")
check("--no-event still exits 0", p.returncode == 0)
check("--no-event writes no event line", len(open(events).read().splitlines()) == n)
check("--no-event doesn't leak into the message", "should not appear" not in open(events).read())

p = notify("--fleet-alert", "db-box is unreachable")
check("--fleet-alert exits 0 (never printed, never leaks into the text)", p.returncode == 0)
check("the flag itself isn't written into the event", "db-box is unreachable" in open(events).read()
      and "--fleet-alert" not in open(events).read())

p = notify("--tab", "FLEET", "--fleet-alert")   # empty message after flags: usage, not a crash
check("no message left after flags: the usage line, exit 1", p.returncode == 1 and "usage" in p.stdout)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
