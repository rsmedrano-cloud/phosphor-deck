"""Shared palette and drawing helpers.

The palette comes from `theme` in the profile's [deck]; PHOSPHOR_THEME
overrides it for a quick try. The names are the phosphors of old monitors:
P31 green, P3 amber, P4 white. EGA is the one that isn't a phosphor: the
16 colors of a PC's EGA card, so it's the only theme in more than one hue.
"""
import os, re, select, shutil, sys, termios, time, tty
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
    # EGA: the 16-color PC card -- light grey text, bright green and cyan,
    # blue rules. The only theme in more than one hue.
    "ega":   {"fg": (170, 170, 170), "dim": (85, 85, 85),    "mute": (0, 170, 170),
              "ph": (85, 255, 85),   "bloom": (85, 255, 255), "warn": (255, 255, 85),
              "bad": (255, 85, 85),  "rule": (0, 0, 170),    "bg": (0, 0, 0)},
    # paper: e-ink screens, dark ink on white
    "paper": {"fg": (26, 26, 26),    "dim": (120, 120, 120), "mute": (58, 58, 58),
              "ph": (31, 90, 40),    "bloom": (0, 0, 0),     "warn": (107, 74, 0),
              "bad": (138, 26, 34),  "rule": (180, 180, 180), "bg": (255, 255, 255)},
}
ALIASES = {"green": "p31", "amber": "p3", "white": "p4"}

# A terminal's 16 ANSI colors, for a theme that has its own (the web client
# is a terminal of its own, so programs in it draw with these). The
# phosphors map those slots onto their one hue instead (gen.web_block).
ANSI = {
    "ega": {"black": (0, 0, 0), "red": (170, 0, 0), "green": (0, 170, 0), "yellow": (170, 85, 0),
            "blue": (0, 0, 170), "magenta": (170, 0, 170), "cyan": (0, 170, 170), "white": (170, 170, 170),
            "bright_black": (85, 85, 85), "bright_red": (255, 85, 85), "bright_green": (85, 255, 85),
            "bright_yellow": (255, 255, 85), "bright_blue": (85, 85, 255), "bright_magenta": (255, 85, 255),
            "bright_cyan": (85, 255, 255), "bright_white": (255, 255, 255)},
}

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
def vcut(s, w):
    """s cut to w visible columns, its colors kept: a line that would
    otherwise wrap in a pane narrower than it was drawn for."""
    if vlen(s) <= w:
        return s
    out, n, i = [], 0, 0
    for m in _ANSI.finditer(s):
        take = s[i:m.start()][:max(0, w - n)]
        out.append(take); n += len(take)
        out.append(m.group()); i = m.end()
    out.append(s[i:][:max(0, w - n)])
    return "".join(out) + RST
def width(cap=100): return min(shutil.get_terminal_size((80, 24)).columns, cap)

def getkey(timeout=None, text=False, mouse=False):
    """One key from the terminal, read straight from the fd. The only
    keyboard reader: every screen goes through it.

    Reading through sys.stdin buffers a whole escape sequence on the first
    read(1), so a following select() sees nothing and an arrow key looks
    like a lone Esc. Returns None on timeout, the full sequence for
    special keys ("\x1b[A" up, "\x1b[B" down...), "\x1b" for Esc,
    ("MOUSE", button, x, y, pressed) for SGR mouse events, else the char --
    or, with text=True, every char that came at once (a paste).

    With mouse=True a mouse event comes simplified: "WUP"/"WDN" for the
    wheel or a two-finger scroll, ("TAP", x, y) for a tap or left click,
    None for anything else (a release, a drag, another button)."""
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
        b, x, y, down = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) == "M"
        if not mouse:
            return ("MOUSE", b, x, y, down)
        if not down: return None
        return {64: "WUP", 65: "WDN"}.get(b) or (("TAP", x, y) if b == 0 else None)
    if s.startswith("\x1b[") or s.startswith("\x1bO"):
        return s[:3] if len(s) >= 3 else s
    if text and s and s[0] >= " ":
        return s
    return s[:1] if s else None

def quiet():
    """For a panel that only draws: until the function it returns is
    called, nothing typed into its pane is echoed. zellij sends a mouse
    wheel as arrow keys, and an echoed ^[[A lands on the frame until the
    next redraw. Ctrl-C still stops it. Without a terminal it does nothing."""
    try:
        fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        return lambda: None
    new = termios.tcgetattr(fd)
    new[3] &= ~(termios.ECHO | termios.ICANON)
    termios.tcsetattr(fd, termios.TCSANOW, new)
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)

def idle(seconds):
    """Sleep, throwing away whatever reaches the pane meanwhile, so it
    never piles up in the terminal's buffer (see quiet)."""
    end = time.time() + seconds
    try:
        fd = sys.stdin.fileno()
    except (OSError, ValueError):
        fd = None
    if fd is None or not os.isatty(fd):
        time.sleep(seconds); return
    while (left := end - time.time()) > 0:
        if select.select([fd], [], [], left)[0] and not os.read(fd, 4096):
            time.sleep(max(0, end - time.time())); return    # end of input

