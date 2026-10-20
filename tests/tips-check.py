#!/usr/bin/env python3
"""Did you know: the DECK tab's tip line, built from share/commands.json.

    python3 tests/tips-check.py

Every tip is a command's summary and where to reach it; the ones never run
by hand come first, a new one every while; on the DECK tab it takes the
second line when nothing more urgent does, and a tap on it does what it
says when it names a DECK key. No terminal, nothing of the real deck.
"""
import os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp()
import cli, panel, tips

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

keys = {}
for k, cmds in panel.OPENS.items():
    for c in cmds:
        if k not in "fP": keys.setdefault(c, k)
all_ = tips.all_tips(keys)
entries = cli.entries()
check("there are tips", len(all_) > 20)
for cmd, t in all_:
    e = entries[cmd]
    check("%s: a public command with a card" % cmd, not e.get("hidden") and e["card"]["kind"] != "plumbing")
    check("%s: says where it is" % cmd, t.endswith((" in the DECK tab", " in any tab", "phosphor " + cmd)))
check("send's tip names s", dict(all_)["send"].endswith("s in the DECK tab"))
check("a command a key opens second has that key too (screen: p)", dict(all_)["screen"].endswith("p in the DECK tab"))
check("note's tip names Alt-j", dict(all_)["note"].endswith("Alt-j in any tab"))
check("plumbing has no tip", "run" not in dict(all_))

# the never-run first, then all of them in turns
names = [c for c, _ in all_]
used = set(names) - {"send", "receive"}
seen = {tips.pick(keys, now=n * tips.EVERY, used=used)[0] for n in range(6)}
check("never-run ones first: only send and receive while they're new", seen == {"send", "receive"})
seen = {tips.pick(keys, now=n * tips.EVERY, used=set(names))[0] for n in range(len(names))}
check("all tried: every tip in turn", seen == set(names))
check("the same tip all through a while", tips.pick(keys, now=5, used=set())
      == tips.pick(keys, now=tips.EVERY - 1, used=set()))

# on the DECK tab
plain = lambda s: re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)
panel.marked = lambda step: False
st = {"session": "deck", "version": "1.2.4", "channel": "stable", "news": "", "screens": 2,
      "timer": True, "web": False, "tunnels": [True], "profile_changed": False,
      "dirty_workspaces": 0, "migrate": 0}
real = tips.pick
tips.pick = lambda keys, **kw: ("send", "one real file · s in the DECK tab")
lines, hit, _ = panel.draw({}, st, 100, 40)
check("DECK: the tip on the second line", plain(lines[1]).startswith(" did you know? one real file"))
check("DECK: a tap on it is its key", hit.get(2) == [(1, 100, "s")])
tips.pick = lambda keys, **kw: ("ask", "a question · phosphor ask")
lines, hit, _ = panel.draw({}, st, 100, 40)
check("DECK: a tip with no key isn't a tap target", 2 not in hit)
lines, hit, _ = panel.draw({}, dict(st, news="2.9 is out"), 100, 40)
check("DECK: news comes before a tip", "2.9 is out" in plain(lines[1]))
lines, _, _ = panel.draw({}, st, 36, 40)
check("DECK: no tip on a very narrow pane", "did you know" not in plain(lines[1]))
tips.pick = real

if fails:
    print("tips-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("tips-check ok (%d tips)" % len(all_))
