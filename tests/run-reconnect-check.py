#!/usr/bin/env python3
"""phosphor run --reconnect backs off instead of hammering a dead link every
3s forever -- found from a real 6-hour, 2055-attempt incident in deck.log.

    python3 tests/run-reconnect-check.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import run

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# a link that never comes up: 3, 6, 12, 24, 48, capped at 60, forever
f, delays = 0, []
for _ in range(8):
    f, d = run.reconnect_delay(f, lasted=0.1)
    delays.append(d)
check("escalates then caps at 60s", delays == [3, 6, 12, 24, 48, 60, 60, 60])
check("keeps counting failures while it stays down", f == 8)

# a real connection (up 30s+) forgives the streak: back to a plain 3s next time
f, _ = run.reconnect_delay(5, lasted=0.1)          # deep into backoff
check("mid-backoff sanity", f == 6)
f, d = run.reconnect_delay(f, lasted=45)
check("a real connection resets the failure count", f == 0)
check("...so the very next drop is a plain 3s, not capped", d == 3)

# exactly the 30s boundary: still counts as "never really came up"
f, d = run.reconnect_delay(2, lasted=30)
check("30.0s exactly doesn't count as a real connection (needs to exceed it)", f == 3)

if fails:
    print("run-reconnect-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("run-reconnect-check ok")
