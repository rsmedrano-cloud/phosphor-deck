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
"""
import os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, PH, AMB, RED, RULE, RST, FG, vlen
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


def frame(prof, cols, rows):
    units = [("user", n) for n in phosphor_units(prof)] + extra_units(prof)
    w = max(20, cols)
    out = [RULE + " SERVICES " + "─" * max(0, w - 10) + RST]
    results = fetch(units)
    if not results:
        out.append(DIM + "  nothing to watch" + RST)
        return out[:max(1, rows)]
    name_w = min(max(vlen(label(n)) for _, n, _ in results), max(6, w - 20))
    for _, name, info in results:
        col, tag = classify(info)
        mem = mem_str(info)
        line = "  " + col + "●" + RST + " " + FG + ("%-*s" % (name_w, label(name)))[:name_w] + RST \
            + " " + col + ("%-10s" % tag) + RST
        if mem:
            line += DIM + mem.rjust(6) + RST
        if vlen(line) > w:
            line = line[:w]
        out.append(line)
    return out[:max(1, rows)]


def main():
    prof, _ = deckconf.load()
    interval = settings(prof)
    if "--once" in sys.argv:
        cols = shutil.get_terminal_size((80, 24)).columns
        print("\n".join(frame(prof, cols, 10000)))
        return 0
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
