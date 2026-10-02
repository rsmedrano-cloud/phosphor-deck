"""phosphor recipe - starter tab bundles for an existing deck.

Each recipes/NAME.toml is a [[tabs]] file in the exact shape tabs.d takes
(#8): `phosphor recipe NAME` copies it into ~/.config/phosphor/tabs.d/ and
regenerates. From then on it's a tabs.d tab like any other -- read-only
from Alt-r, `phosphor keep` and `phosphor tabs`; edit the file itself, then
`phosphor gen`, to change it.

    phosphor recipe                what's there, and what's already added
    phosphor recipe NAME           add it
    phosphor recipe --remove NAME  take it back out (its tabs.d file)

A recipe also says what its panes run. Adding one checks which of those
programs aren't installed: what `phosphor store` carries it offers to
install (no sudo, into ~/.local/bin); the rest it names with the line its
[recipe.install] table gives. Taking a recipe out never uninstalls anything.
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

SHELLS = {"", "bash", "zsh", "fish", "sh", "phosphor"}

def _panes(ps):
    for p in ps or []:
        if p.get("panes"):
            yield from _panes(p["panes"])
        else:
            yield p

def _catalog():
    """{binary: entry} for what `phosphor store` downloads itself."""
    import json, store
    try:
        return {store.binname(a): a for a in json.load(open(share("store.json"))) if a.get("r")}
    except Exception:
        return {}

def needs(path):
    """[(program, how)] for what this recipe's panes run that isn't
    installed. how: "store" (phosphor store has it), its [recipe.install]
    line, or "" when the recipe doesn't say."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return []
    hints = (data.get("recipe") or {}).get("install") or {}
    progs = []
    for t in data.get("tabs", []):
        for p in _panes(t.get("panes")):
            b = (p.get("cmd") or "").split()
            if b and b[0] not in SHELLS and b[0] not in progs:
                progs.append(b[0])
    import apps
    cat, out = _catalog(), []
    for b in progs:
        if apps.have(b):
            continue
        h = hints.get(b, "")
        out.append((b, "store" if b in cat else ("your package manager" if h == "package" else h)))
    return out

def offer(path, ask=None, install=None):
    """Say what's missing; install what the store has once `ask` says yes.
    No terminal (and no `ask`): only say it."""
    missing = needs(path)
    if not missing:
        return
    import store
    cat = _catalog()
    fromstore = [b for b, how in missing if how == "store"]
    for b, how in missing:
        if how != "store":
            print(row(AMB, b, "not installed", note=how or "its panes will say so"))
    if not fromstore:
        return
    if ask is None and sys.stdin.isatty():
        ask = lambda q: input("  " + q).strip().lower() in ("", "y", "yes")
    if ask is None or not ask("install %s from the store (no sudo)? (Y/n) " % ", ".join(fromstore)):
        for b in fromstore:
            print(row(AMB, b, "not installed", note="phosphor store has it"))
        return
    install = install or store.install
    for b in fromstore:
        try:
            tag = install(cat.get(b, {"n": b}), lambda m: None)
            print(row(OK, b, "installed", note=tag or ""))
        except Exception as e:
            print(row(BAD, b, "didn't install", note=str(e)[:60]))

def already_in(path):
    got = tab_names(path)
    have = deckconf.tabs_d_names()
    return bool(got) and all(t in have for t in got)

def add(name, src, ask=None, install=None):
    d = deckconf.tabs_d_path()
    dst = os.path.join(d, name + ".toml")
    if os.path.exists(dst):
        print(row(AMB, name, "already in tabs.d", note=dst.replace(os.path.expanduser("~"), "~", 1)))
        offer(src, ask, install)
        return 0
    os.makedirs(d, exist_ok=True)
    shutil.copy(src, dst)
    print(row(OK, name, "added", note=dst.replace(os.path.expanduser("~"), "~", 1)))
    offer(src, ask, install)
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
            miss = [b for b, _ in needs(path)]
            note = "already in tabs.d" if already_in(path) else ""
            if miss:
                note = (note + " · " if note else "") + "needs " + ", ".join(miss)
            print(row(OK if already_in(path) else (DIM + "·" + RST), name, blurb, note=note))
        return 0
    import edit
    items = [(name, blurb + ("  (already in)" if already_in(path) else "")
              + ("  (needs %s)" % ", ".join(b for b, _ in needs(path)) if needs(path) else ""), name)
             for name, (path, blurb) in recipes.items()]
    it = edit.pick("recipes: starter tab bundles", items)
    if not it: return 0
    return add(it[2], recipes[it[2]][0])

if __name__ == "__main__":
    sys.exit(main() or 0)
