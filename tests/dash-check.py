#!/usr/bin/env python3
"""lib/dash.py, a dashboard of your own: the gallery offers every card, a
pane in the profile becomes `phosphor dash`, a change goes back into that
tab of the profile, and the screens fit and take their keys -- with a fake
terminal, fake values and a temporary profile, never the real one.

    python3 tests/dash-check.py
"""
import json, os, re, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
TMP = tempfile.mkdtemp(prefix="dash-check-")
os.environ["PHOSPHOR_PROFILE"] = os.path.join(TMP, "deck.toml")
import card, cli, dash, gen, keep, profcheck, ui
from ui import vlen

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)

# the gallery: every card that isn't plumbing, nothing on its way out
names = dash.gallery_names()
for n in ("usage", "ci", "web", "screens", "note", "doctor", "containers"):
    check("gallery offers %s" % n, n in names)
for n in ("dash", "panel", "gen", "mcp"):
    check("gallery leaves out %s (plumbing)" % n, n not in names)
kinds = [card.spec(n)["kind"] for n in names]
check("gallery: sensors, toggles, buttons, shortcuts, in that order",
      kinds == sorted(kinds, key=[k for k, _ in dash.KINDS].index))
check("unknown: only the names with no card", dash.unknown(["ci", "nope", "gen"]) == ["nope", "gen"])

# the command line: an unknown card is refused, --json only reads
P = os.path.join(ROOT, "phosphor")
r = subprocess.run([sys.executable, P, "dash", "nope"], capture_output=True, text=True, timeout=30)
check("dash nope exits 2 and says why", r.returncode == 2 and "nope" in r.stderr)
r = subprocess.run([sys.executable, P, "dash", "--json"], capture_output=True, text=True, timeout=30)
check("dash --json with no cards is []", r.returncode == 0 and json.loads(r.stdout) == [])
none = dict(os.environ, PHOSPHOR_PROFILE=os.path.join(TMP, "none.toml"))
r = subprocess.run([sys.executable, P, "dash", "version", "--json"], capture_output=True, text=True,
                   timeout=30, env=none, stdin=subprocess.DEVNULL)
check("no profile: --json says nothing on stderr (a script reads 2>&1 too)", r.returncode == 0 and r.stderr == "")
r = subprocess.run([sys.executable, P, "dash", "version"], capture_output=True, text=True,
                   timeout=30, env=none, stdin=subprocess.DEVNULL)
check("no profile: without --json it still says so", "no profile yet" in r.stderr)

FAKE = {"ci": ([{"name": "app"}], "1", "failing: app"), "web": (True, "on", None),
        "usage": ([{}, {}], "2", None)}
card.fetch = lambda n: FAKE.get(n, (None, None, None))
v = dash.values(["ci", "web"])
check("values: state, summary and why per card",
      v == [{"name": "ci", "kind": "sensor", "state": [{"name": "app"}], "value": "1", "why": "failing: app"},
            {"name": "web", "kind": "toggle", "state": True, "value": "on", "why": None}])

# a pane in the profile: gen runs phosphor dash with its cards and its tab
ctx = gen.Ctx({})
kdl = gen.tab_kdl({"name": "WATCH", "panes": [{"dash": ["usage", "ci"]}]}, ctx, "test")
check("gen: a dash pane runs phosphor dash with its cards and --tab",
      re.search(r'"dash" "usage" "ci" "--tab" "WATCH"', kdl))
check("gen: the pane is titled DASH", 'name="DASH"' in kdl)
lay = keep.parse('layout {\n    tab name="WATCH" {\n%s\n    }\n}\n' % gen.pane_kdl({"dash": ["usage", "ci"]}, ctx, 8))
kctx = {"root": "/nowhere", "expand": ctx.expand, "cwd": os.path.expanduser("~"), "tokens": []}
_, specs, _ = keep.tab_specs(lay, "WATCH", kctx)
check("keep: a running dashboard reads back as dash = [...], no --tab", specs == [{"dash": ["usage", "ci"]}])
lay = keep.parse('layout {\n    tab name="WATCH" {\n        pane command="%s" {\n            args "run" "--name" "CARDS" "--" "%s" "%s" "dash" "ci"\n        }\n    }\n}\n'
                 % (gen.PHOSPHOR, sys.executable, gen.PHOSPHOR))
