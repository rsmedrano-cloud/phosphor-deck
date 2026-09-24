#!/usr/bin/env python3
"""phosphor glance - a read-only summary for a small screen.

Three questions, answered at a glance: is the fleet healthy, is there a
chat mention waiting, is there a todo nobody picked up. No editing, no
keys beyond Ctrl-C: this is for a Pi with a small display sitting on a
shelf, or `ssh -t you@brain phosphor glance` from anything with a
terminal and no room for the full deck.

    phosphor glance         refreshes every few seconds, alternate screen
    phosphor glance --once  one frame, for scripting or a narrow test
"""
import json, os, shutil, sys, textwrap, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, FG, PH, AMB, RED, RST, rule
import deckconf
import mentions
import notes
import workspace

HOME  = os.path.expanduser("~")
CACHE = os.path.join(deckconf.cache_dir(), "fleet.json")
INTERVAL = 5

def fleet_state():
    """(ok_count, total, [(name, detail)] for hosts that need attention)."""
    try:
        with open(CACHE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0, 0, None       # no data yet: fleet isn't running here
    stale = time.time() - d.get("t", 0) > 90
    hosts = d.get("hosts", {})
    bad = []
    ok = 0
    for name, h in hosts.items():
        if not h.get("ok"):
            bad.append((name, h.get("err") or "unreachable"))
            continue
        ok += 1
        for _, pct, _ in h.get("mnt", []):
            if pct >= 92:
                bad.append((name, "disk %d%%" % pct))
                break
    return ok, len(hosts), (bad if not stale else [("*", "stale data")])

def wrapped(text, w, color=FG, indent="    "):
    """Wrap plain text (no ANSI in it) and color whole lines afterward --
    textwrap measures bytes, so color codes inside the text would throw
    off where it breaks."""
    lines = textwrap.wrap(text, max(8, w - len(indent)), initial_indent=indent, subsequent_indent=indent)
    return [color + l + RST for l in lines]

def frame(w, rows):
    out = [rule("GLANCE", w), DIM + time.strftime("  %H:%M:%S") + RST, ""]

    out.append(rule("fleet", w))
    ok, total, bad = fleet_state()
    if total == 0:
        out.append(DIM + "  no fleet data (phosphor fleet isn't running here)" + RST)
    elif not bad:
        out.append(PH + ("  ✓ all %d hosts ok" % total) + RST)
    else:
        out.append((PH if ok else RED) + ("  %d/%d ok" % (ok, total)) + RST)
        for name, detail in bad[:4]:
            out += wrapped("✗ %s: %s" % (name, detail), w, color=RED)
    out.append("")

    out.append(rule("mentions", w))
    n = mentions.unread()
    if n:
        out.append(AMB + ("  ● %d unread" % n) + RST)
        for e in mentions.entries()[:2]:
            out += wrapped("%s: %s" % (e.get("from", "?"), e.get("message", "")), w)
    else:
        out.append(DIM + "  nothing unread" + RST)
    out.append("")

    out.append(rule("needs you", w))
    todos = [e for e in notes.entries() if e["kind"] == "todo"]
    if todos:
        out.append(AMB + ("  %d open todo%s" % (len(todos), "" if len(todos) == 1 else "s")) + RST)
        for e in todos[:3]:
            title = e["title"] or (e["body"][0] if e["body"] else "(untitled)")
            out += wrapped(title, w)
    else:
        out.append(DIM + "  nothing pending" + RST)
    out.append("")

    out.append(rule("workspaces", w))
    dirty = workspace.dirty_workspaces()
    if dirty:
        for name, is_dirty, ahead, behind in dirty[:4]:
            bits = ([] if not is_dirty else ["uncommitted"]) \
                 + ([] if not ahead else ["%d ahead" % ahead]) \
                 + ([] if not behind else ["%d behind" % behind])
            out += wrapped("%s: %s" % (name, ", ".join(bits)), w, color=AMB)
    else:
        out.append(DIM + "  nothing dirty or unpushed" + RST)

    return out[:max(1, rows)]

def main():
    if "--once" in sys.argv:
        w = shutil.get_terminal_size((60, 20)).columns
        print("\n".join(frame(w, 10000)))
        return 0
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((60, 20))
            out = frame(cols, rows)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
