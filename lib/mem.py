#!/usr/bin/env python3
"""phosphor mem - how much memory each tab and pane of the deck takes.

    phosphor mem           the panel: heaviest tab first, every 5s; j/k scroll, q leaves
    phosphor mem --once    the same, printed once

A pane is everything it started: zellij puts ZELLIJ_SESSION_NAME and
ZELLIJ_PANE_ID in the environment of every pane, and a process keeps the
environment it was started with (lib/reap.py relies on the same mark), so
an assistant's node workers, a shell's children and an ssh client all count
toward the pane they came from. Every kind of screen's session (deck-phone...)
is counted too, under its own name.

Memory is PSS (/proc/PID/smaps_rollup): a library or a page two processes
share is split between them, so the rows add up to what the deck really
holds instead of counting the same python twice. A kernel without
smaps_rollup gets RSS, which overcounts shared pages. Read-only: it never
touches a pane or a process.
"""
import json, os, re, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, MUTE, PH, AMB, RED, RULE, RST, BLOOM, getkey, pad, vcut, cut, topbar, HEAD
import deckconf, proc, reap

EVERY = 5
MARK = re.compile(r"\s*●\d+$")          # tabmark's unread count on a tab's name


def human(n):
    """Bytes as the panel shows them: 940 KB, 312 MB, 1.4 GB."""
    for unit, size in (("GB", 1 << 30), ("MB", 1 << 20)):
        if n >= size:
            v = n / size
            return ("%.1f %s" if v < 10 else "%.0f %s") % (v, unit)
    return "%d KB" % (n >> 10)