BACK_KEYS = ("q", "Q", "\x1b", "\r", "\n", "\x03", "\x04")   # q, Esc, Enter, Ctrl-C, Ctrl-D

def back(prompt="q · Enter: back"):
    """Wait under something just printed until q, Esc or Enter (the keys
    every TUI the DECK tab opens already takes to go back). Anything else
    is ignored, so a stray key never wipes the output before it's read.
    Without a terminal it returns at once."""
    sys.stdout.write("\n  " + DIM + prompt + " " + RST); sys.stdout.flush()
    while True:
        try:
            k = getkey()
        except (termios.error, OSError, ValueError):
            return
        if k is None or k in BACK_KEYS:       # None: end of input
            print(); return

def rule(title, w=None):
    """A section inside a screen: its title readable, the line dim."""
    w = w or width()
    return RULE + "── " + RST + MUTE + title + RST + " " + RULE + "─" * max(0, w - len(title) - 4) + RST

def cut(s, n):
    return s if len(s) <= n else s[:max(0, n - 1)] + "…"

def topbar(title, sub="", right="", w=None):
    """The top of a whole screen, the same on every panel: its title bright,
    what it is dim beside it, a count or a state on the right, then a line.
    Two lines; the screen's body starts on row 3."""
    w = w or width()
    right = cut(right, max(0, w - len(title) - 4))
    room = w - len(title) - 1 - (len(right) + 2 if right else 0) - 3
    sub = cut(sub, room) if room > 3 else ""
    left = " " + BLOOM + title + RST + (DIM + "   " + sub + RST if sub else "")
    line = pad(left, w - len(right) - 1) + MUTE + right + RST if right else left
    return [line, RULE + " " + "─" * max(0, w - 2) + RST]

HEAD = 2      # rows topbar() takes

def card(title, tag, body, w, tag_col=None):
    """A box exactly w columns wide, the same for every card of every panel:
    title bright on the top border, a tag on the right (in its own color,
    e.g. a status), the body padded inside, the frame dim."""
    inner = w - 2
    tag = cut(tag, max(0, inner - 6)) if tag else ""
    title = " %s " % cut(title, max(1, inner - len(tag) - 5 - (2 if tag else 0)))
    t = (" %s " % tag) if tag else ""
    top = (RULE + "╭─" + RST + BLOOM + title + RST
           + RULE + "─" * max(0, inner - 1 - len(title) - len(t) - 1) + RST
           + (tag_col or MUTE) + t + RST + RULE + "─╮" + RST)
    lines = [top]
    for b in body:
        lines.append(RULE + "│" + RST + b + " " * max(0, inner - vlen(b)) + RULE + "│" + RST)
    lines.append(RULE + "╰" + "─" * inner + "╯" + RST)
    return lines

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

def emit(obj, rc=0):
    """What every read-only command's --json prints: one object, no colors,
    for scripts, gadgets and assistants (glance's shape). Returns rc."""
    import json
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return rc

def tab_source(cmd):
    """Where the tab running `cmd` comes from, as a line saying how to take it
    out: a recipe, a tabs.d file of your own, or your profile. None if no tab runs it."""
    for t, src in deckconf.tabs_d():
        if cmd in str(t.get("panes", "")):
            name = os.path.basename(src)[:-5]
            if os.path.exists(os.path.join(REPO, "recipes", name + ".toml")):
                return "this tab came with `phosphor recipe %s`: `phosphor recipe --remove %s` takes it out" % (name, name)
            return "this tab comes from %s: delete that file, then `phosphor gen`" % src.replace(os.path.expanduser("~"), "~", 1)
    prof, _ = deckconf.load()
    for t in (prof or {}).get("tabs", []):
        if cmd in str(t.get("panes", "")):
            return "this tab is in your profile: `phosphor tabs` (b in the DECK tab) forgets it"
    return None

def not_set_up(title, what, needs, snippet, cmd, w):
    """The screen of a panel that has nothing to show yet: what it is, the
    profile lines that turn it on, and how to take the tab out if you don't
    want it -- instead of a wall of errors that reads as "broken"."""
    import textwrap
    def para(col, text, lead=""):
        lines = textwrap.wrap(lead + text, max(10, w - 4))
        return ["  " + col + l + RST for l in lines]
    out = [RULE + " " + title + " " + "─" * max(0, w - len(title) - 2) + RST, ""]
    out += para(FG, what) + [""]
    out += para(AMB, needs, "Not set up yet: ")
    out += para(DIM, "in " + deckconf.path().replace(os.path.expanduser("~"), "~", 1) + ":") + [""]
    out += ["    " + BLOOM + l + RST for l in snippet] + [""]
    out += para(MUTE, "Save it and this screen picks it up by itself.")
    out += para(DIM, "Every key it takes: phosphor help profile")
    src = tab_source(cmd)
    if src:
        out += [""] + para(MUTE, src, "Not for you? ")
    return out
