#!/usr/bin/env python3
"""phosphor glance - a read-only summary for a small screen.

Three questions, answered at a glance: is the fleet healthy, is there a
chat mention waiting, is there a todo nobody picked up. No editing; r
repaints, q leaves: this is for a Pi with a small display sitting on a
shelf, an e-ink panel, or `ssh -t you@brain phosphor glance` from anything
with a terminal and no room for the full deck.

    phosphor glance         repaints when something changes, alternate screen
    phosphor glance --mono  no color (automatic on TERM=xterm-mono, NO_COLOR)
    phosphor glance --once  one frame, for scripting or a narrow test
    phosphor glance --json  the same answers as one JSON object
    phosphor glance --serve that JSON over HTTP, for a gadget that can't ssh
                            (an ESP32 with e-paper, a Pi Zero with an OLED)

--serve listens only on the brain's tailnet address (the LAN's without
one), answers GET with the token and nothing else, and runs in the
foreground: put it in a tab to keep it up.
"""
import hmac, json, os, secrets, shutil, sys, termios, textwrap, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, FG, PH, AMB, RED, RULE, BLOOM, RST, rule
import deckconf
from sanitize import clean_tree
import ui
import health
import limits
import mentions
import notes
import workspace

HOME  = os.path.expanduser("~")
CACHE = os.path.join(deckconf.cache_dir(), "fleet.json")
INTERVAL = 5

def fleet_scan():
    """(ok_count, total, stale, [(name, detail, down)]) -- down is True for a
    host that didn't answer at all, the rest being things to look at.
    total is None with no data yet (fleet isn't running here)."""
    try:
        with open(CACHE) as f:
            d = clean_tree(json.load(f))
    except (OSError, ValueError):
        return 0, None, False, []
    stale = time.time() - d.get("t", 0) > 90
    hosts = d.get("hosts", {})
    bad = []
    ok = 0
    for name, h in hosts.items():
        if not h.get("ok"):
            bad.append((name, h.get("err") or "unreachable", True))
            continue
        ok += 1
        for _, pct, _ in h.get("mnt", []):
            if limits.red("disk", pct, name):
                bad.append((name, "disk %d%%" % pct, False))
                break
        try: svcfail = int(h.get("SVCFAIL") or 0)
        except (TypeError, ValueError): svcfail = 0
        if svcfail:
            bad.append((name, "%d service%s failed" % (svcfail, "" if svcfail == 1 else "s"), False))
        if h.get("REBOOT"):
            bad.append((name, "reboot pending", False))
        bad += [(name, p, False) for p in health.sensor_problems(h, name)]
    return ok, len(hosts), stale, bad

def fleet_state():
    """(ok_count, total, [(name, detail)] for hosts that need attention)."""
    ok, total, stale, bad = fleet_scan()
    if total is None:
        return 0, 0, None
    return ok, total, ([(n, d) for n, d, _ in bad] if not stale else [("*", "stale data")])

def open_todos():
    return [e for e in notes.entries() if e["kind"] == "todo"]

def light(total, stale, bad, n_unread):
    """The status light, from fleet_scan()'s answer and the unread count
    (see payload)."""
    if total is None:
        return "unknown"
    if stale or any(down for _, _, down in bad):
        return "red"
    return "amber" if bad or n_unread else "green"

def payload():
    """What --json prints and --serve answers: the same four questions as the
    screen, flattened for a microcontroller. status is the light to show:
    red when a host is down or the readings stopped, amber for anything else
    to look at (a host's problem, an unread mention), green otherwise,
    unknown with no fleet data. Open todos and dirty workspaces are counted
    but never change the color -- there's nearly always one."""
    ok, total, stale, bad = fleet_scan()
    n_unread = mentions.unread()
    status = light(total, stale, bad, n_unread)
    if stale:
        worst = {"host": "*", "detail": "stale data"}
    else:
        first = sorted(bad, key=lambda b: not b[2])[:1]
        worst = {"host": first[0][0], "detail": first[0][1]} if first else None
    return {
        "status": status,
        "t": int(time.time()),
        "fleet": {"ok": ok, "total": total or 0, "stale": stale,
                  "problems": [{"host": n, "detail": d, "down": down} for n, d, down in bad]},
        "worst": worst,
        "mentions": n_unread,
        "todos": len(open_todos()),
        "workspaces": len(workspace.dirty_workspaces()),
    }

def wrapped(text, w, color=FG, indent="    "):
    """Wrap plain text (no ANSI in it) and color whole lines afterward --
    textwrap measures bytes, so color codes inside the text would throw
    off where it breaks."""
    lines = textwrap.wrap(text, max(8, w - len(indent)), initial_indent=indent, subsequent_indent=indent)
    return [color + l + RST for l in lines]

WIDE = 96          # from this many columns the four sections sit in a 2x2 grid
LABEL = {"green": "all clear", "amber": "worth a look", "red": "attention", "unknown": "no data"}
BOLD, INV = "\x1b[1m", "\x1b[7m"

