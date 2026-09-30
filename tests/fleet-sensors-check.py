#!/usr/bin/env python3
"""fleet sensors: collect.sh reads the CPU's temperature and a battery
from sysfs, and SMART through smartctl only where it answers without a
password, at most every 30 minutes. Run against a made-up /sys
(PHOSPHOR_SYS) and a fake smartctl/sudo, never the real ones; then the
card, glance and the one-way SMART alert.

    python3 tests/fleet-sensors-check.py
"""
import json, os, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import fleet, health

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)

def fake_sys(cpu_hwmon=True):
    s = tempfile.mkdtemp()
    if cpu_hwmon:
        put(s + "/class/hwmon/hwmon0/name", "coretemp\n")
        put(s + "/class/hwmon/hwmon0/temp1_input", "45000\n")
        put(s + "/class/hwmon/hwmon0/temp2_input", "61000\n")
    put(s + "/class/hwmon/hwmon1/name", "nvme\n")            # not the CPU: ignored
    put(s + "/class/hwmon/hwmon1/temp1_input", "80000\n")
    put(s + "/class/thermal/thermal_zone0/type", "x86_pkg_temp\n")
    put(s + "/class/thermal/thermal_zone0/temp", "52000\n")
    put(s + "/class/power_supply/hidpp_battery_0/type", "Battery\n")   # a mouse
    put(s + "/class/power_supply/hidpp_battery_0/scope", "Device\n")
    put(s + "/class/power_supply/hidpp_battery_0/capacity", "5\n")
    put(s + "/class/power_supply/BAT0/type", "Battery\n")
    put(s + "/class/power_supply/BAT0/capacity", "23\n")
    put(s + "/class/power_supply/BAT0/status", "Discharging\n")
    for dev in ("sda", "sdb", "nvme0n1", "loop0"):
        os.makedirs(s + "/block/" + dev)
    return s

def fake_bin(smart):
    """smartctl answering per device from `smart` ({dev: (exit, text)});
    sudo just runs what follows -n. Every call is logged."""
    b = tempfile.mkdtemp()
    log = os.path.join(b, "calls")
    put(os.path.join(b, "smartctl"), """#!/bin/sh
echo "$*" >> %s
for a; do dev=$a; done
case "$dev" in
%s
esac
exit 2
""" % (log, "\n".join("  /dev/%s) echo '%s'; exit %d ;;" % (d, t, r) for d, (r, t) in smart.items())))
    put(os.path.join(b, "sudo"), '#!/bin/sh\n[ "$1" = -n ] && shift\nexec "$@"\n')
    for f in ("smartctl", "sudo"):
        os.chmod(os.path.join(b, f), 0o755)
    return b, log

def run(sysroot, binroot, run_dir):
    env = dict(os.environ, PHOSPHOR_SYS=sysroot, XDG_RUNTIME_DIR=run_dir,
               PATH=binroot + ":" + os.environ["PATH"])
    r = subprocess.run(["sh", os.path.join(ROOT, "share", "collect.sh")],
                       capture_output=True, text=True, env=env, timeout=30)
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l), r.returncode

HEALTHY = {"sda": (0, "PASSED"), "nvme0n1": (8, "FAILED!"),
           "sdb": (2, "Device is in STANDBY mode, exit(2)")}

s, (b, log), rd = fake_sys(), fake_bin(HEALTHY), tempfile.mkdtemp()
out, rc = run(s, b, rd)
check("collect.sh still exits 0", rc == 0)
check("TEMP is the CPU driver's hottest reading, not the nvme's: %r" % out.get("TEMP"),
      out.get("TEMP") == "61")
check("BAT is the laptop's battery, never a mouse's: %r" % out.get("BAT"),
      out.get("BAT") == "23|Discharging")
check("SMART counts checked disks, skips a sleeping one and loop0: %r" % out.get("SMART"),
      out.get("SMART") == "1|2")
calls = open(log).read()
check("-n standby on every call, so no disk spins up", calls.count("-n standby") == calls.count("\n"))
check("loop devices never asked", "loop0" not in calls)

