#!/usr/bin/env python3
"""Fleet health alerts: a host's ok/not-ok flip calls `phosphor notify`
itself, once per transition, at most once a minute, never on the first
poll (which would alert about a host already down before we started
watching it). Nothing spawned for real: subprocess.Popen is patched.

    python3 tests/fleet-alert-check.py
"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import fleet

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

calls = []
real_popen = fleet.subprocess.Popen
def fake_popen(argv, **kw):
    calls.append(argv)
    class P: pass
    return P()
fleet.subprocess.Popen = fake_popen

def reset():
    fleet.STATE.clear(); fleet.FAILS.clear()
    fleet.PREV_OK.clear(); fleet.LAST_ALERT.clear()
    calls.clear()

def alert_texts():
    return [a[-1] for a in calls]   # the trailing message, after --fleet-alert

try:
    # first poll ever: no transition to alert about, even if already down
    reset()
    fleet.update_host("db-box", {"ok": False, "err": "timeout"})
    check("no alert on the very first poll", calls == [])

    # a real down transition, after an ok baseline
    reset()
    fleet.update_host("db-box", {"ok": True, "CPU": 5})
    fleet.update_host("db-box", {"ok": False, "err": "timeout"})
    check("a single failed poll is a blip, not an alert yet", calls == [])
    fleet.update_host("db-box", {"ok": False, "err": "timeout"})   # 2nd in a row: real
    check("down after 2 failed polls alerts once", len(calls) == 1)
    check("alert names the host and says unreachable",
          "db-box is unreachable" in alert_texts())
    check("goes through phosphor notify --fleet-alert",
          calls[0][2] == "notify" and "--fleet-alert" in calls[0])

    # recovering fires the "back" alert too, once the per-host cooldown
    # from the down alert above has passed
    fleet.LAST_ALERT["db-box"] = time.time() - 61
    fleet.update_host("db-box", {"ok": True, "CPU": 5})
    check("coming back alerts again", len(calls) == 2)
    check("says back, not unreachable", "db-box is back" in alert_texts())

    # staying down (or staying up) never refires: only the flip does
    reset()
    fleet.update_host("db-box", {"ok": True})
    fleet.update_host("db-box", {"ok": False}); fleet.update_host("db-box", {"ok": False})
    n = len(calls)
    fleet.update_host("db-box", {"ok": False})
    check("a level, still down, doesn't refire", len(calls) == n)

    # the per-host cooldown: a flapping link doesn't flood the phone
    reset()
    fleet.update_host("relay", {"ok": True})
    fleet.update_host("relay", {"ok": False}); fleet.update_host("relay", {"ok": False})
    check("first flip alerts", len(calls) == 1)
    fleet.update_host("relay", {"ok": True})     # back up right away
    check("cooldown swallows an immediate re-flip", len(calls) == 1)
    fleet.LAST_ALERT["relay"] = time.time() - 61   # cooldown has passed
    fleet.update_host("relay", {"ok": False}); fleet.update_host("relay", {"ok": False})
    check("a flip after the cooldown alerts again", len(calls) == 2)

    # two hosts don't share a cooldown
    reset()
    fleet.update_host("db-box", {"ok": True}); fleet.update_host("nimbus", {"ok": True})
    fleet.update_host("db-box", {"ok": False}); fleet.update_host("db-box", {"ok": False})
    fleet.update_host("nimbus", {"ok": False}); fleet.update_host("nimbus", {"ok": False})
    check("each host gets its own alert", len(calls) == 2)

    # demo mode's own loop never calls update_host: no alerts possible
    reset()
    fleet.DEMO = True
    for n, _ in [("nebula", None)]:
        fleet.STATE[n] = fleet.demo_collect(n)
    check("demo never routes through update_host/_alert", calls == [])
    fleet.DEMO = False
finally:
    fleet.subprocess.Popen = real_popen

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