def footprint(pid):
    """A process's memory in bytes: its PSS, or its RSS without smaps_rollup."""
    try:
        with open("/proc/%d/smaps_rollup" % pid) as f:
            for line in f:
                if line.startswith("Pss:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        with open("/proc/%d/statm" % pid) as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return 0


def cmdline(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def procs():
    """[(pid, environ, args)] of every process this user can read."""
    out = []
    for d in os.listdir("/proc"):
        if d.isdigit():
            pid = int(d)
            env = reap.env_of(pid)
            if env:
                out.append((pid, env, cmdline(pid)))
    return out


def group(sessions, ps):
    """({(session, pane_id): [pid]}, {session: [pid]}): each pane's
    processes, and each session's own zellij server (no pane mark: it
    started the panes, it isn't in one)."""
    panes, servers = {}, {}
    marks = {("ZELLIJ_SESSION_NAME=%s" % s).encode(): s for s in sessions}
    server = {s: re.compile(r"zellij --server .*/%s(\s|$)" % re.escape(s)) for s in sessions}
    for pid, env, args in ps:
        sess = next((marks[e] for e in env if e in marks), None)
        pane = next((e[len(b"ZELLIJ_PANE_ID="):] for e in env if e.startswith(b"ZELLIJ_PANE_ID=")), None)
        if sess and pane is not None and pane.isdigit():
            panes.setdefault((sess, int(pane)), []).append(pid)
            continue
        hit = next((s for s, rx in server.items() if rx.search(args)), None)
        if hit:
            servers.setdefault(hit, []).append(pid)
    return panes, servers


def layout(session):
    """{pane_id: (tab position, tab name, pane title)} from zellij itself;
    {} when it doesn't answer (the counts still show, by pane number)."""
    zj = proc.zellij()
    if not zj:
        return {}
    try:
        out = subprocess.run([zj, "-s", session, "action", "list-panes", "-a", "-j"],
                             capture_output=True, text=True, timeout=10).stdout
        rows = json.loads(out or "[]")
    except (ValueError, subprocess.SubprocessError, OSError):
        return {}
    return {p["id"]: (p.get("tab_position", 99), MARK.sub("", p.get("tab_name") or "?"), p.get("title") or "")
            for p in rows if not p.get("is_plugin")}


def tally(base, sessions, panes, servers, names, size=footprint):
    """[(tab label, bytes, [(pane label, bytes, nprocs)])], heaviest tab
    first and heaviest pane first inside it; plus zellij's own bytes.
    `names` is {session: layout(session)}; a tab of another session than
    the deck's carries that session's kind ("NOTES · phone")."""
    tabs = {}
    for (sess, pid_), pids in panes.items():
        pos, tab, title = names.get(sess, {}).get(pid_, (99, "unlisted", ""))
        if sess != base:
            tab = "%s · %s" % (tab, sess[len(base) + 1:] if sess.startswith(base + "-") else sess)
        b = sum(size(p) for p in pids)
        t = tabs.setdefault((sess != base, tab), [pos, 0, []])
        t[1] += b
        t[2].append((title or "pane %d" % pid_, b, len(pids)))
    out = [(tab, total, sorted(ps, key=lambda p: -p[1]))
           for (_, tab), (pos, total, ps) in tabs.items()]
    out.sort(key=lambda t: -t[1])
    zellij = sum(size(p) for s in servers.values() for p in s)
    return out, zellij


def meminfo():
    """(total, available) bytes of this machine, or (0, 0)."""
    got = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                got[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return got.get("MemTotal", 0), got.get("MemAvailable", 0)


def collect(prof):
    import kinds
    base = ((prof or {}).get("deck") or {}).get("session", "deck")
    sessions = [base] + kinds.all_sessions(prof or {})
    panes, servers = group(sessions, procs())
    live = sorted({s for s, _ in panes} | set(servers))
    names = {s: layout(s) for s in live}
    tabs, zellij = tally(base, sessions, panes, servers, names)
    return {"base": base, "tabs": tabs, "zellij": zellij, "machine": meminfo()}


def frame(data, cols, rows=None, off=0):
    """The screen's lines (all of them; the caller scrolls)."""
    w = min(cols, 100)
    tabs, zellij = data["tabs"], data["zellij"]
    total = sum(t[1] for t in tabs) + zellij
    mt, ma = data["machine"]
    right = "%s of %s" % (human(total), human(mt)) if mt else human(total)
    out = topbar("MEMORY", "what each tab and pane holds", right, w)
    if not tabs:
        out.append(" " + DIM + "the deck isn't running (no pane of %s found)" % data["base"] + RST)
        return out
    top = max(t[1] for t in tabs) or 1
    bar_w = max(4, w - 40)
    for tab, b, ps in tabs:
        n = max(1 if b else 0, round(bar_w * b / top))
        out.append(" " + BLOOM + pad(cut(tab, 20), 21) + RST + FG + "%9s" % human(b) + RST
                   + "  " + PH + "█" * n + RST + RULE + "·" * (bar_w - n) + RST)
        for title, pb, n_ in ps:
            out.append("   " + FG + pad(cut(title, 18), 19) + RST + MUTE + "%9s" % human(pb) + RST
                       + DIM + "  %d process%s" % (n_, "" if n_ == 1 else "es") + RST)
    out.append("")
    out.append(" " + MUTE + pad("zellij itself", 21) + "%9s" % human(zellij) + RST)
    if mt:
        used = mt - ma
        col = RED if ma < mt * 0.1 else AMB if ma < mt * 0.25 else MUTE
        out.append(" " + col + pad("the machine", 21) + "%9s" % human(used) + RST
                   + DIM + "  in use of %s (the deck: %d%% of it)" % (human(mt), round(100 * total / used) if used else 0) + RST)
    return [vcut(l, w) for l in out]


def main():
    prof = deckconf.load()[0] or {}
    if "--once" in sys.argv[1:] or not sys.stdin.isatty():
        print("\n".join(frame(collect(prof), shutil.get_terminal_size((80, 24)).columns)))
        return 0
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    data, last, off = None, 0, 0
    try:
        while True:
            if time.time() - last >= EVERY:
                data, last = collect(prof), time.time()
            cols, rows = shutil.get_terminal_size((80, 24))
            lines = frame(data, cols)
            body = rows - HEAD - 1
            maxoff = max(0, len(lines) - HEAD - body)
            off = min(off, maxoff)
            shown = lines[:HEAD] + lines[HEAD + off:HEAD + off + body]
            shown.append(DIM + " " + ("j/k scroll · " if maxoff else "") + "q back" + RST)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(shown) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            k = getkey(max(0.1, EVERY - (time.time() - last)))
            if k in ("q", "Q", "\x1b", "\x03", "\x04"):
                break
            if k in ("j", "\x1b[B"):
                off = min(maxoff, off + 1)
            elif k in ("k", "\x1b[A"):
                off = max(0, off - 1)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1049l\x1b[?25h")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
