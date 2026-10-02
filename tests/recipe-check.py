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

# -- the empty panels say where their tab came from and how to take it out --
import ui
src = ui.tab_source("phosphor prom")
check("a recipe's PROM tab names `phosphor recipe --remove homelab` (%r)" % src,
      src and "phosphor recipe --remove homelab" in src)
check("a program no tab runs has no source", ui.tab_source("phosphor nothing-runs-this") is None)

# -- --remove undoes it, placed stub included --
import tabs
check("moving CI up writes stubs into the profile", tabs.move("CI", -1) is None
      and any(t.get("name") == "CI" for t in deckconf.load()[0].get("tabs", [])))
check("remove() reports success", recipe.remove("homelab") == 0)
check("its tabs.d file is gone", not os.path.exists(dropped))
check("the stub it left in the profile is gone too",
      not any(t.get("name") in ("PROM", "CI") for t in deckconf.load()[0].get("tabs", [])))
check("removing what isn't there says so, not a crash", recipe.remove("homelab") == 1)

# -- a recipe brings its programs: the store's it offers, the rest it names --
bindir = os.path.join(tmp, "nobin"); os.makedirs(bindir)
os.environ["PATH"] = bindir  # nothing a recipe runs is installed
miss = dict(recipe.needs(recipes["bubble"][0]))
check("bubble needs its four programs (%r)" % miss, set(miss) == {"neomutt", "newsboat", "toot", "gomuks"})
check("gomuks comes from the store", miss.get("gomuks") == "store")
check("neomutt from the package manager", miss.get("neomutt") == "your package manager")
check("toot says how", miss.get("toot") == "pipx install toot")
check("homelab runs only phosphor panels: needs nothing", recipe.needs(recipes["homelab"][0]) == [])
check("every recipe says how to get each non-store program",
      all(how for path, _ in recipes.values() for _, how in recipe.needs(path)))
got, asked = [], []
def fake_install(app, say):
    got.append(app["n"])
    exe = os.path.join(tmp, ".local/bin", app["n"]); os.makedirs(os.path.dirname(exe), exist_ok=True)
    open(exe, "w").write("#!/bin/sh\n"); os.chmod(exe, 0o755)
    return "v1"
check("adding bubble offers the store install", recipe.add("bubble", recipes["bubble"][0],
      ask=lambda q: asked.append(q) or True, install=fake_install) == 0)
check("it asked once, naming gomuks (%r)" % asked, len(asked) == 1 and "gomuks" in asked[0])
check("only the store's program was installed (%r)" % got, got == ["gomuks"])
check("and now it isn't missing", "gomuks" not in dict(recipe.needs(recipes["bubble"][0])))
got.clear(); os.remove(os.path.join(tmp, ".local/bin", "gomuks"))
recipe.add("bubble", recipes["bubble"][0], ask=lambda q: False, install=fake_install)
check("no to the question installs nothing", got == [])
fake_install({"n": "gomuks"}, None)
check("taking it out leaves the program alone", recipe.remove("bubble") == 0
      and os.path.exists(os.path.join(tmp, ".local/bin", "gomuks")))

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
