"""phosphor edit - change a tab on purpose, then save it or put it back.

Tabs are locked: no resizing, no panes added or closed. Alt-r opens this
screen over the focused pane (zellij runs it in place):

- the first time, it unlocks the tab (the tab bar marks it with a pencil):
  resize, split, close panes with zellij's own keys;
- the next Alt-r shows what changed against how the tab started, and asks:
  s saves it into the profile (as `phosphor keep` would), d puts the tab back
  the way the profile has it, r swaps the program of the pane underneath
  (ctop for lazydocker), e goes on editing.

Swapping and putting back need this screen gone first (it covers the very
pane they change), so a small helper finishes them after it closes.
"""
import json, os, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
from ui import getkey as ui_getkey
import deckconf, keep, newtab, apps

MARK = " ✎"
PHOSPHOR = os.path.join(REPO, "phosphor")

def zj(*a):
    return newtab.zj(*a)

def panes():
    try:
        return json.loads(zj("list-panes", "-a", "-j") or "[]")
    except ValueError:
        return []

def state_path(tab_id):
    d = os.path.expanduser("~/.cache/phosphor/edit")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s-%s.json" % (os.environ.get("ZELLIJ_SESSION_NAME", "deck"), tab_id))

def where_am_i():
    """(my tab id, its position, its name without the mark, the pane I cover)."""
    me = int(os.environ.get("ZELLIJ_PANE_ID", "-1"))
    ps = [p for p in panes() if not p["is_plugin"]]
    mine = next((p for p in ps if p["id"] == me), None)
    if not mine:
        return None
    geo = lambda p: (p["pane_x"], p["pane_y"], p["pane_rows"], p["pane_columns"])
    under = [p for p in ps if p["tab_id"] == mine["tab_id"] and p["id"] != me
             and p["is_suppressed"] and geo(p) == geo(mine)]
    covered = max((p["id"] for p in under), default=None)     # the latest one is right under me
    name = mine["tab_name"]
    if name.endswith(MARK): name = name[:-len(MARK)]
    return mine["tab_id"], mine["tab_position"], name, covered

def argv_of(pane_id):
    """The command line a pane was started with, from its first process."""
    procs = pane_procs(pane_id)
    for p in procs:
        try:
            ppid = int(open("/proc/%d/stat" % p).read().rsplit(")", 1)[1].split()[1])
            if ppid not in procs:
                return [a for a in open("/proc/%d/cmdline" % p).read().split("\0") if a]
        except (OSError, ValueError, IndexError):
            continue
    return None

def unmask(node, argv):
    """zellij describes this screen, not the pane under it: put that one back."""
    for c in node["children"]:
        if c["word"] == "pane" and c["attrs"].get("name") == "EDIT":
            c["attrs"].pop("name")
            if argv:
                c["attrs"]["command"] = argv[0]
                c["children"] = [k for k in c["children"] if k["word"] != "args"] + \
                                [{"word": "args", "attrs": {}, "args": argv[1:], "children": []}]
            else:                          # nothing to read: a plain shell
                c["attrs"].pop("command", None)
                c["children"] = [k for k in c["children"] if k["word"] != "args"]
        unmask(c, argv)

def tab_now(name, covered=None):
    """The tab as zellij has it now, in profile shape: (specs, split)."""
    layout = keep.parse(zj("dump-layout"))
    unmask(layout, argv_of(covered) if covered is not None else None)
    for n in (name + MARK, name):
        got, specs, split = keep.tab_specs(layout, n)
        if got: return specs, split
    return [], None

# ── what changed ──────────────────────────────────────────────
def leaves(specs, split=None, path=""):
    out = []
    for i, s in enumerate(specs):
        if "panes" in s:
            out += leaves(s["panes"], s.get("split"), path + "%d." % i)
        else:
            out.append(s)
    return out

def label(s):
    if "ssh" in s: return "ssh " + s["ssh"]
    if not s.get("cmd"): return "shell"
    return " ".join([s["cmd"]] + [str(a) for a in s.get("args", [])])

