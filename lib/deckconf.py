"""The deck's profile, read in one place.

Everything that needs to know which machines exist (fleet, path, gen, setup)
asks here: the profile is the only source of truth, and no host list is
written into the code.
"""
import os

# tomllib is 3.11+. Ubuntu 22.04, Debian 11 and older Raspberry Pi OS ship
# 3.9/3.10, and that's exactly the hardware this project wants to reuse.
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.expanduser("~/.config/phosphor/deck.toml")
EXAMPLE = os.path.join(REPO, "profiles", "example.toml")
ERR  = ""   # why the last load failed

def path():
    p = os.environ.get("PHOSPHOR_PROFILE", CONF)
    if not os.path.exists(p):
        p = EXAMPLE
    return p

def example():
    """True while there's no profile and the repo's example stands in for it."""
    return path() == EXAMPLE

def load():
    """(profile, path). profile is None when there's no parser or it can't be read."""
    global ERR
    p = path()
    if tomllib is None:
        ERR = "no TOML parser: pip install --user tomli"
        return None, p
    try:
        with open(p, "rb") as f:
            return tomllib.load(f), p
    except Exception as e:
        ERR = str(e)
        return None, p

ORDER = {"brain": 0, "work": 1, "desktop": 2, "storage": 3, "node": 4, "viewer": 5}

def hosts(prof):
    """The profile's hosts, brain first, then by role."""
    return sorted((prof or {}).get("hosts", []),
                  key=lambda h: (ORDER.get(h.get("role"), 9), h.get("name", "")))

def target(h):
    """Where ssh goes: user@alias when the profile has a user."""
    t = h.get("ssh") or h.get("ip") or h["name"]
    return "%s@%s" % (h["user"], t) if h.get("user") else t

def fleet_hosts(prof):
    """[(name, ssh target | None for this machine)]: what fleet polls.

    Viewers (phones, tablets) aren't polled. `fleet = false` on a host takes
    it off the panel without taking it out of the deck."""
    out = []
    for h in hosts(prof):
        if h.get("fleet") is False:
            continue
        if h.get("local"):
            out.append((h["name"], None))
        elif h.get("role") != "viewer":
            out.append((h["name"], target(h)))
    return out or [(os.uname().nodename, None)]

def tunnels(prof):
    """[[tunnels]] entries: {"host": ssh alias, optional "config": ssh config file}."""
    return [t for t in (prof or {}).get("tunnels", []) if t.get("host")]

# ── tabs you can share: single-file tab definitions, dropped in ─────
def tabs_d_path():
    return os.environ.get("PHOSPHOR_TABS_D") or os.path.join(os.path.dirname(CONF), "tabs.d")

def tabs_d():
    """[(tab, its file)] from every *.toml in tabs.d, sorted by file name.
    A file that fails to parse is skipped, not fatal to gen."""
    out, d = [], tabs_d_path()
    if tomllib is None or not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".toml"): continue
        p = os.path.join(d, name)
        try:
            with open(p, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue
        for t in data.get("tabs", []):
            if t.get("name"): out.append((t, p))
    return out

def tabs_d_names():
    return {t.get("name"): src for t, src in tabs_d()}

def is_real_tab(t):
    """A tab with its own content, not a stub pointing at tabs.d."""
    return "panes" in t or "split" in t

def pinned_tabs_d(prof):
    """{name} of tabs.d tabs your profile has explicitly placed: a
    [[tabs]] block with just a name, no panes -- `phosphor tabs` moving
    one there for the first time writes exactly this."""
    return {t.get("name") for t in (prof or {}).get("tabs", []) if not is_real_tab(t)}

def effective_tabs(prof):
    """What gen actually builds: the profile's own tabs, in their own
    order, then tabs.d's -- dropped in, not edited by hand, appended in
    file-name order unless a name-only stub in the profile pins one
    somewhere else. A name your profile already gives real content to
    wins: yours over one you were handed."""
    own = list((prof or {}).get("tabs", []))
    shared = {}
    for t, _ in tabs_d():
        shared.setdefault(t.get("name"), t)
    out, placed = [], set()
    for t in own:
        name = t.get("name")
        if not is_real_tab(t) and name in shared:
            out.append(shared[name])       # a stub: this position is tabs.d's tab
        else:
            out.append(t)
        placed.add(name)
    out += [t for name, t in shared.items() if name not in placed]
    return out

# ── the shell and the editor every pane gets ─────────────────
EDITORS = ["nano", "micro", "hx", "nvim", "vim", "emacs", "vi"]
SHELLS  = ["bash", "zsh", "fish", "nu", "sh"]

def data_dir():
    """Where phosphor keeps its data (mentions, work notes, steps). PHOSPHOR_DATA points it
    elsewhere: `phosphor demo` uses that so it never reads or writes the real ones."""
    return os.environ.get("PHOSPHOR_DATA") or os.path.expanduser("~/.local/share/phosphor")

def cache_dir():
    """The same for what's only cached (events, the fleet's readings, the log): PHOSPHOR_CACHE."""
    return os.environ.get("PHOSPHOR_CACHE") or os.path.expanduser("~/.cache/phosphor")

def exe(name):
    """A program's path: ~/.local/bin first (the zellij server's PATH lacks it)."""
    if not name: return None
    name = os.path.expanduser(name)
    if os.sep in name:
        return name if os.access(name, os.X_OK) else None
    local = os.path.expanduser("~/.local/bin/" + name)
    import shutil
    return local if os.access(local, os.X_OK) else shutil.which(name)

def login_shell():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_shell or None
    except Exception as e:
        import dlog
        dlog.event("DECKCONF", "login-shell-failed", str(e)[:60])
        return None

def shell(prof):
    """`shell` in [deck], else your login shell, else bash, else sh."""
    want = ((prof or {}).get("deck") or {}).get("shell")
    for s in (want, login_shell(), "bash", "/bin/sh"):
        p = exe(s)
        if p: return p
    return "/bin/sh"

def editor(prof, ask_login=True):
    """`editor` in [deck], else your $EDITOR, else nano, else vi. Without one,
    programs fall back to vi, which traps people."""
    want = ((prof or {}).get("deck") or {}).get("editor")
    if want: return want
    e = os.environ.get("EDITOR", "")
    if not e and ask_login:
        try:
            import subprocess
            e = subprocess.run(["bash", "-lc", "echo $EDITOR"], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        except Exception as err:
            import dlog
            dlog.event("DECKCONF", "editor-probe-failed", str(err)[:60])
            e = ""
    return e or exe("nano") or "vi"

def installed(names):
    return [n for n in names if exe(n)]

def mount_root(prof):
    return os.path.expanduser(((prof or {}).get("deck") or {}).get("mount_root", "~/fleet"))

def label(m):
    """Folder name of a local disk under mount_root/<host>/: / is root, ~ is
    home, anything else its last component (/mnt/Data2 -> Data2)."""
    m = m.rstrip("/") or "/"
    if m == "/":
        return "root"
    if os.path.expanduser(m) == os.path.expanduser("~"):
        return "home"
    return os.path.basename(os.path.expanduser(m))

def fleet_map(prof):
    """[(prefix under mount_root, host, real path)]: the same map gen mounts
    with, so path translates exactly what yazi shows."""
    out = []
    for h in hosts(prof):
        if h.get("local"):
            for m in h.get("mounts", []):
                out.append(("%s/%s" % (h["name"], label(m)), h["name"], os.path.expanduser(m)))
        elif h.get("mount"):
            out.append((h["name"], h["name"], h["mount"]))
    return out
