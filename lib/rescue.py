"""When the deck won't start: the screen `deck` shows instead of zellij's
"No session found". It says why (deck.service's state and for how long,
how its last start ended, zellij's last panic) and what holds the start
up (a start that never finished, a screen's reconnect loop, another
`deck` waiting, the browser-access server), and offers the fixes on one
key or tap each: retry, start without browser access, close what holds it
up, the log, doctor, a shell. Locked out on a phone, nothing here needs
ssh from somewhere else or an assistant.

The reading half (state(), panics(), holders(), lines()) has no terminal
and no side effects: doctor uses it too, and tests feed it text.
"""
import os, re, signal, subprocess, sys, time
from ui import *
import proc

LOG = "/tmp/zellij-%d/zellij-log/zellij.log" % os.getuid()
UP = os.path.expanduser("~/.local/share/phosphor/%s-up.sh")
STUCK = 120          # a start this long is hung: deck-up's own timeout is 60


# --- reading -----------------------------------------------------------------

def _mono_to_epoch(us, now=None, mono=None):
    """systemd's *TimestampMonotonic (µs since boot, 0 = never) as epoch."""
    if not us: return None
    now = time.time() if now is None else now
    mono = time.monotonic() if mono is None else mono
    return now - (mono - us / 1e6)

def parse_show(text, now=None, mono=None):
    """`systemctl show -p ...` output as what the screen says: state, sub,
    result, status (deck-up's exit), since (epoch the state began),
    started (epoch of the last start)."""
    p = dict(l.split("=", 1) for l in text.splitlines() if "=" in l)
    num = lambda k: int(p.get(k) or 0) if (p.get(k) or "0").isdigit() else 0
    return {"state": p.get("ActiveState", ""), "sub": p.get("SubState", ""),
            "result": p.get("Result", ""), "status": p.get("ExecMainStatus", ""),
            "since": _mono_to_epoch(num("StateChangeTimestampMonotonic"), now, mono),
            "started": _mono_to_epoch(num("InactiveExitTimestampMonotonic"), now, mono)}

SHOW = ["-p", "ActiveState", "-p", "SubState", "-p", "Result", "-p", "ExecMainStatus",
        "-p", "StateChangeTimestampMonotonic", "-p", "InactiveExitTimestampMonotonic"]

def state(sess):
    """deck.service and deck.timer, or None without a user systemd."""
    r = proc.run(["systemctl", "--user", "show", "%s.service" % sess] + SHOW, timeout=10)
    if r.returncode != 0 or "ActiveState=" not in r.stdout:
        return None
    s = parse_show(r.stdout)
    t = proc.run(["systemctl", "--user", "is-active", "%s.timer" % sess], timeout=10)
    s["timer"] = t.stdout.strip() or "unknown"
    return s

_STAMP = re.compile(r"\| (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ ")

def panics(text, since=None):
    """[(epoch, "where: what")] for each panic of zellij's server in its
    log text, oldest first, only those after since (epoch) when given."""
    out, rows = [], text.splitlines()
    for i, l in enumerate(rows):
        if "Panic occurred" not in l: continue
        m = _STAMP.search(l)
        try: t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")) if m else None
        except ValueError: t = None
        if t is None or (since and t < since): continue
        where = msg = ""
        server = False
        for d in rows[i + 1:i + 6]:
            d = d.strip()
            if d.startswith("location:"):
                where = d.split(":", 1)[1].strip().replace("At ", "", 1)
                server = where.startswith("zellij-server/")
                where = re.sub(r"^zellij-\w+/src/", "", where)
            elif d.startswith("message:"):
                msg = d.split(":", 1)[1].strip()
        # a client's panic is a screen whose link dropped (EIO on its
        # stdin): every disconnect can leave one. The server's are the deck.
        if not server: continue
        out.append((t, ("%s: %s" % (where, msg)).strip(": ")))
    return out

