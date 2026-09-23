#!/usr/bin/env python3
"""Demo mode checks: made-up machines, made-up notebook, real layout.

    python3 tests/demo-check.py

Verifies:
- profiles/demo.toml parses and carries `[deck] demo = true`
- fleet.py fabricates plausible, varying readings instead of polling ssh
- the notebook is seeded once, from profiles/demo-notes.md, never overwritten
- gen.deck_kdl builds a real layout from the demo profile
- the session it builds in the background never inherits ZELLIJ_SESSION_NAME
  from the calling shell (else it lands inside whatever session you called
  it from, not a throwaway one -- see background_env())
"""
import os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import demo, fleet, gen

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# 1. The demo profile itself
prof = demo.load_profile()
check("profile parses", prof is not None)
check("demo flag is set", ((prof.get("deck") or {}).get("demo")) is True)
check("session isn't the real one", prof["deck"]["session"] != "deck")
names = [h["name"] for h in prof.get("hosts", [])]
check("has more than one host", len(names) > 1)
check("exactly one brain, local", sum(1 for h in prof["hosts"] if h.get("role") == "brain") == 1)

# 2. Fabricated fleet readings, not a frozen frame
for n in names:
    a, b = fleet.demo_collect(n), fleet.demo_collect(n)
    check("%s: ok" % n, a["ok"] is True)
    check("%s: has CPU/RAM" % n, "CPU" in a and "MEMU" in a and "MEMT" in a)
    check("%s: RAM never exceeds total" % n, a["MEMU"] <= a["MEMT"])
check("readings drift over consecutive polls", any(
    fleet.demo_collect(n)["CPU"] != fleet.demo_collect(n)["CPU"] for n in names for _ in range(6)))

# 3. Rendering doesn't choke on the fabricated shape
for n in names:
    head, body = fleet.card(n, 32, fleet.demo_collect(n))
    check("%s: card renders" % n, head and body)

# 4. The notebook is seeded once, and never clobbered afterwards
with tempfile.TemporaryDirectory() as td:
    demo.seed_notes(td)
    dest = os.path.join(td, "notes.md")
    check("notebook seeded", os.path.isfile(dest))
    check("seeded from the template, not empty", os.path.getsize(dest) > 0)
    open(dest, "a").write("\n## 2026-01-01 00:00 · idea · you · Your own note\n\nDon't touch this.\n")
    before = open(dest).read()
    demo.seed_notes(td)   # a second run must not overwrite what's there
    check("existing notebook left alone", open(dest).read() == before)

# 5. A real layout comes out of gen, from this profile alone
ctx = gen.Ctx(prof)
kdl = gen.deck_kdl(prof, ctx, "profiles/demo.toml")
check("layout mentions every demo tab", all(('tab name="%s"' % t["name"]) in kdl
                                            for t in prof.get("tabs", [])))
check("layout runs phosphor fleet/pulse, not a real host's ssh",
      "phosphor" in kdl and "ssh" not in kdl.lower())

# 6. Never leaks the calling shell's own session into the subprocess env
_state = tempfile.mkdtemp()
demo.STATE = os.path.join(_state, "demo-state")
os.environ["ZELLIJ"] = "0"
os.environ["ZELLIJ_SESSION_NAME"] = "deck"
os.environ["ZELLIJ_PANE_ID"] = "13"
try:
    env = demo.background_env()
    check("ZELLIJ stripped", "ZELLIJ" not in env)
    check("ZELLIJ_SESSION_NAME stripped", "ZELLIJ_SESSION_NAME" not in env)
    check("ZELLIJ_PANE_ID stripped", "ZELLIJ_PANE_ID" not in env)
finally:
    for k in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID"):
        os.environ.pop(k, None)

# 7. Nothing the demo reads or writes at run time is the machine's real data: mentions, the
#    adjutant's events, the fleet's readings and the log all follow PHOSPHOR_DATA / PHOSPHOR_CACHE
#    (a demo on a machine with a real chat feed once showed a real name)
import subprocess
real_home = os.path.expanduser("~")
probe = ("import sys; sys.path.insert(0, %r); import mentions, adjutant, fleet, glance, pulse, dlog, version, panel;"
         "print(*[mentions.FEED, mentions.SEEN, mentions.EVENTS, mentions.WORK, adjutant.CACHE, fleet.CACHE,"
         " glance.CACHE, pulse.CACHE, dlog.DIR, version.CACHE, panel.STEPS], sep=' ')" % os.path.join(ROOT, "lib"))
out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True).stdout.split()
check("every state path is read", len(out) == 11)
check("no state path is under the real ~/.local/share/phosphor or ~/.cache/phosphor",
      out and not any(p.startswith(os.path.join(real_home, ".local/share/phosphor")) or
                      p.startswith(os.path.join(real_home, ".cache/phosphor")) for p in out))
check("they are under the demo's state", out and all(p.startswith(demo.STATE) for p in out))

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
