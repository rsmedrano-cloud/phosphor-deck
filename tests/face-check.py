#!/usr/bin/env python3
"""The adjutant's bitmap face: the bundled one loads and draws at any pane
size (always exactly rows x cols, whatever the glitch, blink or alert), and
`phosphor face` takes a complete frame out of an optimized GIF instead of
the partial rectangle that frame stores.

    python3 tests/face-check.py
"""
import json, os, random, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
# a cache of its own: what it logs never lands in the real deck.log
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp()
import adjutant, face, facebmp
from ui import PALETTES, vlen

fails = []
def check(what, ok):
    if not ok: fails.append(what)

# the bundled face: both eyes, and a light layer to pulse
d = json.load(open(os.path.join(ROOT, "share", "adjutant-face.json")))
bm = d["bitmap"]
check("bundled face has open and closed eyes", set(bm) == {"open", "closed"})
check("bundled face has amber lights", any(c in facebmp.ACCENTS for r in bm["open"] for c in r))
check("open and closed frames are the same size",
      len(bm["open"]) == len(bm["closed"]) and len(bm["open"][0]) == len(bm["closed"][0]))

for theme in PALETTES:
    f = facebmp.Face(bm, PALETTES[theme])
    for cols, rows in ((30, 14), (44, 22), (98, 40), (20, 4), (60, 3)):
        for frame, level, burst, sweep in (("open", 0, 0.0, None), ("closed", 2, 1.0, 0.5)):
            random.seed(1)
            out = f.draw(cols, rows, frame, level, 1.3, burst, sweep)
            check("%s %dx%d %s: exactly %d lines" % (theme, cols, rows, frame, rows), len(out) == rows)
            check("%s %dx%d %s: every line %d wide" % (theme, cols, rows, frame, cols),
                  all(vlen(l) == cols for l in out))
f = facebmp.Face(bm, PALETTES["p31"])
check("a frame that isn't there falls back to open", f.draw(30, 14, "nope") == f.draw(30, 14, "open"))
a = [l for l in f.draw(44, 22, "open", 0, 0.0)]
b = [l for l in f.draw(44, 22, "open", 2, 0.0)]
check("an alert changes the lights' color", a != b)

# loading: the bundled face by default, a missing one is None (the ASCII helmet takes over)
check("default face loads", adjutant.load_bitmap() is not None)
check("a face that isn't there is None, not a crash", adjutant.load_bitmap("no-such-face-xyz") is None)

# the animation loop draws it (not a tty: display only), and exits when killed
# its own empty cache: the real fleet.json (a host down) would replace "listening"
env = dict(os.environ, COLUMNS="50", LINES="24", PHOSPHOR_CACHE=tempfile.mkdtemp())
try:
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import adjutant; adjutant.main()"
                        % os.path.join(ROOT, "lib")], env=env,
                       capture_output=True, text=True, timeout=2)
    out = r.stdout
except subprocess.TimeoutExpired as e:
    out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
check("adjutant draws the bitmap face", "▀" in out and "listening" in out)

# an optimized GIF: frame 1 stores only the rectangle that changed
if shutil.which("convert"):
    t = tempfile.mkdtemp()
    run = lambda *a: subprocess.run(a, check=True, capture_output=True)
    run("convert", "-size", "16x16", "xc:white", os.path.join(t, "a.png"))
    run("convert", os.path.join(t, "a.png"), "-fill", "black", "-draw", "rectangle 0,0 3,3", os.path.join(t, "b.png"))
    gif = os.path.join(t, "o.gif")
    run("convert", "-delay", "10", os.path.join(t, "a.png"), os.path.join(t, "b.png"), "-layers", "optimize", gif)
    sizes = subprocess.run(["identify", gif], capture_output=True, text=True).stdout
    g = face.grid(gif, 1, 8, 8, 1.0, half=False, mode="thr")
    # frame 1 = white everywhere except the top-left corner: a partial frame
    # alone would be all corner (or empty), a coalesced one is mostly white
    solid = sum(row.count("█") for row in g)
    check("optimized GIF frame comes out whole (%d of 64 cells lit)" % solid, solid >= 40)
    shutil.rmtree(t, ignore_errors=True)

if fails:
    print("face-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("face-check ok")