_, specs, _ = keep.tab_specs(lay, "WATCH", kctx)
check("keep: the + menu's cards (phosphor through python) read back as dash = [...]", specs == [{"dash": ["ci"]}])

# profcheck: a dash that isn't a list, or names no card
found = profcheck.problems({"tabs": [{"name": "W", "panes": [{"dash": ["ci", "nope"]}, {"dash": "ci"}]}]})
words = " ".join(w for _, w in found)
check("profcheck: a name with no card", "nope has no card" in words)
check("profcheck: dash must be a list", "dash is a list" in words)
check("profcheck: a good dash is quiet",
      not profcheck.problems({"tabs": [{"name": "W", "panes": [{"dash": ["ci", "web"]}]}]}))

# keeping a change: only that pane of that tab, a .bak first
prof = os.environ["PHOSPHOR_PROFILE"]
TEXT = '''# my deck
[deck]
session = "deck"

[[tabs]]
name = "SYS"
panes = [ { cmd = "btop" } ]

[[tabs]]
name  = "WATCH"
split = "cols"
panes = [ { cmd = "btop", size = "40%" }, { dash = ["usage", "ci"] } ]
'''
open(prof, "w").write(TEXT)
check("swap: nested panes", dash.swap([{"panes": [{"dash": ["a"]}]}], ["a"], ["b"]) == [{"panes": [{"dash": ["b"]}]}])
check("swap: none with those cards", dash.swap([{"dash": ["a"]}], ["x"], ["b"]) is None)
err = dash.keep("WATCH", ["usage", "ci"], ["usage", "ci", "web"], p=prof)
check("keep: written (%s)" % err, err is None)
import deckconf
after = deckconf.tomllib.loads(open(prof).read())
w = next(t for t in after["tabs"] if t["name"] == "WATCH")
check("keep: the new cards, the other pane and the split as they were",
      w["panes"] == [{"cmd": "btop", "size": "40%"}, {"dash": ["usage", "ci", "web"]}] and w["split"] == "cols")
check("keep: the rest of the profile untouched", "# my deck" in open(prof).read()
      and next(t for t in after["tabs"] if t["name"] == "SYS")["panes"] == [{"cmd": "btop"}])
check("keep: a .bak of the old one", os.path.exists(prof + ".bak") and open(prof + ".bak").read() == TEXT)
check("keep: a tab the profile doesn't have is said", "isn't a tab" in (dash.keep("NOPE", [], ["ci"], p=prof) or ""))
check("keep: cards it no longer has are said", "no dashboard" in (dash.keep("WATCH", ["x"], ["ci"], p=prof) or ""))
check("save: nothing to say without a tab", dash.save(None, ["a"], ["b"]) is None)

# the dashboard: fits its width, keys in order, the whys under it
class FakeLive:
    def get(self, n): return (FAKE.get(n, (None, None, None))[1], bool(FAKE.get(n, (0, 0, None))[2]))
    def why(self, n): return FAKE.get(n, (None, None, None))[2]
    def raw(self, n): return FAKE.get(n, (None, None, None))[0]
for w in (30, 48, 80, 140):
    lines, hit = dash.draw(["usage", "ci", "web"], FakeLive(), w, 20)
    check("draw %d: fits" % w, all(vlen(l) <= w for l in lines))
    check("draw %d: as many lines as rows" % w, len(lines) == 20)
lines, hit = dash.draw(["usage", "ci", "web"], FakeLive(), 100, 20)
txt = [plain(l) for l in lines]
check("draw: cards keyed 1 2 3", [l[:3] for l in txt[2:5]] == ["  1", "  2", "  3"])
check("draw: ci wants a look (!)", txt[3].startswith("  2!"))
check("draw: the command beside it", "phosphor ci" in txt[3])
check("draw: its why under the cards", any("! ci  failing: app" in l for l in txt))
check("draw: a tap on a card's row is its key", hit[3] == "1" and hit[5] == "3")
check("draw: the foot says + and -", "+ add a card" in txt[-1] and "- take one away" in txt[-1])
lines, hit = dash.draw([], FakeLive(), 60, 12)
check("draw: no cards says + picks some", any("+ picks some" in plain(l) for l in lines))

