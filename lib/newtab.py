"""phosphor new - what a new tab opens: a small touch menu.

The tab bar's "+" (and zellij's own new-tab) run it through the layout's
new_tab_template. Pick a shell here, a shell on a fleet machine, an installed
assistant, one of your own apps (apps.toml), files, or any command. This process then becomes it (exec), so
when it exits the tab closes. "keep" also writes the tab into the profile,
so it comes back after restarts.
"""
import json, os, select, shutil, subprocess, sys, termios, tty
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
from ui import getkey as ui_getkey
import deckconf, apps

HOME = os.path.expanduser("~")
BIN  = os.path.join(HOME, ".local/bin")
PHOSPHOR = os.path.join(REPO, "phosphor")
# Assistant CLIs offered when installed: (binary, label).
ASSISTANTS = [("claude", "Claude Code"), ("aichat", "aichat"), ("gemini", "Gemini CLI"),
              ("codex", "Codex"), ("opencode", "opencode")]
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

def getkey():
    """A key, ("CLICK", row) for a tap/left click, or None for other mouse events."""
    k = ui_getkey(None)
    if isinstance(k, tuple):
        return ("CLICK", k[3]) if k[1] == 0 and k[4] else None
    return k

def render(its, sel, keep, w):
    """Lines plus what each screen row does: an entry index, "cmd", "keep" or None."""
    rows, acts = [], []
    def add(text, act=None): rows.append(text); acts.append(act)
    add(BLOOM + " NEW TAB" + RST + DIM + "   tap one, or press its number" + RST)
    add(RULE + " " + "─" * max(0, w - 2) + RST)
    for i, (label, note, *_rest) in enumerate(its):
        num = str(i + 1) if i < 9 else " "
        line = " %s  %-14s %s" % (num, label[:14], note)
        add((INV + pad(line, w - 1) + RST) if i == sel else
            (" " + AMB + num + RST + "  " + FG + "%-14s" % label[:14] + RST + " " + DIM + note + RST), i)
    n = len(its)
    line = " +  a command..."
    add((INV + pad(line, w - 1) + RST) if sel == n else (" " + AMB + "+" + RST + "  " + FG + "a command..." + RST), "cmd")
    add("")
    box = "[x]" if keep else "[ ]"
    line = " %s keep this tab after restarts" % box
    add((INV + pad(line, w - 1) + RST) if sel == n + 1 else
        (" " + (PH if keep else DIM) + box + RST + " " + MUTE + "keep this tab after restarts" + RST), "keep")
    add("")
    add(DIM + " q / Esc: close this tab" + RST)
    return rows, acts

def taken_names():
    names = set()
    for l in zj("list-tabs").splitlines()[1:]:
        f = l.split(None, 2)
        if len(f) == 3: names.add(f[2].strip())
    return names

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

def ask_command(rows):
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[%d;1H\x1b[K " % rows + AMB + "command: " + RST)
    sys.stdout.flush()
    try:
        text = sys.stdin.readline().strip()
    except KeyboardInterrupt:
        text = ""
    sys.stdout.write("\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    return text

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
    d = os.path.expanduser("~/.cache/phosphor/layouts")
    os.makedirs(d, exist_ok=True)
    lay = os.path.join(d, "%s.kdl" % name.lower())
    with open(lay, "w") as f:
        f.write(gen.tab_kdl(tab, gen.Ctx(prof or {}), "phosphor new (layout)"))
    zj("new-tab", "--layout", lay, "--name", name)
    return name

def here():
    """Alt-n: a new tab in the folder of the pane you're in. It runs in place
    over that pane for a moment, reads where its foreground program is (your
    shell after a cd) and opens the menu there."""
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
    sel, keep, n = 0, False, len(its)
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((60, 20))
            w = min(cols, 80)
            lines, acts = render(its, sel, keep, w)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines[:rows]) + "\x1b[K\x1b[J"); sys.stdout.flush()
            k = getkey()
            act = None
            if isinstance(k, tuple):
                r = k[1] - 1
                act = acts[r] if 0 <= r < len(acts) else None
                if act is None: continue
            elif k in ("q", "\x1b", "\x03"):
                return 0
            elif k in ("j", "\x1b[B"): sel = min(n + 1, sel + 1); continue
            elif k in ("k", "\x1b[A"): sel = max(0, sel - 1); continue
            elif k and k.isdigit() and 0 < int(k) <= min(9, n): act = int(k) - 1
            elif k in ("\r", "\n", " "): act = sel if sel < n else ("cmd" if sel == n else "keep")
            else: continue
            if act == "keep":
                keep = not keep; continue
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
            launch(name, argv, spec, keep)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h")

if __name__ == "__main__":
    sys.exit(main() or 0)
