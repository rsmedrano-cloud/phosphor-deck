"""phosphor screen --probe - what this screen can draw. Project Phosphor Deck.

    ssh -t you@brain '~/.local/bin/phosphor screen --probe'

One page, printed once, numbered: the lines, blocks, Braille and marks the
deck draws with, its colors, and a few lines of the deck in its own theme
and in paper. Run on a screen nobody has tried yet (an e-ink reader, a Pi
Zero's console), it turns "it looks off" into a report: the numbers that
look wrong, and line 0. Nothing is written, nothing waits for a key.

The rows that use 24-bit color come last: a client that misreads them
(some e-ink ssh clients turn the numbers into bold or reverse) then only
spoils the rows after it, and that is itself the answer.
"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *

def rows(cols, theme):
    """The probe's lines, each (number, label, sample); number None for a
    line that only goes with the one above it."""
    import theme as themes
    w = max(20, min(cols - 4, 60))
    out = [
        (1, "lines", "┌─┬─┐ ╔═╗ ├┼┤ ║ └─┴─┘ ╚═╝"),
        (2, "blocks", "▁▂▃▄▅▆▇█  ▏▎▍▌▋▊▉  ░▒▓"),
        (3, "braille", "⣀⣠⣤⣴⣶⣾⣿ ⡇⢸ ⠁⠂⠄⡀"),
        (4, "marks", "✓ ⚠ ✗ ● ○ ◆ ▸ › · … ↑↓←→"),
        (5, "attrs", "\x1b[1mbold\x1b[0m \x1b[2mdim\x1b[0m \x1b[7mreverse\x1b[0m "
                     "\x1b[4munder\x1b[0m"),
        (6, "16 colors", "".join("\x1b[%dm  " % (40 + i) for i in range(8)) + RST + " "
                         + "".join("\x1b[%dm  " % (100 + i) for i in range(8)) + RST),
        (7, "256 colors", "".join("\x1b[48;5;%dm " % c for c in range(232, 256)) + RST),
        (8, "24-bit", "".join("\x1b[48;2;%d;%d;%dm " % (i * 10, 255 - i * 10, 128)
                              for i in range(24)) + RST),
    ]
    n = 9
    for name in dict.fromkeys((theme, "paper")):
        lines = themes.preview(name, w)
        out.append((n, "deck, " + name, ""))
        out += [(None, "", l) for l in lines]
        n += 1
    return out

def main():
    cols, lines = shutil.get_terminal_size((80, 24))
    env = lambda k: os.environ.get(k) or "-"
    print(BLOOM + "phosphor screen --probe" + RST + DIM + " · what this screen draws" + RST)
    print(" 0  TERM %s  COLORTERM %s  LANG %s  %dx%d%s" % (
        env("TERM"), env("COLORTERM"), os.environ.get("LC_ALL") or env("LANG"), cols, lines,
        "  NO_COLOR" if os.environ.get("NO_COLOR") else ""))
    for n, label, sample in rows(cols, THEME):
        if n is None:
            print("    " + sample)
        else:
            print("%2d  %-10s %s" % (n, label, sample) if sample else "%2d  %s" % (n, label))
    print(DIM + "Report the numbers that look wrong (a box, a ?, nothing, the wrong color),"
          " and line 0." + RST)
    return 0

if __name__ == "__main__":
    sys.exit(main())
