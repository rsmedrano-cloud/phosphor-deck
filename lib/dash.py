"""phosphor dash - a dashboard of your own: the cards you pick, live.

Every public command has a card (share/commands.json, lib/card.py): its
live value, the command that does the same in a terminal, and a tap. A
dashboard is a pane showing some of them, in your order:

    phosphor dash usage ci web screens        # in any terminal
    panes = [ { dash = ["usage", "ci"] } ]    # a pane in a profile tab

Each card is a box: its value big, the why behind a !, its first entries,
the command; the boxes fill the pane in rows and columns (grid). A key or a
tap zooms the pane and opens the card there; Esc in it comes back to the
boxes and gives the tab back.

+ opens the gallery (every card, each with its live value): Space picks,
a picks all, Enter applies, Esc cancels; beside the list, the card under
the cursor as it'll look in its pane (placed). - then a card's key takes
one away. In a profile tab (gen passes --tab),
a change is kept in deck.toml, the usual way (a .bak first).

The one-line list stays where boxes don't fit: piped (one line per card,
once), a screen with no color (e-ink), a pane narrower than a box. In a
pane too short for one card a line (zoom.short: a row of SYS), the cards
sit side by side under the title; the title's mark zooms (Alt-z), Esc
gives the tab back.
"""
import json, os, re, shutil, subprocess, sys, textwrap, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
from ui import getkey
import card, cli, deckconf, ui, zoom

PHOSPHOR = os.path.join(REPO, "phosphor")
KEYS = "123456789abcdefghijklmnoprstuvwyz"     # q leaves, + adds, - removes
KINDS = (("sensor", "sensors: a value, a tap opens it"), ("toggle", "toggles: on or off, a tap flips it"),
         ("button", "buttons: a tap runs it"), ("shortcut", "shortcuts: straight into a sub-screen"))


def gallery_names():
    """Every command a dashboard can hold: public, with a card that isn't
    plumbing, not on its way out. In kind order, then the manifest's."""
    gone = {d["name"] for d in cli.deprecations("command")}
    es = {n: e for n, e in cli.entries().items() if n not in gone}
    return [n for k, _ in KINDS for n, e in es.items() if (e.get("card") or {}).get("kind") == k]


def unknown(names):
    """The names no dashboard can hold, in order."""
    ok = set(gallery_names())
    return [n for n in names if n not in ok]


def values(names):
    """What --json prints: each card's state, its summary and its why."""
    out = []
    for n in names:
        raw, v, why = card.fetch(n)
        out.append({"name": n, "kind": card.spec(n)["kind"], "state": raw, "value": v, "why": why})
    return out


def row(key, name, live, w):
    """One card of a dashboard (or the gallery), w wide."""
    v, warn = live.get(name)
    e = cli.entries().get(name) or {}
    return card.line(key, name, v, "phosphor " + name, e.get("summary", ""), w, warn)


# ── this dashboard in the profile ──────────────────────────────
def swap(panes, old, new):
    """The panes with the first `dash = old` pane now `dash = new`; None if none is."""
    out, done = [], False
    for p in panes:
        if not done and isinstance(p, dict):
            if p.get("dash") == old:
                p, done = dict(p, dash=new), True
            elif "panes" in p:
                inner = swap(p["panes"], old, new)
                if inner is not None:
                    p, done = dict(p, panes=inner), True
        out.append(p)
    return out if done else None


def keep(tab, old, new, p=None):
    """Write the dashboard's new cards into its tab of the profile. None
    when written, else why not (and nothing was touched)."""
    import keep as k
    p = p or deckconf.path()
    if p == deckconf.EXAMPLE:
        return "there's no profile yet: phosphor init"
    text = open(p).read()
    prof = deckconf.tomllib.loads(text) if deckconf.tomllib else None
    if prof is None:
        return "no TOML parser: pip install --user tomli"
    t = next((t for t in prof.get("tabs", []) if t.get("name") == tab and deckconf.is_real_tab(t)), None)
    if t is None:
        return "%s isn't a tab of your profile (tabs.d's are kept in their own file)" % tab
    panes = swap(t.get("panes", []), old, new)
    if panes is None:
        return "%s has no dashboard with these cards any more" % tab
    blk = k.block(tab, panes, t.get("split"))
    return deckconf.write_profile(k.put(text, tab, blk),
                                  lambda pr: any(swap(x.get("panes", []), new, new) is not None
                                                 for x in pr.get("tabs", []) if x.get("name") == tab),
                                  expect=text, p=p)


