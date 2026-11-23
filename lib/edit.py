"""phosphor edit - change a tab on purpose, then save it or put it back.

Tabs are locked: no resizing, no panes added or closed by accident. Alt-r
(EDIT on the bar) opens this screen over the focused pane and widens it to
the whole tab (#125): the tab drawn as a map of its panes, each with its
number, what runs in it and its size. Every action is on screen, a key or
a tap each, never a shortcut you have to know:

    1-9, a tap, the arrows, Tab   pick a pane
    + / -                         it gets bigger / smaller, a step at a time
    b / v                         a new pane below / beside it
    r                             another program in it (or cards)
    c                             its cards (on a row of cards), or a row under it
    x                             it goes
    s                             save into the profile (a .bak first), the tab reloads
    d                             put the tab back the way the profile has it
    Esc / q                       leave, nothing changed

The changes are made to the map (lib/tabmap.py), not the live tab: nothing
moves until s. Saving and putting back replace this very tab, so a small
helper finishes them after this screen closes.
"""
import json, os, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
from ui import getkey as ui_getkey
import deckconf, keep, newtab, apps, tabmap

MARK = " ✎"

def editing(name):
    """The tab's name while it's edited: the pencil, and the key that ends
    it, so the tab bar says how to finish."""
    import shortcuts
    return name + MARK + " " + shortcuts.dash(shortcuts.current(deckconf.load()[0])["edit"])
PHOSPHOR = os.path.join(REPO, "phosphor")

def zj(*a):
    return newtab.zj(*a)

def panes():
    try:
        return json.loads(zj("list-panes", "-a", "-j") or "[]")
    except ValueError:
        return []

def state_path(tab_id):
    d = os.path.join(deckconf.cache_dir(), "edit")
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
    if MARK in name: name = name.split(MARK)[0]       # "SYS ✎ Alt r" while it's edited
    return mine["tab_id"], mine["tab_position"], name, covered

_covering = []

def covering():
    """(name, still running) of the pane this screen was opened over, in
    place (a key on the bar, an Alt key), or None. That pane is only hidden
    underneath: it comes back when this screen ends. Asked once a process."""
    if not _covering:
        found = None
        here = where_am_i() if os.environ.get("ZELLIJ_PANE_ID") else None
        if here and here[3] is not None:
            p = next((p for p in panes() if p["id"] == here[3] and not p["is_plugin"]), None)
            if p:
                name = p.get("title") or os.path.basename((p.get("pane_command") or "").split(" ")[0]) or "the pane"
                found = (name, not p.get("exited"))
        _covering.append(found)
    return _covering[0]

def back_line():
    """The first line of a screen opened over a pane (#110): how to get back
    to it, and that it's still there; "" over nothing."""
    over = covering()
    if not over:
        return ""
    return "  " + DIM + "Esc: back to " + RST + FG + over[0] + RST + DIM + (" (still running)" if over[1] else "") + RST

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
    for n in (editing(name), name + MARK, name):
        got, specs, split = keep.tab_specs(layout, n)
        if got: return specs, split
    return [], None

# ── what changed ──────────────────────────────────────────────
def flat(specs):
    r = tabmap.root(specs)
    return [tabmap.node(r, p) for p in tabmap.leaves(r)]

label = tabmap.label

def changes(before, after):
    """Lines saying what's different, in words."""
    (b, bs), (a, as_) = before, after
    lb, la = flat(b), flat(a)
    out = []
    if (bs or "rows") != (as_ or "rows"):
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

def in_profile(name):
    """A real entry, not just a tabs.d stub placing it somewhere (deckconf.pinned_tabs_d)."""
    prof, _ = deckconf.load()
    return any(t.get("name") == name and deckconf.is_real_tab(t) for t in (prof or {}).get("tabs", []))

def finish(tab_id, name):
    """A tab an older Alt-r left unlocked and marked: back as it was."""
    zj("rename-tab-by-id", str(tab_id), name)
    try: os.remove(state_path(tab_id))
    except OSError: pass
    zj("switch-mode", "locked")