def changes(before, after):
    """Lines saying what's different, in words."""
    (b, bs), (a, as_) = before, after
    lb, la = leaves(b), leaves(a)
    out = []
    if bs != as_:
        out.append("split: %s → %s" % (bs or "rows", as_ or "rows"))
    if len(lb) != len(la):
        out.append("panes: %d → %d" % (len(lb), len(la)))
    for x, y in zip(lb, la):
        if label(x) != label(y):
            out.append("%s → %s" % (label(x), label(y)))
        elif x.get("size") != y.get("size") and len(lb) == len(la):
            out.append("%s: %s → %s" % (label(y), x.get("size", "auto"), y.get("size", "auto")))
    if not out and json.dumps(b, sort_keys=True) != json.dumps(a, sort_keys=True):
        out.append("layout changed")
    return out

# ── the screen ────────────────────────────────────────────────
# Every action is a row of its own: a key, or a tap anywhere on that row.
def screen(head, buttons):
    """Draw the head lines and one row per (key, label, action); return the
    action of the key pressed or the row tapped."""
    import shutil
    height = shutil.get_terminal_size((60, 20)).lines
    head = list(head)[:max(0, height - len(buttons) - 1)]   # a small pane keeps its buttons, and rows stay put
    rows, acts = head + [""], [None] * (len(head) + 1)
    for k, text, act in buttons:
        rows.append("  " + AMB + "%-9s" % k + RST + FG + text + RST)
        acts.append(act)
    rows = rows[:height]
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J" + "\n".join(rows))
    sys.stdout.flush()
    keys = {}
    for k, _, act in buttons:
        for one in k.split(" / "):
            keys[{"Enter": "\r", "Esc": "\x1b"}.get(one, one)] = act
    if "\r" in keys: keys["\n"] = keys[" "] = keys["\r"]
    while True:
        k = ui_getkey(None)
        if isinstance(k, tuple):
            if k[1] == 0 and k[4] and 0 < k[3] <= len(acts) and acts[k[3] - 1]:
                return acts[k[3] - 1]
            continue
        if k in keys: return keys[k]
        if k and k.lower() in keys: return keys[k.lower()]

def in_profile(name):
    """A real entry, not just a tabs.d stub placing it somewhere (deckconf.pinned_tabs_d)."""
    prof, _ = deckconf.load()
    return any(t.get("name") == name and deckconf.is_real_tab(t) for t in (prof or {}).get("tabs", []))

def begin(tab_id, name, covered):
    import shortcuts
    ek = shortcuts.dash(shortcuts.current(deckconf.load()[0])["edit"])
    head = ["", BLOOM + "  EDIT " + name + RST, "",
            "  " + FG + "The tab unlocks until you're done." + RST,
            "  " + DIM + "resize: drag a border, or Ctrl-n and the arrows" + RST,
            "  " + DIM + "panes: Ctrl-p n / x, or split and close from %s" % ek + RST,
            "  " + DIM + "done: %s (EDIT on the phone) to save, put back, swap" % ek + RST]
    if screen(head, [("Enter", "start editing", "start"), ("q / Esc", "leave it locked", "quit")]) != "start":
        return
    json.dump({"name": name, "before": tab_now(name, covered), "started": time.time()}, open(state_path(tab_id), "w"))
    zj("rename-tab-by-id", str(tab_id), name + MARK)
    zj("switch-mode", "normal")

def finish(tab_id, name):
    zj("rename-tab-by-id", str(tab_id), name)
    try: os.remove(state_path(tab_id))
    except OSError: pass
    zj("switch-mode", "locked")

def visible(tab_id, covered):
    """The panes you can see in this tab once this screen is gone."""
    me = int(os.environ.get("ZELLIJ_PANE_ID", "-1"))
    ps = [p for p in panes() if not p["is_plugin"] and p["tab_id"] == tab_id]
    return [p["id"] for p in ps if p["id"] != me and (not p["is_suppressed"] or p["id"] == covered)]