# ── the screens ────────────────────────────────────────────────
def paint(lines, rows):
    lines = lines[:rows] + [""] * max(0, rows - len(lines))
    sys.stdout.write("\x1b[H" + "\x1b[K\n".join(lines) + "\x1b[K\x1b[J"); sys.stdout.flush()


def tapped(k):
    """("TAP", x, y) from getkey(mouse=True), or the row of a plain click."""
    if isinstance(k, tuple) and k[0] == "TAP":
        return k[2]
    return None


def tapped_at(k):
    """(x, y) of a tap, or None."""
    return (k[1], k[2]) if isinstance(k, tuple) and k[0] == "TAP" else None


def placed(name, picked, live, cell, pw, ph):
    """The card under the cursor the way the dashboard will draw it in a
    pane of cell (columns, rows), beside the cards picked so far: its box at
    that size (smaller if it doesn't fit pw x ph), or its line where the
    pane gets lines. Its lines, a caption under them, none wider than pw."""
    have = picked if name in picked else picked + [name]
    cw, ch = cell
    how = mode(have, cw, ch)
    where = "box %d of %d in a %d×%d pane" % (have.index(name) + 1, len(have), cw, ch)
    if how == "tiles" and pw >= TILE_W:
        _, tw, th, _ = grid(len(have), cw, ch - HEAD - 2)
        sw, sh = max(TILE_W, min(tw, pw)), max(TILE_H, min(th, ph - 3))
        lines = tile(KEYS[have.index(name)] if have.index(name) < len(KEYS) else "", name, live, sw, sh)
        note = "%s, %d×%d%s" % (where, tw, th, "" if (sw, sh) == (tw, th) else " (drawn smaller)")
    else:
        sw = min(pw, cw)
        lines = [row("", name, live, sw)]
        note = "%s, no room here to draw its box" % where if how == "tiles" else \
            "a line in a %d×%d pane: %s" % (cw, ch, "too short for boxes" if how == "short" else
                                               "no color here" if mono_term() else "too narrow for boxes")
    return [MUTE + "as it'll look" + RST] + lines + [DIM + l + RST for l in textwrap.wrap(note, max(12, sw))]


def gallery(have, rows=None, cols=None, enter="make the tab", cell=None):
    """Every card with its live value: Space or a tap picks one or takes it
    away, a all or none, Enter applies. The new list (its order kept, new
    ones last), or None for Esc: nothing changed. enter says what Enter
    does here, on the top bar and the footer; beside the list (under it on
    a narrow screen) the card under the cursor as it'll look in the pane it
    goes into: cell (columns, rows), this pane's own size when None."""
    names = gallery_names()
    live = card.Live(names, every=30)
    picked, sel, top = list(have), 0, 0
    tip = first_times("gallery", "Space marks the cards you want [x], then Enter: %s · Esc changes nothing" % enter)
    try:
        while True:
            c, r = shutil.get_terminal_size((60, 30))
            w, rows_ = cols or c, rows or r
            lw, side, below = w, [], []
            if w - GALLERY_W - 1 >= TILE_W:
                side = placed(names[sel], picked, live, cell or (w, rows_), w - GALLERY_W - 1, rows_ - 4)
                lw = w - max(vlen(l) for l in side) - 1
            elif rows_ >= 4 + 6 + TILE_H + 3:
                below = placed(names[sel], picked, live, cell or (w, rows_), w, min(TILE_H + 3, rows_ - 10))
            body, at = [], []                  # at: the card each body line is, or None
            for kind, title in KINDS:
                these = [n for n in names if card.spec(n)["kind"] == kind]
                if these:
                    body.append(rule(title, lw)); at.append(None)
                    for n in these:
                        mark = (PH + "[x]" if n in picked else DIM + "[ ]") + RST
                        line = row("", n, live, lw - 4)
                        idx = names.index(n)
                        body.append((AMB + ">" + RST if idx == sel else " ") + mark + line); at.append(idx)
            room = max(3, rows_ - 4 - len(below) - (1 if tip else 0))
            mine = next(i for i, a in enumerate(at) if a == sel)
            top = min(max(top, mine - room + 1), mine)
            lines = topbar("CARDS", "Space or a tap picks a card",
                           "%d picked · Enter: %s" % (len(picked), enter), w)
            shown = body[top:top + room]
            if side:
                import preview as pv
                shown = pv.beside(shown + [""] * (room - len(shown)), side[:room], lw)
            lines += shown
            if below:
                lines += [""] * max(0, 2 + room - len(lines)) + below
            lines += [""] * max(0, rows_ - (2 if tip else 1) - len(lines))
            if tip:
                lines.append(vcut(new_here(tip), w))
            lines.append(vcut(DIM + " ↑↓ · Space or tap: pick · a: all / none · Enter: %s · Esc: cancel"
                              % enter + RST, w))
            paint(lines, rows_)
            k = getkey(1.0, mouse=True)
            y = tapped(k)
            if y is not None and k[1] > lw:    # a tap on the preview
                continue
            if y is not None:
                i = y - 3 + top
                if 0 <= y - 3 < room and i < len(at) and at[i] is not None:
                    sel, k = at[i], " "
                else:
                    continue
            if k == "WUP" or k == "\x1b[A":
                sel = max(0, sel - (3 if k == "WUP" else 1))
            elif k == "WDN" or k == "\x1b[B":
                sel = min(len(names) - 1, sel + (3 if k == "WDN" else 1))
            elif k == " ":
                n = names[sel]
                picked = [x for x in picked if x != n] if n in picked else picked + [n]
            elif k == "a":                     # all, or none when all are picked already
                picked = [] if set(names) <= set(picked) else picked + [n for n in names if n not in picked]
            elif k in ("\r", "\n"):
                return picked
            elif k in ("q", "\x1b", "\x03"):
                return None
    finally:
        live.stop()


