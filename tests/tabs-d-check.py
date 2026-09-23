#!/usr/bin/env python3
"""tabs.d: tabs you can share (#8) -- dropped-in files add tabs to the
deck. Their content is read-only from Alt-r and phosphor keep, but
phosphor tabs can still place one somewhere on purpose: a name-only stub
in the profile pins its position, without moving its content out of the
file it came from.

    python3 tests/tabs-d-check.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
os.environ.pop("ZELLIJ", None)

d = os.path.join(tmp, ".config", "phosphor", "tabs.d")
os.makedirs(d)
open(os.path.join(d, "shared.toml"), "w").write(
    '[[tabs]]\nname = "SHARED"\npanes = [ { cmd = "htop" } ]\n')
open(os.path.join(d, "broken.toml"), "w").write("this is [ not valid toml")

profile = os.path.join(tmp, "deck.toml")
open(profile, "w").write(
    '[deck]\nsession = "deck"\n\n[[hosts]]\nname = "x"\nrole = "brain"\nlocal = true\n\n'
    '[[tabs]]\nname = "WORK"\npanes = [ { cmd = "bash" } ]\n')
os.environ["PHOSPHOR_PROFILE"] = profile

import deckconf

check("finds the valid file's tab", "SHARED" in deckconf.tabs_d_names())
check("a broken file doesn't crash the scan", len(deckconf.tabs_d()) == 1)

prof, _ = deckconf.load()
eff = [t["name"] for t in deckconf.effective_tabs(prof)]
check("effective_tabs has both, profile's first", eff == ["WORK", "SHARED"])

# -- a name the profile already has wins over tabs.d --
prof2 = {"tabs": [{"name": "SHARED", "panes": [{"cmd": "mine"}]}]}
eff2 = deckconf.effective_tabs(prof2)
check("a profile tab shadows a tabs.d tab of the same name",
      len(eff2) == 1 and eff2[0]["panes"][0]["cmd"] == "mine")

# -- gen actually builds it into the session layout --
import gen
ctx = gen.Ctx(prof)
kdl = gen.deck_kdl(prof, ctx, profile)
check("SHARED lands in the generated layout", "SHARED" in kdl)
check("so does the profile's own WORK", "WORK" in kdl)

# -- phosphor tabs: sees it, and can place it, but never rewrites its file --
import tabs
check("kept() is true for a tabs.d tab (it does come back)", tabs.kept("SHARED"))
check("kept() is true for a profile tab too", tabs.kept("WORK"))
check("kept() is false for a name that's neither", not tabs.kept("NOPE"))
check("not pinned before it's ever moved", not tabs.pinned("SHARED"))
names = [t["name"] for t in tabs.all_tabs(prof)]
check("all_tabs() lists both, profile's first", names == ["WORK", "SHARED"])

msg = tabs.forget("SHARED")
check("forgetting an unplaced tabs.d tab is a no-op, not an error",
      msg and "already at the end" in msg)
check("and touches nothing", "SHARED" not in open(profile).read())

err = tabs.move("SHARED", -1)
check("move() places it: swaps with its real neighbour", err is None)
new_text = open(profile).read()
check("the profile gets a name-only stub, not the tab's content",
      'name = "SHARED"' in new_text and "htop" not in new_text)
check("pinned() now agrees", tabs.pinned("SHARED"))
prof3, _ = deckconf.load()
check("effective order actually moved: SHARED before WORK",
      [t["name"] for t in deckconf.effective_tabs(prof3)] == ["SHARED", "WORK"])
check("its real content still comes from the tabs.d file",
      [t for t in deckconf.effective_tabs(prof3) if t["name"] == "SHARED"][0]["panes"][0]["cmd"] == "htop")

msg2 = tabs.forget("SHARED")
check("forgetting a placed tabs.d tab un-places it", msg2 is None)
check("its stub is gone", "SHARED" not in open(profile).read())
check("but the tabs.d file is untouched", os.path.exists(os.path.join(d, "shared.toml")))
check("and it's still there, just back at the end",
      [t["name"] for t in deckconf.effective_tabs(deckconf.load()[0])] == ["WORK", "SHARED"])

# -- moving one of several unplaced tabs.d tabs pins them all, in their
# fallback order, so it swaps with its real effective neighbour (another
# tabs.d tab) instead of jumping past it --
open(os.path.join(d, "second.toml"), "w").write(
    '[[tabs]]\nname = "SECOND"\npanes = [ { cmd = "top" } ]\n')
before = [t["name"] for t in deckconf.effective_tabs(deckconf.load()[0])]
check("both unplaced tabs.d tabs fall back in file-name order",
      before == ["WORK", "SECOND", "SHARED"])
err3 = tabs.move("SHARED", -1)
check("moving SHARED left succeeds", err3 is None)
after = [t["name"] for t in deckconf.effective_tabs(deckconf.load()[0])]
check("it swapped with SECOND, its real neighbour -- not WORK",
      after == ["WORK", "SHARED", "SECOND"])
check("moving it pinned SECOND too, not just SHARED", tabs.pinned("SECOND"))

# -- keep: won't let a captured tab shadow one from tabs.d --
import keep, io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ok = keep.save("SHARED", "[[tabs]]\nname = \"SHARED\"\npanes = [ { cmd = \"mine\" } ]\n")
check("keep.save() refuses to shadow a tabs.d tab", ok is False)
check("and says why", "shared.toml" in buf.getvalue())
check("deck.toml is untouched", "mine" not in open(profile).read())

# -- a name that's already the profile's own can still be re-kept --
buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    ok2 = keep.save("WORK", "[[tabs]]\nname = \"WORK\"\npanes = [ { cmd = \"zsh\" } ]\n")
check("keep.save() still works for the profile's own tabs", ok2 is True)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