# Asked again within 30 minutes: the cached answer, smartctl not run.
n = calls.count("\n")
out, _ = run(s, b, rd)
check("SMART cached for 30 minutes", out.get("SMART") == "1|2" and open(log).read().count("\n") == n)

# Without the CPU's own hwmon: the package thermal zone.
out, _ = run(fake_sys(cpu_hwmon=False), b, tempfile.mkdtemp())
check("TEMP falls back to x86_pkg_temp: %r" % out.get("TEMP"), out.get("TEMP") == "52")

# Not allowed: nothing shown, and not asked again for a day.
b2, log2 = fake_bin({"sda": (2, "Smartctl open device: /dev/sda failed: Permission denied")})
rd2 = tempfile.mkdtemp()
out, _ = run(s, b2, rd2)
check("no permission: no SMART line", "SMART" not in out)
check("no permission: remembered as an empty file",
      os.path.getsize(os.path.join(rd2, "phosphor-smart")) == 0)
os.utime(os.path.join(rd2, "phosphor-smart"), (time.time() - 3600,) * 2)
n = open(log2).read().count("\n")
run(s, b2, rd2)
check("no permission: not asked again an hour later", open(log2).read().count("\n") == n)

# Parsing, whatever type fleet.json carries.
check("sensors() from collect.sh's strings",
      health.sensors({"TEMP": "61", "BAT": "23|Discharging", "SMART": "1|2"})
      == (61, (23, "Discharging"), (1, 2)))
check("sensors() never trusts a type",
      health.sensors({"TEMP": "x", "BAT": "?|", "SMART": "0|0"}) == (None, None, None))

# The card.
_, body = fleet.card("db-box", 40, {"ok": True, "CPU": 3, "MEMU": 1, "MEMT": 2,
                                     "TEMP": "61", "BAT": "23|Discharging", "SMART": "0|2"})
text = "\n".join(body)
check("card shows TEMP, BAT and SMART ok", "61°C" in text and "23%↓" in text and "SMART ok" in text)
_, body = fleet.card("db-box", 40, {"ok": True, "CPU": 3, "MEMU": 1, "MEMT": 2, "SMART": "2|3"})
check("card calls out failing disks", "2 disks failing SMART" in "\n".join(body))
_, body = fleet.card("db-box", 40, {"ok": True, "CPU": 3, "MEMU": 1, "MEMT": 2})
check("a host without sensors shows none", "TEMP" not in "\n".join(body) and "SMART" not in "\n".join(body))

# glance: only what needs attention.
check("glance flags SMART, heat and a nearly flat battery",
      health.sensor_problems({"TEMP": "93", "BAT": "7|Discharging", "SMART": "1|2"})
      == ["1 disk failing SMART", "cpu 93°C", "battery 7%"])
check("glance ignores a low battery that's charging, and a warm CPU",
      health.sensor_problems({"TEMP": "75", "BAT": "7|Charging", "SMART": "0|2"}) == [])
import glance
glance.CACHE = os.path.join(tempfile.mkdtemp(), "fleet.json")
json.dump({"t": time.time(), "hosts": {"db-box": {"ok": True, "mnt": [], "SMART": "1|2"}}},
          open(glance.CACHE, "w"))
check("glance lists it", ("db-box", "1 disk failing SMART") in glance.fleet_state()[2])

# The alert: going bad, never on the first poll, never going back to 0.
said = []
fleet._alert = lambda n, ok, text=None: said.append(text)
fleet.update_host("db-box", {"ok": True, "SMART": "1|2"})
check("no alert on the first poll", said == [])
fleet.update_host("db-box", {"ok": True, "SMART": "2|2"})
check("alert when another disk starts failing", said == ["db-box: 2 disks failing SMART"])
fleet.update_host("db-box", {"ok": True, "SMART": "0|2"})
fleet.update_host("db-box", {"ok": True})
check("no alert going back to 0, or when SMART goes quiet", len(said) == 1)

if fails:
    print("\n".join("FAIL: " + f for f in fails))
    sys.exit(1)
print("ok")
