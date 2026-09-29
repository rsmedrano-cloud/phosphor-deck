"""phosphor recipe - starter tab bundles for an existing deck.

Each recipes/NAME.toml is a [[tabs]] file in the exact shape tabs.d takes
(#8): `phosphor recipe NAME` copies it into ~/.config/phosphor/tabs.d/ and
regenerates. From then on it's a tabs.d tab like any other -- read-only
from Alt-r, `phosphor keep` and `phosphor tabs`; edit the file itself, then
`phosphor gen`, to change it.

    phosphor recipe                what's there, and what's already added
    phosphor recipe NAME           add it
    phosphor recipe --remove NAME  take it back out (its tabs.d file)
"""
import os, shutil, subprocess, sys, tomllib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

RECIPES = os.path.join(REPO, "recipes")

def available():
    """{name: (file path, its one-line blurb)}, sorted by name."""
    out = {}
    if not os.path.isdir(RECIPES):
        return out
    for n in sorted(os.listdir(RECIPES)):
        if not n.endswith(".toml"):
            continue
        p = os.path.join(RECIPES, n)
        blurb = ""
        with open(p) as f:
            for line in f:
                if line.startswith("# Recipe:"):
                    blurb = line.split(":", 1)[1].strip()
                    break
        out[n[:-5]] = (p, blurb)
    return out

def tab_names(path):
    try:
        with open(path, "rb") as f:
            return [t["name"] for t in tomllib.load(f).get("tabs", []) if t.get("name")]
    except Exception:
        return []

def already_in(path):
    got = tab_names(path)
    have = deckconf.tabs_d_names()
    return bool(got) and all(t in have for t in got)

def add(name, src):
    d = deckconf.tabs_d_path()
    dst = os.path.join(d, name + ".toml")
    if os.path.exists(dst):
        print(row(AMB, name, "already in tabs.d", note=dst.replace(os.path.expanduser("~"), "~", 1)))
        return 0
    os.makedirs(d, exist_ok=True)
    shutil.copy(src, dst)
    print(row(OK, name, "added", note=dst.replace(os.path.expanduser("~"), "~", 1)))
    subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "gen"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("  " + DIM + "phosphor restart to see it · phosphor recipe --remove %s undoes it" % name + RST)
    return 0

def remove(name):
    """Undo `phosphor recipe NAME`: its file out of tabs.d, and gen. A stub
    your profile keeps for one of its tabs (from `phosphor tabs`, K/J) goes
    too, or gen would find a tab with nothing behind it."""
    dst = os.path.join(deckconf.tabs_d_path(), name + ".toml")
    if not os.path.exists(dst):
        print(row(AMB, name, "not in tabs.d: nothing to remove"))
        return 1
    names = tab_names(dst)
    import tabs
    prof, _ = deckconf.load()
    for t in (prof or {}).get("tabs", []):
        if t.get("name") in names and not deckconf.is_real_tab(t):
            err = tabs.forget(t["name"])
            if err:
                print(row(BAD, name, err)); return 1
    os.remove(dst)
    print(row(OK, name, "removed", note=", ".join(names)))
    subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "gen"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("  " + DIM + "phosphor restart to see it gone" + RST)
    return 0

def main():
    argv = sys.argv[1:]
    recipes = available()
    if not recipes:
        print("  no recipes bundled with this install"); return 1
    if argv and argv[0] in ("--remove", "-r"):
        if len(argv) < 2:
            print("  usage: phosphor recipe --remove NAME"); return 1
        return remove(argv[1])
    if argv:
        name = argv[0]
        if name not in recipes:
            print("  no recipe named %r -- phosphor recipe lists what's there" % name)
            return 1
        return add(name, recipes[name][0])
    if not sys.stdin.isatty():
        for name, (path, blurb) in recipes.items():
            print(row(OK if already_in(path) else (DIM + "·" + RST), name, blurb,
                      note="already in tabs.d" if already_in(path) else ""))
        return 0
    import edit
    items = [(name, blurb + ("  (already in)" if already_in(path) else ""), name)
             for name, (path, blurb) in recipes.items()]
    it = edit.pick("recipes: starter tab bundles", items)
    if not it: return 0
    return add(it[2], recipes[it[2]][0])

if __name__ == "__main__":
    sys.exit(main() or 0)
