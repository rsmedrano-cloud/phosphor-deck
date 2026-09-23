#!/usr/bin/env python3
"""deckconf.backup() rotates a profile write's undo depth (.bak, .bak.2,
.bak.3) instead of overwriting the only one there used to be -- `phosphor
setup` then a recipe, back to back, used to lose the setup-time backup.

    python3 tests/backup-check.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import deckconf

fails = []
def check(what, ok):
    if not ok: fails.append(what)

d = tempfile.mkdtemp()
p = os.path.join(d, "deck.toml")
slots = lambda: [open(p + s).read() if os.path.exists(p + s) else None for s in (".bak", ".bak.2", ".bak.3")]

open(p, "w").write("v1")
check("nothing to back up yet", slots() == [None, None, None])

deckconf.backup(p, "v1")
check("first write: only .bak", slots() == ["v1", None, None])

deckconf.backup(p, "v2")
check("second: v1 rotates to .bak.2, v2 is the newest", slots() == ["v2", "v1", None])

deckconf.backup(p, "v3")
check("third: v2 -> .bak.2, v1 -> .bak.3", slots() == ["v3", "v2", "v1"])

deckconf.backup(p, "v4")
check("fourth: v1 is dropped, not v2 or v3", slots() == ["v4", "v3", "v2"])

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
