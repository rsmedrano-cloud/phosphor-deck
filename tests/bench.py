#!/usr/bin/env python3
"""phosphor bench - the brain's own footprint at rest, for the pre-1.0 docs.

    python3 tests/bench.py                      # homelab + revived
    python3 tests/bench.py --shapes homelab      # just one
    python3 tests/bench.py --include-dev         # also dev (spawns claude/codex)

Builds the exact layout `phosphor init` would write for a shape (lib/init.render,
same code path the wizard uses), with one local host and no chat app -- no real
ssh, no real fleet -- and runs it as a throwaway zellij session via tests/zjprobe's
Probe: its own HOME, its own socket dir, never the live deck. After the TUIs have
had time to draw, it samples every process tagged with that HOME (the same trick
Probe.__exit__ already uses for teardown) over a window and reports RSS and CPU.

Not a pass/fail check (there's no "correct" number): a reporting tool, meant to
run on real, disclosed hardware -- CI's own runner is the brain's, so its numbers
are real too, just noisier (shared with whatever else the runner is doing).

Left out on purpose, measured elsewhere:
- a WORK tab (needs a real reachable host)
- the fleet's real network cost (needs real hosts to poll -- the live deck only)
- phone battery with Termux attached all day (needs a real phone)
--include-dev actually starts `claude`/`codex`: off by default, since an
unattended run has no one to get past a first-time login prompt.
"""
import argparse, os, socket, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import init
from zjprobe import Probe

CLK_TCK = os.sysconf("SC_CLK_TCK")


def profile_for(shape):
    hosts = [{"name": "bench", "role": "brain", "local": True, "mounts": ["~"]}]
    return init.render(hosts, "p31", comms=None, net="none", shape=shape)


def tagged_pids(home_marker):
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            env = open("/proc/%s/environ" % d, "rb").read()
        except OSError:
            continue
        if home_marker in env:
            out.append(int(d))
    return out


def snapshot(pids):
    """pid -> (utime+stime in ticks, RSS in kB, comm)."""
    out = {}
    for pid in pids:
        try:
            stat = open("/proc/%d/stat" % pid).read()
            comm = stat[stat.index("(") + 1: stat.rindex(")")]
            rest = stat[stat.rindex(")") + 2:].split()
            utime, stime = int(rest[11]), int(rest[12])
            rss_kb = 0
            for line in open("/proc/%d/status" % pid):
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break
        except (OSError, ValueError, IndexError):
            continue
        out[pid] = (utime + stime, rss_kb, comm)
    return out


def report(shape, home_marker, settle, sample):
    print("\n== %s ==" % shape)
    time.sleep(settle)
    t0 = time.time()
    before = snapshot(tagged_pids(home_marker))
    time.sleep(sample)
    dt = time.time() - t0
    after = snapshot(tagged_pids(home_marker))

    rows = []
    total_cpu_ticks = 0
    for pid, (ticks1, rss, comm) in after.items():
        ticks0 = before.get(pid, (ticks1, 0, comm))[0]
        d_ticks = max(0, ticks1 - ticks0)
        total_cpu_ticks += d_ticks
        rows.append((comm, pid, rss, d_ticks / CLK_TCK / dt * 100))
    rows.sort(key=lambda r: -r[2])

    print("  %-16s %8s %9s %8s" % ("process", "pid", "RSS MB", "CPU%"))
    for comm, pid, rss, cpu in rows:
        print("  %-16s %8d %9.1f %8.1f" % (comm, pid, rss / 1024, cpu))
    total_rss = sum(r[2] for r in rows) / 1024
    total_cpu = total_cpu_ticks / CLK_TCK / dt * 100
    print("  %-16s %8s %9.1f %8.1f" % ("TOTAL", "", total_rss, total_cpu))
    return {"shape": shape, "processes": len(rows), "rss_mb": round(total_rss, 1),
            "cpu_pct": round(total_cpu, 1), "sample_s": round(dt, 1)}


def hardware():
    try:
        model = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except (OSError, StopIteration):
        model = "unknown CPU"
    try:
        mem_kb = next(int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith("MemTotal:"))
        mem = "%.0f GiB" % (mem_kb / 1024 / 1024)
    except (OSError, StopIteration):
        mem = "unknown RAM"
    return "%s | %s | %d cores | %s | %s" % (
        socket.gethostname(), model, os.cpu_count() or 0, mem, os.uname().release)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shapes", default="homelab,revived")
    ap.add_argument("--include-dev", action="store_true")
    ap.add_argument("--settle", type=float, default=6.0)
    ap.add_argument("--sample", type=float, default=12.0)
    args = ap.parse_args()

    shapes = [s for s in args.shapes.split(",") if s]
    if "dev" in shapes and not args.include_dev:
        print("skipping dev (needs --include-dev: it starts real claude/codex processes)")
        shapes = [s for s in shapes if s != "dev"]

    print("method: %s settle, %s sample window, one local host, no chat app, no real fleet" %
          (args.settle, args.sample))
    print("hardware: %s" % hardware())
    print("phosphor: %s" % open(os.path.join(ROOT, "VERSION")).read().strip())

    results = []
    for shape in shapes:
        prof = profile_for(shape)
        with Probe(prof, session="bench-%s" % shape) as z:
            marker = z.home.encode()
            results.append(report(shape, marker, args.settle, args.sample))

    print("\nsummary (RSS MB / CPU%%, %s hardware):" % socket.gethostname())
    for r in results:
        print("  %-10s %6.1f MB   %5.1f%%   (%d processes, %ss sample)" %
              (r["shape"], r["rss_mb"], r["cpu_pct"], r["processes"], r["sample_s"]))


if __name__ == "__main__":
    main()
