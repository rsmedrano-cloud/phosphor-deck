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

# the gallery: arrows, Enter adds, again takes away, q is done
sys.stdout = open(os.devnull, "w")
def keys(*ks):
    it = iter(ks)
    dash.getkey = lambda *a, **k: next(it)
keys("\r", "\x1b[B", "\r", "q")
got = dash.gallery([], rows=24, cols=80)
check("gallery: Enter adds the first card, then the next", got == names[:2])
keys("\r", "q")
check("gallery: Enter on a picked card takes it away", dash.gallery([names[0]], rows=24, cols=80) == [])
keys("q")
check("gallery: nothing changed is None", dash.gallery(["ci"], rows=24, cols=80) is None)
keys(("TAP", 5, 4), "q")
check("gallery: a tap on a card picks it", dash.gallery([], rows=24, cols=80) == [names[0]])
sys.stdout = sys.__stdout__

# the whole screen in a pty: + opens the gallery, Enter adds, q back, -
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
for k in (b"+", b"\r", b"q", b"-", b"1", b"q"):
    drain(1.2); os.write(fd, k)
drain(2)
_, status = os.waitpid(pid, 0)
seen = plain(out.decode("utf-8", "replace"))
check("pty: no traceback", "Traceback" not in seen)
check("pty: it exits 0 on q", os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0)
check("pty: the dashboard and the gallery were drawn", "DASH" in seen and "CARDS" in seen)

if fails:
    print("dash-check FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("dash-check ok")
