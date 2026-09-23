"""Shared palette and drawing helpers.

The palette comes from `theme` in the profile's [deck]; PHOSPHOR_THEME
overrides it for a quick try. The names are the phosphors of old monitors:
P31 green, P3 amber, P4 white.
"""
import os, re, select, shutil, sys, termios, tty
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def share(name):
    """A data file: a copy in ~/.local/share/phosphor overrides the repo's.
    Only put one there on purpose — a stale copy hides every repo update."""
    user = os.path.join(deckconf.data_dir(), name)
    return user if os.path.exists(user) else os.path.join(REPO, "share", name)

PALETTES = {
    # P31: the green of VT terminals and oscilloscopes
    "p31":   {"fg": (168, 229, 176), "dim": (74, 110, 83),   "mute": (107, 154, 118),
              "ph": (51, 255, 68),   "bloom": (102, 255, 119), "warn": (255, 176, 0),
              "bad": (255, 51, 68),  "rule": (27, 50, 38),   "bg": (5, 11, 6)},
    # P3: the amber of the IBM 5151 and Wyse terminals
    "p3":    {"fg": (240, 200, 140), "dim": (112, 78, 28),   "mute": (176, 128, 56),
              "ph": (255, 176, 0),   "bloom": (255, 204, 77), "warn": (255, 110, 40),
              "bad": (255, 51, 51),  "rule": (52, 36, 12),   "bg": (12, 8, 0)},
    # P4: the bluish white of black-and-white terminals
    "p4":    {"fg": (200, 208, 214), "dim": (84, 90, 96),    "mute": (130, 138, 146),
              "ph": (236, 242, 248), "bloom": (255, 255, 255), "warn": (255, 176, 0),
              "bad": (255, 51, 68),  "rule": (38, 42, 46),   "bg": (8, 9, 10)},
    # paper: e-ink screens, dark ink on white
    "paper": {"fg": (26, 26, 26),    "dim": (120, 120, 120), "mute": (58, 58, 58),
              "ph": (31, 90, 40),    "bloom": (0, 0, 0),     "warn": (107, 74, 0),
              "bad": (138, 26, 34),  "rule": (180, 180, 180), "bg": (255, 255, 255)},
}
ALIASES = {"green": "p31", "amber": "p3", "white": "p4"}

def theme_name(prof=None):
    t = os.environ.get("PHOSPHOR_THEME")
    if not t:
        if prof is None:
            prof, _ = deckconf.load()
        t = ((prof or {}).get("deck") or {}).get("theme", "p31")
    t = ALIASES.get(t, t)
    return t if t in PALETTES else "p31"

THEME = theme_name()

def rgb(r, g, b): return "\x1b[38;2;%d;%d;%dm" % (r, g, b)
def hexc(c): return "#%02X%02X%02X" % tuple(c)

_PAL = PALETTES[THEME]
FG, DIM, MUTE = rgb(*_PAL["fg"]), rgb(*_PAL["dim"]), rgb(*_PAL["mute"])
PH, BLOOM, AMB, RED, RULE = (rgb(*_PAL[k]) for k in ("ph", "bloom", "warn", "bad", "rule"))
RST = "\x1b[0m"
OK, WARN, BAD = PH + "✓" + RST, AMB + "⚠" + RST, RED + "✗" + RST

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
def vlen(s): return len(_ANSI.sub("", s))
def pad(s, w): return s + " " * max(0, w - vlen(s))
def width(cap=100): return min(shutil.get_terminal_size((80, 24)).columns, cap)

def getkey(timeout=None):
    """One key from the terminal, read straight from the fd.

    Reading through sys.stdin buffers a whole escape sequence on the first
    read(1), so a following select() sees nothing and an arrow key looks
    like a lone Esc. Returns None on timeout, the full sequence for
    special keys ("\x1b[A" up, "\x1b[B" down...), "\x1b" for Esc,
    ("MOUSE", button, x, y, pressed) for SGR mouse events, else the char."""
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if not select.select([fd], [], [], timeout)[0]:
            return None
        data = os.read(fd, 64)
        while data.startswith(b"\x1b") and select.select([fd], [], [], 0.02)[0] and len(data) < 64:
            data += os.read(fd, 64)                       # a sequence split in two writes
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    s = data.decode("utf-8", "ignore")
    m = re.match(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])", s)
    if m:
        return ("MOUSE", int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) == "M")
    if s.startswith("\x1b[") or s.startswith("\x1bO"):
        return s[:3] if len(s) >= 3 else s
    return s[:1] if s else None

def rule(title, w=None):
    w = w or width()
    h = "── " + title + " "
    return RULE + h + "─" * max(0, w - len(h)) + RST

def row(sym, label, value, w=None, note=""):
    w = w or width()
    line = "  %s %s" % (sym, FG + ("%-26s" % label) + RST)
    line += MUTE + value + RST
    if note:
        space = w - vlen(line) - len(note) - 2
        if space >= 2:
            line = pad(line, w - len(note) - 2) + DIM + note + RST
        else:                      # doesn't fit beside it: goes below, indented
            line += "\n" + " " * 31 + DIM + note + RST
    return line
