#!/usr/bin/env python3
"""phosphor services - the brain's own systemd units, at a glance in a pane.

The units Phosphor itself writes (the deck's service and watchdog timer,
one fleet-*.service per mounted host, one tunnel per [[tunnels]]) come
straight from `gen`, the same source `phosphor gen` writes to
~/.config/systemd/user/ -- nothing to configure for those. Add your own
homelab services with [services] extra in the profile:

    [services]
    extra = ["nginx.service", "user:some-user-timer.timer"]

A plain name is a system unit (`systemctl show`, no --user, works without
sudo for a read-only status); prefix it "user:" for one of yours.

    phosphor services           the panel, redrawn every interval
    phosphor services --once    one frame on stdout

On a terminal the panel is also a picker: j/k or a tap picks a unit, `l`
reads its logs, `r` restarts it and `s` starts or stops it -- both ask
first. A system unit goes through sudo (its password prompt shows as
usual); the deck's own service and timer are left to `phosphor restart`.
"""
import os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, PH, AMB, RED, RULE, RST, FG, vlen, pad, getkey, topbar, HEAD

INV = "\x1b[7m"
import deckconf, gen

INTERVAL = 5
PROPS = "LoadState,ActiveState,SubState,MemoryCurrent"


def phosphor_units(prof):
    """Every unit `phosphor gen` writes for this profile -- one source of
    truth, so this list can never drift from what's actually installed."""
    return sorted(gen.units(gen.Ctx(prof)).keys())


def extra_units(prof):
    raw = ((prof or {}).get("services") or {}).get("extra", [])
    out = []
    for item in raw:
        if item.startswith("user:"):
            out.append(("user", item[5:]))
        else:
            out.append(("system", item))
    return out


def settings(prof):
    return ((prof or {}).get("services") or {}).get("interval", INTERVAL)


def query(scope, name, timeout=4):
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) \
        + ["show", name, "--no-page", "--property=" + PROPS]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        d = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
        return d
    except Exception:
        return {}


def classify(info):
    """(color, tag) for one unit's state. inactive/dead isn't necessarily a
    problem (a tunnel you turned off is meant to sit there) -- only failed
    or missing gets a loud color."""
    if info.get("LoadState") == "not-found":
        return MUTE, "not found"
    a = info.get("ActiveState", "")
    if a == "active":
        return PH, info.get("SubState") or "active"
    if a == "failed":
        return RED, "failed"
    if a in ("activating", "reloading", "deactivating"):
        return AMB, a
    if not a:
        return MUTE, "unknown"
    return DIM, info.get("SubState") or a


def mem_str(info):
    raw = info.get("MemoryCurrent", "")
    if not raw or raw == "[not set]":
        return ""
    try:
        n = int(raw)
    except ValueError:
        return ""
    if n <= 0:
        return ""
    mb = n / (1024.0 * 1024.0)
    return ("%.0fM" if mb >= 10 else "%.1fM") % mb


def label(name):
    base, _, kind = name.rpartition(".")
    return base if kind in ("", "service") else "%s (%s)" % (base, kind)


def fetch(units):
    if not units:
        return []
    with ThreadPoolExecutor(max_workers=max(2, len(units))) as ex:
        futs = [ex.submit(query, scope, name) for scope, name in units]
        return [(scope, name, f.result()) for (scope, name), f in zip(units, futs)]


def all_units(prof):
    return [("user", n) for n in phosphor_units(prof)] + extra_units(prof)


def lines(results, w, sel=None):
    """One line per unit; sel: the picked one, in reverse video."""
    if not results:
        return [DIM + "  nothing to watch" + RST]
    name_w = min(max(vlen(label(n)) for _, n, _ in results), max(6, w - 20))
    out = []
    for i, (_, name, info) in enumerate(results):
        col, tag = classify(info)
        mem = mem_str(info)
        if i == sel:
            txt = " ● " + ("%-*s" % (name_w, label(name)))[:name_w] + " " + "%-10s" % tag + mem.rjust(6 if mem else 0)
            out.append(" " + INV + pad(txt, w - 2)[:w - 2] + RST)
            continue
        line = "  " + col + "●" + RST + " " + FG + ("%-*s" % (name_w, label(name)))[:name_w] + RST \
            + " " + col + ("%-10s" % tag) + RST
        if mem:
            line += DIM + mem.rjust(6) + RST
        if vlen(line) > w:
            line = line[:w]
        out.append(line)
    return out


def frame(prof, cols, rows):
    w = max(20, cols)
    res = fetch(all_units(prof))
    out = topbar("SERVICES", "systemd units", "%d units" % len(res), w)
    out += lines(res, w)
    return out[:max(1, rows)]


# ── acting on one ─────────────────────────────────────────────
KEYS = [("l", "logs"), ("r", "restart"), ("s", "start/stop"), ("q", "quit")]


def own(prof, name):
    """The deck's own service or watchdog: stopping it from a pane inside
    it would take the pane down mid-question. phosphor restart does it
    properly (and brings every screen back)."""
    sess = ((prof or {}).get("deck") or {}).get("session", "deck")
    return name in (sess + ".service", sess + ".timer")