GALLERY_W = 46     # what the list keeps when the preview sits beside it
CELL = card.HEAD_W + card.LABEL_W + 1 + card.VALUE_W     # the narrowest card, side by side


def heading(names, w):
    """The topbar, its first line ending in zoom's mark."""
    count = "%d card%s" % (len(names), "" if len(names) == 1 else "s")
    lines = topbar("DASH", "your cards, live", count, w)
    if zoom.here():
        lines[0] = zoom.mark(topbar("DASH", "your cards, live", count, w - 3)[0], w)
    return lines


def draw_short(names, live, w, rows, msg=None, removing=False):
    """A pane a few rows high: the title, then the cards side by side,
    as many to a line as fit. Its lines and tap targets ({(row, column):
    key}, cell width); a tap on the title or on "+N more" zooms."""
    per = max(1, (w + 1) // (CELL + 1))
    cw = (w + 1) // per - 1
    room = max(1, rows - 1 - (1 if msg or removing else 0)) * per
    shown = names if len(names) <= room else names[:room - 1]
    cells = [(KEYS[i], row(KEYS[i], n, live, cw)) for i, n in enumerate(shown)]
    if len(shown) < len(names):
        cells.append((None, DIM + "  +%d more · a tap shows them all" % (len(names) - len(shown)) + RST))
    lines, hit = heading(names, w)[:1], {}
    for i in range(0, len(cells), per):
        for j, (key, _) in enumerate(cells[i:i + per]):
            if key:
                hit[(len(lines) + 1, j)] = key
        lines.append(" ".join(pad(vcut(t, cw), cw) for _, t in cells[i:i + per]))
    if not names:
        lines.append(vcut("  " + FG + "no cards yet: " + AMB + "+" + RST + FG + " picks some" + RST, w))
    if msg or removing:
        lines.append(vcut(" " + (DIM + "which one? its key · Esc: none" if removing else
                                 (OK if msg.startswith("kept") else WARN) + msg) + RST, w))
    return lines[:rows], (hit, cw)


def draw(names, live, w, rows, msg=None, removing=False):
    """The dashboard's lines and its tap targets {row: key}."""
    lines, hit = heading(names, w), {}
    if not names:
        lines.append("")
        lines.append(vcut("  " + FG + "no cards yet: " + AMB + "+" + RST + FG + " picks some from the gallery" + RST, w))
        hit[len(lines)] = "+"
    for key, n in zip(KEYS, names):
        lines.append(row(key, n, live, w)); hit[len(lines)] = key
    whys = [(n, live.why(n)) for n in names if live.why(n)]
    if whys:
        lines.append("")
        for n, why in whys:
            lines.append(vcut("  " + AMB + "! " + n + RST + "  " + FG + why + RST, w))
    lines += [""] * max(0, rows - 2 - len(lines))
    lines.append(vcut(" " + (OK if msg.startswith("kept") else WARN) + " " + msg + RST, w) if msg else "")
    lines.append(vcut(DIM + (" which one? its key or a tap · Esc: none" if removing else
                             " a key or a tap opens it · + add a card · - take one away · q leave") + RST, w))
    hit[rows] = "+" if not removing else None
    return lines[:rows], hit


TILE_W, TILE_H = 22, 4     # the smallest box: a border, the value, the command, a border
BOLD = "\x1b[1m"


def grid(n, w, h):
    """How n boxes fill w x h: (columns, box width, box height, box rows
    that fit). As square as a terminal cell allows, an empty slot costs
    a box's width; when they don't fit at TILE_H, the smallest ones and
    the rest a scroll away."""
    best = None
    for c in range(1, n + 1):
        tw = (w + 1) // c - 1
        if tw < TILE_W:
            break
        r = -(-n // c)
        th = h // r
        if th < TILE_H:
            continue
        score = abs(tw - 2.5 * th) + (r * c - n) * tw
        if best is None or score < best[0]:
            best = (score, c, tw, th, r)
    if best:
        return best[1:]
    c = max(1, (w + 1) // (TILE_W + 1))
    return c, (w + 1) // c - 1, TILE_H, max(1, h // TILE_H)


def tile(key, name, live, tw, th):
    """One card as a box tw x th: key and name on the border (and ! when it
    wants a look), its value big, the why, its first entries or what the
    command does, and the command at the foot."""
    v, warn = live.get(name)
    why, iw, ih = live.why(name), tw - 2, th - 2
    top = []
    if (card.spec(name) or {}).get("state"):
        top.append(" " + BOLD + (AMB if warn else BLOOM) + (v or "–") + RST)
        if why:
            top.append(" " + AMB + "! " + RST + FG + why + RST)
        room = ih - 1 - len(top)
        more = [" " + l for l in card.detail(live.raw(name), iw - 1, room)]
    else:
        about = (cli.entries().get(name) or {}).get("summary", "")
        more = [" " + DIM + l + RST for l in textwrap.wrap(about, max(8, iw - 1))]
        more = more[:max(0, ih - 1)]
    body = (top + more)[:max(1, ih - 1)]
    if ih >= 2:
        body += [""] * (ih - 1 - len(body)) + [" " + DIM + "phosphor " + name + RST]
    title = (key + " " if key else "") + name
    return ui.card(title, "!" if warn else "", [vcut(l, iw) for l in body], tw, AMB)


def draw_tiles(names, live, w, rows, msg=None, removing=False, first=0):
    """The dashboard as boxes filling the pane: its lines, tap targets
    [(top, bottom, left, right, what)] (a card's index, or + on the foot)
    and the first box row shown (first, kept in range)."""
    lines = heading(names, w)
    cols, tw, th, fit = grid(len(names), w, rows - HEAD - 2)
    total = -(-len(names) // cols)
    first = max(0, min(first, total - fit))
    hit = []
    for gr in range(first, min(total, first + fit)):
        these = range(gr * cols, min(len(names), (gr + 1) * cols))
        boxes = [tile(KEYS[i] if i < len(KEYS) else "", names[i], live, tw, th) for i in these]
        y = len(lines) + 1
        for j, i in enumerate(these):
            hit.append((y, y + th - 1, j * (tw + 1) + 1, j * (tw + 1) + tw, i))
        lines += [" ".join(b[r] for b in boxes) for r in range(th)]
    lines += [""] * max(0, rows - 2 - len(lines))
    lines.append(vcut(" " + (OK if msg.startswith("kept") else WARN) + " " + msg + RST, w) if msg else "")
    more = " · ↑↓ more" if total > fit else ""
    lines.append(vcut(DIM + (" which one? its key or a tap · Esc: none" if removing else
                             " a key or a tap opens it · + add · - take one away · q leave" + more) + RST, w))
    if not removing:
        hit.append((rows, rows, 1, w, "+"))
    return lines[:rows], hit, first


def mode(names, w, rows):
    """How the dashboard draws in a pane w x rows: short, list or tiles."""
    if zoom.short(rows):
        return "short"
    if not names or mono_term() or w < TILE_W:
        return "list"
    return "tiles"


def printed(names, w):
    """The dashboard piped: one line per card, then the whys, no color."""
    plain = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s).rstrip()
    out, whys = [], []
    for d in values(names):
        e = cli.entries().get(d["name"]) or {}
        out.append(plain(card.line("", d["name"], d["value"], "phosphor " + d["name"],
                                   e.get("summary", ""), w, bool(d["why"]))))
        if d["why"]:
            whys.append("  ! %s  %s" % (d["name"], d["why"]))
    return "\n".join(out + ([""] + whys if whys else []))


def run_card(name, live):
    """A tap on a card: the pane takes the whole tab, card.tap in it, then
    back here and the tab given back: at once from a screen of the card's
    own (Esc or q in it), after q, Esc or Enter from output to be read."""
    grew = zoom.here() and not zoom.zoomed()
    if grew:
        zoom.toggle()
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
    try:
        r = card.tap(name, live.raw(name))
        if r is not None and card.waits(name):
            back()
    finally:
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J"); sys.stdout.flush()
        if grew:
            zoom.toggle()


def main():
    args = sys.argv[1:]
    tab = None
    if "--tab" in args:
        i = args.index("--tab")
        tab = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    as_json = "--json" in args
    names = list(dict.fromkeys(a for a in args if a != "--json"))
    bad = unknown(names)
    if bad:
        print("phosphor dash: no card for %s (+ in a dashboard shows every card there is)"
              % ", ".join(bad), file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(values(names), indent=1)); return 0
    if not sys.stdout.isatty() and names:
        print(printed(names, shutil.get_terminal_size((100, 24)).columns)); return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("phosphor dash needs a terminal (or --json)"); return 1
    mono_stdout()
    live = card.Live(names)
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    msg, removing, first = None, False, 0
    try:
        if not names:
            names = gallery([], enter="show them") or []
            live.set(names)
            msg = save(tab, [], names)
        while True:
            w, rows = shutil.get_terminal_size((60, 30))
            how = mode(names, w, rows)
            short = how == "short"
            if how == "tiles":
                lines, hit, first = draw_tiles(names, live, w, rows, msg, removing, first)
            else:
                lines, hit = (draw_short if short else draw)(names, live, w, rows, msg, removing)
            paint(lines, rows)
            k = getkey(1.0, mouse=True)
            at = tapped_at(k)
            if at is not None:
                x, y = at
                if zoom.on_mark(x, y, w) or (short and y == 1):
                    zoom.toggle(); continue
                if short:
                    cells, cw = hit
                    k = cells.get((y, (x - 1) // (cw + 1)))
                    if k is None and y > 1:
                        zoom.toggle(); continue      # "+N more", or between cards
                elif how == "tiles":
                    k = next((t for top, bot, l, r, t in hit if top <= y <= bot and l <= x <= r), None)
                else:
                    k = hit.get(y)
            if how == "tiles" and k in ("WUP", "WDN", "\x1b[A", "\x1b[B"):
                first += -1 if k in ("WUP", "\x1b[A") else 1
                continue
            if k is None or k in ("WUP", "WDN"):
                continue
            if k == "\x1b" and not removing and zoom.back():
                continue
            i = k if isinstance(k, int) else KEYS.index(k) if k in KEYS[:len(names)] else None
            msg = None
            if removing:
                removing = False
                if i is not None:
                    old, names = names, names[:i] + names[i + 1:]
                    live.set(names); msg = save(tab, old, names)
            elif k == "-" and names:
                removing = True
            elif k == "+":
                grew = short and not zoom.zoomed()
                if grew:
                    zoom.toggle()                    # the gallery needs the whole tab
                new = gallery(names, enter="update the tab" if tab else "show them")
                if grew:
                    zoom.toggle()
                if new is not None:
                    old, names = names, new
                    live.set(names); msg = save(tab, old, names)
            elif k in ("q", "\x1b", "\x03"):
                return 0
            elif i is not None:
                run_card(names[i], live)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n"); sys.stdout.flush()


def save(tab, old, new):
    """Keep a change when this dashboard is a profile tab's, then gen (the
    deck's layouts follow the profile; the restart stays yours). What to
    say about it, or None for nothing to say."""
    if not tab or old == new:
        return None
    err = keep(tab, old, new)
    if err:
        return "not kept: " + err
    subprocess.run([sys.executable, PHOSPHOR, "gen"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "kept in your profile (%s)" % tab


if __name__ == "__main__":
    sys.exit(main() or 0)
