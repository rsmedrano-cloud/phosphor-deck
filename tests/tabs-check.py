#!/usr/bin/env python3
"""Forgetting and moving tabs in the profile, as text.

    python3 tests/tabs-check.py

A forgotten tab leaves the profile and nothing else does: other tabs, other
sections and their comments stay put; moving swaps two neighbours.
"""
import os, sys, tomllib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import tabs
fails = []
def need(what, ok):
    if not ok: fails.append(what)

PROFILE = '''[deck]
theme = "p31"

# Tabs, in order: Alt-1..9 or tap the bar.
[[tabs]]
name  = "A"
panes = [ {} ]

[[tabs]]
name  = "B"
split = "rows"
panes = [
  { cmd = "btop" },
]

# ── MENTIONS ──
[mentions]
by = "x"

[[tabs]]
name = "C"
panes = [ {} ]
'''
names = lambda t: [x["name"] for x in tomllib.loads(t).get("tabs", [])]
r = tabs.remove_text(PROFILE, "B")
need("forget B", names(r) == ["A", "C"])
need("the next section's comment stays", "# ── MENTIONS ──" in r and 'by = "x"' in r)
need("the header comment stays", "# Tabs, in order" in r)
need("forgetting the last tab", names(tabs.remove_text(PROFILE, "C")) == ["A", "B"])
need("an unknown tab changes nothing", tabs.remove_text(PROFILE, "Z") == PROFILE)
need("move A right", names(tabs.move_text(PROFILE, "A", 1)) == ["B", "A", "C"])
need("move C left, across a section", names(tabs.move_text(PROFILE, "C", -1)) == ["A", "C", "B"])
need("A can't move left", tabs.move_text(PROFILE, "A", -1) == PROFILE)
need("marks come off a tab name", tabs.bare("COMMS ●2") == "COMMS" and tabs.bare("SYS ✎") == "SYS")

# --forget NAME: the non-interactive escape hatch rust/run's own "f" (a
# kept tab's last program ending) shells out to instead of reimplementing
# forget()'s comment-preserving text surgery in a second language. Real
# forget() never runs here: patched, so no file is touched.
import io, contextlib
calls = []
real_forget = tabs.forget
tabs.forget = lambda name: (calls.append(name), None)[1]
try:
    sys.argv = ["phosphor-tabs", "--forget", "SOMETAB"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = tabs.main()
    need("--forget calls forget() with that name", calls == ["SOMETAB"])
    need("--forget NAME exits 0 on success", rc == 0)
    need("--forget NAME says so", "forgotten" in out.getvalue())

    tabs.forget = lambda name: "nope: %s isn't in your profile" % name
    sys.argv = ["phosphor-tabs", "--forget", "GHOST"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = tabs.main()
    need("--forget NAME exits 1 on an error from forget()", rc == 1)

    sys.argv = ["phosphor-tabs", "--forget"]
    rc = tabs.main()
    need("--forget with no name is a usage error, not a crash", rc == 2)
finally:
    tabs.forget = real_forget

# --closing: read-only "is this pane a kept tab's last program?", the other
# half rust/run shells out to. mine()/kept() and ZELLIJ itself are all
# patched: nothing here touches a real zellij session or the real profile.
real_mine, real_kept = tabs.mine, tabs.kept
old_zellij = os.environ.get("ZELLIJ")
try:
    os.environ["ZELLIJ"] = "0"
    tabs.mine = lambda: ("SYS", 1)
    tabs.kept = lambda name: True
    sys.argv = ["phosphor-tabs", "--closing"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = tabs.main()
    need("--closing prints the kept tab's name", out.getvalue().strip() == "SYS")
    need("--closing exits 0", rc == 0)

    tabs.mine = lambda: ("SYS", 2)  # not the last pane
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        tabs.main()
    need("--closing prints nothing when it isn't the last pane", out.getvalue() == "")

    tabs.mine = lambda: ("SYS", 1)
    tabs.kept = lambda name: False  # last pane, but not a kept tab
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        tabs.main()
    need("--closing prints nothing for a tab that isn't kept", out.getvalue() == "")

    del os.environ["ZELLIJ"]
    tabs.kept = lambda name: True
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        tabs.main()
    need("--closing prints nothing outside a zellij session", out.getvalue() == "")
finally:
    tabs.mine, tabs.kept = real_mine, real_kept
    if old_zellij is None: os.environ.pop("ZELLIJ", None)
    else: os.environ["ZELLIJ"] = old_zellij

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
