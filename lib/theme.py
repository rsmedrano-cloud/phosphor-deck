"""phosphor theme - pick the deck's color with a preview. Project Phosphor Deck.

    phosphor theme            the picker: ↑↓, j/k or a tap previews, Enter keeps it
    phosphor theme NAME       set it straight away (p31, p3, p4, ega, paper)
    phosphor theme --list     the themes, with a swatch each

Moving through the list repaints a small deck in that phosphor, on its own
background, before anything is written. Enter saves `theme` in [deck] (the
same one-line edit `phosphor setup` makes, backup included) and offers
`phosphor gen` and a restart; q leaves the profile as it was.
"""
import os, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

def names():
    import deck_setup
    return [k for k, _ in deck_setup.THEMES]

def cut(s, w):
    """s cut to w visible characters, its color codes kept (a phone's pane
    can be narrower than a fleet card)."""
    out, n, i = [], 0, 0
    while i < len(s) and n < w:
        m = re.match(r"\x1b\[[0-9;]*m", s[i:])
        if m:
            out.append(m.group()); i += m.end(); continue
        out.append(s[i]); n += 1; i += 1
    return "".join(out)

def preview(name, w=60):
    """A few lines of a deck painted in NAME's palette, each exactly w wide,
    on that theme's own background: what the tab bar, a fleet card, a note
    and the ok/warn/bad marks look like before choosing it."""
    P = PALETTES[name]
    bg = "\x1b[48;2;%d;%d;%dm" % P["bg"]
    c = lambda k: rgb(*P[k])
    def line(*parts):
        text = cut("".join(parts), w)
        return bg + text + bg + " " * max(0, w - vlen(text)) + RST
    rev = "\x1b[48;2;%d;%d;%dm" % P["ph"] + rgb(*P["bg"])
    tabs = " " + rev + " SYS " + bg + c("mute") + "  DECK   NOTES   CLOUD" + c("dim") + "   +"
    bars = c("ph") + "▁▂▃▅▇▅▃▂" + c("bloom") + "▇"
    return [
        line(tabs),
        line(" ", c("rule"), "── fleet ", "─" * max(0, w - 11)),
        line("  ", c("ph"), "✓ ", c("fg"), "%-9s" % "db-box", c("mute"), "work     ",
             bars, c("fg"), "  12%  ", c("mute"), "41°C"),
        line("  ", c("warn"), "⚠ ", c("fg"), "%-9s" % "nimbus", c("mute"), "storage  ",
             c("warn"), "disk 91%", c("dim"), "  SMART ok"),
        line("  ", c("bad"), "✗ ", c("fg"), "%-9s" % "relay", c("mute"), "node     ",
             c("bad"), "unreachable", c("dim"), " · 25s"),
        line(" ", c("rule"), "── notes ", "─" * max(0, w - 11)),
        line("  ", c("bloom"), "TODO ", c("fg"), "back up the NAS", c("dim"), "  · from SYS"),
        line("  ", c("dim"), "the profile is the only source of truth"),
    ]

def listing():
    import deck_setup
    cur = theme_name()
    for k, d in deck_setup.THEMES:
        mark = PH + "›" + RST if k == cur else " "
        print("  %s %-6s %s  %s" % (mark, k, deck_setup.swatch(k), DIM + d + RST))
    return 0

def set_theme(name):
    """Write theme = NAME into [deck]; True when the file changed."""
    import deck_setup
    p = deckconf.path()
    text = open(p).read()
    if (deckconf.tomllib.loads(text).get("deck") or {}).get("theme") == name:
        print(row(OK, "theme", name, note="already")); return False
    return deck_setup.save(deck_setup.set_theme_text(text, name),
                           lambda pr: (pr.get("deck") or {}).get("theme") == name)

def pick(current):
    """The full-screen picker. Returns the theme chosen, or None for back."""
    import deck_setup
    themes = deck_setup.THEMES
    keys = [k for k, _ in themes]
    sel = keys.index(current) if current in keys else 0
    top = 4                        # the first theme's row (1-based): blank, title, back
    try:
        while True:
            cols = shutil.get_terminal_size((70, 24)).columns
            w = max(20, min(cols - 4, 72))
            lines = ["", BLOOM + "  phosphor theme" + RST + DIM + "   the deck's color" + RST,
                     "  " + AMB + "< back" + RST + DIM + "   (q: leave it as it was)" + RST]
            for i, (k, d) in enumerate(themes):
                now = DIM + "  (now)" + RST if k == current else ""
                t = "%-6s %s  " % (k, deck_setup.swatch(k))
                if i == sel:
                    lines.append("  " + PH + "› " + RST + BLOOM + t + RST + FG + d + RST + now)
                else:
                    lines.append("    " + FG + t + RST + DIM + d + RST + now)
            lines += [""] + ["  " + l for l in preview(keys[sel], w)] + [""]
            lines.append("  " + DIM + "↑↓ or a tap: preview · " + RST + AMB + "Enter" + RST
                         + DIM + " keeps " + RST + BLOOM + keys[sel] + RST + DIM + " · q: back" + RST)
            sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J"
                             + "\n".join(lines))
            sys.stdout.flush()
            k = getkey(None)
            if k is None:
                return None
            if isinstance(k, tuple):
                if not k[4] or k[1] != 0: continue
                r = k[3]
                if r == 3: return None
                if top <= r < top + len(keys):
                    if sel == r - top: return keys[sel]    # a second tap on it keeps it
                    sel = r - top
                continue
            if k in ("q", "\x1b", "\x03", "\x04"): return None
            if k in ("j", "\x1b[B"): sel = (sel + 1) % len(keys)
            elif k in ("k", "\x1b[A"): sel = (sel - 1) % len(keys)
            elif k.isdigit() and 0 < int(k) <= len(keys): sel = int(k) - 1
            elif k in ("\r", "\n"): return keys[sel]
    finally:
        sys.stdout.write("\x1b[?1000l\x1b[?1006l\x1b[?25h\x1b[?1049l"); sys.stdout.flush()

def refuse_here(prof):
    """Why this machine can't change the deck's color, or None."""
    if ((prof or {}).get("deck") or {}).get("demo"):
        return "this is the demo's profile: its color stays as phosphor demo set it"
    loc = next((h for h in (prof or {}).get("hosts", []) if h.get("local")), None)
    if not loc or loc.get("role") != "brain":
        return "the color belongs to the brain, where the deck lives: run it there"
    return None

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip().split("\n\n")[1]); return 0
    if argv and argv[0] in ("--list", "-l"):
        return listing()
    prof, p = deckconf.load()
    if prof is None or p == deckconf.EXAMPLE:     # never write the repo's example
        print("  no profile yet: phosphor init"); return 1
    cur = theme_name(prof)
    if argv:
        name = ALIASES.get(argv[0], argv[0])
        if name not in names():
            print(row(BAD, "no such theme", argv[0], note=" · ".join(names()))); return 2
        why = refuse_here(prof)
        if why:
            print("  " + why); return 1
        if set_theme(name):
            print("    " + DIM + "phosphor gen && phosphor restart shows it everywhere "
                  "(or f in the DECK tab)" + RST)
        return 0
    if not sys.stdin.isatty():
        return listing()
    why = refuse_here(prof)
    choice = pick(cur)
    if choice is None or choice == cur:
        return 0
    if why:
        print("  " + why); return 1
    if set_theme(choice):
        import deck_setup
        deck_setup.apply([], [])
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
