"""phosphor recipe - starter tab bundles for an existing deck.

Each recipes/NAME.toml is a [[tabs]] file in the exact shape tabs.d takes
(#8): `phosphor recipe NAME` copies it into ~/.config/phosphor/tabs.d/ and
regenerates. From then on it's a tabs.d tab like any other -- read-only
from Alt-r, `phosphor keep` and `phosphor tabs`; edit the file itself, then
`phosphor gen`, to change it.

    phosphor recipe            what's there, and what's already added
    phosphor recipe NAME       add it
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
    print("  " + DIM + "phosphor restart to see it" + RST)
    return 0

def main():
    argv = sys.argv[1:]
    recipes = available()
    if not recipes:
        print("  no recipes bundled with this install"); return 1
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
