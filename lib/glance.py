#!/usr/bin/env python3
"""phosphor glance - a read-only summary for a small screen.

Three questions, answered at a glance: is the fleet healthy, is there a
chat mention waiting, is there a todo nobody picked up. No editing, no
keys beyond Ctrl-C: this is for a Pi with a small display sitting on a
shelf, or `ssh -t you@brain phosphor glance` from anything with a
terminal and no room for the full deck.

    phosphor glance         refreshes every few seconds, alternate screen
    phosphor glance --once  one frame, for scripting or a narrow test
    phosphor glance --json  the same answers as one JSON object
    phosphor glance --serve that JSON over HTTP, for a gadget that can't ssh
                            (an ESP32 with e-paper, a Pi Zero with an OLED)

--serve listens only on the brain's tailnet address (the LAN's without
one), answers GET with the token and nothing else, and runs in the
foreground: put it in a tab to keep it up.
"""
import hmac, json, os, secrets, shutil, sys, textwrap, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, FG, PH, AMB, RED, RST, rule
import deckconf
from sanitize import clean_tree
import ui
import health
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
            if pct >= 92:
                bad.append((name, "disk %d%%" % pct, False))
                break
        try: svcfail = int(h.get("SVCFAIL") or 0)
        except (TypeError, ValueError): svcfail = 0
        if svcfail:
            bad.append((name, "%d service%s failed" % (svcfail, "" if svcfail == 1 else "s"), False))
        if h.get("REBOOT"):
            bad.append((name, "reboot pending", False))
        bad += [(name, p, False) for p in health.sensor_problems(h)]
    return ok, len(hosts), stale, bad

def fleet_state():
    """(ok_count, total, [(name, detail)] for hosts that need attention)."""
    ok, total, stale, bad = fleet_scan()
    if total is None:
        return 0, 0, None
    return ok, total, ([(n, d) for n, d, _ in bad] if not stale else [("*", "stale data")])

def open_todos():
    return [e for e in notes.entries() if e["kind"] == "todo"]

def payload():
    """What --json prints and --serve answers: the same four questions as the
    screen, flattened for a microcontroller. status is the light to show:
    red when a host is down or the readings stopped, amber for anything else
    to look at (a host's problem, an unread mention), green otherwise,
    unknown with no fleet data. Open todos and dirty workspaces are counted
    but never change the color -- there's nearly always one."""
    ok, total, stale, bad = fleet_scan()
    n_unread = mentions.unread()
    if total is None:
        status = "unknown"
    elif stale or any(down for _, _, down in bad):
        status = "red"
    elif bad or n_unread:
        status = "amber"
    else:
        status = "green"
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
    todos = open_todos()
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

# ── --serve ───────────────────────────────────────────────────
PORT = 8484
SERVE_USAGE = "usage: phosphor glance [--once | --json | --serve [--port N] [--new-token]]"

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
        print(json.dumps(payload(), indent=2))
        return 0
    if "--serve" in a:
        port = PORT
        if "--port" in a:
            try:
                port = int(a[a.index("--port") + 1])
            except (IndexError, ValueError):
                print(SERVE_USAGE); return 1
        return serve(port, new_token="--new-token" in a)
    if "--once" in a:
        w = shutil.get_terminal_size((60, 20)).columns
        print("\n".join(frame(w, 10000)))
        return 0
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    loud = ui.quiet()
    try:
        while True:
            cols, rows = shutil.get_terminal_size((60, 20))
            out = frame(cols, rows)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            ui.idle(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        loud()
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