# the boxes: a grid that fills the pane, each card its value, why, entries, command
check("grid: 3 cards in a wide pane sit in one row", dash.grid(3, 80, 8)[:1] == (3,) and dash.grid(3, 80, 8)[3] == 1)
c, tw, th, fit = dash.grid(6, 100, 22)
check("grid: 6 cards leave no slot empty", 6 % c == 0 and tw >= dash.TILE_W and th >= dash.TILE_H)
c, tw, th, fit = dash.grid(54, 80, 20)
check("grid: too many to fit: the smallest boxes, the rest a scroll away",
      th == dash.TILE_H and fit * c < 54 and c * (tw + 1) - 1 <= 80)
FAKE["fleet"] = ({"db-box": {"ok": True}, "nimbus": {"ok": False, "error": "timeout"}, "relay": {"ok": True}}, "3", None)
for w, r in ((24, 12), (60, 20), (100, 30), (160, 50)):
    lines, hit, first = dash.draw_tiles(["usage", "ci", "web", "fleet", "doctor"], FakeLive(), w, r)
    check("tiles %dx%d: fit" % (w, r), all(vlen(l) <= w for l in lines) and len(lines) == r)
lines, hit, first = dash.draw_tiles(["ci", "web", "fleet", "doctor"], FakeLive(), 100, 20)
txt = [plain(l) for l in lines]
box = "\n".join(txt)
check("tiles: key and name on the border", "╭─ 1 ci " in box and "╭─ 3 fleet " in box)
check("tiles: ci wants a look: ! on its border, its why inside", "─ ! ─╮" in txt[2] and "! failing: app" in box)
check("tiles: the first entries, how each is", "nimbus  timeout" in box and "db-box  up" in box)
check("tiles: a button says what it does", "preflight" in box)
check("tiles: the command at each foot", all("phosphor " + n in box for n in ("ci", "web", "fleet", "doctor")))
at = lambda x, y: next((t for top, bot, l, r, t in hit if top <= y <= bot and l <= x <= r), None)
check("tiles: a tap anywhere on a box is that card", at(2, 3) == 0 and at(5, 7) == 0 and at(30, 5) == 1)
check("tiles: a tap on the foot is +", at(10, 20) == "+")
check("tiles: the foot says the keys", "+ add" in txt[-1] and "q leave" in txt[-1])
many = dash.gallery_names()
lines, hit, first = dash.draw_tiles(many, FakeLive(), 80, 20, first=99)
check("tiles: scrolled past the end comes back in range", 0 < first and "↑↓ more" in plain(lines[-1]))
check("detail: entries and how many more",
      [plain(l) for l in card.detail([{"unit": "a", "state": "ok"}, {"unit": "b"}, {"unit": "c"}], 30, 2)]
      == ["a  ok", "+2 more"])
check("detail: one value says nothing more", card.detail(True, 30, 3) == [] and card.detail({"total": 1}, 30, 3) == [])
check("summary: one entry per name counts them", card.summary({"a": {}, "b": {}}) == "2")
os.environ.pop("NO_COLOR", None)
os.environ["TERM"] = "xterm-256color"  # TERM=dumb would mean no color, so no boxes
check("mode: short pane, its row", dash.mode(["ci"], 80, 3) == "short")
check("mode: boxes where they fit", dash.mode(["ci"], 80, 20) == "tiles")
check("mode: the list when narrower than a box, or no cards", dash.mode(["ci"], 20, 20) == "list" and dash.mode([], 80, 20) == "list")
os.environ["NO_COLOR"] = "1"
check("mode: the list on a screen with no color", dash.mode(["ci"], 80, 20) == "list")
del os.environ["NO_COLOR"]
out = dash.printed(["ci", "web"], 100)
check("piped: one plain line per card, then its why", "\x1b" not in out and out.splitlines()[0].lstrip().startswith("! ci")
      and "phosphor web" in out and "! ci  failing: app" in out)

# the gallery: Space or a tap picks, a all / none, Enter applies, Esc cancels
sys.stdout = open(os.devnull, "w")
def keys(*ks):
    it = iter(ks)
    dash.getkey = lambda *a, **k: next(it)
