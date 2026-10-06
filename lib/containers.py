#!/usr/bin/env python3
"""phosphor containers - one fleet host's containers, and a hand on them.

    phosphor containers [HOST]          the panel (HOST: a name from the profile;
                                        none: this machine)
    phosphor containers HOST --once     one frame on stdout

Docker, or podman when docker isn't there or doesn't answer -- the same
engine FLEET's card counts. Listed over ssh (BatchMode, a key, never a
password prompt) riding FLEET's own connection when it's up; this machine
runs it locally. On a terminal it's a picker: j/k or a tap picks one, `l`
reads its last 300 log lines, `r` restarts it and `s` starts or stops it,
both asking first. Nothing runs through sudo: if the listing works without
it, so does acting on it.

What comes back from the host (names, states, logs) is shown as text, never
as terminal commands (sanitize.py), and a name only goes back into a command
when it looks like a container name.
"""
import os, re, shlex, shutil, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, PH, AMB, RED, RST, FG, vlen, pad, getkey, topbar, HEAD
import deckconf
from sanitize import clean, clean_text

INV = "\x1b[7m"
INTERVAL = 10

# The same choice share/collect.sh makes for the card's count.
LIST = r"""
if command -v docker >/dev/null 2>&1 && docker ps -q >/dev/null 2>&1; then e=docker
elif command -v podman >/dev/null 2>&1; then e=podman
else echo ENGINE=; exit 0; fi
echo ENGINE=$e
$e ps -a --format '{{.Names}}	{{.State}}	{{.Status}}	{{.Image}}' 2>&1
"""

# Made-up containers for `phosphor demo`'s made-up machines.
DEMO = {"nebula": ("docker", [("jellyfin", "running", "Up 3 days", "jellyfin/jellyfin"),
                              ("navidrome", "running", "Up 3 days", "deluan/navidrome"),
                              ("paperless", "running", "Up 2 hours", "paperless-ngx"),
                              ("immich-server", "running", "Up 3 days", "immich-server"),
                              ("immich-db", "running", "Up 3 days", "postgres:16"),
                              ("vaultwarden", "running", "Up 9 days", "vaultwarden/server"),
                              ("uptime-kuma", "running", "Up 9 days", "louislam/uptime-kuma")]),
        "relay": ("podman", [("caddy", "running", "Up 5 days", "caddy:2"),
                             ("headscale", "running", "Up 5 days", "headscale/headscale"),
                             ("adguard", "exited", "Exited (137) 40 minutes ago", "adguard/adguardhome"),
                             ("ntfy", "running", "Up 5 days", "binwiederhier/ntfy")])}

NAME_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def find(prof, name):
    """(name, ssh target | None for this machine), or None: not a host."""
    hs = deckconf.hosts(prof)
    if not name:
        h = next((h for h in hs if h.get("local")), None)
        return (h["name"], None) if h else (os.uname().nodename, None)
    h = next((h for h in hs if h.get("name") == name), None)
    if h is None:
        return None
    return h["name"], (None if h.get("local") else deckconf.target(h))


def ssh_argv(target, remote, connect_t=8):
    """The host's ssh, riding FLEET's ControlMaster socket when it's up."""
    ctrl = os.path.join(deckconf.cache_dir(), "ssh")
    os.makedirs(ctrl, mode=0o700, exist_ok=True)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % connect_t,
            "-o", "ControlMaster=auto", "-o", "ControlPersist=60s",
            "-o", "ControlPath=" + os.path.join(ctrl, "%C"), target, remote]