def sections(w):
    """(status, [(title, lines)]): the four questions, each section's lines
    already fitted to w columns."""
    ok, total, stale, bad = fleet_scan()
    n = mentions.unread()
    status = light(total, stale, bad, n)

    fleet = []
    problems = [(nm, d) for nm, d, _ in bad] if not stale else [("*", "stale data")]
    if total is None:
        fleet.append(DIM + "  no fleet data (phosphor fleet isn't running here)" + RST)
    elif not problems:
        fleet.append(PH + ("  ✓ all %d hosts ok" % total) + RST)
    else:
        fleet.append((PH if ok else RED) + ("  %d/%d ok" % (ok, total)) + RST)
        for name, detail in problems[:4]:
            fleet += wrapped("✗ %s: %s" % (name, detail), w, color=RED)

    said = []
    if n:
        said.append(AMB + ("  ● %d unread" % n) + RST)
        for e in mentions.entries()[:2]:
            said += wrapped("%s: %s" % (e.get("from", "?"), e.get("message", "")), w)
    else:
        said.append(DIM + "  nothing unread" + RST)

    needs = []
    todos = open_todos()
    if todos:
        needs.append(AMB + ("  %d open todo%s" % (len(todos), "" if len(todos) == 1 else "s")) + RST)
        for e in todos[:5]:             # one line each: a todo with no title is its whole body
            title = e["title"] or (e["body"][0] if e["body"] else "(untitled)")
            needs.append(FG + "    " + ui.cut(title, max(8, w - 4)) + RST)
    else:
        needs.append(DIM + "  nothing pending" + RST)

    ws = []
    dirty = workspace.dirty_workspaces()
    if dirty:
        for name, is_dirty, ahead, behind in dirty[:4]:
            bits = ([] if not is_dirty else ["uncommitted"]) \
                 + ([] if not ahead else ["%d ahead" % ahead]) \
                 + ([] if not behind else ["%d behind" % behind])
            ws += wrapped("%s: %s" % (name, ", ".join(bits)), w, color=AMB)
    else:
        ws.append(DIM + "  nothing dirty or unpushed" + RST)

    return status, [("fleet", fleet), ("mentions", said), ("needs you", needs), ("workspaces", ws)]

def head(w, status, stamp=None):
    """One line: the name, the light in words (reversed when it's red, so
    it reads across a room and on a screen with no color) and the time."""
    word = LABEL[status]
    word = " %s " % word.upper() if status == "red" else word
    col = (INV + RED) if status == "red" else AMB if status == "amber" else PH if status == "green" else DIM
    stamp = stamp or time.strftime("%H:%M")
    fill = max(1, w - 17 - len(word) - len(stamp))
    return (RULE + "── " + RST + BLOOM + "GLANCE" + RST + " " + RULE + "─" * fill + RST + " "
            + col + word + RST + DIM + " · " + stamp + RST + RULE + " ──" + RST)

