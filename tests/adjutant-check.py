#!/usr/bin/env python3
"""phosphor adjutant's fleet_alert(): checked every 20ms by the main loop,
but only actually re-reads fleet.json when its mtime moves -- not fifty
times a second, which stutters on a slow SD card (see #the revived shape).

    python3 tests/adjutant-check.py
"""
import json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
# a cache of its own: what it logs never lands in the real deck.log
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp()
import adjutant

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

d = tempfile.mkdtemp()
adjutant.FLEET = os.path.join(d, "fleet.json")
adjutant._fleet_cache = {"mtime": None, "data": None}

reads = []
real_load = adjutant.json.load
def counting_load(f):
    reads.append(1)
    return real_load(f)
adjutant.json.load = counting_load

def write(payload):
    with open(adjutant.FLEET, "w") as f:
        json.dump(payload, f)

try:
    # no file yet: no alert, no crash, nothing read
    check("missing file: no alert", adjutant.fleet_alert() is None)
    check("missing file: health empty", adjutant.fleet_health() == (0, ""))
    check("missing file: never tried to parse anything", reads == [])

    # a fresh host-down snapshot: one real read
    write({"t": time.time(), "hosts": {"db-box": {"ok": False, "mnt": []}}})
    al = adjutant.fleet_alert()
    check("a down host alerts", al is not None and "unreachable" in al[1])
    check("a down host health is critical", adjutant.fleet_health() == (2, "db-box unreachable"))
    check("first look: exactly one real read", len(reads) == 1)

    # called again, file unchanged: no new read, same answer from cache
    al2 = adjutant.fleet_alert()
    check("same answer without the file changing", al2 == al)
    check("mtime unchanged: still just one read, not re-parsed", len(reads) == 1)

    # a disk-full alert takes priority path too, and a real change re-reads
    time.sleep(0.05)   # some filesystems have 1-tick mtime resolution below this
    write({"t": time.time(), "hosts": {"db-box": {"ok": True, "mnt": [("/", 95, "1T")]}}})
    al3 = adjutant.fleet_alert()
    check("mtime moved: re-read for real", len(reads) == 2)
    check("now reports the disk instead", al3 is not None and "disk" in al3[1])
    check("disk full health reports level 2", adjutant.fleet_health() == (2, "db-box disk 95%"))

    # warning level (disk 88%): no critical alert, but health is level 1
    time.sleep(0.05)
    write({"t": time.time(), "hosts": {"db-box": {"ok": True, "mnt": [("/", 88, "1T")]}}})
    check("warning disk: no critical alert", adjutant.fleet_alert() is None)
    check("warning disk: health is level 1", adjutant.fleet_health() == (1, "db-box disk 88%"))

    # all ok: no alert, health is nominal
    time.sleep(0.05)
    write({"t": time.time(), "hosts": {"db-box": {"ok": True, "mnt": [("/", 40, "1T")]}}})
    check("nominal: no alert", adjutant.fleet_alert() is None)
    check("nominal: health is nominal", adjutant.fleet_health() == (0, "nominal"))

    # stale data (older than 120s) never alerts, health reports stale data
    time.sleep(0.05)
    write({"t": time.time() - 200, "hosts": {"db-box": {"ok": False, "mnt": []}}})
    check("stale snapshot: no alert", adjutant.fleet_alert() is None)
    check("stale snapshot: health is stale data", adjutant.fleet_health() == (1, "stale data"))

    # a genuinely broken file: no crash, no alert, empty health
    with open(adjutant.FLEET, "w") as f:
        f.write("{not json")
    os.utime(adjutant.FLEET, (time.time() + 10, time.time() + 10))
    check("garbled json: no crash, no alert", adjutant.fleet_alert() is None)
    check("garbled json: health is empty", adjutant.fleet_health() == (0, ""))
finally:
    adjutant.json.load = real_load

if fails:
    print("adjutant-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("adjutant-check ok")
