"""The deck's own log: what happened, not what you typed.

Until now a crash's traceback scrolled off with Enter/x, a frozen pane
closed without a trace, and about thirty `except Exception` in lib/ threw
the reason away. `phosphor run` (every program in the deck runs through
it) now writes one line per fact -- crash, hang, non-zero exit, a dropped
ssh link -- to `~/.cache/phosphor/deck.log`, always on and size-capped.

`phosphor trace TOOL` turns on a verbose file for one tool only,
trace-TOOL.log, and it turns itself off: `tracing()` stops saying yes
after ~30 minutes, so nothing is left running by accident.

Privacy: only actions and short technical detail go through here -- never
note text, never a host name or path a caller doesn't already log
elsewhere. That's what makes a log safe to paste into an issue;
`phosphor privacy` scans it like any other file.
"""
import os, sys, time, traceback

DIR = os.environ.get("PHOSPHOR_CACHE") or os.path.expanduser("~/.cache/phosphor")
LOG = os.path.join(DIR, "deck.log")
CAP = 200 * 1024          # deck.log stays under this; the oldest half goes first


def _stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _append(path, line, cap=None):
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(path, "a") as f:
            f.write(line if line.endswith("\n") else line + "\n")
        if cap and os.path.getsize(path) > cap:
            lines = open(path).readlines()
            open(path, "w").writelines(lines[len(lines) // 2:])
    except OSError:
        pass


def event(tool, what, detail=""):
    """One line in the base log: always on, size-capped."""
    line = "%s  %-10s %-6s" % (_stamp(), tool, what)
    if detail: line += " " + detail
    _append(LOG, line, CAP)


def crash(tool, exc=None):
    """A crash's traceback, kept instead of scrolling off the pane."""
    if exc is None:
        et, ev, tb = sys.exc_info()
    else:
        et, ev, tb = type(exc), exc, exc.__traceback__
    event(tool, "crash", "%s: %s" % (et.__name__, ev) if et else str(exc))
    if et is None: return
    for line in "".join(traceback.format_exception(et, ev, tb)).rstrip("\n").splitlines():
        _append(LOG, "%s  %-10s     %s" % (_stamp(), tool, line), CAP)


def tail(path, n=200):
    """The last n lines of a log file, or [] if it doesn't exist yet."""
    try:
        with open(path) as f:
            return [l.rstrip("\n") for l in f.readlines()[-n:]]
    except OSError:
        return []


def tail_for(tool, n=200):
    """The last n base-log lines (events and their tracebacks) for TOOL."""
    out = []
    for line in tail(LOG, 5000):
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[2].lower() == tool.lower():
            out.append(line)
    return out[-n:]


def flag(tool):
    return os.path.join(DIR, "trace-%s" % tool)


def tracefile(tool):
    return os.path.join(DIR, "trace-%s.log" % tool)


def tracing(tool):
    """Is TOOL's trace on right now? Clears an expired flag as it checks."""
    p = flag(tool)
    try:
        until = float(open(p).read().strip())
    except (OSError, ValueError):
        return False
    if time.time() >= until:
        try: os.remove(p)
        except OSError: pass
        return False
    return True


def start_trace(tool, minutes=30):
    os.makedirs(DIR, exist_ok=True)
    with open(flag(tool), "w") as f:
        f.write(str(time.time() + minutes * 60))
    open(tracefile(tool), "a").close()


_throttled = {}

def event_throttled(tool, what, detail="", every=300):
    """Like event(), but at most once every `every` seconds per (tool, what)
    in this process: for something checked every few seconds in a loop
    (fleet, pulse, the adjutant), so a stuck failure doesn't fill the log
    with the same line forever."""
    key = (tool, what)
    now = time.time()
    if now - _throttled.get(key, 0) < every:
        return
    _throttled[key] = now
    event(tool, what, detail)


def trace(tool, msg):
    """A verbose line for TOOL, kept only while its trace is on."""
    if tracing(tool):
        _append(tracefile(tool), "%s  %s" % (_stamp(), msg))


def active_traces():
    """[(tool, minutes left), ...] for every trace on right now."""
    out = []
    try:
        names = os.listdir(DIR)
    except OSError:
        return out
    for n in names:
        if not n.startswith("trace-") or n.endswith(".log"): continue
        tool = n[len("trace-"):]
        if not tracing(tool): continue
        try:
            until = float(open(os.path.join(DIR, n)).read().strip())
        except (OSError, ValueError):
            continue
        out.append((tool, max(1, int((until - time.time()) / 60) + 1)))
    return out
