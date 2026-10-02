"""phosphor new - what a new tab opens: a small touch menu.

The tab bar's "+" (and zellij's own new-tab) run it through the layout's
new_tab_template. Pick a shell here, a shell on a fleet machine, an installed
assistant, one of your own apps (apps.toml), files, or any command. This process then becomes it (exec), so
when it exits the tab closes. "keep" also writes the tab into the profile,
so it comes back after restarts.
"""
import json, os, select, shutil, subprocess, sys, termios, time, tty
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
from ui import getkey as ui_getkey
import deckconf, apps

HOME = os.path.expanduser("~")
BIN  = os.path.join(HOME, ".local/bin")
PHOSPHOR = os.path.join(REPO, "phosphor")
# Assistant CLIs offered when installed: (binary, label).
ASSISTANTS = [("claude", "Claude Code"), ("aichat", "aichat"), ("gemini", "Gemini CLI"),
              ("codex", "Codex"), ("opencode", "opencode"), ("aider", "Aider"), ("agy", "Antigravity")]
INV = "\x1b[7m"

def have(b):
    p = os.path.join(BIN, b)
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else shutil.which(b)

ZJ = have("zellij") or "zellij"

def zj(*a):
    try:
        return subprocess.run([ZJ, "action"] + list(a), capture_output=True, text=True, timeout=8).stdout
    except Exception:
        import dlog
        dlog.event("NEWTAB", "zj-failed")   # never str(e): it quotes the command, home path included
        return ""

def entries(prof):
    """[(label, note, tab name, argv, profile pane spec)]"""
    sh = deckconf.shell(prof)
    me = next((h["name"] for h in (prof or {}).get("hosts", []) if h.get("local")), os.uname().nodename)
    out = [("shell", me, "SHELL", [sh, "-l"], {})]
    for name, tgt in deckconf.fleet_hosts(prof):
        if tgt:
            out.append(("shell", name, name.upper(), ["ssh", "-t", tgt], {"ssh": tgt}))
    for b, label in ASSISTANTS:
        if have(b):
            # a login shell: these CLIs usually live in a PATH only rc files set
            out.append((label, "assistant", b.upper(), ["bash", "-lc", "exec " + b],
                        {"cmd": "bash", "args": ["-lc", "exec " + b]}))
    for a in apps.yours()[0]:
        p = apps.have(a["cmd"])
        if p:
            out.append((a["n"], "yours", apps.tab_name(a), [p] + a["args"], apps.spec(a)))
    if have("matterhorn") or os.path.exists(os.path.join(deckconf.data_dir(), "mentions.jsonl")):
        out.append(("mentions", "read-only feed", "MENTIONS", [sys.executable, PHOSPHOR, "mentions"],
                    {"cmd": "phosphor mentions"}))
    if os.path.exists(os.path.join(deckconf.data_dir(), "work.md")):
        out.append(("work notes", "prepared notes", "WORK", [sys.executable, PHOSPHOR, "notes", "--book", "work"],
                    {"cmd": "phosphor notes", "args": ["--book", "work"]}))
    import tunnels
    if tunnels.ssh_config_forwards() or deckconf.tunnels(prof):
        out.append(("tunnels", "ssh forwards", "TUNNELS", [sys.executable, PHOSPHOR, "tunnel"],
                    {"cmd": "phosphor tunnel"}))
    if (prof or {}).get("prometheus"):
        out.append(("prometheus", "prometheus gauges", "PROM", [sys.executable, PHOSPHOR, "prom"],
                    {"cmd": "phosphor prom"}))
    if (prof or {}).get("ci"):
        out.append(("ci", "CI/CD pipelines status", "CI", [sys.executable, PHOSPHOR, "ci"],
                    {"cmd": "phosphor ci"}))
    out.append(("services", "systemd units and their state", "SERVICES", [sys.executable, PHOSPHOR, "services"],
                {"cmd": "phosphor services"}))
    if deckconf.exe("glab") or deckconf.exe("gh"):
        out.append(("review", "merge/pull requests", "REVIEW", [sys.executable, PHOSPHOR, "review"],
                    {"cmd": "phosphor review"}))
    if any(have(b) for b in ("claude", "gemini", "codex", "opencode")):
        out.append(("workspace", "a project folder with assistants", "WORKSPACE",
                    [sys.executable, PHOSPHOR, "workspace", "new", "--pause-on-error"], None))
    out.append(("layout", "several panes at once", "LAYOUT", [], None))
    y = have("yazi")
    if y:
        root = deckconf.mount_root(prof)
        out.append(("files", root.replace(HOME, "~", 1), "FILES", [y, root],
                    {"cmd": "yazi", "args": ["@mount_root"], "needs_size": True}))
    return out

