"""phosphor commands - every phosphor subcommand, browsable by category.

    phosphor commands

Pick a category, then a command -- or `/` to search every command's name
and note at once -- the same categories doc/manual/commands.md
and README already use, so nothing new to learn if you've read either. A
read-only command (share/commands.json says `mutates: false`) runs right
there when you pick it; anything else shows its usage and copies the
invocation to every screen's clipboard instead of guessing at missing
arguments (a file, a host, a message) for you.
"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import cli, edit

PHOSPHOR = os.path.join(REPO, "phosphor")

# (category, [(command, usage, one-line note), ...]) -- the categories and
# order of share/commands.json, the one definition phosphor help, --help and
# completion read too (lib/cli.py).
CATEGORIES = [(cat, [(c, e["usage"], e["summary"]) for c, e in cmds]) for cat, cmds in cli.categories()]

# "Before you push a fork" doesn't fit pick()'s 16-char label column; the
# shorter form, for the menu only.
SHORT_CATEGORY = {"Before you push a fork": "Before you push"}


# Run with nothing on a terminal, these ask for what they need on a screen
# of their own (lib/form.py), and any change still asks before it happens:
# Enter runs them even though they can mutate something.
ASKS = {"ask", "broadcast", "send", "clip", "receive", "triage", "face", "push", "tts", "trace", "read"}


manifest = cli.manifest


def category_items():
    return [(SHORT_CATEGORY.get(name, name), "%d command%s" % (len(cmds), "" if len(cmds) == 1 else "s"),
              name, cmds) for name, cmds in CATEGORIES]


def command_items(cmds):
    return [(cmd, note, usage) for cmd, usage, note in cmds]


def find(q):
    """Every command whose name, usage, note or category contains q
    (case-insensitive): the name matching first, then menu order."""
    q = q.strip().lower()
    return sorted([(cmd, note, usage) for name, cmds in CATEGORIES for cmd, usage, note in cmds
            if q and any(q in f.lower() for f in (cmd, usage, note, name))],
                  key=lambda it: (it[0] != q, not it[0].startswith(q)))


def ask_query():
    """A one-line search prompt. Returns the query, or None if cancelled."""
    q = ""
    while True:
        screen(["", "  " + BLOOM + "search every command" + RST,
                "  " + DIM + "a name or a word -- Enter searches, Esc goes back" + RST, "",
                "  " + AMB + "/" + RST + FG + q + RST + "\x1b[?25h"])
        k = getkey(None, text=True)
        if k is None or isinstance(k, tuple):
            continue
        if k in ("\r", "\n"): return q
        if k in ("\x03", "\x1b"): return None
        if k in ("\x7f", "\x08"): q = q[:-1]
        elif k == "\x15": q = ""                          # Ctrl-u
        elif k[0] >= " ": q += k                           # typed, or pasted at once


def screen(lines):
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[H\x1b[2J" + "\n".join(lines))
    sys.stdout.flush()


def detail(cmd, usage, note, man):
    entry = man.get(cmd) or {}
    safe = entry.get("mutates") is False
    asks = cmd in ASKS
    while True:
        lines = ["", "  " + BLOOM + usage + RST, "", "  " + FG + note + RST]
        if entry.get("note"):
            lines += ["", "  " + DIM + entry["note"] + RST]
        lines.append("")
        if safe or asks:
            lines.append("  " + AMB + "Enter" + RST + FG + (" runs it: it asks for the rest" if asks
                                                           else " runs it now") + RST)
        lines.append("  " + AMB + "c" + RST + FG + " copies `" + usage + "` to every screen's clipboard" + RST)
        lines.append("  " + AMB + "b" + RST + FG + " back" + DIM + "   (q)" + RST)
        screen(lines)
        k = getkey(None)
        if k in ("q", "\x1b", "b"):
            return
        if k in ("\r", "\n") and (safe or asks):
            sys.stdout.write("\x1b[?1049l\x1b[?25h"); sys.stdout.flush()
            subprocess.run([sys.executable, PHOSPHOR, cmd])
            back()
            return
        if k == "c":
            import clip
            clip.send(usage.encode())


def main():
    man = manifest()
    while True:
        cat = edit.pick("phosphor commands", category_items(), extra=[("/", "search every command")])
        if cat is None:
            return 0
        if cat == "/":
            q = ask_query()
            if not q:
                continue
            found = find(q)
            title = ("%d match%s for '%s'" % (len(found), "" if len(found) == 1 else "es", q)) if found \
                else "nothing matches '%s'" % q
        else:
            _, _, title, cmds = cat
            found = command_items(cmds)
        while True:
            item = edit.pick(title, found)
            if item is None:
                break
            cmd, note, usage = item
            detail(cmd, usage, note, man)


if __name__ == "__main__":
    sys.exit(main() or 0)