def origin(name):
    """(in your profile, the tabs.d file it comes from): either way gen wrote
    its layout, so d can put it back; neither is a tab opened with +."""
    mine = in_profile(name)
    return mine, None if mine else deckconf.tabs_d_names().get(name)

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
    for t in newtab.deck_tools(prof):
        if t[0] != "yazi" and all(i[0] != t[0] for i in items):
            items.append(t)
    return items

LIST_W = 44     # what the list keeps when a preview sits beside it

def pick(title, items, extra=(), side=None, hint=None):
    """A list to pick from by key, tap or scroll. items: (label, note, ...);
    extra: (key, label) rows above them; side(item, w, h), when given, draws
    what the item under the cursor will look like: beside the list on a
    wide screen, under it on a tall one; hint, a line at the foot (what
    Enter does here, ui.first_times). Returns an item, an extra's key,
    or None for back."""
    sel, top = 0, 0
    fixed = 3 + len(extra)
    while True:
        cols, rows = __import__("shutil").get_terminal_size((60, 20))
        lw, below = cols, []
        if side and cols >= LIST_W + 24:
            lw = LIST_W
        elif side and rows >= fixed + 6 + 8:
            below = [""] + side(items[sel] if items else None, cols - 4, min(10, rows // 3))
        room = max(3, rows - fixed - 1 - len(below) - (1 if hint else 0))
        top = min(max(top, sel - room + 1), sel)
        lines = ["", BLOOM + "  " + title + RST, "  " + AMB + "< back" + RST + DIM + "   (q)" + RST]
        lines += ["  " + AMB + "%-3s" % k + RST + FG + text + RST for k, text in extra]
        shown = items[top:top + room]
        for i, it in enumerate(shown, top):
            t = vcut("  %-16s %s" % (it[0][:16], it[1]), lw)
            lines.append(("\x1b[7m" + pad(t, lw) + RST) if i == sel else (FG + t + RST))
        if lw < cols:
            import preview
            right = side(items[sel] if items else None, cols - lw - 3, rows - 3)
            lines = lines[:2] + preview.beside(lines[2:], [""] + right, lw + 1)
        elif below:
            lines += [""] * (fixed + room - len(lines)) + ["  " + l for l in below]
        if hint:
            lines = lines[:rows - 1] + [""] * (rows - 1 - len(lines)) + [vcut(new_here(hint), cols)]
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J" + "\n".join(lines[:rows]))
        sys.stdout.flush()
        k = ui_getkey(None)
        if isinstance(k, tuple):
            if not k[4] or k[1] not in (0, 64, 65): continue
            if k[1] == 64: sel = max(0, sel - 3); continue          # wheel / touch scroll
            if k[1] == 65: sel = min(len(items) - 1, sel + 3); continue
            r = k[3]
            if k[2] > lw: continue                                  # a tap on the preview
            if r == 3: return None
            if 3 < r <= fixed: return extra[r - 4][0]
            if fixed < r <= fixed + len(shown): return items[top + r - fixed - 1]
            continue
        if k in ("q", "\x1b"): return None
        if k in [e[0] for e in extra]: return k
        if k in ("j", "\x1b[B"): sel = min(len(items) - 1, sel + 1)
        elif k in ("k", "\x1b[A"): sel = max(0, sel - 1)
        elif k in ("\r", "\n") and items: return items[sel]

def cards(it, cell=None):
    """An item of options() as it goes in a pane: cards are picked in the
    gallery first, previewed at the pane's size (cell: its columns and rows,
    this pane's when None). None if the gallery was left with Esc or none."""
    if "dash" not in (it[4] or {}): return it
    import dash
    names = dash.gallery([], enter="put them here", cell=cell)
    if not names: return None
    return it[:3] + ([PHOSPHOR, "dash"] + names, {"dash": names})

def choose(cell=None):
    """Pick one of options() for a pane of cell (columns, rows): its spec,
    as it goes in the profile, or None."""
    import preview
    items = options()
    cell = cell or (60, 20)
    def side(it, w, h):              # the pane: what goes in it, at the size it has
        return [DIM + "this pane" + RST] + preview.shape_map(0, {0: it[0] if it else "?"}, 0,
                                                            min(w, 36), min(h - 1, 8), (cell[0] + 2, cell[1] + 2))
    hint = first_times("pane", "↑↓ or a tap · Enter: it goes in this pane · q: back")
    while True:
        it = pick("what goes in this pane?", items, side=side, hint=hint)
        if not it: return None
        it = cards(it, cell)
        if it: return dict(it[4])

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
    if os.environ.get("ZELLIJ_SOCKET_DIR"):  # a stray session of that name on another socket isn't this one
        want.append(("ZELLIJ_SOCKET_DIR=%s" % os.environ["ZELLIJ_SOCKET_DIR"]).encode())
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
    """`edit --later restore TAB_ID POS NAME`: the tab again from the layout
    gen wrote for it, at the same place, once this screen is gone."""
    what = argv[0]
    ok = wait_gone(caller)
    print(time.strftime("%H:%M:%S"), what, " ".join(argv[1:]), "" if ok else "(the screen didn't close in time)", flush=True)
    if what == "restore":
        import apply, gen
        tab_id, name = argv[1], argv[3]
        sess = os.environ.get("ZELLIJ_SESSION_NAME", "deck")
        lay = os.path.join(gen.ZDIR, "tab-%s.kdl" % name.lower())
        was = apply.tabs(sess)
        old = next((t for t in was if str(t["tab_id"]) == tab_id), None)
        if not old or not os.path.exists(lay): return
        zj("new-tab", "--layout", lay, "--name", name)
        end, new = time.time() + 5, None
        while not new and time.time() < end:  # where it is now, not where a pane said it was
            new = next((t for t in apply.tabs(sess) if t["tab_id"] not in {w["tab_id"] for w in was}), None)
            time.sleep(0.2)
        old = next((t for t in apply.tabs(sess) if str(t["tab_id"]) == tab_id), old)
        for _ in range(max(0, (new["position"] if new else 0) - old["position"])):
            zj("move-tab", "left")
        gone = [pid for p in panes() if not p["is_plugin"] and str(p["tab_id"]) == tab_id and p["id"] != caller
                for pid in pane_procs(p["id"])]
        zj("close-tab-by-id", tab_id)
        time.sleep(0.5)
        for p in gone:                    # a pane still hidden under this screen outlives its closed tab
            try: os.kill(p, signal.SIGKILL)
            except OSError: pass

# ── the map ───────────────────────────────────────────────────
ARROWS = {"\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
          "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left"}

def area(tab_id):
    """(the tab's (columns, rows) its panes share, bars left out; the centre
    of this screen, which is where the pane it covers is)."""
    import bar
    me = int(os.environ.get("ZELLIJ_PANE_ID", "-1"))
    ps = [p for p in panes() if not p["is_plugin"] and p["tab_id"] == tab_id and not bar.is_bar(p)
          and not p.get("is_floating") and (not p["is_suppressed"] or p["id"] == me)]
    if not ps:
        return (80, 24), (40, 12)
    x0, y0 = min(p["pane_x"] for p in ps), min(p["pane_y"] for p in ps)
    w = max(p["pane_x"] + p["pane_columns"] for p in ps) - x0
    h = max(p["pane_y"] + p["pane_rows"] for p in ps) - y0
    mine = next((p for p in ps if p["id"] == me), ps[0])
    return (w, h), (mine["pane_x"] - x0 + mine["pane_columns"] / 2, mine["pane_y"] - y0 + mine["pane_rows"] / 2)

def flow(buttons, width, first=0, indent=1):
    """Buttons (key, text, act) laid out in as many lines as width needs:
    (lines, [(line, x0, x1, act)]) with 1-based columns, x1 included."""
    lines, spots, line, x = [], [], "", indent
    for k, text, act in buttons:
        n = len(k) + 1 + len(text)
        if x + n > width and line:
            lines.append(line); line, x = "", indent
        if not line:
            line = " " * indent
        spots.append((first + len(lines), x + 1, x + n, act))
        line += AMB + k + RST + " " + FG + text + RST + "   "
        x += n + 3
    if line:
        lines.append(line)
    return lines, spots

def mapscreen(tab_id, pos, name, covered, where):
    """The tab as a map: pick a pane, change it, save. Returns when done.
    where is area(), read before the screen widened itself."""
    import shutil
    before = tab_now(name, covered)
    specs, split0 = before
    if not specs:
        print("  couldn't read this tab's panes"); time.sleep(2); return
    r = tabmap.root(specs, split0)
    real, centre = where
    placed = tabmap.rects(r, real[0], real[1], real)
    def far(p):
        x, y, w, h = placed[p]
        return abs(x + w / 2 - centre[0]) + abs(y + h / 2 - centre[1])
    sel = min(tabmap.leaves(r), key=far)       # the pane Alt-r was pressed on
    mine, src = origin(name)
    known = mine or bool(src)
    note, armed, first = "", None, True
    while True:
        W, H = shutil.get_terminal_size((80, 24))
        now = tabmap.unroot(r, split0)
        diff = changes(before, now)
        spec = tabmap.node(r, sel)
        strip = ([("s", "save", "save")] if not src else []) + ([("d", "put back", "back")] if known else []) \
            + [("Esc", "cancel" if diff else "leave", "quit")]
        tools = [("+", "bigger", "grow"), ("-", "smaller", "shrink"), ("b", "split below", "below"),
                 ("v", "split beside", "beside"), ("r", "program", "swap"),
                 ("c", "its cards" if "dash" in spec else "cards under it", "cards"), ("x", "close", "close")]
        title = " EDIT " + name
        top, spots = flow(strip, W - len(title) - 2, 0, 0)
        if len(top) == 1:
            top = [BLOOM + title + RST + "  " + top[0]]
            spots = [(0, x + len(title) + 2, y + len(title) + 2, act) for _, x, y, act in spots]
        else:
            top, spots = flow(strip, W, 1)
            top = [BLOOM + title + RST] + top
        if note:
            status = note
        elif src:
            status = AMB + " comes from " + src.replace(os.path.expanduser("~"), "~", 1) + ": edit that file" + RST
        elif diff:
            status = FG + " " + " · ".join(diff) + RST
        else:
            status = (back_line()[1:] + DIM + " · " if covering() else DIM + " ") + "pick a pane: a tap, its number or the arrows" + (
                "" if mine else " · save adds " + name + " to your profile") + RST
        head = top + [vcut(status, W)]
        low, lspots = flow(tools, W)
        mh = max(4, H - len(head) - len(low) - 1)
        drawn, mplaced = tabmap.draw(r, sel, W, mh, real)
        rows = head + drawn + [""] + low
        spots += [(len(head) + mh + 1 + i, x0, x1, act) for i, x0, x1, act in lspots]
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J" + "\n".join(rows[:H]))
        sys.stdout.flush()
        k = ui_getkey(0.5, mouse=True, typeahead=not first)
        first = False
        if k is None:
            continue
        act = None
        if isinstance(k, tuple) and k[0] == "TAP":
            x, y = k[1], k[2]
            hit = [a for row, x0, x1, a in spots if row == y - 1 and x0 <= x <= x1]
            if hit:
                act = hit[0]
            else:
                my = y - 1 - len(head)
                inside = [p for p, (px, py, pw, ph) in mplaced.items() if px <= x - 1 < px + pw and py <= my < py + ph]
                if inside:
                    sel, note, armed = inside[0], "", None
                continue
        elif isinstance(k, str):
            if k in ARROWS:
                sel, note, armed = tabmap.nearest(mplaced, sel, ARROWS[k]), "", None; continue
            order = tabmap.leaves(r)
            if k == "\t":
                sel, note, armed = order[(order.index(sel) + 1) % len(order)], "", None; continue
            if k in tabmap.KEYS[:len(order)]:
                sel, note, armed = order[tabmap.KEYS.index(k)], "", None; continue
            act = {"+": "grow", "=": "grow", "-": "shrink", "_": "shrink", "b": "below", "v": "beside",
                   "r": "swap", "c": "cards", "x": "close", "s": "save", "d": "back",
                   "\x1b": "quit", "q": "quit"}.get(k.lower() if len(k) == 1 else k)
        if not act:
            continue
        was, armed, note = armed, None, ""
        if act in ("grow", "shrink"):
            why = tabmap.resize(r, sel, 1 if act == "grow" else -1, real)
            if why: note = AMB + " " + why + RST
        elif act in ("below", "beside"):
            sel = tabmap.split(r, sel, "rows" if act == "below" else "cols")
        elif act == "close":
            got = tabmap.close(r, sel)
            if isinstance(got, str): note = AMB + " " + got + RST
            else: sel = got
        elif act == "swap":
            x, y, w, h = tabmap.rects(r, real[0], real[1], real)[sel]
            got = choose((max(1, w - 2), max(1, h - 2)))
            if got: tabmap.put(r, sel, got)
        elif act == "cards":
            import dash
            if "dash" in spec:
                new = dash.gallery(spec["dash"], enter="update this pane")
                if new == []:
                    note = AMB + " no cards left: x closes the pane" + RST
                elif new is not None:
                    spec["dash"] = new
            else:
                new = dash.gallery([], enter="put them under this pane")
                if new:
                    sel = tabmap.split(r, sel, "rows", {"dash": new, "size": 5})
        elif act == "quit":
            if diff and was != "quit":
                note, armed = AMB + " not saved: Esc again leaves it as it was, s saves" + RST, "quit"
                continue
            return
        elif act in ("save", "back"):
            if act == "save" and src:
                note = AMB + " " + name + " comes from a file of tabs.d: edit that file, then phosphor gen" + RST
                continue
            reloads = act == "back" or diff
            held = keeping(tab_id) if reloads else []
            if held and was != act:
                note, armed = AMB + " %s reloads %s: %s start%s over · %s again" % (
                    "saving" if act == "save" else "putting it back", name, ", ".join(held),
                    "s" if len(held) == 1 else "", act[0]) + RST, act
                continue
            if act == "save":
                import io, contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    ok = keep.save(name, keep.block(name, *now))
                if not ok:
                    note = RED + " not saved: " + (buf.getvalue().strip()[-70:] or "there's no profile yet: phosphor init") + RST
                    continue
                subprocess.run([sys.executable, PHOSPHOR, "gen"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if reloads:
                later("restore", str(tab_id), str(pos), name)
            return

def keeping(tab_id):
    """What a reload of this tab would lose (a shell, an editor), this
    screen left out."""
    import apply
    me = int(os.environ.get("ZELLIJ_PANE_ID", "-1"))
    sess = os.environ.get("ZELLIJ_SESSION_NAME", "deck")
    real_panes = apply.panes
    try:
        apply.panes = lambda s: [p for p in real_panes(s) if p["id"] != me]
        return apply.keeping(sess, tab_id)
    finally:
        apply.panes = real_panes

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
    if os.path.exists(state_path(tab_id)):     # unlocked by the Alt-r before #125
        finish(tab_id, name)
    where = area(tab_id)                       # before it widens: then it's where the pane under it is
    covering()
    import bar
    wide = sum(1 for p in panes() if not p["is_plugin"] and p["tab_id"] == tab_id
               and not p["is_suppressed"] and not bar.is_bar(p)) > 1
    if wide:
        zj("toggle-fullscreen")                # the map needs the whole tab
    try:
        mapscreen(tab_id, pos, name, covered, where)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h"); sys.stdout.flush()
        if wide:
            zj("toggle-fullscreen")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
