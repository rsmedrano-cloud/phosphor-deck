#!/usr/bin/env python3
"""phosphor theme: the preview paints each palette on its own background at
the width it's given, the picker previews without writing and keeps what
Enter (or a second tap) picks, and `theme NAME` edits only the theme line --
never on the demo's profile or a viewer.

    python3 tests/theme-check.py
"""
import contextlib, io, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.environ.pop("PHOSPHOR_THEME", None)
import theme, ui

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# preview(): every line exactly w wide, on the theme's own background
for name in theme.names():
    bg = "\x1b[48;2;%d;%d;%dm" % ui.PALETTES[name]["bg"]
    for w in (20, 40, 72):
        lines = theme.preview(name, w)
        check("%s preview at %d: every line %d wide" % (name, w, w), all(ui.vlen(l) == w for l in lines))
        check("%s preview on its own background" % name, all(l.startswith(bg) for l in lines))

# pick(): keys and taps, nothing written
def run_pick(keys, current="p31"):
    it = iter(keys)
    theme.getkey = lambda timeout=None: next(it, None)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        got = theme.pick(current)
    return got, out.getvalue()

got, out = run_pick(["j", "q"])
check("q leaves without a choice", got is None)
check("j repaints the preview in p3's background", "\x1b[48;2;12;8;0m" in out)
check("the screen is given back", out.endswith("\x1b[?1049l"))
check("j then Enter picks p3", run_pick(["j", "\r"])[0] == "p3")
check("k wraps to the last one", run_pick(["k", "\n"])[0] == "paper")
check("a number jumps to it", run_pick(["3", "\r"])[0] == "p4")
tap = lambda row: ("MOUSE", 0, 5, row, True)
check("one tap previews, a second keeps it", run_pick([tap(5), tap(5)])[0] == "p3")
check("a tap on back leaves", run_pick([tap(3)])[0] is None)
check("end of input leaves", run_pick([])[0] is None)

# `phosphor theme NAME` on a throwaway profile
PROFILE = """# my own comment
[deck]
session = "deck"
theme   = "p31"

[[hosts]]
name = "db-box"
role = "brain"
local = true
"""
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "deck.toml")
    open(p, "w").write(PROFILE)
    env = dict(os.environ, PHOSPHOR_PROFILE=p, HOME=d)
    env.pop("PHOSPHOR_THEME", None)
    ph = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "theme"] + list(a),
                                   env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    r = ph("p3")
    check("theme p3 exits 0: " + r.stdout + r.stderr, r.returncode == 0)
    check("theme p3 writes only the theme line", open(p).read() == PROFILE.replace('"p31"', '"p3"'))
    check("theme p3 keeps a backup", open(p + ".bak").read() == PROFILE)
    check("theme p3 says how to apply it", "phosphor gen && phosphor restart" in r.stdout)
    r = ph("amber")
    check("an alias that's already set: nothing written", "already" in r.stdout
          and open(p).read() == PROFILE.replace('"p31"', '"p3"'))
    r = ph("mauve")
    check("an unknown theme exits 2", r.returncode == 2 and open(p).read() == PROFILE.replace('"p31"', '"p3"'))
    r = ph("--list")
    check("--list names every theme", r.returncode == 0 and all(n in r.stdout for n in theme.names()))
    r = ph()
    check("no terminal: just the list", r.returncode == 0 and "paper" in r.stdout)

    open(p, "w").write(PROFILE.replace('role = "brain"', 'role = "viewer"'))
    r = ph("p4")
    check("a viewer refuses", r.returncode == 1 and '"p4"' not in open(p).read())
    open(p, "w").write(PROFILE.replace('[deck]\n', '[deck]\ndemo = true\n'))
    r = ph("p4")
    check("the demo's profile refuses", r.returncode == 1 and '"p4"' not in open(p).read())

    env["PHOSPHOR_PROFILE"] = os.path.join(d, "missing.toml")
    ex = open(os.path.join(ROOT, "profiles", "example.toml")).read()
    r = ph("p4")
    check("no profile: never writes the repo's example", r.returncode == 1
          and open(os.path.join(ROOT, "profiles", "example.toml")).read() == ex)

if fails:
    print("theme-check: FAIL\n  " + "\n  ".join(fails)); sys.exit(1)
print("theme-check: ok")