def log_tail(path=LOG, size=2 << 20):
    """The end of zellij's log ('' when there is none): it grows to MBs."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); f.seek(max(0, f.tell() - size))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""

def what(argv, sess):
    """What a process is, when it's one that can hold the deck's start up;
    None for anything else. argv: its argument list."""
    if not argv: return None
    prog = os.path.basename(argv[0])
    rest = argv[1:]
    if prog == "zellij":
        if "attach" in rest and "--create-background" in rest and sess in rest:
            return "a start that never finished"
        if rest[:1] == ["web"] or ("web" in rest and "--start" in rest):
            return "the browser-access server"
        if rest[-2:] == ["attach", sess] or rest[-1:] == [sess] and "attach" in rest:
            return "a screen still attached to the old deck"
        return None
    if prog in ("sh", "bash", "dash", "zsh") and "-c" in rest:
        cmd = rest[rest.index("-c") + 1] if rest.index("-c") + 1 < len(rest) else ""
        if re.search(r"\bdeck\b.*\|\|.*zellij attach|while .*\bdeck\b", cmd):
            return "a screen's reconnect loop"
        return None
    if prog.startswith("python") and len(rest) >= 2 and os.path.basename(rest[0]) == "phosphor" \
            and rest[1] in ("attach", "deck"):
        return "another screen waiting to get in"
    return None

def _ancestors(pid):
    out = set()
    while pid > 1 and pid not in out:
        out.add(pid)
        try:
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out

def _started(pid):
    """When a process started (epoch), from /proc."""
    try:
        with open("/proc/stat") as f:
            boot = next(int(l.split()[1]) for l in f if l.startswith("btime "))
        with open("/proc/%d/stat" % pid) as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, StopIteration, IndexError):
        return None

def holders(sess, me=None):
    """[(pid, what, since)] the processes that can hold a start up, this
    one and the ones it runs under left out (a screen's own loop)."""
    mine = _ancestors(me or os.getpid())
    uid, out = os.getuid(), []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) in mine: continue
        try:
            if os.stat("/proc/" + d).st_uid != uid: continue
            with open("/proc/%s/cmdline" % d, "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        w = what(argv, sess)
        if w: out.append((int(d), w, _started(int(d))))
    return sorted(out, key=lambda x: x[2] or 0)


# --- saying it ---------------------------------------------------------------

def ago(t, now=None):
    s = max(0, int((now or time.time()) - t))
    if s < 90: return "%ds" % s
    if s < 5400: return "%dm" % (s // 60)
    h, m = divmod(s // 60, 60)
    return "%dh %dm" % (h, m) if h < 48 else "%dd" % (h // 24)

def clock(t):
    return time.strftime("%H:%M", time.localtime(t))

def describe(st, now=None):
    """(sym, what deck.service is doing) for the screen and doctor."""
    if st is None:
        return BAD, "no user systemd here: nothing starts the deck"
    since = (" for %s (since %s)" % (ago(st["since"], now), clock(st["since"]))) if st["since"] else ""
    if st["state"] == "activating":
        return (BAD if st["since"] and (now or time.time()) - st["since"] > STUCK else WARN), "starting" + since
    if st["state"] == "failed":
        how = {"timeout": "timed out", "exit-code": "exit %s" % st["status"]}.get(st["result"], st["result"])
        return BAD, "its last start failed (%s)%s" % (how, since.replace(" for", ","))
    if st["state"] in ("inactive", "active"):
        if st["timer"] != "active":
            return WARN, "stopped, and its watchdog too (phosphor down?)"
        last = " (last start %s)" % clock(st["started"]) if st["started"] else ""
        return WARN, "started fine, but the session is gone%s" % last
    return WARN, st["state"] + since

def lines(sess, st, pan, held, web, w, now=None):
    """The whole screen, and {row: key} for taps (rows count from 1)."""
    now = now or time.time()
    out = topbar("PHOSPHOR DECK", "the deck isn't up", sess, w)
    def item(sym, label, val):
        """Beside its label when it fits, else on the next line (a phone)."""
        head = "  %s %s%-14s%s" % (sym, FG, label, RST)
        if 18 + len(val) <= w:
            return [head + " " + val]
        return [head, "    " + MUTE + cut(val, w - 5) + RST]
    sym, say = describe(st, now)
    out += [""] + item(sym, sess + ".service", say)
    if pan:
        t, msg = pan[-1]
        out += item(WARN, "zellij", "panicked at %s: %s" % (clock(t), msg))
    taps = {}
    if held:
        out += ["", "  " + rule("holding it up", w - 4)]
        for i, (pid, what_, since) in enumerate(held[:9], 1):
            when = "since %s (%s)" % (clock(since), ago(since, now)) if since else ""
            rows = ["  %s%d%s  %s" % (AMB, i, RST, cut(what_, w - 7))]
            if when and 7 + len(what_) + 2 + len(when) <= w:
                rows[0] += "  " + DIM + when + RST
            elif when:
                rows.append("     " + DIM + when + RST)
            for r in rows:
                out.append(r); taps[len(out)] = str(i)
    out.append("")
    opts = [("r", "retry the start")]
    if web: opts.append(("w", "start without browser access"))
    if held: opts.append(("k", "close all of the above, then retry"))
    opts += [("l", "the log"), ("d", "doctor"), ("s", "a shell here"), ("q", "leave")]
    for k, label in opts:
        out.append("  " + AMB + k + RST + "  " + FG + label + RST)
        taps[len(out)] = k
    if held:
        out.append("  " + DIM + cut("1-%d closes just that one" % min(9, len(held)), w - 4) + RST)
    return out, taps


# --- doing it ----------------------------------------------------------------

def close(pids, wait=3.0):
    """TERM, then KILL whatever is still there after wait seconds."""
    for p in pids:
        try: os.kill(p, signal.SIGTERM)
        except OSError: pass
    end = time.time() + wait
    while time.time() < end and any(os.path.exists("/proc/%d" % p) for p in pids):
        time.sleep(0.1)
    for p in pids:
        try: os.kill(p, signal.SIGKILL)
        except OSError: pass

def can_skip_web(sess):
    """The generated deck-up reads PHOSPHOR_WEB (a gen from 2.7.5 on)."""
    try:
        with open(UP % sess) as f: return "PHOSPHOR_WEB" in f.read()
    except OSError:
        return False

def start(sess, web=True):
    """Stop the hung start, start again (and the watchdog, if it's off).
    Without web, this one start makes the session without browser access:
    the unit reads it from the user manager's environment."""
    close([p for p, w, _ in holders(sess) if w == "a start that never finished"])
    sc = ["systemctl", "--user"]
    if not web:
        proc.run(sc + ["set-environment", "PHOSPHOR_WEB=0"], timeout=10)
    try:
        proc.run(sc + ["start", "%s.timer" % sess], timeout=15)
        r = proc.run(sc + ["restart", "%s.service" % sess], timeout=150)
    finally:
        if not web:
            proc.run(sc + ["unset-environment", "PHOSPHOR_WEB"], timeout=10)
    return r.returncode == 0

def the_log(sess):
    j = proc.run(["journalctl", "--user", "-u", "%s.service" % sess, "-n", "40", "--no-pager"], timeout=15)
    z = [l for l in log_tail().splitlines() if l.startswith(("ERROR", "WARN"))
         or l.startswith(" ") and ("location:" in l or "message:" in l)][-40:]
    return ("%s.service, its last lines (journalctl --user -u %s.service)\n\n%s\n\n"
            "zellij's errors (%s)\n\n%s\n" % (sess, sess, (j.stdout or j.stderr or "(nothing)").rstrip(),
                                             LOG, "\n".join(z) or "(nothing)"))

def screen(zj, sess, prof, live):
    """Until the deck is up (True: go in) or q (False). live(): is it up."""
    import form
    web = bool(((prof or {}).get("deck") or {}).get("web")) and can_skip_web(sess)
    msg, first = "", True
    try:
        while True:
            if live():
                form.leave(); print("  the deck is up: going in"); return True
            st = state(sess)
            pan = panics(log_tail(), (st or {}).get("started"))
            held = holders(sess)
            w = width()
            out, taps = lines(sess, st, pan, held, web, w)
            if msg: out += ["", "  " + AMB + cut(msg, w - 4) + RST]
            form.screen(out)
            k = getkey(5, mouse=True, typeahead=not first)   # kept between polls; not from before it showed (#120)
            first = False
            if isinstance(k, tuple):
                k = taps.get(k[2]) if k[0] == "TAP" else None
            if k is None: continue
            msg = ""
            if k in ("q", "Q", "\x1b", "\x03", "\x04"):
                return False
            if k in ("r", "w", "k") or (k.isdigit() and 0 < int(k) <= len(held)):
                if k == "w" and not web: continue
                if k.isdigit():
                    pid, what_, _ = held[int(k) - 1]
                    close([pid]); msg = "closed %s (pid %d)" % (what_, pid); continue
                if k == "k":
                    close([p for p, _, _ in held])
                form.screen(out + ["", "  " + AMB + "starting the deck... (up to two minutes)" + RST])
                ok = start(sess, web=(k != "w"))
                if not (ok and __import__("session").poll_until(live, 15)):
                    msg = "it didn't come up: l shows why"
                continue
            if k == "l":
                form.pager(the_log(sess))
            elif k == "d":
                form.leave()
                r = subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "doctor"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                form.pager(r.stdout.decode("utf-8", "replace"))
            elif k == "s":
                form.leave()
                sh = os.environ.get("SHELL") or "/bin/sh"
                print("  a shell on this machine: exit goes back to the deck's screen")
                subprocess.call([sh, "-l"])
    finally:
        form.leave()