HINT_SHOWS = 20     # opens of the + menu with the deck's keys at its foot; then it's learned

def hint(prof):
    """One line of the deck's own keys (as [keys] has them) for someone
    who's never seen it, the first HINT_SHOWS times the menu opens; after
    that, None. The DECK tab keeps the whole list."""
    p = os.path.join(deckconf.data_dir(), "hint-shown")
    try:
        n = int(open(p).read().strip() or 0)
    except (OSError, ValueError):
        n = 0
    if n >= HINT_SHOWS: return None
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(str(n + 1))
    except OSError:
        pass
    import shortcuts
    k = shortcuts.current(prof)
    parts = [(k["edit"], "edit tab"), (k["note"], "note"), (k["zoom"], "zoom"),
             (k["tabs"] + " 1-9" if k["tabs"] else "", "tabs"), (k["leave"], "leave")]
    return "  ".join("%s %s" % (shortcuts.dash(key), what) for key, what in parts if key)

def getkey():
    """A key, ("CLICK", row) for a tap/left click, or None for other mouse events."""
    k = ui_getkey(None)
    if isinstance(k, tuple):
        return ("CLICK", k[3]) if k[1] == 0 and k[4] else None
    return k

def render(its, sel, keep, w, msg=None, tip=None):
    """Lines plus what each screen row does: an entry index, "cmd", "keep" or None."""
    rows, acts = [], []
    def add(text, act=None): rows.append(text); acts.append(act)
    for l in topbar("NEW TAB", "tap one, or press its number", "", w): add(l)
    for i, (label, note, *_rest) in enumerate(its):
        num = str(i + 1) if i < 9 else " "
        line = " %s  %-14s %s" % (num, label[:14], note)
        add((INV + pad(line, w - 1) + RST) if i == sel else
            (" " + AMB + num + RST + "  " + FG + "%-14s" % label[:14] + RST + " " + DIM + note + RST), i)
    n = len(its)
    line = " +  a command..."
    add((INV + pad(line, w - 1) + RST) if sel == n else (" " + AMB + "+" + RST + "  " + FG + "a command..." + RST), "cmd")
    line = " /  search everything..."
    add((INV + pad(line, w - 1) + RST) if sel == n + 1 else
        (" " + AMB + "/" + RST + "  " + FG + "search everything..." + RST + DIM + "  tabs, workspaces, tools, commands" + RST), "search")
    add("")
    box = "[x]" if keep else "[ ]"
    line = " %s keep this tab after restarts" % box
    add((INV + pad(line, w - 1) + RST) if sel == n + 2 else
        (" " + (PH if keep else DIM) + box + RST + " " + MUTE + "keep this tab after restarts" + RST), "keep")
    add("")
    if msg: add(" " + WARN + " " + msg)
    add(" " + AMB + "x" + RST + "  " + FG + "close this tab" + RST + DIM + "  q / Esc" + RST, "close")   # a tap: no keyboard needed
    if tip: add(" " + MUTE + tip[:max(0, w - 2)] + RST)
    return rows, acts

def open_tabs():
    """[(tab id, name)] of the session, in order."""
    out = []
    for l in zj("list-tabs").splitlines()[1:]:
        f = l.split(None, 2)
        if len(f) == 3: out.append((f[0], f[2].strip()))
    return out

def taken_names():
    return {name for _, name in open_tabs()}

def unique(name, names):
    if name not in names: return name
    i = 2
    while "%s%d" % (name, i) in names: i += 1
    return "%s%d" % (name, i)

def my_tab_id():
    pid = "terminal_%s" % os.environ.get("ZELLIJ_PANE_ID", "")
    for l in zj("list-panes", "-t").splitlines()[1:]:
        f = l.split()
        if pid in f: return f[0]
    return None

def toml(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, list): return "[" + ", ".join(toml(x) for x in v) + "]"
    return json.dumps(v)            # a JSON string is a valid TOML basic string

