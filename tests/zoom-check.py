#!/usr/bin/env python3
"""lib/zoom.py, zoom you can tap: a panel's title ends in the mark, a tap on
it zooms the pane (Alt-z), Esc gives the tab back; a pane too short for a
panel draws a summary of one to three lines; a dashboard a few rows high
puts its cards side by side; the shipped shapes start SYS with a row of
cards that only holds what's set up. A fake terminal first, then a
throwaway zellij (tests/zjprobe.py) for the tap and the Esc themselves.

    python3 tests/zoom-check.py
"""
import json, os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="zoom-check-")
os.environ["PHOSPHOR_PROFILE"] = os.path.join(TMP, "deck.toml")
for k in [k for k in os.environ if k.startswith("ZELLIJ")]:
    del os.environ[k]                      # never the deck this runs in
import card, dash, init, tui, zoom, zjprobe
from ui import vlen

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)

calls = []                                 # what zoom asked zellij, faked
fullscreen = [False]
def fake_zj(*a):
    calls.append(a)
    if a[0] == "list-panes":
        return json.dumps([{"id": 7, "is_plugin": False, "is_fullscreen": fullscreen[0]}])
    return ""
zoom.zj = fake_zj

class Panel(tui.ListPanel):
    TITLE, SUB = "UNITS", "a test"
    def fetch(self): return ["unit-%d" % i for i in range(10)]
    def lines(self, w, sel): return [("> " if i == sel else "  ") + r for i, r in enumerate(self.rows)]

# outside zellij: no mark, Esc closes as it always did
p = Panel(); p.update()
out = p.frame(60, 24)
check("outside zellij: no mark", zoom.MARK not in out[0])
check("outside zellij: Esc closes the panel", p.key("\x1b") is False and not calls)

os.environ.update(ZELLIJ="0", ZELLIJ_PANE_ID="7")
p = Panel(); p.update()
out = p.frame(60, 24)
check("the title ends in the mark, in its last column but one",
      plain(out[0]).rstrip().endswith(zoom.MARK) and vlen(out[0]) == 59)
check("the count stays whole beside it", "10" in plain(out[0]))
check("a tall pane draws every row", sum("unit-" in plain(l) for l in out) == 10)

# a tap on the mark zooms; elsewhere on the title it doesn't
del calls[:]
p.key(("MOUSE", 0, 30, 1, True))
check("a tap on the title, off the mark: no zoom", ("toggle-fullscreen",) not in calls)
p.key(("MOUSE", 0, 58, 1, True))
check("a tap on the mark zooms", ("toggle-fullscreen",) in calls)

# Esc: gives the tab back when zoomed, else closes as before
del calls[:]; fullscreen[0] = True
check("Esc when zoomed: the tab back, the panel stays", p.key("\x1b") is True and ("toggle-fullscreen",) in calls)
del calls[:]; fullscreen[0] = False
check("Esc not zoomed: closes", p.key("\x1b") is False and ("toggle-fullscreen",) not in calls)

# a short pane: the title and at most three lines, a tap anywhere zooms
for h in (2, 3, 4, 5):
    out = p.frame(60, h)
    body = [plain(l) for l in out[1:]]
    check("%d rows: no more lines than the pane" % h, len(out) <= h)
    check("%d rows: at most %d lines of summary" % (h, zoom.SUMMARY), 1 <= len(body) <= zoom.SUMMARY)
    check("%d rows: says how many more" % h, "more" in body[-1] and re.search(r"\+\d+", body[-1]))
    check("%d rows: the title keeps its mark" % h, plain(out[0]).rstrip().endswith(zoom.MARK))
out = p.frame(60, 4)
check("short: the first rows, then +N more", "unit-0" in plain(out[1]) and "unit-1" in plain(out[2])
      and "+8 more" in plain(out[3]))
del calls[:]
p.frame(60, 4); p.key(("MOUSE", 0, 10, 3, True))
check("short: a tap on the summary zooms", ("toggle-fullscreen",) in calls)
check("tall enough: no summary", not zoom.short(zoom.SHORT) and zoom.short(zoom.SHORT - 1))
p.problem = "systemd isn't answering"
check("short: a problem says so", "isn't answering" in plain(p.frame(60, 3)[1]))

# a dashboard a few rows high: the cards side by side under the title
class FakeLive:
    def get(self, n): return ("3 up", n == "ci")
    def why(self, n): return None
