#!/usr/bin/env python3
"""Alt-r's map of a tab (lib/tabmap.py, #125): no zellij needed.
    python3 tests/tabmap-check.py
Sizes in steps that leave the tab whole, splits and closes that keep the
profile's shape, a program swapped at the size it had, the arrows going to
the pane next door, and the map drawn with each pane's number and size.
"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import tabmap as t

fails = []
def need(what, ok):
    if not ok: fails.append(what)
    return ok

plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
REAL = (120, 40)
SYS = lambda: t.root([{"cmd": "btop", "size": "55%"}, {"cmd": "ctop"}], "rows")

# ── reading it ────────────────────────────────────────────────
r = t.root([{"cmd": "btop"}, {"split": "cols", "panes": [{"cmd": "a"}, {"cmd": "b"}]}])
need("leaves: in the order panes get their numbers", t.leaves(r) == [(0,), (1, 0), (1, 1)])
need("label: cards, ssh, a shell, a program",
     [t.label(s) for s in ({"dash": ["ci", "web"]}, {"ssh": "db-box"}, {"cmd": ""}, {"cmd": "/usr/bin/gping", "args": ["@hosts"]})]
     == ["cards: ci, web", "ssh db-box", "shell", "gping @hosts"])
need("unroot: the tab's split as it said it (none for rows)", t.unroot(t.root([{"cmd": ""}]))[1] is None
     and t.unroot(t.root([{"cmd": ""}], "rows"), "rows")[1] == "rows")
p = t.rects(SYS(), 120, 40)
need("rects: 55% and the rest, the whole height", p[(0,)] == (0, 0, 120, 22) and p[(1,)] == (0, 22, 120, 18))
p = t.rects(t.root([{"cmd": "a"}, {"dash": ["ci"], "size": 5}]), 60, 20, REAL)
need("rects: a size in cells scaled from the real tab, never under 3 rows", p[(1,)][3] == 3 and p[(0,)][3] == 17)
need("share: what a pane has of its row now", t.share(SYS(), (0,), REAL) == 55 and t.share(SYS(), (1,), REAL) == 45)

# ── + and - ───────────────────────────────────────────────────
r = SYS(); t.resize(r, (1,), 1, REAL)
need("+: a step up, its neighbour takes what's left", r["panes"] == [{"cmd": "btop"}, {"cmd": "ctop", "size": "50%"}])
r = SYS(); t.resize(r, (0,), -1, REAL)
need("-: a step down to the next ten", r["panes"][0]["size"] == "50%" and "size" not in r["panes"][1])
r = t.root([{"cmd": "a", "size": "80%"}, {"cmd": "b"}])
t.resize(r, (0,), 1, REAL)
why = t.resize(r, (0,), 1, REAL)
need("+: never past 90%, and it says why", r["panes"][0]["size"] == "90%" and why and "big" in why)
r = t.root([{"cmd": "a"}, {"dash": ["ci"], "size": 5}])
t.resize(r, (1,), 1, REAL); t.resize(r, (1,), 1, REAL)
need("+ on a row of cards: a line at a time", r["panes"][1]["size"] == 7)
need("+ on the only pane: it says it fills the tab", "only" in t.resize(t.root([{"cmd": "a"}]), (0,), 1, REAL))
r = t.root([{"dash": ["ci"], "size": 5}, {"cmd": "a"}])
need("+ on the pane that takes what's left: it says so", "others" in t.resize(r, (1,), 1, REAL))
r = t.root([{"cmd": "a"}, {"split": "cols", "panes": [{"cmd": "b"}, {"cmd": "c"}]}])
t.resize(r, (1, 0), 1, REAL)
need("+ inside a box: along that box's split", r["panes"][1]["panes"][0]["size"] == "60%")

# ── split, close, swap ────────────────────────────────────────
r = SYS(); at = t.split(r, (0,), "rows")
need("b on a row of rows: a shell after it, half its size each",
     at == (1,) and r["panes"][:2] == [{"cmd": "btop", "size": "28%"}, {"cmd": "", "size": "27%"}])
r = SYS(); at = t.split(r, (0,), "cols")
need("v: it and a shell side by side, the box keeps its size",
     at == (0, 1) and r["panes"][0] == {"split": "cols", "size": "55%", "panes": [{"cmd": "btop"}, {"cmd": ""}]})
r = SYS(); at = t.split(r, (1,), "rows", {"dash": ["ci"], "size": 5})
need("c under a pane: a row of cards of its own size", r["panes"][2] == {"dash": ["ci"], "size": 5} and at == (2,))
r = t.root([{"cmd": "only"}]); at = t.split(r, (), "cols")
need("split on a tab of one pane", t.leaves(r) == [(0, 0), (0, 1)] and at == (0, 1))
r = SYS(); at = t.split(r, (0,), "rows")
nxt = t.close(r, at)
need("x on the new half: its space back to the pane it came from",
     r["panes"] == [{"cmd": "btop", "size": "55%"}, {"cmd": "ctop"}] and nxt == (0,))
r = t.root([{"cmd": "a"}, {"cmd": "b", "size": "25%"}, {"cmd": "c", "size": "25%"}]); t.close(r, (0,))
need("x on the pane that took what was left: its neighbour takes it now",
     r["panes"] == [{"cmd": "b"}, {"cmd": "c", "size": "25%"}])
r = SYS(); t.split(r, (0,), "cols"); nxt = t.close(r, (0, 1))
need("x leaving one pane in a box: the box becomes it, at the box's size",
     r["panes"][0] == {"cmd": "btop", "size": "55%"} and nxt == (0,))
r = t.root([{"split": "cols", "panes": [{"cmd": "a"}, {"cmd": "b"}]}, {"cmd": "c"}]); t.close(r, (1,))
need("x leaving the tab one box: the box is the tab's split",
     r == {"split": "cols", "panes": [{"cmd": "a"}, {"cmd": "b"}]})
r = t.root([{"cmd": "a"}])
need("x on the only pane: it says why", isinstance(t.close(r, (0,)), str) and len(t.leaves(r)) == 1)
r = SYS(); t.put(r, (0,), {"cmd": "lazydocker", "size": "10%"})
need("r: another program at the size the pane had", r["panes"][0] == {"cmd": "lazydocker", "size": "55%"})

# ── the arrows ────────────────────────────────────────────────
quad = t.root([{"split": "cols", "panes": [{"cmd": "a"}, {"cmd": "b"}]},
               {"split": "cols", "panes": [{"cmd": "c"}, {"cmd": "d"}]}])
placed = t.rects(quad, 80, 24)
need("arrows: the pane next door, or where you are at the edge",
     t.nearest(placed, (0, 0), "right") == (0, 1) and t.nearest(placed, (0, 0), "down") == (1, 0)
     and t.nearest(placed, (1, 1), "up") == (0, 1) and t.nearest(placed, (0, 0), "left") == (0, 0))

# ── the map ───────────────────────────────────────────────────
lines, placed = t.draw(SYS(), (1,), 60, 16, REAL)
m = [plain(l) for l in lines]
need("draw: as wide and tall as asked", len(m) == 16 and all(len(l) == 60 for l in m))
need("draw: every pane's number, program and size", "1 btop" in m[1] and "55%" in m[2]
     and "▶ 2 ctop" in "".join(m) and "auto" in "".join(m))
need("draw: where each pane is, for a tap", placed[(1,)][1] == 9)
lines, _ = t.draw(t.root([{"cmd": "a"}, {"dash": ["ci"], "size": 5}]), (1,), 60, 12, REAL)
need("draw: a box too short for a size line says it beside the name",
     any("2 cards: ci · 5 rows" in plain(l) for l in lines))

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
print("tabmap: ok")