def keep_tab(name, spec):
    """Append the tab to the profile, check it parses, then regenerate."""
    p = os.environ.get("PHOSPHOR_PROFILE", deckconf.CONF)   # never the repo's example
    if not os.path.exists(p) or deckconf.tomllib is None:
        return "no profile to write to"
    text = open(p).read()
    have_names = {t.get("name") for t in deckconf.tomllib.loads(text).get("tabs", [])}
    name = unique(name, have_names)
    if "ssh" not in spec and os.getcwd() != HOME:
        spec = dict(spec, cwd=os.getcwd().replace(HOME, "~", 1))
    pane = "{ " + ", ".join("%s = %s" % (k, toml(v)) for k, v in spec.items()) + " }" if spec else "{}"
    block = "\n[[tabs]]\nname  = %s\npanes = [ %s ]\n" % (json.dumps(name), pane)
    new = text.rstrip("\n") + "\n" + block
    try:
        ok = any(t.get("name") == name for t in deckconf.tomllib.loads(new).get("tabs", []))
    except Exception:
        ok = False
    if not ok:
        return "the profile wouldn't parse, left it alone"
    deckconf.backup(p, text)
    open(p, "w").write(new)
    subprocess.run([sys.executable, PHOSPHOR, "gen"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None

def launch(name, argv, spec, keep):
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
    if os.environ.get("ZELLIJ_PANE_ID"):
        name = unique(name, taken_names())
        tid = my_tab_id()
        if tid is not None: zj("rename-tab-by-id", tid, name)
        else: zj("rename-tab", name)
    if keep:
        err = keep_tab(name, spec)
        print(("  " + WARN + " not kept: " + err) if err else ("  " + OK + " kept in your profile as " + name))
    # through `phosphor run`: when it ends, the tab asks before closing
    opts = ["--name", name] + (["--reconnect"] if argv[0] == "ssh" else []) \
        + (["--wait", "1"] if spec.get("needs_size") else []) + (["--alt"] if spec.get("alt") else [])
    os.execv(sys.executable, [sys.executable, PHOSPHOR, "run"] + opts + ["--"] + argv)

# What `/` in the + menu searches, in this order when two match as well.
KINDS = ("tab", "entry", "workspace", "app", "command")

def search_items(prof, its):
    """Everything `/` can find: [(label, note, kind, payload)]. Open tabs
    (not this one), the menu's own entries, workspaces without an open tab,
    installed tools the menu doesn't already list, then every command."""
    import commands, workspace
    out, mine = [], my_tab_id() if os.environ.get("ZELLIJ_PANE_ID") else None
    tabs = open_tabs() if os.environ.get("ZELLIJ") else []
    for tid, name in tabs:
        if tid != mine:
            out.append((name, "open tab: go there", "tab", name))
    for i, (label, note, *_r) in enumerate(its):
        out.append((label, note, "entry", i))
    import tabs as tabs_
    open_names = {tabs_.bare(n) for _, n in tabs}
    for w in workspace.names():
        if w.upper() not in open_names:
            out.append((w, "workspace: open its tab", "workspace", w))
    listed = {a[3][0] for a in its if a[3]} | {os.path.basename(a[3][0]) for a in its if a[3]}
    try:
        catalog = json.load(open(share("store.json")))
    except (OSError, ValueError):
        catalog = []
    for a in catalog:
        if a.get("action"): continue                  # a voice or a model, not a program
        p = apps.have(apps.exe(a))
        if p and p not in listed and os.path.basename(p) not in listed:
            out.append((a["n"], "installed: " + a.get("d", ""), "app", a))
    for _cat, cmds in commands.CATEGORIES:
        for cmd, usage, note in cmds:
            out.append((cmd, "command: " + note, "command", (cmd, usage, note)))
    return out

def find(items, q):
    """Items whose label or note has every word of q (case-insensitive):
    the label equal to q first, then starting with it, then containing it,
    then only the note; KINDS order within each."""
    words = q.lower().split()
    if not words: return list(items)
    q = " ".join(words)
    def rank(it):
        l = it[0].lower()
        return (0 if l == q else 1 if l.startswith(q) else 2 if q in l else 3, KINDS.index(it[2]))
    return sorted([it for it in items if all(w in (it[0] + " " + it[1]).lower() for w in words)], key=rank)

def search(items, rows, cols, q=""):
    """Type to narrow, arrows or a tap to pick, Enter takes it. The item, or
    None for Esc."""
    sel, top = 0, 0
    while True:
        found = find(items, q)
        sel = max(0, min(sel, len(found) - 1))
        w = min(cols, 80)
        room = max(3, rows - 5)
        top = min(max(top, sel - room + 1), sel)
        lines = [BLOOM + " SEARCH" + RST + DIM + "   tabs, the menu, workspaces, tools, commands" + RST,
                 " " + AMB + "/" + RST + FG + q + RST + DIM + "_" + RST,
                 RULE + " " + "─" * max(0, w - 2) + RST]
        shown = found[top:top + room]
        for i, (label, note, *_r) in enumerate(shown, top):
            line = " %-16s %s" % (label[:16], note)
            lines.append((INV + pad(line[:w - 1], w - 1) + RST) if i == sel else
                         (" " + FG + "%-16s" % label[:16] + RST + " " + DIM + note[:max(0, w - 19)] + RST))
        if not found:
            lines.append(" " + DIM + "nothing matches: Backspace, or Esc to go back" + RST)
        lines += [""] * max(0, rows - 1 - len(lines))
        lines.append(DIM + " type to search · ↑↓ or tap · Enter opens it · Esc back" + RST)
        sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines[:rows]) + "\x1b[K\x1b[J"); sys.stdout.flush()
        k = ui_getkey(None, text=True)
        if isinstance(k, tuple):
            if not k[4] or k[1] not in (0, 64, 65): continue
            if k[1] == 64: sel = max(0, sel - 3); continue          # wheel / touch scroll
            if k[1] == 65: sel = min(len(found) - 1, sel + 3); continue
            r = k[3] - 4
            if 0 <= r < len(shown): return shown[r]
            continue
        if k is None: continue
        if k in ("\x1b", "\x03"): return None
        if k in ("\r", "\n"):
            if found: return found[sel]
        elif k == "\x1b[B": sel += 1
        elif k == "\x1b[A": sel = max(0, sel - 1)
        elif k in ("\x7f", "\x08"): q, sel = q[:-1], 0
        elif k == "\x15": q, sel = "", 0                          # Ctrl-u
        elif k[0] >= " " and not k.startswith("\x1b"): q, sel = q + k, 0