def done(tab_id, pos, name, covered, st):
    before, now = tuple(st["before"]), tab_now(name, covered)
    diff = changes(before, now)
    known = in_profile(name)
    src = None if known else deckconf.tabs_d_names().get(name)
    head = ["", BLOOM + "  EDIT " + name + RST + DIM + "  what changed" + RST, ""]
    head += ["  " + FG + "· " + d + RST for d in diff] or ["  " + DIM + "nothing yet" + RST]
    if src:
        head += ["", "  " + AMB + name + " comes from " + src.replace(os.path.expanduser("~"), "~", 1)
                 + ": edit that file, then phosphor gen" + RST]
    elif not known:
        head += ["", "  " + AMB + name + " isn't in your profile yet: save adds it" + RST]
    note = ""
    while True:
        buttons = [("s", "save into the profile", "save"),
                   ("d", "put it back as it was", "back"),
                   ("r", "swap this pane's program", "swap"),
                   ("b", "split: a new pane below this one", "below"),
                   ("v", "split: a new pane beside this one", "beside"),
                   ("x", "close this pane", "close"),
                   ("e / Esc", "keep editing", "edit")]
        if src:
            buttons = [b for b in buttons if b[2] != "save"]
        act = screen(head + ([note] if note else []), buttons)
        note = ""
        if act == "save":
            specs, split = now
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ok = keep.save(name, keep.block(name, specs, split))
            if ok:
                subprocess.run([sys.executable, PHOSPHOR, "gen"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                finish(tab_id, name)
                return
            why = buf.getvalue().strip()[-70:] or "there's no profile yet: phosphor init"
            note = "  " + RED + "not saved: " + why + RST
        elif act == "back":
            finish(tab_id, name)
            if known and diff:
                later("restore", str(tab_id), str(pos), name)
            return
        elif act == "swap" and covered is not None:
            chosen = choose()
            if chosen:
                later("swap", str(covered), *chosen)
                zj("switch-mode", "normal")
                return
        elif act in ("below", "beside") and covered is not None:
            later("split", str(covered), "down" if act == "below" else "right")
            zj("switch-mode", "normal")
            return
        elif act == "close" and covered is not None:
            if len(visible(tab_id, covered)) < 2:
                note = "  " + AMB + "it's the only pane in the tab: put something else in it with r" + RST
                continue
            later("close", str(covered))
            zj("switch-mode", "normal")
            return
        elif act == "edit":
            zj("switch-mode", "normal")
            return

def options():
    """What can go in a pane: the + menu's programs and every installed app,
    as (label, note, tab name, argv, spec)."""
    prof, _ = deckconf.load()
    items = []
    for label_, note, name, argv, spec in newtab.entries(prof):
        if spec is None: continue
        items.append((label_, note, name, argv, spec))
    import store
    store.CATALOG = share("store.json")
    seen = {i[0] for i in items}
    for a in store.catalog()[0]:
        p = apps.have(apps.exe(a))
        if p and a["n"] not in seen:
            items.append((a["n"], a["c"], apps.tab_name(a), [p] + a.get("args", []), apps.spec(a)))
    for b, flags in (("btop", {}), ("ctop", {"alt": True}), ("gping", {"alt": True})):
        p = apps.have(b)
        if p and b not in seen and all(i[0] != b for i in items):
            items.append((b, "deck tool", b.upper(), [p], dict(flags, cmd=b)))
    return items

def pick(title, items, extra=()):
    """A list to pick from by key, tap or scroll. items: (label, note, ...);
    extra: (key, label) rows above them. Returns an item, an extra's key, or
    None for back."""
    sel, top = 0, 0
    fixed = 3 + len(extra)
    while True:
        cols, rows = __import__("shutil").get_terminal_size((60, 20))
        room = max(3, rows - fixed - 1)
        top = min(max(top, sel - room + 1), sel)
        lines = ["", BLOOM + "  " + title + RST, "  " + AMB + "< back" + RST + DIM + "   (q)" + RST]
        lines += ["  " + AMB + "%-3s" % k + RST + FG + text + RST for k, text in extra]
        shown = items[top:top + room]
        for i, it in enumerate(shown, top):
            t = "  %-16s %s" % (it[0][:16], it[1])
            lines.append(("\x1b[7m" + t + RST) if i == sel else (FG + t + RST))
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J" + "\n".join(lines[:rows]))
        sys.stdout.flush()
        k = ui_getkey(None)
        if isinstance(k, tuple):
            if not k[4] or k[1] not in (0, 64, 65): continue
            if k[1] == 64: sel = max(0, sel - 3); continue          # wheel / touch scroll
            if k[1] == 65: sel = min(len(items) - 1, sel + 3); continue
            r = k[3]
            if r == 3: return None
            if 3 < r <= fixed: return extra[r - 4][0]
            if fixed < r <= fixed + len(shown): return items[top + r - fixed - 1]
            continue
        if k in ("q", "\x1b"): return None
        if k in [e[0] for e in extra]: return k
        if k in ("j", "\x1b[B"): sel = min(len(items) - 1, sel + 1)
        elif k in ("k", "\x1b[A"): sel = max(0, sel - 1)
        elif k in ("\r", "\n") and items: return items[sel]

def run_flags(argv, spec):
    return (["--reconnect"] if argv[0] == "ssh" else []) \
        + (["--wait", "1"] if spec.get("needs_size") else []) + (["--alt"] if spec.get("alt") else [])

def choose():
    """Pick one of options(). Returns [name, flags..., "--", argv...] or None."""
    it = pick("what goes in this pane?", options())
    if not it: return None
    _, _, name, argv, spec = it
    return [name] + run_flags(argv, spec) + ["--"] + argv

def later(*args):
    """The helper that finishes after this screen closes."""
    log = open(os.path.join(os.path.dirname(state_path(0)), "later.log"), "a")
    subprocess.Popen([sys.executable, PHOSPHOR, "edit", "--later"] + list(args),
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)

# ── after the screen is gone ──────────────────────────────────
def wait_gone(pane_id, under=None, timeout=10):
    """Until this screen's pane is gone and the one it covered shows again."""
    end = time.time() + timeout
    while time.time() < end:
        ps = [p for p in panes() if not p["is_plugin"]]
        if not any(p["id"] == pane_id for p in ps) and \
           not any(p["id"] == under and p["is_suppressed"] for p in ps):
            return True
        time.sleep(0.2)
    return False

def pane_procs(pane_id):
    """The processes of one pane of this session."""
    want = [b"ZELLIJ_PANE_ID=%d" % pane_id,
            ("ZELLIJ_SESSION_NAME=%s" % os.environ.get("ZELLIJ_SESSION_NAME", "")).encode()]
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == os.getpid(): continue
        try:
            env = open("/proc/%s/environ" % d, "rb").read().split(b"\0")
        except OSError:
            continue
        if all(w in env for w in want):
            out.append(int(d))
    return out

def run_later(argv, caller):
    what = argv[0]
    ok = wait_gone(caller, int(argv[1]) if what in ("swap", "split", "close") else None)
    print(time.strftime("%H:%M:%S"), what, " ".join(argv[1:]), "" if ok else "(the screen didn't close in time)", flush=True)
    if what == "swap":
        covered, name, rest = int(argv[1]), argv[2], argv[3:]
        old = pane_procs(covered)
        zj("new-pane", "--in-place", "--pane-id", "terminal_%d" % covered, "--close-on-exit",
           "--name", name, "--", sys.executable, PHOSPHOR, "run", "--name", name, *rest)
        time.sleep(0.5)
        for p in old:                     # what was there: nothing shows it any more
            try: os.kill(p, signal.SIGKILL)
            except OSError: pass
    elif what == "split":
        zj("new-pane", "--direction", argv[2])
    elif what == "close":
        zj("close-pane", "--pane-id", "terminal_%s" % argv[1])
    elif what == "restore":
        tab_id, pos, name = argv[1], int(argv[2]), argv[3]
        lay = os.path.expanduser("~/.config/zellij/layouts/tab-%s.kdl" % name.lower())
        if not os.path.exists(lay): return
        zj("new-tab", "--layout", lay, "--name", name)
        time.sleep(0.5)
        ntabs = len({p["tab_id"] for p in panes()})
        for _ in range(max(0, ntabs - 1 - pos)):
            zj("move-tab", "left")
        zj("close-tab-by-id", tab_id)

def main():
    a = sys.argv[1:]
    if a[:1] == ["--later"]:
        run_later(a[1:], int(os.environ.get("ZELLIJ_PANE_ID", "-1")))
        return 0
    if not os.environ.get("ZELLIJ"):
        print("  inside the deck, Alt-r (or your [keys] edit) edits the tab you're in"); return 1
    here = where_am_i()
    if not here:
        print("  couldn't find this pane in the session"); return 1
    tab_id, pos, name, covered = here
    try:
        st = json.load(open(state_path(tab_id)))
    except (OSError, ValueError):
        st = None
    try:
        if st: done(tab_id, pos, name, covered, st)
        else: begin(tab_id, name, covered)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h"); sys.stdout.flush()
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
