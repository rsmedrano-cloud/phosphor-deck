#!/usr/bin/env python3
"""tui - the list panel several phosphor commands share.

A ListPanel is a pane's picker over rows that refresh on their own: the
alternate screen, SGR mouse, j/k or the wheel to pick, a tap on a row, a
tappable key bar, a y/n question before anything happens, a pager for long
text, and scrolling when the rows don't fit. A panel says only what's its
own:

    class Units(tui.ListPanel):
        KEYS = [("l", "logs"), ("r", "restart"), ("q", "quit")]
        def fetch(self):            return [...]          # every INTERVAL s
        def header(self, w):        return topbar(...)
        def lines(self, w, sel):    return [...]          # one per row
        def act(self, k, row):                            # a key in KEYS
            self.confirm("restart %s?" % row, lambda: (True, "restarted"))

    Units().run()

act() answers with confirm() (asks, then runs the function, which returns
(ok, message); a note says what it costs, on lines of its own), say() (a line under the keys), page() (text in the pager)
or refresh() (fetch again now); draw() shows a say() at once, for an action
that takes a while, and line() asks for a line of text. Enter comes to act()
as "enter"; g and G jump to the first and last row. lines() may put a Head
among the rows: a group's title, never picked. A fix to keys or taps here
reaches every panel at once.
"""
import os, shutil, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, AMB, PH, RED, RST, FG, getkey, HEAD

ON = "\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"     # alt screen, no cursor, SGR mouse
OFF = "\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h"
QUIT = ("q", "Q", "\x03", "\x1b")


class Head(str):
    """A line of lines() that isn't a row: a group's title."""


def on():
    sys.stdout.write(ON); sys.stdout.flush()


def off():
    sys.stdout.write(OFF); sys.stdout.flush()


class ListPanel:
    KEYS = []            # [(key, label)]: the key bar, tappable; q quits on its own
    INTERVAL = 5         # seconds between fetches

    def __init__(self):
        self.rows, self.sel, self.last = [], 0, 0.0
        self.problem = ""          # set by fetch(): shown instead of the rows
        self.ask = None            # (prompt, do, note) while a question waits
        self.msg = ""
        self.layout = (0, 0, 0, [], {})   # first screen row, top line, lines shown, key spans, line -> row

    # ── what a panel says ─────────────────────────────────────
    def fetch(self):
        return []

    def header(self, w):
        return []

    def lines(self, w, sel):
        return []

    def act(self, k, row):
        pass

    # ── what act() can answer with ────────────────────────────
    def confirm(self, prompt, do, note=""):
        self.ask = (prompt, do, note)

    def say(self, text, col=AMB):
        self.msg = col + text + RST

    def page(self, text):
        import form
        form.pager(text)
        on()

    def refresh(self):
        self.last = 0.0

    def draw(self):
        cols, height = shutil.get_terminal_size((80, 24))
        out = self.frame(cols, height)
        sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J"); sys.stdout.flush()

    def line(self, label, text=""):
        """A line typed under the keys: Enter takes it, Esc gives None."""
        while True:
            self.say(label + " " + FG + text + RST + AMB + "▏" + RST); self.draw()
            k = getkey(None, text=True)
            if k in ("\r", "\n"):
                self.msg = ""; return text
            if k in ("\x1b", "\x03"):
                self.msg = ""; return None
            if k in ("\x7f", "\x08"):
                text = text[:-1]
            elif isinstance(k, str) and k >= " " and not k.startswith("\x1b"):
                text += k

    # ── the loop ──────────────────────────────────────────────
    def update(self):
        if time.time() - self.last >= self.INTERVAL:
            self.problem = ""
            self.rows, self.last = self.fetch(), time.time()
            self.sel = min(self.sel, max(0, len(self.rows) - 1))

    def frame(self, cols, height):
        """The screen's lines; remembers where rows and keys landed, for taps."""
        w = max(20, cols)
        out = self.header(w)
        if self.problem:
            body = [" " + AMB + self.problem + RST]
        else:
            body = self.lines(w, self.sel if self.rows else None)
        room = max(1, height - 3 - HEAD - (len(self.ask[2].splitlines()) if self.ask else 0))
        at = [i for i, l in enumerate(body) if not isinstance(l, Head)][:len(self.rows)]
        if self.problem or not self.rows:
            at = []
        here = at[self.sel] if self.sel < len(at) else 0
        top = max(0, min(here - room + 1, len(body) - room)) if len(body) > room else 0
        shown = body[top:top + room]
        out += shown
        spans, x = [], 2
        for k, l in self.KEYS:
            spans.append((x, x + len(k) + 1 + len(l), k)); x += len(k) + 1 + len(l) + 2
        out.append(" " + "  ".join(AMB + k + RST + FG + " " + l + RST for k, l in self.KEYS)
                   + DIM + "  · j/k pick" + RST)
        if self.ask:
            out += [" " + DIM + l + RST for l in self.ask[2].splitlines()]
            out.append(" " + AMB + self.ask[0] + RST + FG + "  y yes · any other key: no" + RST)
        elif self.msg:
            out.append(" " + self.msg)
        self.layout = (HEAD + 1, top, len(shown), spans, {l: r for r, l in enumerate(at)})
        return out

    def move(self, d):
        self.sel, self.msg = max(0, min(len(self.rows) - 1, self.sel + d)), ""

    def key(self, k):
        """One key or mouse event; False when the panel should close."""
        if isinstance(k, tuple):
            if k[0] != "MOUSE" or not k[4] or k[1] not in (0, 64, 65):
                return True
            if k[1] in (64, 65):
                self.move(-1 if k[1] == 64 else 1); return True
            x, y = k[2], k[3]
            if self.ask:
                self.ask = None; self.say("left alone", DIM); return True
            first, top, n, spans, row = self.layout
            if first <= y < first + n:
                if top + y - first in row:
                    self.sel, self.msg = row[top + y - first], ""
                return True
            hit = [kk for a, b, kk in spans if a <= x <= b] if y == first + n else []
            return self.key(hit[0]) if hit else True
        if self.ask:
            do = self.ask[1]
            self.ask = None
            if k in ("y", "Y"):
                ok, m = do()
                self.say(("✓ " if ok else "✗ ") + m, PH if ok else RED)
                self.refresh()
            else:
                self.say("left alone", DIM)
            return True
        if k in QUIT:
            return False
        if k in ("j", "\x1b[B"): self.move(1); return True
        if k in ("k", "\x1b[A"): self.move(-1); return True
        if k == "g": self.move(-len(self.rows)); return True
        if k == "G": self.move(len(self.rows)); return True
        if k in ("\r", "\n"):
            k = "enter"
        if self.rows and not self.problem and k in [kk for kk, _ in self.KEYS]:
            self.act(k, self.rows[self.sel])
        return True

    def run(self):
        on()
        try:
            while True:
                self.update()
                self.draw()
                k = getkey(max(0.2, self.INTERVAL - (time.time() - self.last)))
                if k is not None and not self.key(k):
                    break
        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write(OFF + "\n"); sys.stdout.flush()
        return 0