def run_command(cmd, usage, note, keep):
    """A command found by `/`: a read-only one, or one that asks for what it
    needs, runs in this tab; anything else shows its usage (commands.detail)
    and comes back. False when it came back."""
    import commands
    man = commands.manifest()
    if (man.get(cmd) or {}).get("mutates") is False or cmd in commands.ASKS:
        launch(cmd.upper()[:10], [sys.executable, PHOSPHOR, cmd], {"cmd": "phosphor " + cmd}, keep)
    commands.detail(cmd, usage, note, man)
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    return False

def open_workspace(name):
    """Its tab, from the layout gen wrote; False (and why) when there's none."""
    import workspace
    lay = os.path.expanduser("~/.config/zellij/layouts/tab-%s.kdl" % name.upper().lower())
    if not os.path.exists(lay):
        return "no layout for %s yet: phosphor gen" % name.upper()
    workspace.open_tab(name)
    return None

def ask_command(rows, prompt="command: "):
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[%d;1H\x1b[K " % rows + AMB + prompt + RST)
    sys.stdout.flush()
    try:
        text = sys.stdin.readline().strip()
    except KeyboardInterrupt:
        text = ""
    sys.stdout.write("\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    return text

RECENT = 8      # folders typed by hand that "where?" offers again

def recent_path():
    return os.path.join(deckconf.data_dir(), "folders")

def recent():
    try:
        return [l for l in open(recent_path()).read().splitlines() if os.path.isdir(os.path.expanduser(l))]
    except OSError:
        return []

def remember(path):
    """Put a folder typed by hand first in the recent list (deduped, capped)."""
    t = path.replace(HOME, "~", 1) if path == HOME or path.startswith(HOME + "/") else path
    keep = [t] + [l for l in recent() if l != t]
    try:
        os.makedirs(os.path.dirname(recent_path()), exist_ok=True)
        open(recent_path(), "w").write("\n".join(keep[:RECENT]) + "\n")
    except OSError:
        pass

def resolve(text, cwd):
    """A typed folder: ~ and relative paths work. None if it isn't a folder."""
    p = os.path.normpath(os.path.join(cwd, os.path.expanduser(text.strip())))
    return p if text.strip() and os.path.isdir(p) else None

def places(cwd, prof):
    """Where an assistant can start: [(label, note, path)] -- here first, then
    the projects folder's own folders (workspaces say so), then folders typed
    before. No path twice."""
    import workspace
    tilde = workspace.tilde
    out, seen = [("here", tilde(cwd), cwd)], {cwd}
    root = workspace.root(prof)
    try:
        subs = sorted(n for n in os.listdir(root) if not n.startswith(".") and os.path.isdir(os.path.join(root, n)))
    except OSError:
        subs = []
    for n in subs:
        p = os.path.join(root, n)
        ws = os.path.isfile(os.path.join(p, "NOTES.md"))
        out.append((n, ("workspace  " if ws else "") + tilde(p), p)); seen.add(p)
    for t in recent():
        p = os.path.expanduser(t)
        if p not in seen:
            out.append((os.path.basename(p) or p, t, p)); seen.add(p)
    return out

def where(label, prof, rows):
    """Pick the folder an assistant starts in. The path, or None for back."""
    import edit
    cwd = os.getcwd()
    while True:
        it = edit.pick("%s: which folder?" % label, places(cwd, prof), [("/", "another folder...")])
        if it is None: return None
        if it != "/": return it[2]
        text = ask_command(rows, "folder: ")
        if not text: continue
        p = resolve(text, cwd)
        if p:
            remember(p); return p
        sys.stdout.write("\x1b[%d;1H\x1b[K " % rows + WARN + " not a folder: " + text); sys.stdout.flush()
        time.sleep(1.5)

def review_folder(prof, rows):
    """The repo phosphor review opens on: this folder if its remote is GitLab
    or GitHub, else one picked like an assistant's. None for back."""
    import review
    cwd = os.getcwd()
    if review.provider():
        return cwd
    while True:
        p = where("review", prof, rows)
        if p is None: return None
        try:
            os.chdir(p); ok = review.provider()
        finally:
            os.chdir(cwd)
        if ok: return p
        sys.stdout.write("\x1b[%d;1H\x1b[K " % rows + WARN + " no GitLab or GitHub remote in " + p.replace(HOME, "~", 1))
        sys.stdout.flush(); time.sleep(1.5)

# (label, picture, slots, how the slots make a tab)
SHAPES = [
    ("2 columns", "▌▐", 2, lambda s: {"split": "cols", "panes": s}),
    ("2 rows",    "▀▄", 2, lambda s: {"split": "rows", "panes": s}),
    ("2 × 2",     "▚▞", 4, lambda s: {"split": "cols", "panes": [{"split": "rows", "panes": s[:2]},
                                                                  {"split": "rows", "panes": s[2:]}]}),
    ("3 columns", "▌█▐", 3, lambda s: {"split": "cols", "panes": s}),
]

def layout(prof, keep):
    """Pick a shape, then what goes in each slot; opens the tab. None if backed out."""
    import edit, gen
    shape = edit.pick("which shape?", [(label, pic) for label, pic, _, _ in SHAPES])
    if not shape: return None
    label, _, n, make = next(s for s in SHAPES if s[0] == shape[0])
    items, slots, names = edit.options(), [], []
    while len(slots) < n:
        extra = [("=", "the same in the rest")] if slots else []
        it = edit.pick("%s · pane %d of %d: what goes here?" % (label, len(slots) + 1, n), items, extra)
        if it is None: return None
        if it == "=":
            slots += [slots[-1]] * (n - len(slots)); names += [names[-1]] * (n - len(names)); break
        slots.append({k: v for k, v in it[4].items()}); names.append(it[2])
    name = unique(names[0] if len(set(names)) == 1 else "LAYOUT", taken_names())
    tab = dict(make(slots), name=name)
    if keep:
        import keep as k
        blk = k.block(name, tab["panes"], tab["split"])
        if k.save(name, blk):
            subprocess.run([sys.executable, PHOSPHOR, "gen"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    d = os.path.join(deckconf.cache_dir(), "layouts")
    os.makedirs(d, exist_ok=True)
    lay = os.path.join(d, "%s.kdl" % name.lower())
    with open(lay, "w") as f:
        f.write(gen.tab_kdl(tab, gen.Ctx(prof or {}), "phosphor new (layout)"))
    zj("new-tab", "--layout", lay, "--name", name)
    return name

def attached():
    """False only when we can positively confirm nobody's attached to this
    session (list-clients ran fine and named none): if the check itself
    fails, don't block a real Alt-n press on it. A real keypress -- Alt-n,
    or a tap on the tab bar's + -- already proves a client is attached; this
    guards the one path that doesn't, `--here` called out of band (a script,
    an assistant), which is exactly the "zellij action new-tab with no
    client attached" case AGENTS.md warns against."""
    try:
        r = subprocess.run([ZJ, "action", "list-clients"], capture_output=True, text=True, timeout=8)
    except Exception:
        return True
    if r.returncode != 0:
        return True
    return len([l for l in r.stdout.splitlines() if l.strip()]) > 1     # header + at least one client

def here():
    """Alt-n: a new tab in the folder of the pane you're in. It runs in place
    over that pane for a moment, reads where its foreground program is (your
    shell after a cd) and opens the menu there."""
    if not os.environ.get("ZELLIJ"):
        # No pane context at all: without $ZELLIJ_SESSION_NAME to pin it down,
        # `zellij action` falls back to "the only session running" -- which,
        # on a real box, is someone's live deck. Refuse outright rather than
        # let that implicit default decide.
        print("  --here only makes sense run from inside a pane of the deck"); return 1
    if not attached():
        print("phosphor new --here: nobody's attached to this session, refusing to add a tab.")
        return 1
    import edit
    at = edit.where_am_i()
    cwd = None
    if at and at[3] is not None:
        for p in sorted(edit.pane_procs(at[3]), reverse=True):     # the newest first
            try:
                f = open("/proc/%d/stat" % p).read().rsplit(")", 1)[1].split()
                if f[2] == f[5]:                                   # its group owns the terminal
                    cwd = os.readlink("/proc/%d/cwd" % p); break
            except (OSError, IndexError):
                continue
    zj("new-tab", *(["--cwd", cwd] if cwd else []))
    return 0

def main():
    if "--here" in sys.argv[1:]:
        return here()
    prof, _ = deckconf.load()
    its = entries(prof)
    if not sys.stdin.isatty():
        for label, note, name, argv, _s in its: print("%-14s %-16s %s" % (label, note, " ".join(argv)))
        return 0
    sel, keep, n, items, msg, tip = 0, False, len(its), None, None, hint(prof)
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((60, 20))
            w = min(cols, 80)
            lines, acts = render(its, sel, keep, w, msg, tip)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines[:rows]) + "\x1b[K\x1b[J"); sys.stdout.flush()
            k = getkey()
            act = None
            if isinstance(k, tuple):
                r = k[1] - 1
                act = acts[r] if 0 <= r < len(acts) else None
                if act is None: continue
            elif k in ("q", "x", "\x1b", "\x03"):
                return 0
            elif k in ("j", "\x1b[B"): sel = min(n + 2, sel + 1); continue
            elif k in ("k", "\x1b[A"): sel = max(0, sel - 1); continue
            elif k and k.isdigit() and 0 < int(k) <= min(9, n): act = int(k) - 1
            elif k == "/": act = "search"
            elif k in ("\r", "\n", " "): act = sel if sel < n else ("cmd", "search", "keep")[sel - n]
            else: continue
            if act == "close":
                return 0
            if act == "keep":
                keep = not keep; continue
            if act == "search":
                if items is None: items = search_items(prof, its)
                it = search(items, rows, cols)
                if it is None: continue
                label, note, kind, what = it
                if kind == "tab":
                    zj("go-to-tab-name", what); return 0        # there: this menu's tab closes
                if kind == "workspace":
                    err = open_workspace(what)
                    if err is None: return 0
                    msg = err; continue
                if kind == "app":
                    p = apps.have(apps.exe(what))
                    launch(apps.tab_name(what), [p] + what.get("args", []), apps.spec(what), keep)
                if kind == "command":
                    run_command(*what, keep); continue
                act = what                                      # one of the menu's own entries
            if act == "cmd":
                text = ask_command(rows)
                if text:
                    word = os.path.basename(text.split()[0]).upper()[:10] or "CMD"
                    launch(word, ["bash", "-lc", text], {"cmd": "bash", "args": ["-lc", text]}, keep)
                continue
            label, note, name, argv, spec = its[act]
            if label == "layout":
                if layout(prof, keep):
                    return 0                  # the new tab is open: this menu's tab closes
                sys.stdout.write("\x1b[?1000h\x1b[?1006h"); continue
            if spec is None:                  # a wizard, not a tab of its own: it opens the real one
                sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
                os.execv(argv[0], argv)
            if note == "assistant" or label == "review":
                folder = review_folder(prof, rows) if label == "review" else where(label, prof, rows)
                if folder is None:
                    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); continue
                if folder != os.getcwd():
                    if note == "assistant":   # review keeps its own name: the repo shows in its header
                        name = (os.path.basename(folder) or name).upper()[:12]
                    os.chdir(folder)          # it starts here; keep_tab() saves it as cwd
            launch(name, argv, spec, keep)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h")

if __name__ == "__main__":
    sys.exit(main() or 0)
