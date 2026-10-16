"""card - one phosphor command as a card: its live value, one line, its tap.

share/commands.json gives every public command a `card` (its _schema says
what each field means). A sensor shows a live value and a tap opens it; a
toggle shows on or off and a tap flips it; a button runs it; a shortcut asks
what it needs first and goes straight there; plumbing has no card. This is
the widget the DECK tab is drawn with, and any dashboard after it:

    live = card.Live(["screens", "web"])     # values refresh in the background
    v, warn = live.get("screens")
    card.line("v", "screens", v, "phosphor screens", note, w, warn)
    card.tap("web", live.raw("web"))         # asks first when the card says so

A card always shows the command it stands for, so the deck teaches the
terminal; on a screen with no color, a ! after the key is what wants a look.
"""
import json, os, re, subprocess, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import REPO, AMB, BLOOM, DIM, FG, RST, vcut
import cli

PHOSPHOR = os.path.join(REPO, "phosphor")
LABEL_W = 16           # the longest label the DECK has ("machines & setup")
VALUE_W = 8            # "3 dirty", "40% free": right-aligned after the label
HEAD_W = 5             # "  k! ": the key, and ! when it wants a look


def spec(name):
    """The card of a command, or None (an unknown or hidden one)."""
    return (cli.entries().get(name) or {}).get("card")


def summary(v):
    """A state as a few characters: on/off, a count, a share, a word."""
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, list):
        return str(len(v))
    if isinstance(v, (int, float)):
        return str(int(v))
    if isinstance(v, str):
        return v
    if isinstance(v, dict) and v.get("total") and "available" in v:
        return "%d%% free" % (100 * v["available"] // v["total"])
    return None


def fetch(name):
    """(raw state, its summary) from the command's own --json, or (None,
    None) when it has none yet or doesn't answer."""
    c = spec(name) or {}
    argv = c.get("from", ["--json"])
    if "state" not in c or "--json" not in (cli.entries().get(name) or {}).get("options", []):
        return None, None
    try:
        r = subprocess.run([sys.executable, PHOSPHOR, name] + argv, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=10)
        v = json.loads(r.stdout)
        for k in c["state"].split("."):
            v = v[k]
    except Exception:          # no answer is no value, never a broken card
        return None, None
    return v, summary(v)


class Live:
    """The values of some cards, fetched in a background thread every
    `every` seconds: drawing never waits on a command."""

    def __init__(self, names, every=15):
        self.names, self.every, self.got = [n for n in names if (spec(n) or {}).get("state")], every, {}
        if self.names:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            for n in self.names:
                self.got[n] = fetch(n)
            time.sleep(self.every)

    def get(self, name):
        """(summary, warn) for line()."""
        return (self.got.get(name) or (None, None))[1], False

    def raw(self, name):
        return (self.got.get(name) or (None, None))[0]


def line(key, label, value, cmd, note, w, warn=False):
    """One card, one line w wide: key, label, live value, the command that
    does the same in a terminal (whole, or left out), and the note in
    whatever room is left: whole, or its first clauses, or cut at a word."""
    head = "  " + (AMB + key + RST if key else " ") + (AMB + "!" + RST if warn else " ") + " "
    color = AMB if warn else FG
    value = (value or "")[:VALUE_W]
    left = color + label[:LABEL_W].ljust(LABEL_W) + RST + " " + BLOOM + value.rjust(VALUE_W) + RST
    room = w - HEAD_W - LABEL_W - 1 - VALUE_W
    if not cmd or room < 2 + len(cmd.rstrip()):
        return vcut(head + left, w)
    s = head + left + "  " + DIM + cmd + RST
    room -= 2 + len(cmd)
    if note and room >= 14:
        s += "  " + DIM + shorten(note, room - 2) + RST
    return vcut(s, w)


def shorten(note, n):
    """note in n columns: whole, else up to the last ; : , ( that fits, else
    cut at a word with an ellipsis."""
    if len(note) <= n:
        return note
    stops = [m.start() for m in re.finditer(r"[;:,(]", note) if m.start() <= n]
    if stops and stops[-1] >= 8:
        return note[:stops[-1]].rstrip()
    return note[:n - 1].rsplit(" ", 1)[0].rstrip(";:,·-– ") + "…"


def tap(name, raw=None):
    """What a tap on the card does: a toggle flips (raw is its state; with
    none known it opens bare), anything else runs its args; ask comes first,
    then the y/n when the card says confirm. The CompletedProcess, or None
    when nothing ran."""
    from init import yes
    c = spec(name) or {}
    kind = c.get("kind")
    if kind in (None, "plumbing"):
        return None
    if kind == "toggle" and raw is not None:
        args = list(c["off"] if raw else c["on"])
        q = "turn %s %s?" % (name, "off" if raw else "on")
    else:
        args = list(c.get("args", []))
        q = "run " + " ".join(["phosphor", name] + args) + "?"
    for label in c.get("ask", []):
        try:
            a = input("  %s: " % label).strip()
        except (EOFError, KeyboardInterrupt):
            a = ""
        if not a:
            return None
        args.append(a)
    if c.get("confirm") and not yes(q, False):
        return None
    return subprocess.run([sys.executable, PHOSPHOR, name] + args)
