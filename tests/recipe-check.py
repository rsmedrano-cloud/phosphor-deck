#!/usr/bin/env python3
"""Recipes (#7): starter tab bundles via tabs.d, and the wizard's shapes.

    python3 tests/recipe-check.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
profile = os.path.join(tmp, "deck.toml")
open(profile, "w").write('[deck]\nsession = "deck"\n\n[[hosts]]\nname = "x"\nrole = "brain"\nlocal = true\n')
os.environ["PHOSPHOR_PROFILE"] = profile

import recipe, deckconf

recipes = recipe.available()
check("every bundled recipe file is found", set(recipes) == {"homelab", "dev", "bubble", "workbench"})
check("each has a one-line blurb", all(blurb for _, blurb in recipes.values()))

import tomllib
for name, (path, _) in recipes.items():
    with open(path, "rb") as f:
        data = tomllib.load(f)
    check("%s.toml parses and has at least one named tab" % name,
          bool(data.get("tabs")) and all(t.get("name") for t in data["tabs"]))

check("nothing's added yet", not recipe.already_in(recipes["homelab"][0]))
rc = recipe.add("homelab", recipes["homelab"][0])
check("add() reports success", rc == 0)
dropped = os.path.join(deckconf.tabs_d_path(), "homelab.toml")
check("it lands in tabs.d under the right name", os.path.exists(dropped))
check("its content matches the shipped recipe", open(dropped).read() == open(recipes["homelab"][0]).read())
check("already_in() now agrees", recipe.already_in(recipes["homelab"][0]))

# adding it again doesn't error or duplicate
rc2 = recipe.add("homelab", recipes["homelab"][0])
check("adding twice is a no-op, not an error", rc2 == 0)
check("still just the one file", os.listdir(os.path.dirname(dropped)) == ["homelab.toml"])

# -- gen actually builds a recipe's tabs into the layout --
import gen
prof, _ = deckconf.load()
ctx = gen.Ctx(prof)
kdl = gen.deck_kdl(prof, ctx, profile)
check("the recipe's tabs show up in the generated layout", "PROM" in kdl and "CI" in kdl)

# -- the wizard's shapes: what tabs each one builds --
import init
hosts = [{"name": "x", "role": "brain", "local": True, "mounts": ["/"]},
         {"name": "w", "role": "work", "ssh": "w"}]
want = {
    "homelab": ["WORK", "SYS", "CLOUD", "DECK", "NOTES"],
    "revived": ["WORK", "SYS", "DECK", "NOTES"],
    "dev":     ["DEV", "WORK", "SYS", "CLOUD", "DECK", "NOTES"],
}
for shape, expect in want.items():
    body = init.render(hosts, "p31", None, "none", False, (), None, None, None, shape)
    names = [t["name"] for t in tomllib.loads(body).get("tabs", [])]
    check("shape %s builds %s" % (shape, expect), names == expect)

check("revived skips the CLOUD tab (the point of it)",
      "CLOUD" not in [t["name"] for t in tomllib.loads(
          init.render(hosts, "p31", None, "none", False, (), None, None, None, "revived")).get("tabs", [])])

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