def run(target, script, timeout=30):
    """(exit code, output) of a sh script there; -1 when it never ran."""
    argv = ssh_argv(target, "sh -s") if target else ["sh", "-s"]
    try:
        r = subprocess.run(argv, input=script, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def parse(out):
    """(engine or "", [(name, state, status, image)], error line or "")."""
    engine, rows, err = None, [], ""
    for line in out.splitlines():
        if engine is None:
            if line.startswith("ENGINE="):
                engine = clean(line[7:].strip())
            continue
        f = line.split("\t")
        if len(f) == 4:
            rows.append(tuple(clean(x).strip() for x in f))
        elif line.strip() and not err:
            err = clean(line.strip())
    return engine or "", rows, err


def fetch(name, target, demo=False):
    """(engine, rows, problem): problem is "" when the list is good."""
    if demo:
        e, rows = DEMO.get(name, ("", []))
        return e, list(rows), ""
    rc, out = run(target, LIST)
    if rc == 255 or rc == -1:
        return "", [], "can't reach %s over ssh" % name
    engine, rows, err = parse(out)
    if not engine:
        return "", [], "no docker or podman on %s" % name
    if rc != 0 and not rows:
        return engine, [], err or "%s ps failed (exit %d)" % (engine, rc)
    order = {"running": 0, "restarting": 1, "paused": 2}
    rows.sort(key=lambda r: (order.get(r[1].lower(), 3), r[0]))
    return engine, rows, ""


def exit_code(status):
    m = re.match(r"Exited \((-?\d+)\)", status)
    return int(m.group(1)) if m else None


def classify(state, status):
    """(color, tag). An exit that wasn't 0 is the loud one: a container
    that finished its job and left with 0 is meant to sit there."""
    s = state.lower()
    if s == "running":
        return PH, "running"
    if s in ("restarting", "paused", "created", "removing"):
        return AMB, s
    if s in ("exited", "dead"):
        code = exit_code(status)
        if code in (0, None) and s == "exited":
            return DIM, "exited"
        return RED, s if code in (0, None) else "exit %d" % code
    return MUTE, s or "unknown"


def since(status):
    """"Up 3 days" -> "3 days"; "Exited (1) 40 minutes ago" -> "40 minutes ago"."""
    return re.sub(r"^(Up|Exited \(-?\d+\))\s*", "", status)


def lines(rows, w, sel=None):
    """One line per container; sel: the picked one, in reverse video."""
    if not rows:
        return [DIM + "  no containers" + RST]
    nw = min(max(vlen(r[0]) for r in rows), max(6, w // 3))
    out = []
    for i, (name, state, status, image) in enumerate(rows):
        col, tag = classify(state, status)
        rest = " " + since(status)
        if i == sel:
            txt = " ● " + ("%-*s" % (nw, name))[:nw] + " " + "%-10s" % tag + rest
            out.append(" " + INV + pad(txt[:w - 2], w - 2) + RST)
            continue
        line = "  " + col + "●" + RST + " " + FG + ("%-*s" % (nw, name))[:nw] + RST \
            + " " + col + ("%-10s" % tag) + RST + DIM + rest[:max(0, w - nw - 15)] + RST
        out.append(line)
    return out


def header(name, engine, rows, w):
    sub = (engine + " on " if engine else "") + name
    run_n = sum(1 for r in rows if r[1].lower() == "running")
    return topbar("CONTAINERS", sub, "%d/%d up" % (run_n, len(rows)) if rows else "", w)


def frame(name, target, cols, rows_max, demo=False):
    w = max(20, cols)
    engine, rows, problem = fetch(name, target, demo)
    out = header(name, engine, rows, w)
    out += [" " + AMB + problem + RST] if problem else lines(rows, w)
    return out[:max(1, rows_max)]


# ── acting on one ─────────────────────────────────────────────
KEYS = [("l", "logs"), ("r", "restart"), ("s", "start/stop"), ("q", "quit")]


def command(engine, verb, cname):
    """The command for `verb` on one container, or None when the name
    doesn't look like one (it came from the host: never trust it in a
    shell line just because it was listed)."""
    if engine not in ("docker", "podman") or not NAME_OK.match(cname):
        return None
    if verb == "logs":
        return "%s logs --tail 300 %s 2>&1" % (engine, shlex.quote(cname))
    if verb in ("restart", "start", "stop"):
        return "%s %s %s" % (engine, verb, shlex.quote(cname))
    return None


def logs(target, engine, cname):
    cmd = command(engine, "logs", cname)
    if not cmd:
        return "that name doesn't look like a container's\n"
    rc, out = run(target, cmd + "\n", timeout=20)
    text = clean_text(out).strip()
    if rc == -1 or rc == 255:
        return "couldn't reach the host\n"
    return text + "\n" if text else "no log lines for %s\n" % cname


def act(target, engine, verb, cname):
    """(ok, message)."""
    cmd = command(engine, verb, cname)
    if not cmd:
        return False, "that name doesn't look like a container's"
    rc, out = run(target, cmd + "\n", timeout=120)
    past = {"restart": "restarted", "start": "started", "stop": "stopped"}[verb]
    if rc == 0:
        return True, "%s %s" % (past, cname)
    last = clean(out.strip().splitlines()[-1]) if out.strip() else ""
    return False, "%s %s failed%s" % (verb, cname, (": " + last) if last else
                                      ("" if rc < 0 else " (exit %d)" % rc))


def panel(name, target, demo=False):
    import form
    rows, engine, problem, last = [], "", "", 0.0
    sel, ask, msg = 0, None, ""
    on = "\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"
    sys.stdout.write(on); sys.stdout.flush()
    try:
        while True:
            if time.time() - last >= INTERVAL:
                engine, rows, problem = fetch(name, target, demo)
                last = time.time()
                sel = min(sel, max(0, len(rows) - 1))
            cols, height = shutil.get_terminal_size((80, 24))
            w = max(20, cols)
            out = header(name, engine, rows, w)
            body = [" " + AMB + problem + RST] if problem else lines(rows, w, sel if rows else None)
            room = max(1, height - 3 - HEAD)
            top = max(0, min(sel - room + 1, len(body) - room)) if len(body) > room else 0
            shown = body[top:top + room]
            out += shown
            first = HEAD + 1
            spans, x, foot = [], 2, " "
            for k, l in KEYS:
                spans.append((x, x + len(k) + 1 + len(l), k)); x += len(k) + 1 + len(l) + 2
            foot += "  ".join(AMB + k + RST + FG + " " + l + RST for k, l in KEYS) + DIM + "  · j/k pick" + RST
            out.append(foot)
            if ask:
                out.append(" " + AMB + "%s %s on %s?" % (ask[0], ask[1], name) + RST
                           + FG + "  y yes · any other key: no" + RST)
            elif msg:
                out.append(" " + msg)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J"); sys.stdout.flush()

            k = getkey(max(0.2, INTERVAL - (time.time() - last)))
            if k is None:
                continue
            if isinstance(k, tuple):
                if k[0] != "MOUSE" or not k[4] or k[1] not in (0, 64, 65):
                    continue
                if k[1] == 64: sel = max(0, sel - 1); continue
                if k[1] == 65: sel = min(max(0, len(rows) - 1), sel + 1); continue
                x, y = k[2], k[3]
                if ask:
                    ask = None; msg = DIM + "left alone" + RST; continue
                if first <= y < first + len(shown) and rows and not problem:
                    sel, msg = top + y - first, ""; continue
                if y == first + len(shown):
                    hit = [kk for a, b, kk in spans if a <= x <= b]
                    if not hit: continue
                    k = hit[0]
                else:
                    continue
            if ask:
                verb, cname = ask
                ask = None
                if k in ("y", "Y"):
                    msg = DIM + "%s %s..." % (verb, cname) + RST
                    ok, m = act(target, engine, verb, cname)
                    msg = (PH + "✓ " if ok else RED + "✗ ") + m + RST
                    last = 0.0
                else:
                    msg = DIM + "left alone" + RST
                continue
            if k in ("q", "Q", "\x03", "\x1b"):
                break
            if k in ("j", "\x1b[B"): sel, msg = min(max(0, len(rows) - 1), sel + 1), ""; continue
            if k in ("k", "\x1b[A"): sel, msg = max(0, sel - 1), ""; continue
            if not rows or k not in ("l", "r", "s"):
                continue
            if demo:
                msg = AMB + "the demo's machines aren't real: nothing to touch" + RST; continue
            cname, state = rows[sel][0], rows[sel][1].lower()
            if k == "l":
                form.pager(logs(target, engine, cname))
                sys.stdout.write(on); sys.stdout.flush()
                continue
            if k == "r":
                ask = ("restart", cname)
            else:
                ask = ("stop" if state in ("running", "restarting", "paused") else "start", cname)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n"); sys.stdout.flush()
    return 0


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    prof, _ = deckconf.load()
    got = find(prof, a[0] if a else None)
    if got is None:
        names = ", ".join(h.get("name", "?") for h in deckconf.hosts(prof)) or "none"
        sys.stderr.write("phosphor containers: no host %s in the profile (hosts: %s)\n" % (a[0], names))
        return 2
    name, target = got
    demo = bool(((prof or {}).get("deck") or {}).get("demo", False))
    if "--once" in sys.argv:
        cols = shutil.get_terminal_size((80, 24)).columns
        print("\n".join(frame(name, target, cols, 10000, demo)))
        return 0
    if sys.stdin.isatty() and sys.stdout.isatty():
        return panel(name, target, demo)
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, height = shutil.get_terminal_size((80, 24))
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(frame(name, target, cols, height, demo)) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
