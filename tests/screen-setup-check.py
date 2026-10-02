#!/usr/bin/env python3
"""phosphor setup's "its own deck?" step: it says what a deck of its own
costs before anyone picks it, writes or drops [screens.KIND] as text, and
leaves the profile alone when the answer is to share this deck.

    python3 tests/screen-setup-check.py
"""
import io, os, sys, tempfile, contextlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
profile = os.path.join(tmp, "deck.toml")
BASE = ('[deck]\nsession = "deck"\n\n[[hosts]]\nname = "db-box"\nrole = "brain"\nlocal = true\n\n'
        '[[tabs]]\nname = "SYS"\n\n[[tabs]]\nname = "NOTES"\n\n[[tabs]]\nname = "DECK"\n\n'
        '[screens.lcd]\ntabs = ["SYS"]\n')
open(profile, "w").write(BASE)
os.environ["PHOSPHOR_PROFILE"] = profile

import deckconf, deck_setup as ds

def run(answers):
    """screen_kind() with typed answers (no terminal: pick takes a number)."""
    prof = deckconf.tomllib.loads(open(profile).read())
    sys.stdin = io.StringIO("\n".join(answers) + "\n")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        text, changed = ds.screen_kind(prof, open(profile).read())
    sys.stdin = sys.__stdin__
    return text, changed, out.getvalue()

text, changed, out = run(["1"])
check("sharing the deck changes nothing", not changed and text == BASE)
check("the cost is said before the choice", "second time" in out and "phosphor mem" in out)

text, changed, out = run(["2", "tablet", "sys, notes", "y"])
prof = deckconf.tomllib.loads(open(profile).read())
check("a deck of its own writes [screens.tablet]",
      changed and (prof.get("screens") or {}).get("tablet") == {"tabs": ["SYS", "NOTES"]})
check("tab names are matched whatever the case", "NOTES" in open(profile).read())
check("it says what to run on that screen", "phone --as tablet" in out and "screen --as tablet" in out)
check("the lcd block is still there", "lcd" in prof["screens"])

text, changed, out = run(["2", "eink", "", "y"])
prof = deckconf.tomllib.loads(open(profile).read())
check("no tabs means every tab", prof["screens"].get("eink") == {})

before = open(profile).read()
text, changed, out = run(["2", "kindle", "SYS GHOST"])
check("a tab that doesn't exist saves nothing", not changed and open(profile).read() == before)

text, changed, out = run(["2", "tablet"])
check("a kind that has one already is left alone", not changed and open(profile).read() == before)

# 1 share, 2 own, then one "stop" per kind in the profile's order: lcd, tablet, eink
text, changed, out = run(["4"])
prof = deckconf.tomllib.loads(open(profile).read())
check("stop drops just that kind", changed and set(prof["screens"]) == {"lcd", "eink"})
check("and the rest of the profile reads the same",
      [t["name"] for t in prof["tabs"]] == ["SYS", "NOTES", "DECK"])
check("a backup was kept", os.path.exists(profile + ".bak"))

if fails:
    print("FAIL: " + "; ".join(fails)); sys.exit(1)
print("ok")
