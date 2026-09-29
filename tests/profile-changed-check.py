#!/usr/bin/env python3
"""A hand edit of the profile says so: gen records what it read, the DECK
tab and doctor notice when the profile (or tabs.d) no longer matches, and
the DECK tab's f applies it (gen, then restart) only after asking.

    python3 tests/profile-changed-check.py

A throwaway HOME: gen writes there, never into the real one.
"""
import builtins, io, os, subprocess, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

fails = []
def need(what, ok):
    if not ok: fails.append(what)

home = tempfile.mkdtemp()
conf = os.path.join(home, ".config/phosphor")
prof = os.path.join(conf, "deck.toml")
os.makedirs(conf); os.makedirs(os.path.join(home, ".local/bin"))
open(prof, "w").write('[deck]\ntheme = "p31"\n\n[[hosts]]\nname = "box"\nrole = "brain"\nlocal = true\n\n'
                      '[[tabs]]\nname = "A"\npanes = [ {} ]\n')
env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
env.update(PATH="/usr/bin:/bin", HOME=home, PHOSPHOR_PROFILE=prof, PHOSPHOR_DATA=os.path.join(home, "data"),
           PHOSPHOR_TABS_D=os.path.join(conf, "tabs.d"))
stamp = os.path.join(home, "data", "gen-profile")

def phosphor(*a):
    return subprocess.run([sys.executable, os.path.join(ROOT, "phosphor")] + list(a),
                          capture_output=True, text=True, env=env, timeout=120)

def changed():
    return subprocess.run([sys.executable, "-c", "import deckconf; print(deckconf.profile_changed())"],
                          capture_output=True, text=True, env=env, cwd=os.path.join(ROOT, "lib")).stdout.strip()

need("no gen yet: nothing to say (never nags an older install)", changed() == "False")
phosphor("gen", "--dry-run")
need("gen --dry-run records nothing", not os.path.exists(stamp))
g = phosphor("gen")
need("gen runs to the end (no zellij here is fine): " + g.stderr[-300:], g.returncode == 0)
need("gen records the profile it read", os.path.exists(stamp))
need("right after gen: unchanged", changed() == "False")

open(prof, "a").write('\n[[tabs]]\nname = "B"\npanes = [ {} ]\n')
need("a hand edit of deck.toml is noticed", changed() == "True")
d = phosphor("doctor").stdout
need("doctor says the profile changed since the last gen", "changed since the last phosphor gen" in d)
need("doctor says what applies it", "phosphor gen && phosphor restart" in d)

phosphor("gen")
need("gen again: unchanged", changed() == "False")
need("doctor quiet again", "changed since the last phosphor gen" not in phosphor("doctor").stdout)

os.makedirs(env["PHOSPHOR_TABS_D"])
open(os.path.join(env["PHOSPHOR_TABS_D"], "x.toml"), "w").write('[[tabs]]\nname = "X"\npanes = [ {} ]\n')
need("a new tabs.d file is noticed too", changed() == "True")

# the DECK tab: the status line says it (and a tap on it applies it), f asks first
import panel, init
st = {"session": "deck", "version": "1", "channel": "stable", "news": "", "screens": None,
      "timer": True, "web": False, "tunnels": [], "profile_changed": True}
lines, hit = panel.draw({}, st, 100, 60)
need("the status line says it", "profile changed: f applies it" in lines[1])
need("a tap on that line is f", hit.get(2) == "f")
lines, hit = panel.draw({}, dict(st, profile_changed=False), 100, 60)
need("unchanged: the status line doesn't mention it", "profile changed" not in lines[1] and "f" not in hit.values())

ran, rc = [], {"gen": 0}
panel.subprocess.run = lambda cmd, **kw: ran.append(cmd[-1]) or types.SimpleNamespace(returncode=rc.get(cmd[-1], 0))
panel.back = lambda *a, **kw: None
def act(answer):
    init.yes = lambda *a, **kw: answer
    ran.clear()
    saved, sys.stdout = sys.stdout, io.StringIO()
    try: panel.act("f", st)
    finally: sys.stdout = saved
    return list(ran)
need("f, declined: nothing runs", act(False) == [])
need("f, confirmed: gen, then restart", act(True) == ["gen", "restart"])
rc["gen"] = 1
need("f, gen fails: no restart", act(True) == ["gen"])

if fails:
    print("profile-changed-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("profile-changed-check ok")
