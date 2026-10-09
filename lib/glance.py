#!/usr/bin/env python3
"""phosphor glance - a summary for a small screen.

Three questions, answered at a glance: is the fleet healthy, is there a
chat mention waiting, is there a todo nobody picked up. Up, down and Enter
(all an e-ink panel's wheel sends) open an item whole, and from its page
a todo can be marked done and the mentions read; r repaints, q leaves.
This is for a Pi with a small display sitting on a shelf, an e-ink panel,
or `ssh -t you@brain phosphor glance` from anything with a terminal and no
room for the full deck.

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
import dlog
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

def wrapped(text, w, color=FG, indent="    ", first=None):
    """Wrap plain text (no ANSI in it) and color whole lines afterward --
    textwrap measures bytes, so color codes inside the text would throw
    off where it breaks. first, if given, starts the first line instead
    of indent (the cursor's mark)."""
    lines = textwrap.wrap(text, max(8, w - len(indent)), initial_indent=indent if first is None else first,
                          subsequent_indent=indent)
    return [color + l + RST for l in lines]

WIDE = 96          # from this many columns the four sections sit in a 2x2 grid
LABEL = {"green": "all clear", "amber": "worth a look", "red": "attention", "unknown": "no data"}
BOLD, INV = "\x1b[1m", "\x1b[7m"
MARK = "  ▸ "      # the cursor, before the item it's on (shown reversed too)

def unread_entries():
    """The unread mentions, newest first."""
    s = mentions.seen()
    return [e for e in mentions.entries() if e.get("t", 0) > s][::-1]

def sections(w, sel=None):
    """(status, [(title, lines)], items): the four questions, each
    section's lines already fitted to w columns, and what the cursor can
    stop on, in order -- (kind, title, data) for each host with a problem,
    unread mention, open todo and workspace shown. The item numbered sel
    is drawn reversed, with the cursor's mark."""
    ok, total, stale, bad = fleet_scan()
    n = mentions.unread()
    status = light(total, stale, bad, n)
    items = []

    def item(text, w, color, kind, title, data):
        on = sel == len(items)
        items.append((kind, title, data))
        return wrapped(text, w, color=INV if on else color, first=MARK if on else None)

    fleet = []
    problems = [(nm, d) for nm, d, _ in bad] if not stale else [("*", "stale data")]
    if total is None:
        fleet.append(DIM + "  no fleet data (phosphor fleet isn't running here)" + RST)
    elif not problems:
        fleet.append(PH + ("  ✓ all %d hosts ok" % total) + RST)
    else:
        fleet.append((PH if ok else RED) + ("  %d/%d ok" % (ok, total)) + RST)
        for name, detail in problems[:4]:
            every = [d for nm, d in problems if nm == name]
            fleet += item("✗ %s: %s" % (name, detail), w, RED, "host", name, every)

    said = []
    if n:
        said.append(AMB + ("  ● %d unread" % n) + RST)
        for e in unread_entries()[:2]:
            said += item("%s: %s" % (e.get("from", "?"), e.get("message", "")), w, FG,
                         "mention", "from " + str(e.get("from", "?")), e)
    else:
        said.append(DIM + "  nothing unread" + RST)

    needs = []
    todos = open_todos()
    if todos:
        needs.append(AMB + ("  %d open todo%s" % (len(todos), "" if len(todos) == 1 else "s")) + RST)
        for e in todos[:5]:             # one line each: a todo with no title is its whole body
            title = e["title"] or (e["body"][0] if e["body"] else "(untitled)")
            on = sel == len(items)
            items.append(("todo", title, e))
            needs.append((INV + MARK if on else FG + "    ") + ui.cut(title, max(8, w - 4)) + RST)
    else:
        needs.append(DIM + "  nothing pending" + RST)

    ws = []
    dirty = workspace.dirty_workspaces()
    if dirty:
        for name, is_dirty, ahead, behind in dirty[:4]:
            bits = ([] if not is_dirty else ["uncommitted"]) \
                 + ([] if not ahead else ["%d ahead" % ahead]) \
                 + ([] if not behind else ["%d behind" % behind])
            ws += item("%s: %s" % (name, ", ".join(bits)), w, AMB, "workspace", name, ", ".join(bits))
    else:
        ws.append(DIM + "  nothing dirty or unpushed" + RST)

    return status, [("fleet", fleet), ("mentions", said), ("needs you", needs), ("workspaces", ws)], items

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

def body(w, rows, sel=None):
    """(status, lines, items) under the head: one column on a narrow
    screen, a 2x2 grid on a wide one (a 130x17 e-ink panel shows all four
    sections whole instead of the first two). items: see sections."""
    if w < WIDE:
        status, secs, items = sections(w, sel)
        out = []
        for title, lines in secs:
            out += [rule(title, w)] + lines + [""]
        return status, out[:max(0, rows)], items
    cw = (w - 2) // 2
    status, secs, items = sections(cw, sel)
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
    return status, (top + [""] + blocks[1][:room - len(top)])[:max(0, rows)], items

def frame(w, rows, stamp=None, sel=None):
    status, lines, _ = body(w, rows - 1, sel)
    return [head(w, status, stamp)] + lines

# ── acting on one item ───────────────────────────────────────
ACTIONS = {"todo": ["done", "back"], "mention": ["all read", "back"]}

def actions(kind):
    """What Enter can do on an item's page; back is last, and where the
    cursor starts, so a stray Enter from a wheel changes nothing."""
    return ACTIONS.get(kind, ["back"])

def page(item, w, rows, act):
    """An item's own page: all of it, not the line it gets in the summary,
    and its actions on the last line, the one under the cursor reversed."""
    kind, title, data = item
    if kind == "todo":
        text = ([data["title"]] if data["title"] else []) + data["body"]
        sub = " ".join(x for x in (data.get("when", ""), "#" + data["project"] if data.get("project") else "") if x)
    elif kind == "mention":
        text = [str(data.get("message", ""))]
        sub = "%s · %s" % (data.get("from", "?"), time.strftime("%Y-%m-%d %H:%M", time.localtime(data.get("t", 0))))
    elif kind == "host":
        text, sub = ["✗ " + d for d in data], title
    else:
        text, sub = [data], title
    lines = [rule(kind, w)] + ([DIM + "  " + sub + RST] if sub else [])
    for t in text:
        lines += wrapped(t, w, indent="  ") if t.strip() else [""]
    room = max(1, rows - 2)
    if len(lines) > room:
        lines = lines[:room - 1] + [DIM + "  … %d more lines" % (len(lines) - room + 1) + RST]
    bar = "  ".join((INV + "[ %s ]" + RST) % a if i == act else "[ %s ]" % a
                    for i, a in enumerate(actions(kind)))
    return lines + [""] * (rows - 1 - len(lines)) + ["  " + bar]

def do(item, action):
    """Carry out an action from an item's page; a word for deck.log."""
    kind, title, data = item
    if action == "done":
        return "todo ok" if notes.archive(notes.PATH, data["raw"], done=True) else "todo gone"
    if action == "all read":
        mentions.mark_seen()
        return "mentions all read"
    return None

UP   = ("\x1b[A", "\x1bOA", "k", "\x1b[D", "\x1bOD")
DOWN = ("\x1b[B", "\x1bOB", "j", "\x1b[C", "\x1bOC", "\t")
BACK = ("\x1b", "\x7f", "\x08", "h")
IDLE = 120         # this long with no key, the cursor goes and the summary is back

def press(v, k, items):
    """One key on the screen's state v ({"sel", "page", "act"}): sel is the
    summary's cursor (None: no cursor, the screen as it sits on a shelf),
    page the item open, act its action under the cursor. The panel's
    wheel only sends up, down and Enter, so those three do everything;
    letters are shortcuts for a keyboard. Returns "quit", "repaint", the
    action to carry out, or None."""
    if k in ("\x03", "\x04"):
        return "quit"
    if k in ("r", "R", "\x0c"):
        return "repaint"
    if v["page"]:
        acts = actions(v["page"][0])
        if k in UP:
            v["act"] = (v["act"] - 1) % len(acts)
        elif k in DOWN:
            v["act"] = (v["act"] + 1) % len(acts)
        elif k in ("\r", "\n"):
            a = acts[v["act"]]
            v["page"] = None
            if a != "back":
                return a
        elif k in BACK + ("q", "Q"):
            v["page"] = None
        return None
    if k in ("q", "Q"):
        return "quit"
    if not items:
        v["sel"] = None
    elif k in UP:
        v["sel"] = len(items) - 1 if v["sel"] is None else (v["sel"] - 1) % len(items)
    elif k in DOWN:
        v["sel"] = 0 if v["sel"] is None else (v["sel"] + 1) % len(items)
    elif k in ("\r", "\n") and v["sel"] is not None:
        v["page"] = items[min(v["sel"], len(items) - 1)]
        v["act"] = len(actions(v["page"][0])) - 1
    elif k in BACK:
        v["sel"] = None
    return None

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

def paint(out, prev):
    """What to write so the screen shows out when it shows prev: every
    line when prev is None (a first paint, a clear, a new size), else only
    the lines that differ, each where it goes -- an e-ink panel redraws
    what reaches it, so a cursor that moves sends two lines, not the
    screen."""
    if prev is None:
        return "\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J"
    w = "".join("\x1b[%d;1H%s\x1b[K" % (i + 1, l)
                for i, l in enumerate(out) if i >= len(prev) or prev[i] != l)
    if len(out) < len(prev):
        w += "\x1b[%d;1H\x1b[J" % (len(out) + 1)
    return w

def watch(show):
    """The screen that stays up. It repaints only when what it says changes,
    or every HEARTBEAT: an e-ink panel flashes on every repaint and a slow
    one falls behind a busy screen, so the time on top is when it last
    changed, not a clock. r (or Ctrl-L) clears and repaints, for e-ink
    ghosting; q or Ctrl-C leaves. Up, down and Enter open an item and act
    on it (see press); IDLE with no key brings the plain summary back, so
    a panel left on a page still shows what's wrong. Its start, what it
    did and why it ended go to deck.log: behind a forced ssh command (an
    e-ink panel's key) the session closes on exit and nobody sees what it
    said."""
    size = shutil.get_terminal_size((0, 0))
    dlog.event("GLANCE", "start", "TERM=%s %dx%d" % (os.environ.get("TERM", "?"), size.columns, size.lines))
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    loud = ui.quiet()
    v = {"sel": None, "page": None, "act": 0}
    last, prev, painted, clear, why, touched = None, None, 0, True, "?", time.time()
    try:
        while True:
            cols, rows = shutil.get_terminal_size((60, 20))
            status, lines, items = body(cols, rows - 1, v["sel"])
            if v["sel"] is not None and v["sel"] >= len(items):
                v["sel"] = len(items) - 1 if items else None
                status, lines, items = body(cols, rows - 1, v["sel"])
            if v["page"]:
                lines = page(v["page"], cols, rows - 1, v["act"])
            now = (cols, rows, lines)
            if clear or now != last or time.time() - painted >= HEARTBEAT:
                out = [show(l) for l in [head(cols, status)] + lines]
                fresh = clear or not last or last[:2] != now[:2]
                sys.stdout.write(("\x1b[2J" if clear else "") + paint(out, None if fresh else prev))
                sys.stdout.flush()
                last, prev, painted, clear = now, out, time.time(), False
            k = wait(INTERVAL)
            if k is None:
                if (v["sel"] is not None or v["page"]) and time.time() - touched >= IDLE:
                    v.update(sel=None, page=None)
                continue
            touched = time.time()
            item = v["page"]
            r = press(v, k, items)
            if r == "quit":
                why = "key %r" % k
                break
            clear = r == "repaint"
            if r and not clear:
                dlog.event("GLANCE", r, do(item, r) or "")
    except KeyboardInterrupt:
        why = "Ctrl-C"
    except Exception:
        why = "crash"
        dlog.crash("GLANCE")
        raise
    finally:
        dlog.event("GLANCE", "end", why)
        loud()
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
