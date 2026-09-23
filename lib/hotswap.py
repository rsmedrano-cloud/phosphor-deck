"""phosphor hotswap - after `phosphor update` pulls new code, refresh just
the panes whose own tool changed instead of restarting the whole deck.

Every pane is already its own OS process, and Python only loads a module
into the process that imported it: a pane running `phosphor fleet` keeps
running the *old* lib/fleet.py in memory no matter what's on disk now, but
a pane running btop never cared about lib/fleet.py in the first place. So
"restart everything" is the safe default, not a requirement -- most of the
time only one or two panes actually need a fresh process.

Conservative by design, and it stays that way on purpose (see classify()):
anything that isn't a lib/*.py file nobody else in lib/ imports -- gen.py
(writes config.kdl and the units; zellij itself needs a restart to reread
its own config either way), deckconf.py/ui.py/run.py/tabs.py/dlog.py/
hung.py (shared by enough of the deck that "which panes" stops being a
narrow answer), anything under share/, phosphor or install.sh themselves --
all of it falls back to a real `phosphor restart`. The only thing this
module ever does to a live pane is exactly what lib/edit.py's own Alt-r
"swap the program" (r) already does: `zellij action new-pane --in-place
--close-on-exit`, with that pane's own original argv, on that one pane.
"""
import hashlib, json, os, re, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import REPO
import deckconf

LIB = os.path.join(REPO, "lib")

# Shared enough that a change here can reach panes this module has no way
# to enumerate on its own -- always a real restart, never a guess.
RESTART_TRIGGERS = {"gen", "deckconf", "ui", "run", "tabs", "dlog", "hung", "newtab"}


def file_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return None


def snapshot():
    """{relpath: hash} for every file that could matter to a running pane:
    lib/*.py, share/*, phosphor, install.sh. Call before and after
    `phosphor update` pulls, and diff with changed()."""
    out = {}
    for base in (LIB, os.path.join(REPO, "share")):
        for dirpath, _, files in os.walk(base):
            for f in files:
                full = os.path.join(dirpath, f)
                out[os.path.relpath(full, REPO)] = file_hash(full)
    for f in ("phosphor", "install.sh"):
        full = os.path.join(REPO, f)
        if os.path.exists(full):
            out[f] = file_hash(full)
    return out


def changed(before, after):
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))


def module_of(relpath):
    """"lib/fleet.py" -> "fleet". Anything else (share/*, phosphor,
    install.sh, a non-.py file someone dropped in lib/) -> None, meaning
    "never a leaf, always a restart trigger" to classify()."""
    parts = relpath.split(os.sep)
    if len(parts) == 2 and parts[0] == "lib" and parts[1].endswith(".py"):
        return parts[1][:-3]
    return None


def imported_elsewhere(name):
    """True if some OTHER lib/*.py imports this module -- shared, not a
    leaf: a change to it could reach panes this file alone can't name."""
    pat = re.compile(r"\bimport\s+%s\b|\bfrom\s+%s\b" % (re.escape(name), re.escape(name)))
    for f in os.listdir(LIB):
        if not f.endswith(".py") or f[:-3] == name:
            continue
        try:
            src = open(os.path.join(LIB, f)).read()
        except OSError:
            continue
        if pat.search(src):
            return True
    return False


def classify(changed_paths):
    """({tool names to refresh}, reason for a full restart or None). An
    empty changed_paths is the trivially safe case: nothing to refresh."""
    tools = set()
    for p in changed_paths:
        name = module_of(p)
        if name is None:
            return set(), "%s isn't a lib/ module of its own: needs a real restart" % p
        if name in RESTART_TRIGGERS:
            return set(), "%s.py is shared code, not one tool's own: needs a real restart" % name
        if imported_elsewhere(name):
            return set(), "%s.py is imported elsewhere too: needs a real restart" % name
        tools.add(name)
    return tools, None


# ---- the live session: which panes run an affected tool, and swapping them --------

def zellij_bin():
    return deckconf.exe("zellij")


def pane_procs(session, pane_id):
    """The processes of one pane of `session` -- by environment, not by
    the calling process's own (this may run detached, outside any pane)."""
    want = [("ZELLIJ_PANE_ID=%d" % pane_id).encode(), ("ZELLIJ_SESSION_NAME=%s" % session).encode()]
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            env = open("/proc/%s/environ" % d, "rb").read().split(b"\0")
        except OSError:
            continue
        if all(w in env for w in want):
            out.append(int(d))
    return out


def argv_of(session, pane_id):
    """The command line a pane was started with, from its outermost
    process (lib/edit.py's own argv_of, session-explicit)."""
    procs = pane_procs(session, pane_id)
    for p in procs:
        try:
            ppid = int(open("/proc/%d/stat" % p).read().rsplit(")", 1)[1].split()[1])
            if ppid not in procs:
                return [a for a in open("/proc/%d/cmdline" % p).read().split("\0") if a]
        except (OSError, ValueError, IndexError):
            continue
    return None


def tool_of_argv(argv):
    """If this is `phosphor run ... -- ... phosphor TOOLNAME ...`, TOOLNAME
    -- else None (a shell, btop, an ssh pane, anything phosphor run isn't
    itself wrapping another `phosphor` invocation around)."""
    if not argv or "run" not in argv:
        return None
    try:
        dash = argv.index("--")
    except ValueError:
        return None
    tail = argv[dash + 1:]
    for i, a in enumerate(tail):
        if os.path.basename(a) == "phosphor" and i + 1 < len(tail):
            return tail[i + 1]
    return None


def live_panes(session):
    """[(pane_id, argv)] for this session's real panes (not plugins,
    zellij's own UI), each with the argv it was actually started with."""
    zj = zellij_bin()
    if not zj:
        return []
    try:
        out = subprocess.run([zj, "-s", session, "action", "list-panes", "-a", "-j"],
                             capture_output=True, text=True, timeout=15).stdout
        panes = json.loads(out or "[]")
    except (ValueError, subprocess.SubprocessError, OSError):
        return []
    out = []
    for p in panes:
        if p.get("is_plugin"):
            continue
        argv = argv_of(session, p["id"])
        if argv:
            out.append((p["id"], argv))
    return out


def affected_panes(session, tools):
    """(pane_id, argv) for every live pane running one of `tools`."""
    return [(pid, argv) for pid, argv in live_panes(session) if tool_of_argv(argv) in tools]


def swap(session, pane_id, argv):
    """Replace this pane's content in place with the same argv it already
    had -- a fresh process, fresh code, nothing else in the tab or session
    touched. The exact mechanism lib/edit.py's own Alt-r "swap the
    program" (r) already uses, reused here instead of duplicated."""
    zj = zellij_bin()
    old = pane_procs(session, pane_id)
    subprocess.run([zj, "-s", session, "action", "new-pane", "--in-place",
                    "--pane-id", "terminal_%d" % pane_id, "--close-on-exit", "--"] + argv,
                   capture_output=True, timeout=15)
    time.sleep(0.5)
    for p in old:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass


def apply(session, before, after):
    """The whole thing, called once after `phosphor update` pulls: classify
    what changed, and if it's leaf-only, swap every affected live pane in
    place. Returns (swapped: [(pane_id, tool)], reason: str or None -- a
    reason means nothing was touched and a real restart is still needed)."""
    diff = changed(before, after)
    if not diff:
        return [], None
    tools, reason = classify(diff)
    if reason:
        return [], reason
    panes = affected_panes(session, tools)
    swapped = []
    for pid, argv in panes:
        tool = tool_of_argv(argv)
        swap(session, pid, argv)
        swapped.append((pid, tool))
    return swapped, None
