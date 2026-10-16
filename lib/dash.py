"""phosphor dash - a dashboard of your own: the cards you pick, live.

Every public command has a card (share/commands.json, lib/card.py): its
live value, the command that does the same in a terminal, and a tap. A
dashboard is a pane showing some of them, in your order:

    phosphor dash usage ci web screens        # in any terminal
    panes = [ { dash = ["usage", "ci"] } ]    # a pane in a profile tab

+ opens the gallery (every card, each with its live value) to add one,
- then a card's key takes one away. In a profile tab (gen passes --tab),
a change is kept in deck.toml, the usual way (a .bak first).
"""
import json, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
from ui import getkey
import card, cli, deckconf

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


def gallery(have, rows=None, cols=None):
    """Every card with its live value; Enter or a tap adds or takes one
    away. The dashboard's new list (its order kept, new ones last), or
    None for Esc with nothing changed."""
    names = gallery_names()
    live = card.Live(names, every=30)
    picked, sel, top = list(have), 0, 0
    try:
        while True:
            c, r = shutil.get_terminal_size((60, 30))
            w, rows_ = cols or c, rows or r
            body, at = [], []                  # at: the card each body line is, or None
            for kind, title in KINDS:
                these = [n for n in names if card.spec(n)["kind"] == kind]
                if these:
                    body.append(rule(title, w)); at.append(None)
                    for n in these:
                        mark = (PH + "[x]" if n in picked else DIM + "[ ]") + RST
                        line = row("", n, live, w - 4)
                        idx = names.index(n)
                        body.append((AMB + ">" + RST if idx == sel else " ") + mark + line); at.append(idx)
            room = max(3, rows_ - 4)
            mine = next(i for i, a in enumerate(at) if a == sel)
            top = min(max(top, mine - room + 1), mine)
            lines = topbar("CARDS", "every card, live; Enter or a tap adds it", "%d picked" % len(picked), w)
            lines += body[top:top + room]
            lines += [""] * max(0, rows_ - 1 - len(lines))
            lines.append(DIM + " ↑↓ · Enter or tap: add / take away · q Esc: done" + RST)
            paint(lines, rows_)
            k = getkey(1.0, mouse=True)
            y = tapped(k)
            if y is not None:
                i = y - 3 + top
                if 0 <= y - 3 < room and i < len(at) and at[i] is not None:
                    sel, k = at[i], "\r"
                else:
                    continue
            if k == "WUP" or k == "\x1b[A":
                sel = max(0, sel - (3 if k == "WUP" else 1))
            elif k == "WDN" or k == "\x1b[B":
                sel = min(len(names) - 1, sel + (3 if k == "WDN" else 1))
            elif k in ("\r", "\n", " "):
                n = names[sel]
                picked = [x for x in picked if x != n] if n in picked else picked + [n]
            elif k in ("q", "\x1b", "\x03"):
                return picked if picked != list(have) else None
    finally:
        live.stop()


def draw(names, live, w, rows, msg=None, removing=False):
    """The dashboard's lines and its tap targets {row: key}."""
    lines, hit = topbar("DASH", "your cards, live", "%d card%s" % (len(names), "" if len(names) == 1 else "s"), w), {}
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


def run_card(name, live):
    """A tap on a card: card.tap in this pane, then back here."""
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\x1b[2J\x1b[H"); sys.stdout.flush()
    try:
        r = card.tap(name, live.raw(name))
        if r is not None:
            back()
    finally:
        sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[2J"); sys.stdout.flush()


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
    if not sys.stdin.isatty():
        print("phosphor dash needs a terminal (or --json)"); return 1
    mono_stdout()
    live = card.Live(names)
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    msg, removing = None, False
    try:
        if not names:
            names = gallery([]) or []
            live.set(names)
            msg = save(tab, [], names)
        while True:
            w, rows = shutil.get_terminal_size((60, 30))
            lines, hit = draw(names, live, w, rows, msg, removing)
            paint(lines, rows)
            k = getkey(1.0, mouse=True)
            y = tapped(k)
            if y is not None:
                k = hit.get(y)
            if k is None or k in ("WUP", "WDN"):
                continue
            msg = None
            if removing:
                removing = False
                if k in KEYS[:len(names)]:
                    old, names = names, [n for n in names if n != names[KEYS.index(k)]]
                    live.set(names); msg = save(tab, old, names)
            elif k == "-" and names:
                removing = True
            elif k == "+":
                new = gallery(names)
                if new is not None:
                    old, names = names, new
                    live.set(names); msg = save(tab, old, names)
            elif k in ("q", "\x1b", "\x03"):
                return 0
            elif k in KEYS[:len(names)]:
                run_card(names[KEYS.index(k)], live)
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