keys(" ", "\x1b[B", " ", "\r")
got = dash.gallery([], rows=24, cols=80)
check("gallery: Space picks the first card, then the next; Enter applies", got == names[:2])
keys(" ", "\r")
check("gallery: Space on a picked card takes it away", dash.gallery([names[0]], rows=24, cols=80) == [])
keys(" ", "\x1b[B", " ", "\x1b")
check("gallery: Esc cancels whatever was picked", dash.gallery(["ci"], rows=24, cols=80) is None)
keys(" ", "q")
check("gallery: q cancels too", dash.gallery([], rows=24, cols=80) is None)
keys("\r")
check("gallery: Enter with nothing changed gives the same list", dash.gallery(["ci"], rows=24, cols=80) == ["ci"])
keys("a", "\r")
check("gallery: a picks every card, the ones it had first", dash.gallery(["ci"], rows=24, cols=80) == ["ci"] + [n for n in names if n != "ci"])
keys("a", "\r")
check("gallery: a with all picked picks none", dash.gallery(list(names), rows=24, cols=80) == [])
keys(("TAP", 5, 4), "\r")
check("gallery: a tap on a card picks it, it doesn't apply", dash.gallery([], rows=24, cols=80) == [names[0]])
seen = []
def grab(lines, rows): seen[:] = [plain(l) for l in lines]
paint, dash.paint = dash.paint, grab
keys(" ", "\x1b")
dash.gallery([], rows=24, cols=100, enter="make the tab")
dash.paint = paint
check("gallery: the top bar says how many and what Enter does", "1 picked · Enter: make the tab" in seen[0])
check("gallery: the foot says the keys", all(w in seen[-1] for w in ("Space", "a: all / none", "Enter: make the tab", "Esc: cancel")))

# the preview: the card under the cursor as it'll look in the pane it goes into
paint, dash.paint = dash.paint, grab
keys("\x1b[B", "\x1b")
dash.gallery(["usage"], rows=30, cols=110, cell=(54, 28))
_, tw, th, _ = dash.grid(2, 54, 28 - ui.HEAD - 2)
check("preview: beside the list, the card under the cursor", any("as it'll look" in l for l in seen[2:4])
      and any(("╭─ 2 %s " % names[1]) in l for l in seen))
check("preview: at the box size it'll have beside the cards picked",
      "box 2 of 2 in a 54×28 pane, %d×%d" % (tw, th) in " ".join(seen)
      and max(len(l) - l.index("╭") for l in seen if "╭" in l) == tw)
check("preview: the list keeps its width and nothing wraps", all(len(l) <= 110 for l in seen)
      and any(l.startswith(">[ ]") for l in seen))
keys("\x1b")
dash.gallery([], rows=40, cols=60)
check("preview: under the list on a narrow screen, at this pane's size", "box 1 of 1 in a 60×40 pane" in " ".join(seen[-9:])
      and all(len(l) <= 60 for l in seen))
keys("\x1b")
dash.gallery([], rows=24, cols=110, cell=(30, 4))
check("preview: a pane too short for boxes shows its line", "a line in a 30×4 pane:" in " ".join(seen) and "short for boxes" in " ".join(seen))
narrow = [plain(l) for l in dash.placed("usage", [], card.Live([]), (80, 24), 18, 10)]
check("preview: no room for its box here, its line, none wider than that",
      all(len(l) <= 18 for l in narrow) and "no room here" in " ".join(narrow))
dash.paint = paint
keys(("TAP", 90, 4), "\r")
check("preview: a tap on it picks nothing", dash.gallery([], rows=24, cols=110) == [])

# a tap on a card: output to read waits for q, Esc or Enter; a screen of the
# card's own (left with q or Esc) comes straight back to the boxes
waited, tap, here, back = [], card.tap, dash.zoom.here, dash.back
card.tap = lambda n, raw=None: subprocess.CompletedProcess([n], 0)
dash.zoom.here = lambda: False
dash.back = lambda *a: waited.append(1)
dash.run_card("doctor", card.Live([]))
check("tap: doctor ends on its output, it waits", waited == [1])
for n in ("screens", "ci", "services"):
    waited[:] = []
    dash.run_card(n, card.Live([]))
    check("tap: %s is a screen of its own, no wait after it" % n, waited == [])
