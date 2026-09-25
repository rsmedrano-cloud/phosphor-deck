#!/usr/bin/env python3
"""phosphor adjutant's fleet_alert(): checked every 20ms by the main loop,
but only actually re-reads fleet.json when its mtime moves -- not fifty
times a second, which stutters on a slow SD card (see #the revived shape).

    python3 tests/adjutant-check.py
"""
import json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
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
    check("missing file: never tried to parse anything", reads == [])

    # a fresh host-down snapshot: one real read
    write({"t": time.time(), "hosts": {"db-box": {"ok": False, "mnt": []}}})
    al = adjutant.fleet_alert()
    check("a down host alerts", al is not None and "unreachable" in al[1])
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

    # stale data (older than 120s) never alerts, even though it's cached
    time.sleep(0.05)
    write({"t": time.time() - 200, "hosts": {"db-box": {"ok": False, "mnt": []}}})
    check("stale snapshot: no alert", adjutant.fleet_alert() is None)

    # a genuinely broken file: no crash, no alert
    with open(adjutant.FLEET, "w") as f:
        f.write("{not json")
    os.utime(adjutant.FLEET, (time.time() + 10, time.time() + 10))
    check("garbled json: no crash, no alert", adjutant.fleet_alert() is None)
finally:
    adjutant.json.load = real_load

if fails:
    print("adjutant-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("adjutant-check ok")
