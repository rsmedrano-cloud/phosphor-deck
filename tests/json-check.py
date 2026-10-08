#!/usr/bin/env python3
"""--json on the read-only commands: each prints one JSON object (no color,
no screen codes) with its documented top-level keys, and the pure shapers
turn raw readings into the documented records.

    python3 tests/json-check.py

Runs every command in a throwaway HOME with a demo profile and a session
name no deck uses: all of them only read, but zellij and `who` aren't
fenced by HOME, so nothing here may point at a real session.
"""
import json, os, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
fails = []
def need(what, ok):
    if not ok: fails.append(what)

home = tempfile.mkdtemp()
os.environ["HOME"] = home
for d in (".config/phosphor", ".cache/phosphor", ".local/share/phosphor"):
    os.makedirs(os.path.join(home, d))
prof = os.path.join(home, ".config/phosphor/deck.toml")
open(prof, "w").write('[deck]\nsession = "json-check-nosuch"\ndemo = true\n\n'
                      '[[hosts]]\nname = "nebula"\nssh = "nebula"\n\n'
                      '[[hosts]]\nname = "atlas"\nssh = "atlas"\n')
json.dump({"t": time.time(), "hosts": {
    "nebula": {"ok": True, "CPU": 12, "MEMU": 100, "MEMT": 1000, "LOAD": "0.5 0.4 0.3", "UP": "3d",
               "mnt": [["/", 41, "512G"]], "ctr": ["docker", 7, 1],
               "gpu": [{"name": "GPU", "util": "38", "used": "4200", "total": "12288", "temp": "57"}],
               "SVCFAIL": 2, "REBOOT": "1", "TEMP": "48", "BAT": "83|Discharging", "SMART": "1|4",
               "UPD": "12|", "ms": 600},
}}, open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
env = dict(os.environ, HOME=home, PHOSPHOR_PROFILE=prof, NO_COLOR="1")
for k in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID"):
    env.pop(k, None)

def run(*a):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor")] + list(a), env=env,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90)
    try:
        return r.returncode, json.loads(r.stdout), r.stdout
    except ValueError:
        fails.append("%s: not JSON: %r %r" % (" ".join(a), r.stdout[:200], r.stderr[-300:]))
        return r.returncode, None, r.stdout

CASES = [
    (("fleet", "--json"), {"t", "age", "stale", "hosts"}),
    (("services", "--json"), {"units"}),
    (("containers", "nebula", "--json"), {"host", "engine", "problem", "containers"}),
    (("screens", "--json"), {"session", "problem", "screens"}),
    (("mem", "--json"), {"session", "running", "tabs", "zellij", "machine"}),
    (("security", "--local", "--json"), {"sections"}),
    (("tunnel", "--json"), {"tunnels"}),
    (("version", "--json"), {"version", "commit", "channel", "installed", "check"}),
    (("workspace", "list", "--json"), {"root", "workspaces"}),
    (("glance", "--json"), {"status", "fleet", "worst"}),
]
for argv, keys in CASES:
    rc, d, raw = run(*argv)
    if d is None:
        continue
    name = " ".join(argv)
    need("%s: top-level keys %s" % (name, sorted(keys - set(d))), keys <= set(d))
    need("%s: no escape codes" % name, "\x1b" not in raw)

# what each one says, with the fixtures above
_, d, _ = run("fleet", "--json")
if d:
    n = d["hosts"].get("nebula") or {}
    need("fleet: fresh cache isn't stale", d["stale"] is False)
    need("fleet: a host with no poll yet is null", d["hosts"].get("atlas", 0) is None)
    need("fleet: cpu, memory, load typed", n.get("cpu") == 12 and n.get("memory") == {"used_mb": 100, "total_mb": 1000}
         and n.get("load") == [0.5, 0.4, 0.3])
    need("fleet: disks named", n.get("disks") == [{"mount": "/", "pct": 41, "size": "512G"}])
    need("fleet: containers named", n.get("containers") == {"engine": "docker", "running": 7, "exited": 1})
    need("fleet: gpu numbers are numbers", (n.get("gpus") or [{}])[0].get("total_mb") == 12288)
    need("fleet: sensors", n.get("temp") == 48 and n.get("battery") == {"pct": 83, "status": "Discharging"}
         and n.get("smart") == {"failing": 1, "checked": 4})
    need("fleet: updates without a security count", n.get("updates") == {"pending": 12, "security": None})
    need("fleet: failed units and reboot", n.get("failed_units") == 2 and n.get("reboot") is True)
rc, d, _ = run("containers", "nebula", "--json")
if d:
    need("containers: the demo's engine", d["engine"] == "docker" and d["problem"] is None and rc == 0)
    need("containers: records", all({"name", "state", "tag", "status", "image", "exit"} <= set(c)
                                    for c in d["containers"]) and d["containers"])
rc = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "containers", "nowhere", "--json"],
                    env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30).returncode
need("containers: an unknown host still exits 2", rc == 2)
_, d, _ = run("mem", "--json")
if d:
    need("mem: no such session isn't running", d["running"] is False and d["tabs"] == [])
_, d, _ = run("workspace", "list", "--json")
if d:
    need("workspace: empty root", d["workspaces"] == [] and d["root"].startswith(home))
rc, d, _ = run("security", "--local", "--json")
if d:
    lv = [f["level"] for s in d["sections"] for f in s["findings"]]
    need("security: levels are words", set(lv) <= {"ok", "warn", "bad", "skip"})
    need("security: exit code follows the findings",
         rc == (2 if "bad" in lv else 1 if "warn" in lv else 0))

# the shapers, without a machine behind them
import fleet, services, containers
need("fleet: an unreachable host", fleet.reading({"ok": False, "err": "timeout", "ms": 6000})
     == {"ok": False, "error": "timeout", "ms": 6000})
need("fleet: garbage in doesn't raise", fleet.reading({"ok": True, "CPU": "x", "mnt": [["/"]], "ctr": "?"})["cpu"] is None)
u = services.as_json([("user", "deck.service", {"LoadState": "loaded", "ActiveState": "failed",
                                                "SubState": "failed", "MemoryCurrent": "[not set]"})])
need("services: failed unit", u["units"][0]["state"] == "failed" and u["units"][0]["memory"] is None)
c = containers.as_json("nebula", "podman", [("db", "exited", "Exited (3) 2 hours ago", "pg")], "")
need("containers: exit code read", c["containers"][0]["exit"] == 3 and c["containers"][0]["tag"] == "exit 3")

if fails:
    print("\n".join(fails)); sys.exit(1)
print("json-check ok (%d commands)" % len(CASES))
