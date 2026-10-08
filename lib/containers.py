#!/usr/bin/env python3
"""phosphor containers - one fleet host's containers, and a hand on them.

    phosphor containers [HOST]          the panel (HOST: a name from the profile;
                                        none: this machine)
    phosphor containers HOST --once     one frame on stdout
    phosphor containers HOST --json     the same list as JSON

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
from ui import DIM, MUTE, PH, AMB, RED, RST, FG, vlen, pad, topbar, emit
import deckconf, proc, tui
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
    return proc.ssh(target, remote, connect_t, persist="60s")


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


def as_json(name, engine, rows, problem):
    """--json: the host, its engine and one record per container; `problem`
    is null when the list is good."""
    return {"host": name, "engine": engine or None, "problem": problem or None,
            "containers": [{"name": n, "state": st, "tag": classify(st, status)[1], "status": status,
                            "image": image, "exit": exit_code(status)} for n, st, status, image in rows]}


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


class Panel(tui.ListPanel):
    KEYS = KEYS
    INTERVAL = INTERVAL

    def __init__(self, name, target, demo=False):
        super().__init__()
        self.name, self.target, self.demo, self.engine = name, target, demo, ""

    def fetch(self):
        self.engine, rows, self.problem = fetch(self.name, self.target, self.demo)
        return rows

    def header(self, w):
        return header(self.name, self.engine, self.rows, w)

    def lines(self, w, sel):
        return lines(self.rows, w, sel)

    def act(self, k, row):
        if self.demo:
            return self.say("the demo's machines aren't real: nothing to touch")
        cname, state = row[0], row[1].lower()
        if k == "l":
            return self.page(logs(self.target, self.engine, cname))
        if k == "r":
            verb = "restart"
        else:
            verb = "stop" if state in ("running", "restarting", "paused") else "start"
        self.confirm("%s %s on %s?" % (verb, cname, self.name),
                     lambda: act(self.target, self.engine, verb, cname))


def panel(name, target, demo=False):
    return Panel(name, target, demo).run()


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
    if "--json" in sys.argv:
        engine, rows, problem = fetch(name, target, demo)
        return emit(as_json(name, engine, rows, problem), 1 if problem else 0)
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
