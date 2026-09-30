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
      "dirty_workspaces": 0, "two_panes": False}
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
check("a wide screen gets the notes", "every phosphor command, by category"
      in "".join(map(plain, panel.draw({}, st, 160, 45)[0])))
check("scrolled past the end: clamped, not blank",
      panel.draw({}, st, 40, 35, 999)[0][2] == panel.draw({}, st, 40, 35, panel.draw({}, st, 40, 35)[2])[0][2])

# the old two-pane DECK tab: noticed, offered, rewritten as one pane
two = {"tabs": [{"name": "SYS", "panes": [{"cmd": "phosphor fleet"}]},
                {"name": "DECK", "split": "cols",
                 "panes": [{"cmd": "phosphor panel", "size": "50%"}, {"cmd": "phosphor keys"}]}]}
check("the two-pane DECK tab is found", panel.two_panes(two) == "DECK")
check("a one-pane one isn't", panel.two_panes({"tabs": [{"name": "DECK", "panes": [{"cmd": "phosphor panel"}]}]}) is None)
lines, hit, _ = panel.draw({}, dict(st, two_panes=True), 100, 30)
check("the deck card offers D", "this tab in one pane" in "".join(map(plain, lines))
      and any(k == "D" for s in hit.values() for _, _, k in s))
check("without it, no D", all(k != "D" for s in panel.draw({}, st, 100, 30)[1].values() for _, _, k in s))

d = tempfile.mkdtemp()
prof = os.path.join(d, "deck.toml")
open(prof, "w").write('[deck]\nsession = "deck"\n\n[[tabs]]\nname  = "SYS"\npanes = [ { cmd = "phosphor fleet" } ]\n\n'
                      '[[tabs]]\nname  = "DECK"\nsplit = "cols"\npanes = [\n  { cmd = "phosphor panel", size = "50%" },\n'
                      '  { cmd = "phosphor keys" },\n]\n\n[[tabs]]\nname  = "NOTES"\npanes = [ { cmd = "phosphor notes" } ]\n')
os.environ["PHOSPHOR_PROFILE"] = prof
import init, deckconf
real_yes = init.yes
init.yes = lambda *a, **kw: True
saved, sys.stdout = sys.stdout, io.StringIO()
try:
    panel.one_pane()
finally:
    sys.stdout = saved
    init.yes = real_yes
after = deckconf.load()[0]
deck = [t for t in after["tabs"] if t["name"] == "DECK"]
check("D: DECK is one pane of phosphor panel",
      deck and [p.get("cmd") for p in deck[0]["panes"]] == ["phosphor panel"])
check("D: the other tabs stay, in order", [t["name"] for t in after["tabs"]] == ["SYS", "DECK", "NOTES"])
check("D: a backup is kept", os.path.exists(prof + ".bak"))
check("D: nothing left to offer", panel.two_panes(after) is None)

if fails:
    print("panel-grid-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("panel-grid-check ok")
