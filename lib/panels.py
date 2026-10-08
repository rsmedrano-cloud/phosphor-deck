#!/usr/bin/env python3
"""phosphor panels - your own panels, from ~/.config/phosphor/panels.d.

A panel is one Python file (override the folder: PHOSPHOR_PANELS) with a
class built on phosphor's ListPanel: the same keys, taps, y/n questions and
pager as every panel in the deck. The file's name is the panel's name, its
docstring's first line says what it is:

    # ~/.config/phosphor/panels.d/backups.py
    \"\"\"restic snapshots on the NAS\"\"\"
    import json, proc, tui

    class Backups(tui.ListPanel):
        TITLE, INTERVAL = "BACKUPS", 60
        KEYS = [("enter", "files"), ("q", "quit")]
        def fetch(self):
            rc, out = proc.sh("restic snapshots --json", t=30)
            if rc: self.problem = out or "restic failed"; return []
            return json.loads(out)
        def lines(self, w, sel):
            return [(tui.INV if i == sel else "") + " %s  %s" % (s["time"][:16], s["hostname"]) + tui.RST
                    for i, s in enumerate(self.rows)]
        def act(self, k, row):
            self.page(proc.sh("restic ls %s" % row["short_id"], t=60)[1])

It runs your code, like a cmd in apps.toml: nothing else is imported from
the folder, and a file that breaks says so instead of taking the deck down.

    phosphor panels            # which panels there are (--json for scripts)
    phosphor panels NAME       # open one here
"""
import importlib.util, os, re, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf, tui
from ui import AMB, DIM, FG, RED, RST, emit

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def folder():
    return os.environ.get("PHOSPHOR_PANELS") or os.path.join(os.path.dirname(deckconf.CONF), "panels.d")


def found():
    """[(name, path)] of every panel file, by name. Files starting with _
    (a helper they share) and names that aren't one word are left out."""
    d = folder()
    try:
        fs = sorted(os.listdir(d))
    except OSError:
        return []
    return [(f[:-3], os.path.join(d, f)) for f in fs
            if f.endswith(".py") and not f.startswith("_") and NAME.match(f[:-3])]


def desc(path):
    """The docstring's first line, read without running the file."""
    import ast
    try:
        doc = ast.get_docstring(ast.parse(open(path).read()))
    except (OSError, SyntaxError, ValueError):
        return ""
    return (doc or "").strip().split("\n")[0]


def load(path):
    """(the panel's class, None) or (None, why not). Runs the file."""
    name = os.path.basename(path)[:-3]
    spec = importlib.util.spec_from_file_location("phosphor_panel_" + name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        last = traceback.format_exc().strip().splitlines()
        return None, "%s.py doesn't load: %s" % (name, last[-1] if last else "?")
    own = [c for c in vars(mod).values() if isinstance(c, type) and issubclass(c, tui.ListPanel)
           and c.__module__ == mod.__name__]
    if len(own) != 1:
        return None, "%s.py needs one class built on tui.ListPanel (it has %d)" % (name, len(own))
    return guarded(own[0]), None


def guarded(cls):
    """The panel, with its own code's errors on screen instead of a
    traceback that ends the pane: a fetch that raises shows as the
    problem, an action that raises as a line under the keys."""
    class Guarded(cls):
        def fetch(self):
            try:
                return super().fetch()
            except Exception as e:
                self.problem = "fetch: %s: %s" % (e.__class__.__name__, e)
                return []

        def act(self, k, row):
            try:
                return super().act(k, row)
            except Exception as e:
                self.say("%s: %s: %s" % (k, e.__class__.__name__, e), RED)

        def confirm(self, prompt, do, note=""):
            def safe():
                try:
                    return do()
                except Exception as e:
                    return False, "%s: %s" % (e.__class__.__name__, e)
            return super().confirm(prompt, safe, note)
    Guarded.__name__ = cls.__name__
    return Guarded


def listing():
    return [{"name": n, "desc": desc(p), "file": p} for n, p in found()]


def main():
    args = sys.argv[1:]
    if "--json" in args:
        return emit({"folder": folder(), "panels": listing()})
    names = [a for a in args if not a.startswith("-")]
    if not names:
        ps = listing()
        if not ps:
            print("  no panels yet: put one in %s (phosphor help profile, \"panels.d\")"
                  % folder().replace(os.path.expanduser("~"), "~", 1))
            return 0
        w = max(len(p["name"]) for p in ps)
        for p in ps:
            print("  " + AMB + p["name"].ljust(w) + RST + "  " + FG + p["desc"] + RST)
        print(DIM + "  phosphor panels NAME opens one" + RST)
        return 0
    path = dict(found()).get(names[0])
    if not path:
        print("  no panel %s in %s" % (names[0], folder().replace(os.path.expanduser("~"), "~", 1)))
        return 1
    cls, why = load(path)
    if why:
        print("  " + RED + why + RST)
        return 1
    if not sys.stdout.isatty():
        print("  %s is a panel: open it in a terminal" % names[0])
        return 1
    return cls().run()


if __name__ == "__main__":
    sys.exit(main())
