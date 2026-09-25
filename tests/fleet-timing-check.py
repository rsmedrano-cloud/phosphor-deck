#!/usr/bin/env python3
"""fleet timing: collect() tags every poll with how long it took (STATE,
fleet.json, the FLEET card itself flag a slow one) -- "why does the deck
take 20-60s to load" needs a real number to point at, not a guess. That
number never reaches deck.log: it's meant to be safe to paste into an
issue, and a host's name isn't.

    python3 tests/fleet-timing-check.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import dlog
import fleet

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# Point the log at a throwaway file: this must never touch the real one.
dlog.DIR = tempfile.mkdtemp()
dlog.LOG = os.path.join(dlog.DIR, "deck.log")

def logged():
    return open(dlog.LOG).read() if os.path.exists(dlog.LOG) else ""

# A fast, real local poll (ssh=None runs collect.sh's `sh -s` right here --
# the same ~0.4s CPU sample every real poll takes): just tagged.
d = fleet.collect("local", None)
check("collect() tags how long it took", isinstance(d.get("ms"), int) and d["ms"] >= 0)

# A slow one, without an actual multi-second sleep in the test: fleet's own
# time.time() advances past SLOW_POLL_MS between collect()'s two reads of it.
real_time = fleet.time.time
ticks = [1000.0, 1000.0 + fleet.SLOW_POLL_MS / 1000.0 + 1]
fleet.time.time = lambda: ticks.pop(0) if ticks else real_time()
try:
    slow = fleet.collect("a-real-hostname-example", None)
finally:
    fleet.time.time = real_time
check("a slow poll is tagged past the threshold", slow["ms"] >= fleet.SLOW_POLL_MS)
check("collect() never writes to deck.log at all -- a host's name never "
      "belongs in a log meant to be safe to paste into an issue", logged() == "")

# The card shows it instead -- on screen, local-only, never in that log.
_, body = fleet.card("a-real-hostname-example", 40, slow)
check("the card calls out a slow poll", any("slow poll" in b for b in body))

_, body = fleet.card("dead-host", 40, {"ok": False, "err": "timeout", "ms": 6000})
check("an unreachable host's card shows how long it took to fail",
      any("6.0s" in b for b in body))

# write_cache()/read_state(): the draw loop only ever reads fleet.json --
# whatever writes it (poller() today, a separate process later) is its
# own concern. Point CACHE at a throwaway file, not the real one.
fleet.CACHE = os.path.join(tempfile.mkdtemp(), "fleet.json")
fleet.STATE.clear()
fleet.STATE["roundtrip-host"] = {"ok": True, "CPU": 5, "ms": 12}
fleet.write_cache()
back = fleet.read_state()
check("write_cache() then read_state() round-trips a host's poll",
      back.get("roundtrip-host", {}).get("CPU") == 5)
check("read_state() never touches the writer's in-memory STATE",
      back is not fleet.STATE)

# A chronically down host doesn't need the full patience window every
# round -- collect(known_down=True) should probe fast instead. subprocess.run
# is patched so this is instant and never actually tries to reach anything.
real_run = fleet.subprocess.run
calls = []
def fake_run(cmd, **kw):
    calls.append((cmd, kw.get("timeout")))
    class R: stdout, stderr = "", ""
    return R()
fleet.subprocess.run = fake_run
try:
    fleet.collect("host", "some-alias", known_down=False)
    fleet.collect("host", "some-alias", known_down=True)
finally:
    fleet.subprocess.run = real_run
(cmd0, t0), (cmd1, t1) = calls
check("a normal poll gets the full patience window", "ConnectTimeout=6" in cmd0 and t0 == 25)
check("a known-down host gets a short probe instead", "ConnectTimeout=2" in cmd1 and t1 == 5)
check("multiplexed: one real handshake reused across polls, not one per poll",
      "ControlMaster=auto" in cmd0 and any(c.startswith("ControlPersist=") for c in cmd0))
check("the control socket is keyed per host (ssh's own %C), not shared across them",
      any(c.startswith("ControlPath=") and c.endswith("%C") for c in cmd0))

# poller() only asks for the short probe once a host has really missed
# DOWN_AFTER polls in a row -- a fresh miss (or two) still gets the benefit
# of the doubt. Exercise the exact line poller() uses, not a re-description
# of it, so this breaks if that wiring ever comes apart.
fleet.FAILS.clear()
check("no history yet: not known-down", (fleet.FAILS.get("h", 0) >= fleet.DOWN_AFTER) is False)
fleet.FAILS["h"] = fleet.DOWN_AFTER - 1
check("one below the threshold: still not known-down", (fleet.FAILS.get("h", 0) >= fleet.DOWN_AFTER) is False)
fleet.FAILS["h"] = fleet.DOWN_AFTER
check("right at the threshold: known-down", fleet.FAILS.get("h", 0) >= fleet.DOWN_AFTER)
fleet.FAILS.clear()

# collect.sh's new SVCFAIL/REBOOT lines: parsed like CPU/MEMU/MEMT (a
# number, not left as a string), and the card shows them when present.
real_run = fleet.subprocess.run
def fake_svc_run(cmd, **kw):
    class R: stdout, stderr = "CPU=3\nMEMU=100\nMEMT=1000\nSVCFAIL=2\nREBOOT=1\n", ""
    return R()
fleet.subprocess.run = fake_svc_run
try:
    d = fleet.collect("host", None)
finally:
    fleet.subprocess.run = real_run
check("SVCFAIL parses as an int, like CPU/MEMU/MEMT", d.get("SVCFAIL") == 2)
check("REBOOT is present when the file says so", d.get("REBOOT") == "1")

_, body = fleet.card("host", 40, {"ok": True, "CPU": 3, "MEMU": 100, "MEMT": 1000, "SVCFAIL": 2})
check("the card calls out failed services", any("2 failed" in b for b in body))
_, body = fleet.card("host", 40, {"ok": True, "CPU": 3, "MEMU": 100, "MEMT": 1000, "REBOOT": "1"})
check("the card calls out a pending reboot", any("reboot pending" in b for b in body))
_, body = fleet.card("host", 40, {"ok": True, "CPU": 3, "MEMU": 100, "MEMT": 1000})
check("neither shows up when the host reports neither",
      not any("failed" in b or "reboot" in b for b in body))

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
