"""phosphor glance on a SolarOS panel: reads the brain's
`phosphor glance --serve` and draws it, repainting only when something
changed (an e-ink panel flashes on every repaint). MicroPython, no ssh.

The brain hands this file out with its address and token already in URL:

    curl -o /glance.py "http://BRAIN:8484/solaros.py?token=TOKEN"
    python /glance.py              (or: python /glance.py URL)

Enter (the wheel's press) or r checks now; Esc, q or EXIT leave. It only
reads: marking a todo done or the mentions read stays with `phosphor glance`
over ssh.
"""
import sys, json
import solaros
from solaros import tui

URL = ""            # filled in by the brain when it serves this file
EVERY = 30          # seconds between checks
WORDS = {"green": "all clear", "amber": "worth a look", "red": "ATTENTION", "unknown": "no data"}


def fetch(url):
    """(payload, None) or (None, why)."""
    try:
        r = solaros.http.get(url, None, 8000, 16384)
    except OSError as e:
        return None, "no answer from the brain (%s)" % e
    if r["status_code"] == 401:
        return None, "token refused: fetch /glance.py again"
    if r["status_code"] != 200 or r["truncated"]:
        return None, "the brain answered %d" % r["status_code"]
    try:
        return json.loads(r["body"].decode()), None
    except ValueError:
        return None, "the brain sent something that isn't JSON"


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def lines(p, why, rows):
    """[(text, attr)] for the whole screen but the last row, which is the
    footer. p is the last payload that came through, or None."""
    out = []
    if p is None:
        out.append(("PHOSPHOR", tui.BOLD))
        out.append(("", 0))
        out.append((why or "waiting for the brain...", tui.BOLD))
        return out
    status = p.get("status", "unknown")
    out.append(("PHOSPHOR  " + WORDS.get(status, status),
                tui.INVERSE if status == "red" else tui.BOLD))
    if why:
        out.append(("! " + why, tui.BOLD))
    out.append(("", 0))
    f = p.get("fleet", {})
    total = f.get("total", 0)
    if not total:
        out.append(("fleet: no data", 0))
    elif f.get("stale"):
        out.append(("fleet: readings stopped", tui.BOLD))
    elif not f.get("problems"):
        out.append(("fleet: all %d hosts ok" % total, 0))
    else:
        out.append(("fleet: %d/%d ok" % (f.get("ok", 0), total), tui.BOLD))
    room = max(0, rows - 1 - len(out) - 4)      # keep the three counts and a gap
    for pr in f.get("problems", [])[:room]:
        out.append(("  %s %s: %s" % ("x" if pr.get("down") else "-", pr.get("host", "?"),
                                      pr.get("detail", "")),
                    tui.BOLD if pr.get("down") else 0))
    out.append(("", 0))
    n = p.get("mentions", 0)
    out.append(("mentions: " + ("%d unread" % n if n else "nothing unread"), tui.BOLD if n else 0))
    n = p.get("todos", 0)
    out.append(("todos: " + (plural(n, "open todo") if n else "nothing pending"), 0))
    n = p.get("workspaces", 0)
    out.append(("workspaces: " + (plural(n, "to push or commit") if n else "all clean"), 0))
    return out


def paint(body, rows, cols):
    tui.clear()
    for i, (text, attr) in enumerate(body[:rows - 1]):
        tui.addstr(i, 0, text[:cols], attr or tui.NORMAL)
    tui.addstr(rows - 1, 0, "Enter checks now, Esc leaves"[:cols], tui.NORMAL)   # SolarOS's bar has the time
    tui.refresh()


def wait(seconds):
    """Waits for a key up to seconds: 'check' (Enter, r), 'quit' (Esc, q,
    EXIT) or None when the time ran out."""
    up = getattr(tui, "KEY_UP", None)
    left = seconds * 1000
    while left > 0 and not solaros.should_exit():
        k = tui.getch(500)
        left -= 500
        if k is None or k in (up, getattr(tui, "KEY_DOWN", None)):
            continue
        if k in (10, 13, ord("r")):
            return "check"
        if k in (27, ord("q"), getattr(tui, "KEY_ESCAPE", 27)):
            return "quit"
    return "quit" if solaros.should_exit() else None


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else URL
    if not url:
        solaros.write("usage: python /glance.py URL\n"
                      "  (URL is what `phosphor glance --serve` prints)\n")
        return
    if not hasattr(solaros, "http"):
        solaros.write("this SolarOS build has no HTTP client (network.http-client)\n")
        return
    last, shown = None, None
    while not solaros.should_exit():
        p, why = fetch(url)
        if p is not None:
            last = p
        rows, cols = tui.size()
        body = lines(last, why, rows)
        if body != shown:
            paint(body, rows, cols)
            shown = body
        if wait(EVERY) == "quit":
            break
    tui.clear()
    tui.refresh()


main()
