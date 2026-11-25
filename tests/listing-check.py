#!/usr/bin/env python3
"""Every zellij listing in lib/ is read through proc.listing/proc.layout,
which ask again on an empty, unreadable or crossed answer (#134; zellij
0.45 hands one action another's answer, #122). Against a fake zellij:
    python3 tests/listing-check.py
"""
import glob, os, re, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import proc

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

TABS = '[{"tab_id": 0, "position": 0, "name": "AI"}]'
PANES = '[{"id": 1, "is_plugin": false, "tab_id": 0}]'
LAYOUT = 'layout {\n    tab name="AI" {\n        pane\n    }\n}\n'

def answers(*seq):
    """A fake proc.action giving (exit code, stdout) from seq, the last
    one for good; it counts what it was asked."""
    asked = []
    def action(sess, args, timeout=15):
        asked.append((sess,) + tuple(args))
        rc, out = seq[min(len(asked), len(seq)) - 1]
        return subprocess.CompletedProcess(args, rc, out, "")
    proc.action = action
    return asked

real = proc.action
try:
    asked = answers((0, PANES))
    check("a good answer is read at once", proc.listing("s", "list-panes", "-a", "-j") == [
        {"id": 1, "is_plugin": False, "tab_id": 0}] and len(asked) == 1)
    check("the session and the flags reach zellij", asked[0] == ("s", "list-panes", "-a", "-j"))

    asked = answers((0, ""), (0, "not json"), (0, PANES))
    check("busy (empty, unreadable) is asked again", len(proc.listing(None, "list-panes", "-a", "-j")) == 1
          and len(asked) == 3)

    asked = answers((0, TABS), (0, PANES))
    got = proc.listing(None, "list-panes", "-a", "-j")
    check("list-panes handed the tabs is asked again (#122)", got and "is_plugin" in got[0] and len(asked) == 2)
    asked = answers((0, PANES), (0, TABS))
    got = proc.listing(None, "list-tabs", "-j")
    check("list-tabs handed the panes is asked again", got and "position" in got[0] and len(asked) == 2)

    answers((0, "[1, 2]"))
    t0 = time.time()
    check("never readable: [] once the wait is up", proc.listing(None, "list-tabs", "-j", wait=0.5) == [])
    check("... not before it", time.time() - t0 >= 0.5)

    asked = answers((1, ""))
    check("zellij failing (no such session) is believed at once",
          proc.listing("gone", "list-tabs", "-j") == [] and len(asked) == 1)

    asked = answers((0, ""), (0, TABS), (0, LAYOUT))
    check("dump-layout: busy and crossed answers asked again", proc.layout() == LAYOUT and len(asked) == 3)
    answers((0, TABS))
    check("dump-layout never real: ''", proc.layout(wait=0.3) == "")
finally:
    proc.action = real

# nothing in lib/ asks zellij for a listing by itself
LISTS = re.compile(r"""["'](list-tabs|list-panes|dump-layout)["']""")
for f in sorted(glob.glob(os.path.join(ROOT, "lib", "*.py"))):
    if os.path.basename(f) == "proc.py":
        continue
    for n, line in enumerate(open(f), 1):
        if LISTS.search(line) and not re.search(r"\b(listing|layout)\(", line):
            check("%s:%d reads a zellij listing itself; use proc.listing/proc.layout"
                  % (os.path.relpath(f, ROOT), n), False)

for f in fails:
    print("FAIL:", f)
print("listing-check", "ok" if not fails else "FAILED")
sys.exit(1 if fails else 0)
