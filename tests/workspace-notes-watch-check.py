#!/usr/bin/env python3
"""A workspace's tab gets marked (tabmark.bump, see #26) the moment its
NOTES.md changes -- the only channel a workspace's assistants (or a human)
have to hand work to each other, and until #34 nothing signalled a new
entry landed there. workspace.watch_notes() is what mentions.marker()'s
always-on loop calls every 3s; this exercises its logic directly, with
tabmark.bump() mocked (the real zellij rename plumbing it calls into is
already covered by tests/tabmark-check.py).

    python3 tests/workspace-notes-watch-check.py
"""
import os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import workspace as ws

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

d = tempfile.mkdtemp()
prof_root = os.path.join(d, "projects")
os.makedirs(os.path.join(prof_root, "shop"))
open(os.path.join(prof_root, "shop", "NOTES.md"), "w").write("# shop notes\n")
os.makedirs(os.path.join(prof_root, "no-notes"))   # not a workspace: no NOTES.md

ws.root = lambda prof=None: prof_root
ws.NOTES_SEEN = os.path.join(d, "seen.json")

calls = []
import tabmark   # the same module object watch_notes()'s own `import tabmark` will get
real_bump = tabmark.bump
tabmark.bump = lambda sess, tab: calls.append((sess, tab))

try:
    ws.watch_notes("deck")
    check("first sight: no bump yet, just a baseline", calls == [])
    check("a folder without NOTES.md is never a workspace", "no-notes" not in ws.names())

    ws.watch_notes("deck")
    check("no change since baseline: still no bump", calls == [])

    time.sleep(0.01)
    open(os.path.join(prof_root, "shop", "NOTES.md"), "a").write("\n## new entry\n")
    ws.watch_notes("deck")
    check("NOTES.md changed: the workspace's tab (its name, uppercased) got bumped",
          calls == [("deck", "SHOP")])

    ws.watch_notes("deck")
    check("no further change: no repeat bump", calls == [("deck", "SHOP")])

    check("state persisted across calls, not just in memory",
          os.path.exists(ws.NOTES_SEEN) and "shop" in open(ws.NOTES_SEEN).read())
finally:
    tabmark.bump = real_bump

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
