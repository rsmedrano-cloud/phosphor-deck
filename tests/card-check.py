#!/usr/bin/env python3
"""lib/card.py, the widget every card of the deck is drawn with: a live
value from the command's own --json, one line that fits, and a tap that
does what share/commands.json says -- no real terminal, no real subprocess.

    python3 tests/card-check.py
"""
import builtins, json, os, re, subprocess, sys, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import card, cli, init
from ui import vlen

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)

# a value in a few characters
for v, want in ((True, "on"), (False, "off"), ([1, 2, 3], "3"), ([], "0"), (4, "4"), ("amber", "amber"),
                ({"total": 200, "available": 50}, "25% free"), ({"x": 1}, None), (None, None)):
    check("summary(%r) is %r" % (v, want), card.summary(v) == want)

# one line: never wider than it's given, the command whole or left out
for w in (20, 30, 40, 48, 60, 90, 140):
    s = card.line("v", "screens", "2", "phosphor screens", "who's attached; kick one loose", w)
    check("%d columns: fits" % w, vlen(s) <= w)
    check("%d columns: the command whole or not at all" % w,
          "phosphor screens" in plain(s) or "phosphor" not in plain(s))
    check("%d columns: the key first" % w, plain(s).startswith("  v"))
s = plain(card.line("t", "tunnels", "1/2 up", "phosphor tunnel", "", 60, warn=True))
check("a card that wants a look has ! after its key (no color needed)", s.startswith("  t! "))
check("the value sits right after the label", re.search(r"tunnels +1/2 up  phosphor tunnel", s))
check("no command: just key, label, value", plain(card.line("s", "a shell here", None, "", "x", 60)).rstrip() == "  s  a shell here")

# a note that doesn't fit: its first clauses, else cut at a word
check("shorten: whole when it fits", card.shorten("who's attached", 20) == "who's attached")
check("shorten: up to a clause", card.shorten("who's attached; kick one loose", 20) == "who's attached")
check("shorten: the longest clauses that fit",
      card.shorten("every workspace, its git state; open, diff, new", 32) == "every workspace, its git state")
check("shorten: a word cut with an ellipsis", card.shorten("keep your ssh LocalForward tunnels up", 20) == "keep your ssh…")

# fetch: the state field from the command's --json, dotted; none without --json
real_run = subprocess.run
calls = []
def fake_run(argv, **kw):
    calls.append(argv[2:])
    out = {"version": {"check": {"behind": 3}}, "services": {"units": [{}, {}]},
           "screens": {"attached": 1, "screens": []}, "ci": {"pipelines": [{}], "why": "failing: app"}, "web": {"on": True, "why": None}}.get(argv[2], {})
    return types.SimpleNamespace(stdout=json.dumps(out), returncode=0)
subprocess.run = fake_run
try:
    check("fetch: a list counted", card.fetch("services") == ([{}, {}], "2", None))
    check("fetch: asks the command for --json", calls[-1] == ["services", "--json"])
    check("fetch: screens counts every screen zellij has, not only ssh logins",
          card.fetch("screens") == (1, "1", None))
    check("fetch: a dotted state", card.fetch("version") == (3, "3", None))
    check("fetch: from arguments as the card says", card.fetch("workspace") == (None, None, None)
          and calls[-1] == ["workspace", "list", "--json"])
    check("fetch: the command's why comes along", card.fetch("ci") == ([{}], "1", "failing: app"))
    check("fetch: a toggle's state from status --json", card.fetch("web") == (True, "on", None)
          and calls[-1] == ["web", "status", "--json"])
    calls.clear()
    check("fetch: a button has no value", card.fetch("doctor") == (None, None, None) and not calls)
    subprocess.run = lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 10))
    check("fetch: a command that hangs is no value, not a crash", card.fetch("screens") == (None, None, None))

    # tap: what the card says, asking first when it says so
    ran, asked, said = [], [], []
    subprocess.run = lambda argv, **kw: ran.append(argv[2:]) or types.SimpleNamespace(returncode=0)
    real_yes, real_input = init.yes, builtins.input
    answer = [True]
    init.yes = lambda q, default=True: asked.append(q) or answer[0]
    builtins.input = lambda prompt="": said.append(prompt) or "nimbus"
    try:
        card.tap("doctor")
        check("tap: a button runs bare, no question", ran[-1] == ["doctor"] and not asked)
        card.tap("screens")
        check("tap: a sensor opens its command", ran[-1] == ["screens"])
        ran.clear(); asked.clear()
        card.tap("web", False)
        check("tap: a toggle that's off turns on, asking first (web publishes)",
              ran == [["web", "on", "--yes"]] and asked)
        ran.clear(); asked.clear()
        card.tap("web", True)
        check("tap: a toggle that's on turns off", ran == [["web", "off"]])
        ran.clear(); answer[0] = False
        card.tap("web", False)
        check("tap: no at the question runs nothing", not ran)
        answer[0] = True
        card.tap("tts", None)
        check("tap: a toggle whose state isn't known opens bare", ran[-1] == ["tts"])
        ran.clear(); said.clear()
        card.tap("triage")
        check("tap: a shortcut asks what it needs, then goes there", ran == [["triage", "nimbus"]] and said)
        ran.clear()
        builtins.input = lambda prompt="": ""
        card.tap("triage")
        check("tap: an empty answer backs out, nothing runs", not ran)
        check("tap: plumbing does nothing", card.tap("clip") is None and not ran)
    finally:
        init.yes, builtins.input = real_yes, real_input
finally:
    subprocess.run = real_run

# Live keeps only the cards that have a value to keep
live = card.Live([], every=60)
check("Live with nothing to watch starts no thread", live.get("screens") == (None, False))
live.got["ci"] = ([{}], "1", "failing: app")
check("Live: a why is a card that wants a look", live.get("ci") == ("1", True) and live.why("ci") == "failing: app")

# the second round comes soon (a screen attaches just after the first), then every `every`
real_fetch, real_sleep, naps = card.fetch, card.time.sleep, []
try:
    card.fetch = lambda n: (None, None, None)
    w = card.Live([], every=60)
    w.names = ["screens"]
    def nap(s):
        naps.append(s)
        if len(naps) == 3:
            w.stop()
    card.time.sleep = nap
    w._loop()
finally:
    card.fetch, card.time.sleep = real_fetch, real_sleep
check("Live: a second look %ds after the first, then every 60" % card.SOON, naps == [card.SOON, 60, 60])

if fails:
    print("card-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("card-check ok")
