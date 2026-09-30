"""The small screens a command opens when it's run with nothing on a
terminal: a line of text, boxes to tick, a file to pick, a page to read.
Every one works by key or by tap, and returns None when backed out of (q,
Esc, "< back"), so the command just ends -- the same as the usage line it
printed before, minus the usage line. Piped, or with its arguments, a
command never gets here.
"""
import os, shutil, subprocess, sys
from ui import *
import deckconf, edit


def wanted(argv):
    """A command asks instead of quitting: no arguments, on a terminal."""
    return not argv and sys.stdin.isatty() and sys.stdout.isatty()


def screen(lines):
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h\x1b[H\x1b[2J" + "\n".join(lines))
    sys.stdout.flush()


def leave():
    """Off the alternate screen, mouse off: what runs next prints normally."""
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h"); sys.stdout.flush()


def line(title, hint, initial=""):
    """One line of text. Enter gives it back (maybe empty), Esc or a tap on
    "< back" gives None."""
    q = initial
    while True:
        screen(["", "  " + BLOOM + title + RST,
                "  " + AMB + "< back" + RST + DIM + "   (Esc)" + RST,
                "  " + DIM + hint + RST, "",
                "  " + AMB + ">" + RST + " " + FG + q + RST + "\x1b[?25h"])
        k = getkey(None, text=True)
        if isinstance(k, tuple):
            if k[0] == "MOUSE" and k[1] == 0 and k[4] and k[3] == 3:
                return None
            continue
        if k is None: continue
        if k in ("\r", "\n"): return q
        if k in ("\x03", "\x1b"): return None
        if k in ("\x7f", "\x08"): q = q[:-1]
        elif k == "\x15": q = ""                          # Ctrl-u
        elif k[0] >= " ":                                  # typed, or pasted at once
            q += k.split("\r")[0].split("\n")[0].replace("\x7f", "")
            if "\r" in k or "\n" in k: return q


def ticks(title, items, groups=None, picked=()):
    """Boxes to tick. items: [(label, note)]. groups: {name: [labels]},
    offered under g to tick a whole group at once (a role, say). Space or a
    tap ticks, a ticks all or none, Enter is done. Returns the ticked labels
    in items' order, or None for back."""
    on = set(picked)
    sel, top = 0, 0
    extra = [("\r", "done  (Enter)"), ("a", "all / none")] + ([("g", "by group")] if groups else [])
    fixed = 3 + len(extra)
    while True:
        cols, rows = shutil.get_terminal_size((60, 20))
        room = max(3, rows - fixed - 1)
        top = min(max(top, sel - room + 1), sel)
        lines = ["", BLOOM + "  " + title + RST + DIM + "   %d ticked" % len(on) + RST,
                 "  " + AMB + "< back" + RST + DIM + "   (q)" + RST]
        lines += ["  " + AMB + "%-7s" % ("Enter" if k == "\r" else k) + RST + FG + text.split("  (")[0] + RST
                  for k, text in extra]
        shown = items[top:top + room]
        for i, (label, note) in enumerate(shown, top):
            t = "  [%s] %-16s %s" % ("x" if label in on else " ", label[:16], note)
            lines.append(("\x1b[7m" + t + RST) if i == sel else (FG + t + RST))
        screen(lines[:rows])
        k = getkey(None)
        if isinstance(k, tuple):
            if k[0] != "MOUSE" or not k[4] or k[1] not in (0, 64, 65): continue
            if k[1] == 64: sel = max(0, sel - 3); continue
            if k[1] == 65: sel = min(len(items) - 1, sel + 3); continue
            r = k[3]
            if r == 3: return None
            if 3 < r <= fixed: k = extra[r - 4][0]
            elif fixed < r <= fixed + len(shown):
                sel = top + r - fixed - 1; k = " "
            else: continue
        if k in ("q", "\x1b", "\x03"): return None
        if k in ("\r", "\n"): return [l for l, _ in items if l in on]
        if k in ("j", "\x1b[B"): sel = min(len(items) - 1, sel + 1)
        elif k in ("k", "\x1b[A"): sel = max(0, sel - 1)
        elif k == " " and items:
            on ^= {items[sel][0]}
        elif k == "a":
            on = set() if len(on) == len(items) else {l for l, _ in items}
        elif k == "g" and groups:
            g = edit.pick("tick a whole group", [(n, ", ".join(ls)) for n, ls in groups.items()])
            if g: on = set(groups[g[0]])


def size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0


def file(title, start=None, exts=None):
    """A file, walked to by folders: ~ and ~/fleet one key away. exts: the
    endings to show (".png", ".gif"...), folders always. Returns its full
    path, or None for back."""
    here = os.path.abspath(os.path.expanduser(start or "."))
    fleet = deckconf.mount_root(deckconf.load()[0])
    while True:
        try:
            names = sorted(n for n in os.listdir(here) if not n.startswith("."))
        except OSError:
            names = []                            # unreadable: only .. and the jumps
        dirs = [n for n in names if os.path.isdir(os.path.join(here, n))]
        files = [n for n in names if n not in dirs and os.path.isfile(os.path.join(here, n))
                 and (not exts or n.lower().endswith(tuple(exts)))]
        items = [("folder", "../", "..")] if here != "/" else []
        items += [("folder", d + "/", d) for d in dirs]
        for f in files:
            try: s = size(os.path.getsize(os.path.join(here, f)))
            except OSError: s = "?"
            items.append((s, f, f))
        extra = [("~", "home")] + ([("f", "~/fleet: every machine's files")] if os.path.isdir(fleet) else [])
        got = edit.pick("%s   %s" % (title, tilde(here)), items, extra=extra)
        if got is None: return None
        if got == "~": here = os.path.expanduser("~"); continue
        if got == "f": here = fleet; continue
        p = os.path.normpath(os.path.join(here, got[2]))
        if os.path.isdir(p): here = p
        else: return p


def tilde(p):
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p == home or p.startswith(home + "/") else p


def choice(opts, prompt="q · Enter: back"):
    """Under something just printed: one key of opts [(key, label)] or of
    back's keys. The key, or None for back. Without a terminal, None."""
    sys.stdout.write("\n  " + " · ".join(AMB + k + RST + FG + " " + l + RST for k, l in opts)
                     + DIM + "   " + prompt + " " + RST)
    sys.stdout.flush()
    keys = [k for k, _ in opts]
    while True:
        try:
            k = getkey()
        except (OSError, ValueError, __import__("termios").error):
            return None
        if k in keys:
            print(); return k
        if k is None or k in BACK_KEYS:
            print(); return None


def pager(text):
    """Text to read at leisure: less when there is one, else printed and
    back (q, Esc, Enter)."""
    leave()
    less = shutil.which("less")
    if less and sys.stdout.isatty():
        subprocess.run([less, "-R", "-F", "-X"], input=text.encode())
        if text.count("\n") < shutil.get_terminal_size((80, 24)).lines - 2:
            back()                                    # -F left it on screen: wait for a key
        return
    sys.stdout.write(text + ("" if text.endswith("\n") else "\n"))
    back()
