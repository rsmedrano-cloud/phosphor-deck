"""phosphor home - the grid: your cards and tabs as tiles, one command line.

A prototype beside what exists (#101): nothing it shows is gone from the
DECK tab, dash or the + menu. The layout is one line in the profile:

    [home]
    layout = "fleet:4x2,ci,screens|term@CHAT"

Commas separate tiles, | pages. A tile is a card's name (share/commands.json)
or term@TAB, a tab of the deck: what runs there, its last line and whether
it's busy. :WxH picks one of the sizes it takes (a card's `sizes`; the first
when left out or not one of them); a name nothing knows is skipped.

The grid is 4 columns (2 on a narrow screen, every width halved), a row of
it 3 lines; tiles go first-fit in order, and what doesn't fit on the screen
goes on the next one. Each tile has a key (1-9 a-z, not m, q or s): its key,
a tap, or the arrows and Enter open it.

    m        pick the selected tile up: arrows move it earlier or later
             (into the next page past the last), + / - its sizes,
             Enter puts it down, Esc puts it back where it was
    s        keep the layout in the profile (a .bak first)
    /        the command line: suggestions above it while you type
    PgUp/PgDn  [ ]  the pages (a tap on the dots too)
    q        leave

Tiles only take the theme's ink, paper and dim: a ! is what wants a look.

    phosphor home            the screen
    phosphor home --json     the layout and what each tile shows (MCP: home)
    phosphor home --once     one frame, printed
"""
import copy, json, os, re, subprocess, sys, textwrap, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, RST, REPO, vcut, vlen, pad, getkey, mono_stdout, mono_term, paint
import card, cli, deckconf

PHOSPHOR = os.path.join(REPO, "phosphor")
COLS, NARROW = 4, 60          # grid columns; under NARROW columns of screen, 2 (widths halve)
UNIT_H = 3                    # lines in a row of the grid
TERM = "term@"
TERM_SIZES = ["2x2", "4x2", "4x4"]
BY_KIND = {"sensor": ["2x2", "4x2"], "toggle": ["2x2", "4x2"],
           "button": ["2x1", "2x2"], "shortcut": ["2x1", "2x2"]}
SIZE = re.compile(r"^[124]x[124]$")
DEFAULT = "fleet:4x2,ci,screens,usage,web"
KEYS = "123456789abcdefghijklnoprtuvwxyz"       # m picks up, q leaves, s saves
INV, BOLD = "\x1b[7m", "\x1b[1m"


# ── the layout line ───────────────────────────────────────────
def sizes_of(name):
    """The sizes a tile takes, its default first; None for a name that
    isn't a tile (unknown, hidden, or a card with no tile: plumbing)."""
    if name.startswith(TERM):
        return list(TERM_SIZES) if name[len(TERM):].strip() else None
    c = card.spec(name)
    if not c or c.get("kind") not in BY_KIND:
        return None
    return [s for s in c.get("sizes") or BY_KIND[c["kind"]] if SIZE.match(s)] or ["2x2"]


def parse(line, sizes=sizes_of):
    """(pages, skipped): pages a list of lists of {"name", "size"}; skipped
    the names that aren't tiles, in order."""
    pages, skipped = [], []
    for chunk in (line or "").split("|"):
        page = []
        for part in chunk.split(","):
            name, _, size = part.strip().partition(":")
            name, size = name.strip(), size.strip().lower()
            if not name:
                continue
            if not name.startswith(TERM):
                name = name.lower()
            ok = sizes(name)
            if not ok:
                skipped.append(name)
                continue
            page.append({"name": name, "size": size if size in ok else ok[0]})
        if page:
            pages.append(page)
    return pages, skipped


def line(pages, sizes=sizes_of):
    """The pages as one layout line; a tile's size only when it isn't its first."""
    def one(t):
        ok = sizes(t["name"]) or []
        return t["name"] if ok[:1] == [t["size"]] else "%s:%s" % (t["name"], t["size"])
    return "|".join(",".join(one(t) for t in p) for p in pages if p)


