#!/usr/bin/env python3
"""phosphor panel: the DECK tab's cards reflow with the pane's width (one
column on a phone, more on a computer), every action stays reachable by key
and by tap, and a profile with the old two-pane DECK tab gets it in one.

    python3 tests/panel-grid-check.py
"""
import builtins, io, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import panel
from ui import vlen

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
panel.marked = lambda step: False
st = {"session": "deck", "version": "1.2.4", "channel": "stable", "news": "", "screens": 2,
      "timer": True, "web": False, "tunnels": [True], "profile_changed": False,
      "dirty_workspaces": 0, "migrate": 0}
keys = {a[0] for a in panel.ACTIONS}
check("no duplicate action keys", len(keys) == len({a[0] for a in panel.ACTIONS}) == len(panel.ACTIONS))
check("? is the key guide", "?" in keys)

def columns(lines):
    return max(len(re.findall(r"── [a-z?]", l)) for l in map(plain, lines))

for w, rows in ((40, 35), (60, 40), (100, 30), (160, 45), (240, 50)):
    lines, hit, maxoff = panel.draw({}, st, w, rows)
    check("%dx%d: no line wider than the pane" % (w, rows), all(vlen(l) <= w for l in lines))
    check("%dx%d: never more lines than rows" % (w, rows), len(lines) <= rows)
    # every action is tappable at some scroll, and the tap lands on its own label
    seen = set()
    for off in range(maxoff + 1):
        lines, hit, _ = panel.draw({}, st, w, rows, off)
        for y, spots in hit.items():
            for x0, x1, k in spots:
                seen.add(k)
                check("%dx%d: a tap on %s's spot is %s" % (w, rows, k, k), panel.at(hit, x0 + 2, y) == k)
                check("%dx%d: %s's spot shows its key" % (w, rows, k),
                      plain(lines[y - 1])[x0 - 1:x1].strip().startswith(k))
    check("%dx%d: every action reachable by tap" % (w, rows), keys <= seen)

check("a phone gets one column", columns(panel.draw({}, st, 40, 35)[0]) == 1)
check("a phone scrolls instead of cutting actions off", panel.draw({}, st, 40, 35)[2] > 0)
check("a tablet gets two columns and no scrolling",
      columns(panel.draw({}, st, 100, 30)[0]) == 2 and panel.draw({}, st, 100, 30)[2] == 0)
check("a wide screen gets the notes, whole", "every phosphor command, by category"
      in "".join(map(plain, panel.draw({}, st, 200, 60)[0])))
check("a narrower one gets their first clause, never a word cut in half",
      "every phosphor command  " in "".join(p + "  " for p in map(plain, panel.draw({}, st, 160, 45)[0])))

# every card says what it does in a terminal: whole, or not at all
for w, rows in ((40, 35), (50, 35), (100, 30)):
    lines, hit, maxoff = panel.draw({}, st, w, rows * 3)
    text = "\n".join(map(plain, lines))
    for x in re.findall(r"(?:^|  )(phosphor [a-z]*)(?=  |$)", text, re.M):
        check("%dx%d: %r is a whole command" % (w, rows, x), x in {panel.command(a[0]) for a in panel.ACTIONS})
check("a phone of 50 columns shows the commands", "phosphor workspace" in "".join(map(plain, panel.draw({}, st, 50, 120)[0])))
check("a tablet shows the commands", "phosphor screens" in "".join(map(plain, panel.draw({}, st, 100, 30)[0])))

# the values: the panel's own, and a card.Live's for the rest
class Live:
    def get(self, name): return ({"services": "12", "mem": "40% free"}.get(name), False)
lv = dict(st, web=True, web_local=True, tunnels=[True, False], dirty_workspaces=3, solaros=False, notices=1, news="2.0 is out")
text = "\n".join(map(plain, panel.draw({}, lv, 100, 120, live=Live())[0]))
for k, want in (("v", "2"), ("w", "local"), ("t", "1/2 up"), ("z", "3 dirty"), ("E", "off"), ("n", "1 on"),
                ("u", "new"), ("y", "12"), ("M", "40% free")):
    check("%s shows %s" % (k, want), re.search(r"^  %s.? .*\b%s\b" % (re.escape(k), re.escape(want)), text, re.M))
for k in ("t", "z", "u"):
    check("%s wants a look: ! after its key, for a screen with no color" % k, re.search(r"^  %s! " % k, text, re.M))
check("v doesn't", re.search(r"^  v  ", text, re.M))
check("a key the panel has no value for asks card.Live: live_names",
      {"services", "mem", "workspace"} <= set(panel.live_names()) and "screens" not in panel.live_names())
check("a tall wide screen spreads out instead of one stretched column",
      columns(panel.draw({}, st, 200, 60)[0]) >= 2 and columns(panel.draw({}, st, 240, 60)[0]) >= 3)
check("scrolled past the end: clamped, not blank",
      panel.draw({}, st, 40, 35, 999)[0][2] == panel.draw({}, st, 40, 35, panel.draw({}, st, 40, 35)[2])[0][2])

# the old two-pane DECK tab is a phosphor migrate step now: tests/migrate-check.py

if fails:
    print("panel-grid-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("panel-grid-check ok")
