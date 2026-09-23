#!/usr/bin/env python3
"""phosphor services: the unit list matches what gen writes, extras parse,
states classify sanely, and a frame renders without a real systemd around.

    python3 tests/services-check.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import services as S

fails = []
def need(what, ok):
    if not ok: fails.append(what)

prof = {
    "deck": {"session": "deck"},
    "hosts": [
        {"name": "brainbox", "role": "brain", "local": True},
        {"name": "storage1", "role": "storage", "ssh": "storage1", "mount": "/data"},
    ],
    "tunnels": [{"host": "db-box"}],
    "services": {"extra": ["nginx.service", "user:foo.timer"]},
}

units = S.phosphor_units(prof)
need("deck.service is Phosphor's own", "deck.service" in units)
need("deck.timer is Phosphor's own", "deck.timer" in units)
need("fleet unit for the remote host", "fleet-storage1.service" in units)
need("no fleet unit for the local (brain) host", "fleet-brainbox.service" not in units)
need("tunnel unit is Phosphor's own", any(u.startswith("db-box") or "db-box" in u for u in units))

extras = S.extra_units(prof)
need("plain name is a system unit", ("system", "nginx.service") in extras)
need("user: prefix is a user unit, stripped", ("user", "foo.timer") in extras)

need("active -> green, its substate as the tag",
     S.classify({"ActiveState": "active", "SubState": "running"}) == (S.PH, "running"))
need("failed -> red",
     S.classify({"ActiveState": "failed"})[0] == S.RED)
need("not-found -> muted, regardless of ActiveState",
     S.classify({"LoadState": "not-found", "ActiveState": "inactive"}) == (S.MUTE, "not found"))
need("inactive isn't shouted at (a tunnel you turned off is fine)",
     S.classify({"ActiveState": "inactive", "SubState": "dead"})[0] == S.DIM)
need("no answer at all -> muted unknown, never a crash",
     S.classify({}) == (S.MUTE, "unknown"))

need("memory renders MB", S.mem_str({"MemoryCurrent": str(42 * 1024 * 1024)}).endswith("M"))
need("no memory reported -> blank", S.mem_str({}) == "")
need("'[not set]' -> blank", S.mem_str({"MemoryCurrent": "[not set]"}) == "")

need("label drops .service", S.label("deck.service") == "deck")
need("label keeps other kinds", S.label("deck.timer") == "deck (timer)")

# End to end: even if systemctl fails outright (no session bus in CI), a
# frame renders instead of crashing or hanging.
out = S.frame(prof, 60, 30)
need("frame renders at least a header", len(out) >= 1)
need("frame never widens past cols", all(len(l.encode("ascii", "ignore")) <= 200 for l in out))

if fails:
    print("FAILED:\n  - " + "\n  - ".join(fails))
    sys.exit(1)
print("ok (%d checks)" % (13,))