def move(pages, at, d):
    """The tile at (page, index) one place earlier (d=-1) or later (+1):
    past the first of a page into the previous page's end, past the last
    into the next page's start, past the very last into a page of its own.
    (new pages, where it went); a page left empty goes."""
    pages = copy.deepcopy(pages)
    p, i = at
    t = pages[p][i]
    if 0 <= i + d < len(pages[p]):
        pages[p][i], pages[p][i + d] = pages[p][i + d], t
        return pages, (p, i + d)
    if d < 0 and p == 0 or d > 0 and p == len(pages) - 1 and len(pages[p]) == 1:
        return pages, (p, i)                      # nowhere further
    del pages[p][i]
    if d < 0:
        pages[p - 1].append(t)
        new = (p - 1, len(pages[p - 1]) - 1)
    elif p == len(pages) - 1:
        pages.append([t])
        new = (p + 1, 0)
    else:
        pages[p + 1].insert(0, t)
        new = (p + 1, 0)
    if not pages[p]:
        del pages[p]
        if new[0] > p:
            new = (new[0] - 1, new[1])
    return pages, new


def resize(pages, at, d, sizes=sizes_of):
    """The tile at (page, index) one size along its list (+1 bigger, -1
    back), stopping at either end."""
    pages = copy.deepcopy(pages)
    t = pages[at[0]][at[1]]
    ok = sizes(t["name"]) or [t["size"]]
    i = ok.index(t["size"]) if t["size"] in ok else 0
    t["size"] = ok[max(0, min(len(ok) - 1, i + d))]
    return pages


# ── placing it ────────────────────────────────────────────────
def columns(width):
    return COLS if width >= NARROW else COLS // 2


