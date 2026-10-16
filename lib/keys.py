#!/usr/bin/env python3
"""phosphor keys - the key guide. Shows a section for every installed tool
(share/keys.json) and picks up new installs by itself."""
import json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, BLOOM, AMB, RULE, RST, REPO, share, vlen, pad, topbar
import tui

HOME = os.path.expanduser("~")
BIN  = os.path.join(HOME, ".local/bin")
DB   = None  # resolved in main()
RESCAN = 5

def have(name):
    p = os.path.join(BIN, name)
    if os.path.isfile(p) and os.access(p, os.X_OK): return True
    return shutil.which(name) is not None

def sections(db):
    """[(title, [(key, what)])] for every installed tool; a key "" is a note."""
    return [(sec["t"], sec["k"]) for key, sec in db.items() if sec.get("always") or have(key)]

def build(db, w, sel=None):
    """The guide's lines: a section's title and its notes are Heads, every
    key a row; sel, the picked key (counted across sections), in reverse."""
    kw = min(20, max(12, w // 3))
    lines, n, i = [], 0, 0
    for t, keys in sections(db):
        n += 1
        lines.append(tui.Head(""))
        title = " " + BLOOM + t + RST
        lines.append(tui.Head(title + " " + RULE + "─"*max(0, w - vlen(title) - 2) + RST))
        for k, act in keys:
            if not k:
                lines.append(tui.Head("   " + DIM + act + RST))
                continue
            if i == sel:
                lines.append("  " + tui.INV + pad(" " + "%-*s" % (kw, k) + act, w - 3)[:w - 3] + RST)
            else:
                lines.append("   " + AMB + ("%-*s" % (kw, k)) + RST + FG + act + RST)
            i += 1
    return lines, n

def run_setup():
    """s runs setup in this same pane (no new tab, no floating pane) and the
    guide comes back when it exits. The DECK panel next to it has the rest."""
    tui.off()
    sys.stdout.write("\x1b[2J\x1b[H"); sys.stdout.flush()
    try:
        subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "setup"])
    except KeyboardInterrupt:
        pass
    tui.on()

def mine(db):
    """The deck's own keys as [keys] in the profile has them."""
    if "_deck" in db:
        import deckconf, shortcuts
        db["_deck"]["k"] = shortcuts.guide_rows(db["_deck"]["k"], deckconf.load()[0])
    return db

def load(throttled=False):
    try: return mine(json.load(open(DB)))
    except Exception:
        import dlog
        # never str(e): it can quote the install path
        (dlog.event_throttled if throttled else dlog.event)("KEYS", "load-failed")
        return {}

def dump():
    """No TTY (a pipe, |less, a script): plain dump and exit."""
    lines, n = build(load(), 78)
    print("\n".join(lines))
    print()


class Panel(tui.ListPanel):
    """The guide on the shared list panel: the wheel, j/k and taps scroll
    through the keys (the picked one shows where you are), s runs setup."""
    KEYS = [("s", "setup: machines and color"), ("q", "quit")]
    INTERVAL = RESCAN

    def __init__(self):
        super().__init__()
        self.db = {}

    def fetch(self):
        self.db = load(throttled=True)
        rows = [(t, k) for t, keys in sections(self.db) for k, _ in keys if k]
        if not rows:
            self.problem = "no keys to show: share/keys.json didn't load (phosphor logs)"
        return rows

    def header(self, w):
        return topbar("KEYS", "every installed tool", "%d tools" % len(sections(self.db)), min(w, 100))

    def lines(self, w, sel):
        return build(self.db, min(w, 100), sel)[0]

    def act(self, k, row):
        run_setup()
        self.refresh()


def main():
    global DB
    DB = share("keys.json")
    if not sys.stdin.isatty():
        dump(); return
    Panel().run()

if __name__ == "__main__":
    main()
