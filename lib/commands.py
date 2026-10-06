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
import edit

PHOSPHOR = os.path.join(REPO, "phosphor")

# (category, [(command, usage, one-line note), ...]) -- same categories, same
# order, as doc/manual/commands.md and README's own command table.
CATEGORIES = [
    ("Getting started", [
        ("doctor", "phosphor doctor", "preflight: locales, FUSE, systemd, PATH, fleet reach"),
        ("security", "phosphor security", "how exposed the deck is: file permissions, the fleet's sshd, tunnels, web, sockets"),
        ("attach", "phosphor attach", "get in, from any machine (also: phosphor deck, or just `deck`)"),
        ("init", "phosphor init", "profile wizard"),
        ("setup", "phosphor setup", "add/remove machines, color, editor and shell, phone, browser, tunnels, notebook"),
        ("panel", "phosphor panel", "the DECK tab: state, next steps, every action one key away"),
        ("commands", "phosphor commands", "this: every phosphor command, browsable by category"),
        ("phone", "phosphor phone", "put a phone or tablet one tap away from the deck"),
        ("screen", "phosphor screen", "the same kit as phone, for a computer without Termux"),
        ("gen", "phosphor gen", "generate layouts, units and mounts"),
        ("up", "phosphor up", "start the deck (and at every boot)"),
        ("update", "phosphor update", "a newer version: pull or copy, install, restart"),
        ("version", "phosphor version", "this version, whether there's a newer one, and what it brings"),
    ]),
    ("Session", [
        ("restart", "phosphor restart", "bring the session down cleanly and back up"),
        ("down", "phosphor down", "stop it (and the watchdog timer)"),
    ]),
    ("Workspaces", [
        ("workspace", "phosphor workspace new", "a tab per idea: folder, git, its assistants"),
        ("ask", "phosphor ask [-c] QUESTION", "a one-shot question to whichever assistant CLI is installed, no tab; -c adds your latest notes"),
    ]),
    ("Notes", [
        ("note", "phosphor note TEXT", "add a note to the shared notebook"),
        ("notes", "phosphor notes", "read it (newest first); pick one to edit, archive, chat"),
    ]),
    ("In the deck", [
        ("fleet", "phosphor fleet", "fleet panel"),
        ("pulse", "phosphor pulse", "the heartbeat: a wave tied to real load"),
        ("glance", "phosphor glance", "read-only: fleet, unread mentions, open todos -- for a small screen"),
        ("adjutant", "phosphor adjutant", "the SYS panel that speaks up"),
        ("notify", "phosphor notify MESSAGE", "send the adjutant a message (and your phone, with [push])"),
        ("tts", "phosphor tts", "speak notifications aloud with selectable voices"),
        ("push", "phosphor push", "[push] status, or --qr: a subscribe link/QR for the phone's ntfy app"),
        ("ci", "phosphor ci", "GitLab/GitHub pipeline status cards"),
        ("usage", "phosphor usage", "how much of your Claude Code / Antigravity plan is used, and when it refills"),
        ("prom", "phosphor prom", "Prometheus gauge dashboard (see [prometheus] in the profile)"),
        ("services", "phosphor services", "systemd units and their state: phosphor's own, plus any you add"),
        ("containers", "phosphor containers", "a host's docker/podman containers: logs, restart, start/stop"),
        ("review", "phosphor review", "open merge/pull requests: CI, conflicts, diff, try the branch"),
        ("screens", "phosphor screens", "who's attached (phone, tablet, another computer); kick one loose"),
        ("mem", "phosphor mem", "how much memory each tab and pane of the deck takes, heaviest first"),
        ("keys", "phosphor keys", "key guide, updates itself when you install a tool"),
        ("store", "phosphor store", "install TUIs from their releases, no sudo; open what you have"),
        ("new", "phosphor new", "the + menu: a shell, a machine, an assistant, your apps, a layout"),
        ("keep", "phosphor keep", "write a tab you arranged by hand into your profile"),
        ("tabs", "phosphor tabs", "the tabs your profile brings back: forget one, reorder, reopen"),
        ("recipe", "phosphor recipe", "starter tab bundles: homelab, dev, bubble, workbench"),
        ("shortcuts", "phosphor shortcuts", "the deck's keys, yours to change; updates never reset them"),
        ("theme", "phosphor theme", "the deck's color: p31, p3, p4, ega, paper, previewed before it's saved"),
        ("edit", "phosphor edit", "what Alt-r runs: unlock a tab, change it, save it or put it back"),
        ("mentions", "phosphor mentions", "read-only feed of chat notifications; --setup hooks matterhorn"),
        ("clip", "phosphor clip FILE", "a file or a pipe onto your device's clipboard"),
        ("send", "phosphor send FILE", "one real file, as a one-time link and QR; gone once it's downloaded"),
        ("receive", "phosphor receive", "the other way: a one-time upload link, into ~/received"),
        ("web", "phosphor web", "on / off / status / token: the deck in a browser, tailnet only"),
        ("path", "phosphor path PATH", "turns ~/fleet/x/y into host:/y"),
        ("tail", "phosphor tail HOST", "stream a fleet host's journalctl/docker/podman logs, reconnecting on its own"),
        ("triage", "phosphor triage HOST", "a diagnostic snapshot of a host, piped straight to phosphor ask"),
        ("broadcast", "phosphor broadcast -- CMD", "one command on every fleet host at once, output grouped by host"),
        ("tunnel", "phosphor tunnel", "keep your ssh config's LocalForward tunnels up"),
        ("face", "phosphor face IMAGE", "turn an image into the adjutant's face"),
        ("logs", "phosphor logs", "the deck's own log: crashes, hangs, exits, restarts; -f follows"),
        ("trace", "phosphor trace TOOL", "verbose logging for one tool, for about 30 minutes"),
    ]),
    ("Before you push a fork", [
        ("demo", "phosphor demo", "a throwaway session over made-up machines, for a screenshot"),
        ("privacy", "phosphor privacy", "before you push a fork: finds your own data in it"),
    ]),
    ("Shell", [
        ("completion", "phosphor completion bash", "tab completion for bash or zsh"),
    ]),
    ("Help", [
        ("help", "phosphor help", "the manual, by topic; phosphor docs rebuilds AGENTS.md"),
    ]),
]

# "Before you push a fork" doesn't fit pick()'s 16-char label column; the
# same shorter form phosphor's own --help already uses for it.
SHORT_CATEGORY = {"Before you push a fork": "Before you push"}


# Run with nothing on a terminal, these ask for what they need on a screen
# of their own (lib/form.py), and any change still asks before it happens:
# Enter runs them even though they can mutate something.
ASKS = {"ask", "broadcast", "send", "clip", "receive", "triage", "face", "push", "tts", "trace"}


def manifest():
    try:
        return json.load(open(os.path.join(REPO, "share", "commands.json")))
    except (OSError, ValueError):
        return {}


ALIASES = {"deck": "attach", "tunnels": "tunnel"}


def help_for(cmd):
    """`phosphor CMD --help`: its usage and what it does, from the same
    table this menu shows. False for a command it doesn't know."""
    cmd = ALIASES.get(cmd, cmd)
    hit = next(((u, n) for _, cmds in CATEGORIES for c, u, n in cmds if c == cmd), None)
    if not hit:
        return False
    usage, note = hit
    print("usage: " + usage)
    print("  " + note)
    extra = (manifest().get(cmd) or {}).get("note")
    if extra:
        import textwrap
        print()
        print(textwrap.fill(extra, width=78, initial_indent="  ", subsequent_indent="  "))
    print()
    print("  the manual: phosphor help commands")
    return True


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