def dims(size, cols, fit=None):
    """A size in grid cells on a grid of cols columns, at most fit rows."""
    w, h = (int(x) for x in size.split("x"))
    w = min(cols, w if cols == COLS else max(1, w * cols // COLS))
    return w, (min(h, fit) if fit else h)


def place(tiles, cols, fit=None):
    """First-fit: each tile, in order, at the first spot (top to bottom,
    left to right) it fits in. With fit (the rows a screen holds), what
    doesn't fit goes on the next screen. A list of screens, each a list of
    (index, x, y, w, h)."""
    screens, todo = [], list(range(len(tiles)))
    while todo:
        used, here, rest = set(), [], []
        for i in todo:
            w, h = dims(tiles[i]["size"], cols, fit)
            spot = None
            for y in range((fit or 4 * len(tiles)) - h + 1):
                for x in range(cols - w + 1):
                    if not any((x + a, y + b) in used for a in range(w) for b in range(h)):
                        spot = (x, y)
                        break
                if spot:
                    break
            if spot is None:
                rest.append(i)
                continue
            used |= {(spot[0] + a, spot[1] + b) for a in range(w) for b in range(h)}
            here.append((i, spot[0], spot[1], w, h))
        if not here:                          # can't happen (h <= fit, w <= cols): never loop
            break
        screens.append(here)
        todo = rest
    return screens


def screens_of(pages, cols, fit):
    """Every screen, in order: [(page, [(index, x, y, w, h)])]."""
    return [(p, s) for p, tiles in enumerate(pages) for s in place(tiles, cols, fit)]


def nearest(placed, cur, key):
    """The tile an arrow goes to from cur (an index), among placed: the
    nearest whose middle lies that way. None when there's none."""
    at = {i: (x + w / 2.0, y + h / 2.0) for i, x, y, w, h in placed}
    if cur not in at:
        return None
    cx, cy = at[cur]
    way = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[key]
    best = None
    for i, (x, y) in at.items():
        dx, dy = x - cx, y - cy
        along = dx * way[0] + dy * way[1]
        if i == cur or along <= 0:
            continue
        score = along + 2 * abs(dx * way[1] + dy * way[0])
        if best is None or score < best[0]:
            best = (score, i)
    return best[1] if best else None


# ── what a tile shows ─────────────────────────────────────────
class Terms:
    """term@TAB tiles' state, read in the background: the focused pane's
    command, its last line, and when its screen last changed."""

    EVERY = 2.0

    def __init__(self, tabs, background=True):
        self.tabs, self.got, self.seen, self.stopped = list(tabs), {}, {}, False
        if self.tabs and background:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.stopped:
            self.read()
            time.sleep(self.EVERY)

    def read(self):
        import mirror
        sess = mirror.session()
        ps = mirror.panes(sess)
        for tab in self.tabs:
            hit = sorted((p for p in ps if mirror.tab_name(p).lower() == tab.lower()),
                         key=lambda p: (not p.get("is_focused"), p.get("is_floating", False), p["id"]))
            if not hit:
                self.got[tab] = None
                continue
            p = hit[0]
            text = mirror.zj(sess, "dump-screen", "-p", "terminal_%d" % p["id"]) or ""
            last = next((l.strip() for l in reversed(text.splitlines()) if l.strip()), "")
            if self.seen.get(tab, (None,))[0] != text:
                self.seen[tab] = (text, time.time())
            self.got[tab] = {"runs": what_runs(p), "last": last, "changed": self.seen[tab][1]}

    def get(self, tab):
        """{"runs", "last", "changed"}, None for a tab that isn't open, or
        False before the first read."""
        return self.got.get(tab, False)


def what_runs(p):
    """A list-panes entry's program, in a word or two."""
    cmd = (p.get("terminal_command") or "").split()
    if cmd:
        return " ".join([os.path.basename(cmd[0])] + cmd[1:2])
    return (p.get("title") or "shell").strip()


def ago(t, now=None):
    s = int((now or time.time()) - t)
    if s < 5:
        return "busy"
    return "idle " + ("%ds" % s if s < 60 else "%dm" % (s // 60) if s < 3600 else "%dh" % (s // 3600))


def body(t, live, terms, iw, ih):
    """The lines inside a tile, iw x ih, ink and dim only; and whether it
    wants a look."""
    name = t["name"]
    if name.startswith(TERM):
        st = terms.get(name[len(TERM):]) if terms else False
        if st is False:
            out = [DIM + card.READING + RST]
        elif st is None:
            out = [DIM + "not open" + RST]
        else:
            out = [FG + st["runs"] + RST, DIM + st["last"] + RST, DIM + ago(st["changed"]) + RST]
            if ih == 1:
                out = [FG + st["runs"] + RST + DIM + " · " + ago(st["changed"]) + RST]
        return [vcut(l, iw) for l in out[:ih]], False
    c = card.spec(name) or {}
    warn = False
    if c.get("state"):
        v, warn = live.get(name) if live else (card.READING, False)
        why = live.why(name) if live else None
        out = [(FG + "! " if warn else FG) + BOLD + (v or "–") + RST]
        if why:
            out += [FG + l + RST for l in textwrap.wrap(why, max(8, iw))[:2]]
        elif live and live.line(name):
            out += [DIM + l + RST for l in textwrap.wrap(live.line(name), max(8, iw))[:2]]
        room = ih - 1 - len(out)
        if room > 0 and live:
            out += card.detail(live.raw(name), iw, room)
    else:
        about = (cli.entries().get(name) or {}).get("summary", "")
        out = [DIM + l + RST for l in textwrap.wrap(about, max(8, iw))]
    out = out[:max(1, ih - 1)] if ih >= 3 else out[:ih]
    if ih >= 3:
        out += [""] * (ih - 1 - len(out)) + [DIM + "phosphor " + name + RST]
    return [vcut(l, iw) for l in out], warn


def box(title, lines, w, h, sel=False, held=False):
    """A tile w x h: a border (double while held), the title on it
    (reversed when selected), lines inside."""
    tl, tr, bl, br, hz, vt = ("╔", "╗", "╚", "╝", "═", "║") if held else ("┌", "┐", "└", "┘", "─", "│")
    title = vcut(" %s " % title, max(0, w - 4))
    head = (INV if sel else FG) + title + RST
    top = DIM + tl + hz + RST + head + DIM + hz * max(0, w - 3 - vlen(title)) + tr + RST
    out = [top]
    for r in range(h - 2):
        l = lines[r] if r < len(lines) else ""
        out.append(DIM + vt + RST + " " + pad(vcut(l, w - 4), w - 4) + " " + DIM + vt + RST)
    out.append(DIM + bl + hz * (w - 2) + br + RST)
    return out


# ── the screen ────────────────────────────────────────────────
SUGGEST = 8                   # suggestions above the command line, at most


def shown(found, rows):
    return list(found)[:max(0, min(SUGGEST, rows - 4))]


def where(pages, scr, at):
    """The screen (an index into scr) that shows the tile at (page, index)."""
    return next((n for n, (p, s) in enumerate(scr) if at and p == at[0]
                 and any(i == at[1] for i, *_ in s)), 0)


def frame(pages, at, w, rows, live=None, terms=None, held=False, typing=None, found=(), pick=0, msg=None):
    """The screen w x rows: its lines and tap targets [(top, bottom, left,
    right, what)], 1-based (what: (page, index), ("page", n) or "cmd");
    at is the selected (page, index), or None. No line fills the width:
    zellij would wrap it."""
    cols, fit = columns(w), max(1, (rows - 3) // UNIT_H)
    scr = screens_of(pages, cols, fit)
    now = where(pages, scr, at)
    lines, hit, segs = [""] * rows, [], {}
    dots = " ".join(("●" if n == now else "○") for n in range(len(scr))) if len(scr) > 1 else ""
    head = FG + BOLD + " HOME" + RST + DIM + ("   held: arrows move it, + - its size, Enter puts it down"
                                              if held else "") + RST
    room = w - 2 - (len(dots) + 1 if dots else 0)
    lines[0] = pad(vcut(head, room), room) + (" " + FG + dots + RST if dots else "")
    for n in range(len(scr) if dots else 0):
        x = room + 2 + 2 * n
        hit.append((1, 1, x, x + 1, ("page", n)))
    cw = w // cols
    if scr:
        p, placed = scr[now]
        for n, (i, x, y, tw, th) in enumerate(placed):
            t = pages[p][i]
            bw, bh = tw * cw - 1, th * UNIT_H
            inner, warn = body(t, live, terms, bw - 4, bh - 2)
            title = (KEYS[n] + " " if n < len(KEYS) else "") + t["name"] + (" !" if warn else "")
            top = 1 + y * UNIT_H
            for r, l in enumerate(box(title, inner, bw, bh, sel=(at == (p, i)), held=held and at == (p, i))):
                if top + r < rows - 2:
                    segs.setdefault(top + r, []).append((x * cw, l))
            hit.append((top + 1, top + bh, x * cw + 1, x * cw + bw, (p, i)))
    for row, parts in segs.items():
        s, col = "", 0
        for x, piece in sorted(parts, key=lambda a: a[0]):
            s += " " * max(0, x - col) + piece
            col = x + vlen(piece)
        lines[row] = s
    if typing is not None:
        these = shown(found, rows)
        for n, it in enumerate(these):
            l = " %-16s %s" % (it[0][:16], it[1])
            lines[rows - 2 - len(these) + n] = (INV + pad(vcut(l, w - 2), w - 2) + RST) if n == pick else \
                (" " + FG + "%-16s" % it[0][:16] + RST + " " + DIM + vcut(it[1], max(0, w - 20)) + RST)
    if msg:
        lines[rows - 2] = vcut(" " + FG + msg + RST, w - 1)
    if typing is not None:
        lines[rows - 1] = vcut(" " + FG + "› " + typing + RST + DIM + "_" + RST, w - 1)
    else:
        hint = "Esc puts it back" if held else "m move · s save · ? keys · q leave"
        lines[rows - 1] = vcut(" " + DIM + "› / a command, a tab, a tool   " + hint + RST, w - 1)
        hit.append((rows, rows, 1, w, "cmd"))
    return lines, hit


def flat(pages):
    return [(p, i) for p in range(len(pages)) for i in range(len(pages[p]))]


def payload(pages, skipped, live=None, terms=None, w=100, rows=30):
    """The layout and what each tile shows, for --json and MCP's home."""
    cols, fit = columns(w), max(1, (rows - 3) // UNIT_H)
    out = []
    for n, (p, placed) in enumerate(screens_of(pages, cols, fit)):
        for i, x, y, tw, th in placed:
            t = pages[p][i]
            d = {"name": t["name"], "size": t["size"], "page": p, "screen": n, "x": x, "y": y}
            if t["name"].startswith(TERM):
                st = terms.get(t["name"][len(TERM):]) if terms else None
                d["shows"] = None if not st else {"runs": st["runs"], "last": st["last"],
                                                  "activity": ago(st["changed"])}
            elif live and (card.spec(t["name"]) or {}).get("state"):
                v, _warn = live.get(t["name"])
                d["shows"] = {"value": v, "why": live.why(t["name"]), "line": live.line(t["name"])}
            else:
                d["shows"] = {"summary": (cli.entries().get(t["name"]) or {}).get("summary", "")}
            out.append(d)
    return {"layout": line(pages), "pages": len(pages), "skipped": skipped, "tiles": out}


def layout_line(prof=None):
    """The profile's [home] layout, or the default."""
    if prof is None:
        prof = deckconf.load()[0] or {}
    v = (prof.get("home") or {}).get("layout")
    return v if isinstance(v, str) and v.strip() else DEFAULT


def snapshot():
    """The JSON --json prints and MCP's home returns: the values fetched
    once, side by side."""
    pages, skipped = parse(layout_line())
    names = [t["name"] for p in pages for t in p]
    live = card.Live([n for n in names if not n.startswith(TERM)])
    terms = Terms([n[len(TERM):] for n in names if n.startswith(TERM)], background=False)
    try:
        terms.read()
    except Exception:            # no zellij, no session: those tiles show "not open"
        pass
    deadline = time.time() + 12
    while time.time() < deadline and any(n not in live.got for n in live.names):
        time.sleep(0.2)
    live.stop()
    return payload(pages, skipped, live, terms)


def save(pages):
    """Keep the layout as the profile's [home] layout (a .bak first). None
    when kept, else why not."""
    text = line(pages)
    if deckconf.path() == deckconf.EXAMPLE:
        return "there's no profile yet: phosphor init"
    return None if deckconf.set_key("home", "layout", json.dumps(text)) else "couldn't write the profile"


def aside(fn):
    """Run fn with the pane to itself (zoomed in the deck) and the screen
    given back to the terminal; then back to the grid."""
    import zoom
    grew = zoom.here() and not zoom.zoomed()
    if grew:
        zoom.toggle()
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
    try:
        return fn()
    finally:
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J"); sys.stdout.flush()
        if grew:
            zoom.toggle()


def open_tile(t, live):
    """What Enter or a tap on a tile does: a tab's tile goes there, a card's
    taps it (card.tap, in the pane). What to say, or None."""
    if t["name"].startswith(TERM):
        import newtab
        if not os.environ.get("ZELLIJ"):
            return "not in the deck: phosphor attach, then home"
        newtab.zj("go-to-tab-name", t["name"][len(TERM):])
        return None
    import dash
    dash.run_card(t["name"], live)
    return None


def take(it, prof):
    """A suggestion of the command line, taken: newtab's kinds."""
    import newtab
    label, note, kind, what = it
    if kind == "tab":
        newtab.zj("go-to-tab-name", what)
        return None
    if kind == "workspace":
        return newtab.open_workspace(what)
    if kind == "command":
        import commands
        aside(lambda: commands.detail(*what, commands.manifest()))
        return None
    if kind == "web":
        argv = [sys.executable, PHOSPHOR, "read"] + what
    elif kind == "tool":
        argv = list(what[3])
    elif kind == "app":
        import apps
        argv = [apps.have(apps.exe(what))] + what.get("args", [])
    else:
        return None
    from ui import back
    aside(lambda: (subprocess.run(argv), back()))
    return None


ARROWS = {"\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
          "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left"}
PAGE = {"\x1b[5~": -1, "\x1b[6~": 1, "[": -1, "]": 1}


def items_for(prof):
    """What the command line finds: the + menu's search (newtab), without
    the menu's own entries."""
    import newtab
    return newtab.search_items(prof, [])


def suggestions(items, typing):
    import newtab
    return newtab.with_web(newtab.find(items, typing), typing) if typing.strip() else []


def main():
    import shutil
    args = sys.argv[1:]
    if "--json" in args:
        print(json.dumps(snapshot(), indent=2))
        return 0
    prof = deckconf.load()[0] or {}
    pages, skipped = parse(layout_line(prof))
    cards = [t["name"] for p in pages for t in p if not t["name"].startswith(TERM)]
    if "--once" in args or not sys.stdout.isatty():
        w, rows = shutil.get_terminal_size((80, 24))
        lines, _ = frame(pages, None, w, rows)
        print("\n".join(re.sub(r"\x1b\[[0-9;]*m", "", l).rstrip() for l in lines).rstrip())
        return 0
    if mono_term():
        mono_stdout()
    saved = copy.deepcopy(pages)
    live = card.Live(cards)
    terms = Terms(sorted({t["name"][len(TERM):] for p in pages for t in p if t["name"].startswith(TERM)}))
    at = (0, 0) if pages else None
    held = None                  # (pages, at) as they were when a tile was picked up
    typing, items, pick, found = None, None, 0, []
    msg = ("skipped: " + ", ".join(skipped)) if skipped else None
    prev = None
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    try:
        while True:
            w, rows = shutil.get_terminal_size((80, 24))
            if typing is not None:
                found = suggestions(items, typing)
                pick = max(0, min(pick, len(found) - 1))
            lines, hit = frame(pages, at, w, rows, live, terms, held is not None, typing, found, pick, msg)
            sys.stdout.write(paint(lines, prev)); sys.stdout.flush()
            prev = lines
            k = getkey(1.0, text=typing is not None, mouse=True, typeahead=True)   # a key typed while it gathered is for this screen too (#120)
            if k is None or k in ("WUP", "WDN"):
                continue
            msg = None
            scr = screens_of(pages, columns(w), max(1, (rows - 3) // UNIT_H))
            now = where(pages, scr, at)
            if isinstance(k, tuple):               # a tap
                _, x, y = k
                if typing is not None:
                    these = shown(found, rows)
                    n = y - (rows - 1 - len(these))
                    if 0 <= n < len(these):
                        msg, typing, prev = take(these[n], prof), None, None
                    elif y != rows:
                        typing = None
                    continue
                what = next((h[4] for h in hit if h[0] <= y <= h[1] and h[2] <= x <= h[3]), None)
                if what == "cmd" and held is None:
                    typing, pick = "", 0
                    items = items if items is not None else items_for(prof)
                elif isinstance(what, tuple) and what[0] == "page":
                    at = (scr[what[1]][0], scr[what[1]][1][0][0])
                elif isinstance(what, tuple) and held is None:
                    at = what
                    msg, prev = open_tile(pages[at[0]][at[1]], live), None
                continue
            if typing is not None:                 # the command line has the keys
                if k in ("\x1b", "\x03"):
                    typing = None
                elif k in ("\r", "\n"):
                    if found:
                        msg, prev = take(found[pick], prof), None
                    typing = None
                elif ARROWS.get(k) == "up":
                    pick = max(0, pick - 1)
                elif ARROWS.get(k) == "down":
                    pick += 1
                elif k in ("\x7f", "\x08"):
                    typing, pick = typing[:-1], 0
                elif k == "\x15":                    # Ctrl-u
                    typing, pick = "", 0
                elif k[0] >= " " and not k.startswith("\x1b"):
                    typing, pick = typing + k, 0
                continue
            if held is not None:                   # a tile picked up
                if k in ARROWS:
                    pages, at = move(pages, at, -1 if ARROWS[k] in ("left", "up") else 1)
                elif k in ("+", "="):
                    pages = resize(pages, at, 1)
                elif k in ("-", "_"):
                    pages = resize(pages, at, -1)
                elif k in ("\r", "\n"):
                    held = None
                    msg = "put down: s keeps it in your profile" if pages != saved else None
                elif k in ("\x1b", "\x03"):
                    (pages, at), held = held, None
                continue
            if k in ("q", "\x03"):
                return 0
            if k == "\x1b":
                import zoom
                if zoom.esc():
                    return 0
            elif k in ARROWS and at and scr:
                n = nearest(scr[now][1], at[1], ARROWS[k])
                if n is not None:
                    at = (at[0], n)
                elif ARROWS[k] in ("right", "down") and now + 1 < len(scr):
                    at = (scr[now + 1][0], scr[now + 1][1][0][0])
                elif ARROWS[k] in ("left", "up") and now > 0:
                    at = (scr[now - 1][0], scr[now - 1][1][-1][0])
            elif PAGE.get(k[:3]) or PAGE.get(k):
                d = PAGE.get(k[:3]) or PAGE.get(k)
                if 0 <= now + d < len(scr):
                    at = (scr[now + d][0], scr[now + d][1][0][0])
            elif k in ("\r", "\n") and at:
                msg, prev = open_tile(pages[at[0]][at[1]], live), None
            elif k == "m" and at:
                held = (copy.deepcopy(pages), at)
            elif k == "s":
                err = save(pages) if pages != saved else None
                msg = "nothing changed" if pages == saved else ("not kept: " + err) if err else \
                    "kept in your profile: [home] layout (the old one in deck.toml.bak)"
                if not err:
                    saved = copy.deepcopy(pages)
            elif k == "/":
                typing, pick = "", 0
                items = items if items is not None else items_for(prof)
            elif len(k) == 1 and k in KEYS and scr:
                n = KEYS.index(k)
                if n < len(scr[now][1]):
                    at = (scr[now][0], scr[now][1][n][0])
                    msg, prev = open_tile(pages[at[0]][at[1]], live), None
            elif k == "?":
                import tui
                tui.keys_help("HOME", [("arrows Enter", "pick a tile and open it (its key or a tap too)"),
                                       ("m", "pick it up: arrows move it, + - its size, Enter puts it down, Esc back"),
                                       ("s", "keep the layout in your profile ([home] layout)"),
                                       ("/", "the command line: a command, a tab, a tool"),
                                       ("PgUp PgDn [ ]", "the pages (a tap on the dots too)")])
                prev = None
    except KeyboardInterrupt:
        return 0
    finally:
        terms.stopped = True
        live.stop()
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n"); sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main() or 0)
