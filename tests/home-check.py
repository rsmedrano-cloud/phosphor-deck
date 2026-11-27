#!/usr/bin/env python3
"""phosphor home: the grid prototype (#101).

    python3 tests/home-check.py

The pure parts (the layout line, first-fit placement, moving and resizing
a tile, the arrows), the frame (no line fills the pane, only ink and dim,
the page dots), then a throwaway zellij: select, pick a tile up and move
it, a size, Esc puts it back, s keeps it in the profile (a .bak first), a
tap on a term@ tile goes to that tab, and the command line finds a tab.
"""
import os, re, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import home, ui
fails = []
def need(what, ok):
    if not ok: fails.append(what)

SIZES = {"fleet": ["4x2", "2x2", "4x4"], "ci": ["2x2", "4x2"], "notes": ["2x1", "2x2"]}
def sizes(n):
    if n.startswith(home.TERM):
        return home.TERM_SIZES if n[len(home.TERM):] else None
    return SIZES.get(n)

# ── the layout line ───────────────────────────────────────────
pages, skipped = home.parse(" fleet:4x2 , CI , nosuch , notes:9x9 | | term@CHAT:4x4 ,, term@ ", sizes)
need("parse: pages, names lowercased, a size it doesn't take is its first (%r)" % pages,
     pages == [[{"name": "fleet", "size": "4x2"}, {"name": "ci", "size": "2x2"}, {"name": "notes", "size": "2x1"}],
               [{"name": "term@CHAT", "size": "4x4"}]])
need("parse: unknown names skipped, in order (%r)" % skipped, skipped == ["nosuch", "term@"])
need("line: the size only when it isn't the first (%r)" % home.line(pages, sizes),
     home.line(pages, sizes) == "fleet,ci,notes|term@CHAT:4x4")
need("line and parse round-trip", home.parse(home.line(pages, sizes), sizes)[0] == pages)
need("parse: nothing is no pages", home.parse("", sizes) == ([], []) and home.parse(None, sizes) == ([], []))
need("the real cards: a plumbing card isn't a tile, a sensor takes its own sizes",
     home.sizes_of("dash") is None and home.sizes_of("fleet")[0] == "4x2" and home.sizes_of("web") == ["2x2", "4x2"])

# ── placing ───────────────────────────────────────────────────
T = lambda *s: [{"name": "x%d" % i, "size": z} for i, z in enumerate(s)]
need("first-fit: a small tile fills the gap a wide one left (%r)" % home.place(T("2x2", "4x2", "2x2"), 4),
     home.place(T("2x2", "4x2", "2x2"), 4) == [[(0, 0, 0, 2, 2), (1, 0, 2, 4, 2), (2, 2, 0, 2, 2)]])
need("narrow: widths halve (%r)" % home.place(T("4x2", "2x2", "2x2"), 2),
     home.place(T("4x2", "2x2", "2x2"), 2) == [[(0, 0, 0, 2, 2), (1, 0, 2, 1, 2), (2, 1, 2, 1, 2)]])
over = home.place(T("4x2", "4x2", "2x1"), 4, fit=3)
need("what doesn't fit goes on the next screen, a small one stays (%r)" % over,
     over == [[(0, 0, 0, 4, 2), (2, 0, 2, 2, 1)], [(1, 0, 0, 4, 2)]])
need("a tile taller than the screen is cut to it", home.place(T("4x4"), 4, fit=2) == [[(0, 0, 0, 4, 2)]])
scr = home.screens_of([T("2x2"), T("2x2", "2x2")], 4, 4)
need("screens_of: each page's screens, in order", [p for p, _ in scr] == [0, 1] and len(scr[1][1]) == 2)

# ── moving and resizing ───────────────────────────────────────
P = [T("2x2", "2x2"), T("4x2")]
got, at = home.move(P, (0, 0), 1)
need("later: swaps with the next", [t["name"] for t in got[0]] == ["x1", "x0"] and at == (0, 1))
got, at = home.move(P, (0, 1), 1)
need("past a page's last: the next page's start (%r)" % (got,), len(got[0]) == 1 and got[1][0]["name"] == "x1" and at == (1, 0))
got, at = home.move(P, (1, 0), -1)
need("past a page's first: the previous page's end, the empty page goes (%r)" % (got,),
     len(got) == 1 and got[0][-1]["name"] == "x0" and got[0][-1]["size"] == "4x2" and at == (0, 2))
got, at = home.move([T("2x2", "2x2")], (0, 1), 1)
need("past the very last: a page of its own", len(got) == 2 and got[1][0]["name"] == "x1" and at == (1, 0))
need("past the very first: stays", home.move(P, (0, 0), -1) == (P, (0, 0)))
need("move never touches what it's given", P == [T("2x2", "2x2"), T("4x2")])
R = [[{"name": "fleet", "size": "4x2"}]]
need("resize: along its sizes, stopping at the ends",
     home.resize(R, (0, 0), 1, sizes)[0][0]["size"] == "2x2" and
     home.resize(home.resize(home.resize(R, (0, 0), 1, sizes), (0, 0), 1, sizes), (0, 0), 1, sizes)[0][0]["size"] == "4x4"
     and home.resize(R, (0, 0), -1, sizes)[0][0]["size"] == "4x2")
placed = [(0, 0, 0, 2, 2), (1, 2, 0, 2, 2), (2, 0, 2, 4, 2)]
need("arrows: the nearest that way, none past the edge",
     home.nearest(placed, 0, "right") == 1 and home.nearest(placed, 1, "down") == 2
     and home.nearest(placed, 2, "up") in (0, 1) and home.nearest(placed, 0, "left") is None)