card.tap, dash.zoom.here, dash.back = tap, here, back
sys.stdout = sys.__stdout__

# the whole screen in a pty: + opens the gallery, Space picks, Enter applies, -
# then 1 takes it away, q leaves; nothing raises, the exit is clean
import pty, select, time
WRAP = ("import sys; sys.path.insert(0, %r); import card; "
        "card.fetch = lambda n: (True, 'on', None); import dash; sys.argv = ['dash', 'ci']; "
        "sys.exit(dash.main())" % os.path.join(ROOT, "lib"))
pid, fd = pty.fork()
if pid == 0:
    os.execv(sys.executable, [sys.executable, "-c", WRAP])
out = b""
def drain(t):
    global out
    end = time.time() + t
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                out += os.read(fd, 65536)
            except OSError:
                return
for k in (b"+", b" ", b"\r", b"-", b"1", b"q"):
    drain(1.2); os.write(fd, k)
drain(2)
_, status = os.waitpid(pid, 0)
seen = plain(out.decode("utf-8", "replace"))
check("pty: no traceback", "Traceback" not in seen)
check("pty: it exits 0 on q", os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0)
check("pty: the dashboard and the gallery were drawn", "DASH" in seen and "CARDS" in seen)


# the real thing, in a throwaway zellij: + opens the gallery, Space picks,
# Esc cancels (the next + still shows what it had), a picks all, Enter applies
def live():
    import zjprobe
    if not zjprobe.zellij():
        print("no zellij here: live part skipped"); return
    prof = """[deck]
version = 3
session = "probe"

[[hosts]]
name = "db-box"
role = "brain"
local = true

[[tabs]]
name  = "WATCH"
panes = [ { cmd = "phosphor", args = ["dash", "version"] }, { cmd = "sleep", args = ["9999"] } ]
"""
    every = len(dash.gallery_names())
    with zjprobe.Probe(prof) as z:
        def pane():
            try:
                ps = json.loads(z.action("list-panes", "-a", "-j") or "[]")
            except ValueError:
                return None
            return next(("terminal_%d" % p["id"] for p in ps
                         if not p.get("is_plugin") and "dash" in str(p.get("terminal_command") or "")), None)
        check("live: the dash pane is there", z.wait(lambda: pane() is not None, 20))
        screen = lambda: plain(z.action("dump-screen", "-p", pane() or "") or "")
        check("live: it draws the dashboard", z.wait(lambda: "DASH" in screen(), 20))
        check("live: its card is a box", z.wait(lambda: "╭─ 1 version" in screen(), 20))
        # a panel drops what came while it was drawing (getkey flushes):
        # under load a key can land then, so send again until it takes
        def until(key, cond, tries=4):
            for _ in range(tries):
                z.keys(key, settle=0.3)
                if z.wait(cond, 5):
                    return True
            return False
        picked = lambda n: (lambda: "%d picked" % n in screen())
        check("live: + opens the gallery, the card it has picked", until("+", picked(1)))
        check("live: Space picks or takes one", until(" ", lambda: "1 picked" not in screen()))
        check("live: Esc cancels, back on the dashboard", until("\x1b", lambda: "CARDS" not in screen()))
        check("live: what Esc cancelled isn't there on the next +", until("+", picked(1)))
        check("live: a picks every card", until("a", picked(every)))
        check("live: Enter applies, back on the dashboard", until("\r", lambda: "CARDS" not in screen()))
        check("live: and the next + has them all", until("+", picked(every)))
        check("live: Esc back on the boxes", until("\x1b", lambda: "CARDS" not in screen()))
        def full():
            try:
                ps = json.loads(z.action("list-panes", "-a", "-j") or "[]")
            except ValueError:
                return None
            return next((p.get("is_fullscreen") for p in ps
                         if not p.get("is_plugin") and "dash" in str(p.get("terminal_command") or "")), None)
        check("live: a card's key zooms the pane and opens it", until("1", lambda: full() is True))
        check("live: q in the card gives the tab back, the boxes again",
              until("q", lambda: full() is False and "╭─ 1 version" in screen()))

live()

if fails:
    print("dash-check FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("dash-check ok")
