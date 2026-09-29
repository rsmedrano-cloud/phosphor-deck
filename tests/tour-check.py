#!/usr/bin/env python3
"""phosphor demo --tour: a guide on every tab that checks each step for real.

    python3 tests/tour-check.py

Verifies, without zellij:
- the demo's profile copy parses, carries `tour = true`, and its layout puts
  one TOUR floating pane on every tab (and none without --tour)
And in a throwaway zellij (tests/zjprobe.py), a real walk through the tour:
- the guide starts visible; Enter moves past the welcome
- going to NOTES, writing a note, opening a tab and keeping it into the
  profile each move it on, checked from zellij, the notebook and the profile
- the guide comes back on its own on the tab you're on after a step
- q ends it and hides it
- gen/up/restart refuse to run on a demo profile (Alt-r's save runs gen:
  in the demo that used to rewrite this machine's real layouts and keys)

Needs zellij for the second half; without it, it says so and passes.
"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import zjprobe

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)

# --- the layout, no zellij needed
import demo, gen
with tempfile.TemporaryDirectory() as td:
    demo.STATE, demo.COPY = td, os.path.join(td, "deck.toml")
    for tour in (True, False):
        demo.write_copy(tour)
        prof = demo.load_profile(demo.COPY)
        need("copy parses (tour=%s)" % tour, prof is not None)
        need("tour flag matches (tour=%s)" % tour, bool(prof["deck"].get("tour")) == tour)
        kdl = gen.deck_kdl(prof, gen.Ctx(prof), "test")
        n = kdl.count('"--tour-pane"')
        need("one guide per tab (tour=%s): %d" % (tour, n), n == (len(prof["tabs"]) if tour else 0))

if not zjprobe.zellij():
    print("ok (no zellij: layout checks only)" if not fails else "FAIL: " + "; ".join(fails))
    sys.exit(1 if fails else 0)

PROFILE = '''
[deck]
session = "tour"
demo = true
tour = true

[[hosts]]
name = "box"
role = "brain"
local = true

[notes]
folder = "~/demo-notes"
''' + "\n".join('[[tabs]]\nname = "%s"\npanes = [ { cmd = "" } ]\n' % n for n in ("SYS", "DECK", "NOTES"))

def tabs(z):
    out = subprocess.run([z.zj, "-s", z.session, "action", "list-tabs", "--state", "--json"],
                         env=z.env, capture_output=True, text=True, timeout=10).stdout
    return json.loads(out or "[]")

def active(z):
    return next((t for t in tabs(z) if t.get("active")), {})

def step(z):
    try:
        return json.load(open(os.path.join(z.env["HOME"], ".cache/phosphor/tour.json")))["step"]
    except (OSError, ValueError, KeyError):
        return 0

def phosphor(z, *args):
    return subprocess.run([os.path.join(z.env["HOME"], ".local/bin/phosphor")] + list(args),
                          env=z.env, capture_output=True, text=True, timeout=30)

with zjprobe.Probe(PROFILE, session="tour") as z:
    need("the guide draws", z.wait(lambda: "TOUR" in z.text() and "1/6" in z.text(), 20))
    need("the guide starts visible", z.wait(lambda: active(z).get("are_floating_panes_visible"), 5))
    z.keys("\r")
    need("Enter moves past the welcome", z.wait(lambda: step(z) == 1, 5))

    z.action("go-to-tab-name", "NOTES")
    need("going to NOTES is seen", z.wait(lambda: step(z) == 2, 8))
    need("the guide is there on NOTES", z.wait(lambda: active(z).get("are_floating_panes_visible"), 5))

    z.keys("\r")
    need("Enter steps the guide aside", z.wait(lambda: not active(z).get("are_floating_panes_visible"), 5))
    r = phosphor(z, "note", "from the tour")
    need("a note is written: %s" % r.stderr[-200:], r.returncode == 0)
    need("a new note is seen", z.wait(lambda: step(z) == 3, 8))
    need("the guide comes back after a step", z.wait(lambda: active(z).get("are_floating_panes_visible"), 5))

    z.action("new-tab", "--name", "MINE")
    need("a new tab is seen", z.wait(lambda: step(z) == 4, 8))

    p = z.env["PHOSPHOR_PROFILE"]
    open(p, "a").write('\n[[tabs]]\nname = "MINE"\npanes = [ { cmd = "" } ]\n')
    need("a kept tab is seen", z.wait(lambda: step(z) == 5, 8))

    z.action("go-to-tab-name", "SYS")
    z.action("show-floating-panes")
    z.pump(1)
    z.keys("q")
    need("q hides the guide", z.wait(lambda: not active(z).get("are_floating_panes_visible"), 5))

    for cmd in ("gen", "restart", "up", "down"):
        r = phosphor(z, cmd)
        need("%s refuses a demo profile: %s" % (cmd, r.stdout[-120:]), "writes nothing" in r.stdout)
    need("gen wrote no units", not os.path.exists(os.path.join(z.env["HOME"], ".config/systemd")))
    r = phosphor(z, "gen", "--dry-run")
    need("gen --dry-run still runs", "phosphor gen" in r.stdout)

print("ok" if not fails else "FAIL: " + "; ".join(fails))
sys.exit(1 if fails else 0)