def systemctl(scope, *a):
    cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + list(a)
    if scope == "system" and os.geteuid() != 0 and shutil.which("sudo"):
        cmd = ["sudo"] + cmd
    return cmd


def logs(scope, name):
    cmd = ["journalctl"] + (["--user"] if scope == "user" else []) + ["-u", name, "-n", "300", "--no-pager"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        text = r.stdout + r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        text = "journalctl: %s\n" % e.__class__.__name__
    return text.strip() + "\n" if text.strip() else "no log lines for %s\n" % name


def run_verb(scope, name, verb):
    """Off the panel's screen, so sudo's password prompt shows. (ok, msg)"""
    sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h")
    cmd = systemctl(scope, verb, name)
    print("\n  " + DIM + "$ " + " ".join(cmd) + RST); sys.stdout.flush()
    try:
        rc = subprocess.run(cmd, timeout=120).returncode
    except (OSError, subprocess.TimeoutExpired):
        rc = -1
    except KeyboardInterrupt:
        rc = -2
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    past = {"restart": "restarted", "start": "started", "stop": "stopped"}[verb]
    if rc == 0:
        return True, "%s %s" % (past, label(name))
    return False, "%s %s failed%s" % (verb, label(name), "" if rc < 0 else " (exit %d)" % rc)


def panel(prof):
    import form
    interval = settings(prof)
    units = all_units(prof)
    results, last = [], 0.0
    sel, ask, msg = 0, None, ""
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
    try:
        while True:
            if time.time() - last >= interval:
                results, last = fetch(units), time.time()
                sel = min(sel, max(0, len(results) - 1))
            cols, rows = shutil.get_terminal_size((80, 24))
            w = max(20, cols)
            out = topbar("SERVICES", "systemd units", "%d units" % len(results), w)
            body = lines(results, w, sel if results else None)
            room = max(1, rows - 3 - HEAD)
            top = max(0, min(sel - room + 1, len(body) - room)) if len(body) > room else 0
            shown = body[top:top + room]
            out += shown
            first = HEAD + 1                                # screen row of body[top]
            foot = " " + "  ".join(AMB + k + RST + FG + " " + l + RST for k, l in KEYS) + DIM + "  · j/k pick" + RST
            spans, x = [], 2
            for k, l in KEYS:
                spans.append((x, x + len(k) + 1 + len(l), k)); x += len(k) + 1 + len(l) + 2
            out.append(foot)
            if ask:
                out.append(" " + AMB + "%s %s?" % (ask[0], label(ask[2])) + RST + FG + "  y yes · any other key: no" + RST)
            elif msg:
                out.append(" " + msg)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J"); sys.stdout.flush()

            k = getkey(max(0.2, interval - (time.time() - last)))
            if k is None:
                continue
            if isinstance(k, tuple):
                if k[0] != "MOUSE" or not k[4] or k[1] not in (0, 64, 65):
                    continue
                if k[1] == 64: sel = max(0, sel - 1); continue
                if k[1] == 65: sel = min(len(results) - 1, sel + 1); continue
                x, y = k[2], k[3]
                if ask:
                    ask = None; msg = DIM + "left alone" + RST; continue
                if first <= y < first + len(shown) and results:
                    sel, msg = top + y - first, ""; continue
                if y == first + len(shown):
                    hit = [kk for a, b, kk in spans if a <= x <= b]
                    if not hit: continue
                    k = hit[0]
                else:
                    continue
            if ask:
                verb, scope, name = ask
                ask = None
                if k in ("y", "Y"):
                    ok, m = run_verb(scope, name, verb)
                    msg = (PH + "✓ " if ok else RED + "✗ ") + m + RST
                    last = 0.0
                else:
                    msg = DIM + "left alone" + RST
                continue
            if k in ("q", "Q", "\x03", "\x1b"):
                break
            if k in ("j", "\x1b[B"): sel, msg = min(len(results) - 1, sel + 1), ""; continue
            if k in ("k", "\x1b[A"): sel, msg = max(0, sel - 1), ""; continue
            if not results or k not in ("l", "r", "s"):
                continue
            scope, name, info = results[sel]
            if k == "l":
                form.pager(logs(scope, name))
                sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"); sys.stdout.flush()
                continue
            if own(prof, name):
                msg = AMB + "that's the deck itself: phosphor restart (r in the DECK tab)" + RST; continue
            if info.get("LoadState") == "not-found":
                msg = AMB + "%s isn't installed here" % label(name) + RST; continue
            if k == "r":
                ask = ("restart", scope, name)
            else:
                ask = ("stop" if info.get("ActiveState") in ("active", "activating", "reloading") else "start",
                       scope, name)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h\n"); sys.stdout.flush()
    return 0


def main():
    prof, _ = deckconf.load()
    interval = settings(prof)
    if "--once" in sys.argv:
        cols = shutil.get_terminal_size((80, 24)).columns
        print("\n".join(frame(prof, cols, 10000)))
        return 0
    if sys.stdin.isatty() and sys.stdout.isatty():
        return panel(prof)
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((80, 24))
            out = frame(prof, cols, rows)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