names = ["version", "screens", "usage", "ci", "web", "tunnel", "push", "tts", "glance"]
lines, (hit, cw) = dash.draw_short(names, FakeLive(), 130, 3)
check("short dash: the title and its mark", "DASH" in plain(lines[0]) and plain(lines[0]).rstrip().endswith(zoom.MARK))
check("short dash: never wider than the pane", all(vlen(l) <= 130 for l in lines))
check("short dash: several cards a line", sum(n in plain(lines[1]) for n in names) >= 3)
check("short dash: every line fits", len(lines) <= 3)
per = (130 + 1) // (dash.CELL + 1)
check("short dash: a cell's tap is its card's key", hit.get((2, 0)) == "1" and hit.get((2, 1)) == "2")
check("short dash: what doesn't fit is +N more", "more" in plain(lines[-1]) and len(names) > 2 * per - 1)
lines, (hit, cw) = dash.draw_short(names[:2], FakeLive(), 130, 3)
check("short dash: all of them when they fit", "more" not in plain(" ".join(lines)))
lines, _ = dash.draw_short(names[:2], FakeLive(), 40, 3)
check("short dash: a narrow pane, one card a line", "version" in plain(lines[1]) and "screens" in plain(lines[2]))
lines, _ = dash.draw_short([], FakeLive(), 80, 3)
check("short dash: no cards says + picks some", "+" in plain(lines[1]))

# the shipped shapes: SYS starts with a row of cards, only what's set up
os.environ["HOME"] = TMP                    # nobody signed in
import usage
usage.CLAUDE_CREDS = os.path.join(TMP, "nope"); usage.AGY_TOKEN = os.path.join(TMP, "nope2")
check("cards: version and screens with nothing set up", init.sys_cards() == ["version", "screens"])
check("cards: web and tunnels when they're set up",
      init.sys_cards(web=True, tun=("nimbus",)) == ["version", "screens", "web", "tunnel"])
check("cards: no [ci], no CI card", "ci" not in init.sys_cards() and "ci" in init.sys_cards(ci=True))
open(usage.CLAUDE_CREDS, "w").write("{}")
check("cards: the AI plans once claude is signed in", "usage" in init.sys_cards())
for shape in init.SHAPES:
    import tomllib
    prof = tomllib.loads(init.render([{"name": "db-box", "role": "brain", "local": True}], "p31", None,
                                     shape=shape, cards=["version", "screens"]))
    sys_ = next(t for t in prof["tabs"] if t["name"] == "SYS")
    top = sys_["panes"][0]
    check("%s: SYS starts with the row of cards" % shape, top.get("dash") == ["version", "screens"])
    check("%s: a few rows high, short for a panel" % shape,
          isinstance(top.get("size"), int) and zoom.short(top["size"] - 2))
    check("%s: every card in it is one a dashboard holds" % shape, not dash.unknown(top["dash"]))
for f in ("example.toml", "demo.toml"):
    prof = tomllib.loads(open(os.path.join(ROOT, "profiles", f)).read())
    sys_ = next(t for t in prof["tabs"] if t["name"] == "SYS")
    check("profiles/%s: SYS starts with a row of cards" % f, sys_["panes"][0].get("dash"))


# the real thing: a tap on the mark zooms the pane, Esc gives the tab back
def live():
    if not zjprobe.zellij():
        print("no zellij here: live part skipped"); return
    prof = '''[deck]
version = 3
session = "probe"

[[hosts]]
name = "db-box"
role = "brain"
local = true

[[tabs]]
name  = "SYS"
split = "rows"
panes = [
  { dash = ["version"], size = 5 },
  { cmd = "sh" },
]
'''
    with zjprobe.Probe(prof) as z:
        def pane():
            try:
                ps = json.loads(z.action("list-panes", "-a", "-j") or "[]")
            except ValueError:
                return None
            return next((p for p in ps if not p.get("is_plugin") and "dash" in (p.get("terminal_command") or "")), None)
        check("live: the dash pane is there", z.wait(lambda: pane() is not None, 20))
        check("live: it draws its title", z.wait(lambda: "DASH" in plain(z.text()), 20))
        d = pane() or {}
        if not d:
            return
        x = d["pane_content_x"] + d["pane_content_columns"] - 1     # the mark, 1-based on the screen
        y = d["pane_content_y"] + 1
        # a panel drops what came while it was drawing (getkey flushes):
        # under load a tap can land then, so try again until it takes
        def until(send, cond, tries=4):
            for _ in range(tries):
                send()
                if z.wait(cond, 5):
                    return True
            return False
        zoomed = lambda: (pane() or {}).get("is_fullscreen") is True
        check("live: a tap on the mark zooms the pane",
              until(lambda: z.keys("\x1b[<0;%d;%dM\x1b[<0;%d;%dm" % (x, y, x, y)), zoomed))
        check("live: Esc gives the tab back", until(lambda: z.keys("\x1b", settle=1.0), lambda: not zoomed()))
        check("live: and the dashboard is still there", pane() is not None)

live()

for f in fails:
    print("FAIL", f)
print("zoom-check: %d failures" % len(fails) if fails else "zoom-check: ok")
sys.exit(1 if fails else 0)
