"""Your own apps, and opening any app in a tab of its own.

~/.config/phosphor/apps.toml (override: PHOSPHOR_APPS) lists programs the
store's catalog doesn't have. They show in the store as "yours" and in the
+ menu, and like any installed app they open in a new tab with one key:

    [[apps]]
    name = "lazygit"             # its name in the store and the + menu
    cmd  = "lazygit"             # the program (a name in PATH or a path)
    args = []                    # optional
    desc = "git in a TUI"        # optional
    alt  = false                 # optional: start on the alternate screen
    needs_size = false           # optional: wait a second for the pane's size
"""
import os, re, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf

HOME = os.path.expanduser("~")
BIN = os.path.join(HOME, ".local/bin")

def path():
    return os.environ.get("PHOSPHOR_APPS") or os.path.join(os.path.dirname(deckconf.CONF), "apps.toml")

def have(b):
    """Not just PATH: the zellij server doesn't include ~/.local/bin."""
    if not b: return None
    if os.sep in b:
        b = os.path.expanduser(b)
        return b if os.path.isfile(b) and os.access(b, os.X_OK) else None
    p = os.path.join(BIN, b)
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else shutil.which(b)

def yours():
    """(apps in the store's shape, a problem to show or None)."""
    p = path()
    if not os.path.exists(p):
        return [], None
    if deckconf.tomllib is None:
        return [], "apps.toml needs Python 3.11+ (or tomli)"
    try:
        data = deckconf.tomllib.loads(open(p).read())
    except Exception as e:
        return [], "apps.toml doesn't parse: %s" % str(e)[:60]
    out, bad = [], []
    for i, a in enumerate(data.get("apps", [])):
        name, cmd = str(a.get("name", "")).strip(), str(a.get("cmd", "")).strip()
        args = a.get("args", [])
        if not name or not cmd or not isinstance(args, list):
            bad.append(str(i + 1)); continue
        out.append({"n": name, "c": "yours", "d": str(a.get("desc", "")) or " ".join([cmd] + args),
                    "cmd": cmd, "args": [str(x) for x in args],
                    "alt": bool(a.get("alt")), "needs_size": bool(a.get("needs_size")), "yours": True})
    return out, ("apps.toml: entry %s needs a name and a cmd" % ", ".join(bad)) if bad else None

def exe(app):
    """The program an app runs: yours name it, the catalog's is its binary."""
    return app["cmd"] if app.get("yours") else app.get("b", app["n"])

def spec(app):
    """The app as a profile pane spec (what gen and keep understand)."""
    s = {"cmd": exe(app)}
    if app.get("args"): s["args"] = app["args"]
    if app.get("alt"): s["alt"] = True
    if app.get("needs_size"): s["needs_size"] = True
    return s

def tab_name(app):
    return re.sub(r"[^A-Z0-9]+", "", app["n"].upper())[:10] or "APP"

def open_tab(app):
    """A new tab running it, next to the one you're in. A message either way."""
    if not os.environ.get("ZELLIJ"):
        return False, "open it from inside the deck"
    if not have(exe(app)):
        return False, "%s isn't installed" % exe(app)
    import gen, newtab
    prof, _ = deckconf.load()
    name = newtab.unique(tab_name(app), newtab.taken_names())
    d = os.path.expanduser("~/.cache/phosphor/apps")
    os.makedirs(d, exist_ok=True)
    lay = os.path.join(d, "%s-%s.kdl" % (name.lower(), time.strftime("%Y%m%d-%H%M%S")))
    with open(lay, "w") as f:
        f.write(gen.tab_kdl({"name": name, "panes": [spec(app)]}, gen.Ctx(prof or {}), "phosphor store"))
    newtab.zj("new-tab", "--layout", lay, "--name", name)
    return True, "opened %s in a new tab" % name