def body(w, rows):
    """(status, lines) under the head: one column on a narrow screen, a
    2x2 grid on a wide one (a 130x17 e-ink panel shows all four sections
    whole instead of the first two)."""
    if w < WIDE:
        status, secs = sections(w)
        out = []
        for title, lines in secs:
            out += [rule(title, w)] + lines + [""]
        return status, out[:max(0, rows)]
    cw = (w - 2) // 2
    status, secs = sections(cw)
    blocks = []
    for (t1, l1), (t2, l2) in (secs[:2], secs[2:]):
        b = [rule(t1, cw) + "  " + rule(t2, cw)]
        for i in range(max(len(l1), len(l2))):
            a = ui.vcut(l1[i], cw) if i < len(l1) else ""
            c = ui.vcut(l2[i], cw) if i < len(l2) else ""
            b.append((ui.pad(a, cw) + "  " + c).rstrip())
        blocks.append(b)
    room = rows - 1                     # a blank line between the two halves
    top = blocks[0][:max(room - len(blocks[1]), room // 2)]
    return status, (top + [""] + blocks[1][:room - len(top)])[:max(0, rows)]

def frame(w, rows, stamp=None):
    status, lines = body(w, rows - 1)
    return [head(w, status, stamp)] + lines

def mono(line):
    """A line for a terminal with no color (see ui.mono_term): red and amber
    become bold, inverse stays, every other color goes."""
    return ui.uncolor(line.replace(RED, BOLD).replace(AMB, BOLD))

# ── --serve ───────────────────────────────────────────────────
PORT = 8484
SERVE_USAGE = "usage: phosphor glance [--mono] [--once | --json | --serve [--port N] [--new-token]]"

def token_path():
    return os.path.join(deckconf.data_dir(), "glance-token")

def token(new=False):
    """The token a gadget sends: made once, kept 0600 next to phosphor's data,
    so a device flashed with it keeps working across restarts. new=True
    replaces it (a lost gadget, a token that leaked)."""
    p = token_path()
    if not new:
        try:
            t = open(p).read().strip()
            if t:
                return t
        except OSError:
            pass
    t = secrets.token_urlsafe(18)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t + "\n")
    os.replace(p + ".tmp", p)
    return t

def authorized(path, headers, secret):
    """The token, either as ?token= (what an ESP32's HTTP client sends most
    easily) or as Authorization: Bearer. Compared in constant time."""
    from urllib.parse import urlsplit, parse_qs
    q = parse_qs(urlsplit(path).query).get("token", [""])[0]
    auth = headers.get("Authorization") or ""
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return any(c and hmac.compare_digest(c.encode(), secret.encode()) for c in (q, bearer))

def handler_for(secret):
    from http.server import BaseHTTPRequestHandler
    from urllib.parse import urlsplit
    cache = {"t": 0, "body": b""}

    class H(BaseHTTPRequestHandler):
        timeout = 5                     # a client that opens and says nothing
        server_version = "phosphor-glance"
        sys_version = ""

        def reply(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlsplit(self.path).path not in ("/", "/glance", "/glance.json"):
                return self.reply(404, b'{"error": "not found"}\n')
            if not authorized(self.path, self.headers, secret):
                return self.reply(401, b'{"error": "token"}\n')
            if time.time() - cache["t"] > 2:      # a gadget polling fast doesn't re-run git
                cache["body"] = (json.dumps(payload()) + "\n").encode()
                cache["t"] = time.time()
            self.reply(200, cache["body"])

        def log_message(self, *a):      # the token is in the path: never print it
            pass
    return H

def server(addr, secret):
    """One thread per request: a gadget that connects and stalls can't
    hold the others up."""
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(addr, handler_for(secret))
    httpd.daemon_threads = True
    return httpd

def serve(port=PORT, new_token=False):
    import send
    prof, _ = deckconf.load()
    ip, where = send.pick_address(prof)
    secret = token(new=new_token)
    try:
        httpd = server((ip, port), secret)
    except OSError as e:
        print(ui.row(ui.BAD, "glance", "can't listen on %s:%d" % (ip, port), note=str(e.strerror or e)))
        return 1
    url_ = "http://%s:%d/glance?token=%s" % (ip, httpd.server_port, secret)
    print(ui.row(ui.OK, "serving", url_, note=where + ", read-only JSON"))
    if where == "LAN":
        print(DIM + "  no tailnet: the token crosses the LAN in the clear." + RST)
    for l in send.qr_lines(url_):
        print("  " + l)
    print(DIM + "  Ctrl-C stops it; --new-token replaces the token." + RST)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0

def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print(SERVE_USAGE); return 0
    if "--json" in a:
        return ui.emit(payload())
    if "--serve" in a:
        port = PORT
        if "--port" in a:
            try:
                port = int(a[a.index("--port") + 1])
            except (IndexError, ValueError):
                print(SERVE_USAGE); return 1
        return serve(port, new_token="--new-token" in a)
    show = mono if "--mono" in a or ui.mono_term() else (lambda l: l)
    if "--once" in a:
        w = shutil.get_terminal_size((60, 20)).columns
        print("\n".join(show(l) for l in frame(w, 10000)))
        return 0
    return watch(show)

HEARTBEAT = 600    # repaint at least this often, so a time that stops moving means a dead link

def wait(seconds):
    """A key typed within seconds, else None. Without a terminal, or once
    the input has ended, it just sleeps them out."""
    t0 = time.time()
    try:
        k = ui.getkey(seconds)
    except (termios.error, OSError, ValueError):
        ui.idle(seconds); return None
    if k is None:                        # a timeout, or an end of input that returns at once
        time.sleep(max(0, seconds - (time.time() - t0)))
    return k

def watch(show):
    """The screen that stays up. It repaints only when what it says changes,
    or every HEARTBEAT: an e-ink panel flashes on every repaint and a slow
    one falls behind a busy screen, so the time on top is when it last
    changed, not a clock. r (or Ctrl-L) clears and repaints, for e-ink
    ghosting; q or Ctrl-C leaves."""
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    loud = ui.quiet()
    last, painted, clear = None, 0, True
    try:
        while True:
            cols, rows = shutil.get_terminal_size((60, 20))
            status, lines = body(cols, rows - 1)
            if clear or (cols, rows, lines) != last or time.time() - painted >= HEARTBEAT:
                out = [show(l) for l in [head(cols, status)] + lines]
                sys.stdout.write(("\x1b[2J" if clear else "") + "\x1b[H"
                                 + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
                sys.stdout.flush()
                last, painted, clear = (cols, rows, lines), time.time(), False
            k = wait(INTERVAL)
            if k in ("q", "Q", "\x03", "\x04"):
                break
            clear = k in ("r", "R", "\x0c")
    except KeyboardInterrupt:
        pass
    finally:
        loud()
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