# ── the frame ─────────────────────────────────────────────────
plain = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)
two = [T("4x2", "2x2"), T("2x2")]
for name in ("x0", "x1"):
    SIZES[name] = ["4x2", "2x2"] if name == "x0" else ["2x2"]
real_sizes = home.sizes_of
home.sizes_of = sizes
try:
    for w, rows in ((100, 30), (44, 24), (61, 12)):
        lines, hit = home.frame(two, (0, 1), w, rows)
        need("%dx%d: as many lines as rows, none filling the width" % (w, rows),
             len(lines) == rows and all(ui.vlen(l) < w for l in lines))
        codes = set(re.findall(r"\x1b\[[0-9;]*m", "".join(lines))) - {ui.RST, home.INV, home.BOLD}
        need("%dx%d: only ink and dim (%r)" % (w, rows, codes), codes <= {ui.FG, ui.DIM})
        n = len(home.screens_of(two, home.columns(w), (rows - 3) // home.UNIT_H))
        need("%dx%d: the screen of the selected tile, keys and names" % (w, rows),
             any(re.search(r"[12] x1 ", plain(l)) for l in lines)
             and (n > 2 or any("1 x0" in plain(l) for l in lines)))
        dots = [h for h in hit if isinstance(h[4], tuple) and h[4][0] == "page"]
        top = plain(lines[0])
        need("%dx%d: a tap target on each screen's dot (%r)" % (w, rows, top),
             len(dots) == n and all(top[h[2] - 1] in "●○" for h in dots))
    lines, hit = home.frame(two, (0, 1), 100, 30, typing="ch", found=[("CHAT", "open tab: go there", "tab", "CHAT")])
    need("typing: the suggestion above the command line", "CHAT" in plain(lines[-3]) and "› ch" in plain(lines[-1]))
    lines, _ = home.frame([[{"name": "term@CHAT", "size": "4x2"}]], (0, 0), 100, 30)
    need("a term tile before its first read", "…" in plain(lines[2]))
    class St:
        def get(self, tab): return {"runs": "claude", "last": "> ready", "changed": time.time() - 120}
    lines, _ = home.frame([[{"name": "term@CHAT", "size": "4x2"}]], (0, 0), 100, 30, terms=St())
    text = "\n".join(plain(l) for l in lines)
    need("a term tile: what runs, its last line, idle for how long", "claude" in text and "> ready" in text and "idle 2m" in text)
finally:
    home.sizes_of = real_sizes

# ── in a deck ─────────────────────────────────────────────────
import json, zjprobe
PROFILE = '''
[deck]
session = "homecheck"

[home]
layout = "web,screens,term@CHAT"

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name = "HOME"
panes = [ { cmd = "phosphor", args = ["home"] } ]

[[tabs]]
name = "CHAT"
panes = [ { cmd = "" } ]
'''

def active(z):
    t = [t for t in z.listing("list-tabs", "-j") if t.get("active")]
    return (t[0].get("name") or "") if t else ""

def layout(z):
    try:
        return re.search(r'layout = "([^"]*)"', open(z.env["PHOSPHOR_PROFILE"]).read()).group(1)
    except (OSError, AttributeError):
        return None

def shows(z, text, timeout=10):
    return z.wait(lambda: any(text in r for r in z.screen()), timeout)

if not zjprobe.zellij():
    print("  zellij isn't installed: the pure parts only")
else:
    with zjprobe.Probe(PROFILE, session="homecheck", cols=100, rows=30) as z:
        need("the grid came up", shows(z, "1 web", 20) and shows(z, "3 term@CHAT"))
        need("home reads keys", z.wait(lambda: zjprobe.reading_keys(z, "home"), 10))
        z.keys("m", 0.3); z.keys("\x1b[C", 0.3); z.keys("\r", 0.5)
        need("m, an arrow, Enter: the tile moved later", shows(z, "1 screens") and shows(z, "2 web"))
        need("only on screen: the profile is as it was", layout(z) == "web,screens,term@CHAT")
        z.keys("m", 0.3); z.keys("+", 0.3); z.keys("\r", 0.5)
        z.keys("m", 0.3); z.keys("\x1b[D", 0.3); z.keys("\x1b", 0.8)
        need("Esc puts a picked-up tile back", shows(z, "1 screens"))
        z.keys("s", 1.0)
        need("s keeps it: the new order and size (%r)" % layout(z),
             z.wait(lambda: layout(z) == "screens,web:4x2,term@CHAT", 10))
        need("the old profile in deck.toml.bak", os.path.exists(z.env["PHOSPHOR_PROFILE"] + ".bak")
             and 'layout = "web,screens,term@CHAT"' in open(z.env["PHOSPHOR_PROFILE"] + ".bak").read())
        need("it says so", shows(z, "kept in your profile"))
        need("a tap on the term tile goes to its tab", zjprobe.tap(z, "term@CHAT")
             and z.wait(lambda: active(z) == "CHAT", 10))
        z.action("go-to-tab-name", "HOME")
        # #114: a key typed before HOME has the focus and reads keys, or
        # before the command line is open, isn't the command line's
        need("back on HOME, reading keys", z.wait(lambda: active(z) == "HOME", 10)
             and z.wait(lambda: zjprobe.reading_keys(z, "home"), 10))
        z.keys("/", 0.2)
        need("/ opens the command line", z.wait(lambda: any(r.strip().startswith("› _") for r in z.screen()), 10))
        z.keys("CHAT", 0.3)
        need("the command line suggests the tab", shows(z, "open tab: go there"))
        z.keys("\r", 0.8)
        need("Enter on it goes there", z.wait(lambda: active(z) == "CHAT", 10))

if fails:
    print("\n".join("  FAIL " + f for f in fails)); sys.exit(1)
print("home-check ok")
