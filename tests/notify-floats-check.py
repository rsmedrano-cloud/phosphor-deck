#!/usr/bin/env python3
"""phosphor notify's floating-pane hider only touches tabs it actually
showed (issue #14): looping hide-floating-panes -t over every tab, shown or
not, was the only clue behind zellij 0.45's screen-thread freeze.

    python3 tests/notify-floats-check.py

Needs zellij; without it, it says so and passes (same as edit-check.py).
"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zjprobe

PROFILE = '''
[deck]
session = "notify-floats"
notifier = true
notify_seconds = 1

[[hosts]]
name = "box"
role = "brain"
local = true
''' + "\n".join('[[tabs]]\nname = "T%d"\npanes = [ { cmd = "" } ]\n' % i for i in range(4))

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)

def states(z):
    """{tab_id: are_floating_panes_visible}, straight from zellij's own state."""
    out = subprocess.run([z.zj, "-s", z.session, "action", "list-tabs", "--state", "--json"],
                         env=z.env, capture_output=True, text=True, timeout=10).stdout
    return {str(t["tab_id"]): t["are_floating_panes_visible"] for t in json.loads(out)}

def notify(z, msg):
    p = subprocess.run([os.path.join(z.env["HOME"], ".local/bin/phosphor"), "notify", "--no-tts", "--no-push", msg],
                       env=z.env, capture_output=True, timeout=10)
    assert p.returncode == 0, p.stderr

if not zjprobe.zellij():
    print("ok — zellij isn't installed, skipping"); sys.exit(0)

with zjprobe.Probe(PROFILE, session="notify-floats") as z:
    # Every tab starts with its floating pane visible (the layout's own
    # default); hide them all first, as deck-up.sh does right after start.
    for tid in states(z):
        subprocess.run([z.zj, "-s", z.session, "action", "hide-floating-panes", "-t", tid],
                       env=z.env, capture_output=True, timeout=10)
    need("every tab starts hidden", not any(states(z).values()))

    shown_file = os.path.join(z.env["HOME"], ".cache/phosphor/notify-shown-tabs")

    # A single notify from tab T0 (the active one): only T0 should ever show,
    # and the state file should name only that one tab, not all four.
    notify(z, "one")
    st = states(z)
    need("only the active tab's float showed", [k for k, v in st.items() if v] == ["0"])
    need("the shown-tabs file names only that tab",
         os.path.exists(shown_file) and open(shown_file).read().split() == ["0"])

    time.sleep(1.6)   # notify_seconds=1: let the hider run
    st = states(z)
    need("it hid itself again", not any(st.values()))
    need("the shown-tabs file is cleaned up after hiding", not os.path.exists(shown_file))

    # Two notifies from two different tabs inside the same window: the hider
    # must hide exactly those two, and no others (never all four).
    notify(z, "a")
    z.run("--session", z.session, "action", "go-to-tab", "3")   # 1-based: tab_id 2 is the 3rd tab
    notify(z, "b")
    st = states(z)
    need("both notified tabs show", st.get("0") and st.get("2"))
    need("the other tabs were never touched", not st.get("1") and not st.get("3"))
    need("the shown-tabs file names exactly those two, not every tab",
         sorted(open(shown_file).read().split()) == ["0", "2"])

    time.sleep(1.6)
    need("both hidden again, still none of the others", not any(states(z).values()))
    need("still answers after all of this", z.run("--session", z.session, "action", "list-tabs"))

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok — phosphor notify only hides the tabs it actually showed")
