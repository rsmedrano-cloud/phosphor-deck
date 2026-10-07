#!/usr/bin/env python3
"""The wizard never offers the machine running it back to itself: a
Tailscale peer entry for this same machine (often under a short Tailscale
name that differs from the system hostname) and a ~/.ssh/config alias
pointing at this machine's own hostname or IP must both be filtered out of
init.discover()'s candidate list before "watch X as a machine of your
fleet?" ever asks about them.

    python3 tests/wizard-dedup-check.py

No real tailscale or ssh needed: proc.sh (the shell-out helper) and
os.uname() are monkeypatched.
"""
import json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

fails = []
def check(what, ok):
    if not ok: fails.append(what)

tmp = tempfile.mkdtemp()
os.environ["HOME"] = tmp
os.makedirs(os.path.join(tmp, ".ssh"))

import init

class FakeUname:
    nodename = "dc1.fusco.local"     # the system hostname, distinct from the
                                      # Tailscale short name "dc1" below
init.os.uname = lambda: FakeUname()

TS_JSON = json.dumps({
    "Self": {"DNSName": "dc1.tailnet.ts.net.", "HostName": "dc1",
              "TailscaleIPs": ["192.0.2.10"]},
    "Peer": {
        "1": {"DNSName": "nimbus.tailnet.ts.net.", "HostName": "nimbus",
              "TailscaleIPs": ["192.0.2.20"], "OS": "linux", "Online": True},
        # a phone whose OS reports a generic hostname -- must not collide
        # with another device under the same key
        "2": {"DNSName": "pixel-9.tailnet.ts.net.", "HostName": "localhost",
              "TailscaleIPs": ["192.0.2.31"], "OS": "android", "Online": True},
        "3": {"DNSName": "ipad.tailnet.ts.net.", "HostName": "localhost",
              "TailscaleIPs": ["192.0.2.32"], "OS": "iOS", "Online": False},
    },
})

calls = []
def fake_sh(cmd, t=10, err=False):
    calls.append(cmd)
    if not isinstance(cmd, str):
        return 1, ""
    if cmd.startswith("tailscale status --json"):
        return 0, TS_JSON
    if cmd.startswith("hostname -I"):
        return 0, "192.168.1.50"
    return 1, ""
init.proc.sh = fake_sh

# a ~/.ssh/config alias pointing right back at this machine's own hostname
# (the shape the real bug took: a stray "home" alias someone had lying
# around, aliasing dc1.fusco.local -- its own system hostname) plus a
# second one by IP, and a normal, unrelated machine
open(os.path.join(tmp, ".ssh", "config"), "w").write(
    "Host home\n    HostName dc1.fusco.local\n\n"
    "Host by-ip\n    HostName 192.0.2.10\n\n"
    "Host db-box\n    HostName db.example.org\n"
)

# -- local_identity(): the set of strings this machine can show up under --
ids = init.local_identity("192.0.2.10", "dc1")
check("system hostname is in it", "dc1.fusco.local" in ids)
check("short hostname (no domain) is in it", "dc1" in ids)
check("the tailscale ip is in it", "192.0.2.10" in ids)
check("the tailscale name is in it", "dc1" in ids)
check("localhost is always in it", "localhost" in ids)

# -- discover(): the actual bug --
cands, me, self_ip = init.discover(True)
check("tailscale status --json is what's actually run (not plain-text status)",
      any(c.startswith("tailscale status --json") for c in calls))
check("this machine's own tailscale peer entry never becomes a candidate",
      "dc1" not in cands)
check("me is this machine's tailscale (short) name", me == "dc1")
check("self_ip is this machine's tailscale ip", self_ip == "192.0.2.10")
check("a ~/.ssh/config alias for this machine's own hostname is filtered out",
      "home" not in cands)
check("...and one for its own tailscale ip too", "by-ip" not in cands)
check("a real, different machine still shows up", "nimbus" in cands)
check("an unrelated ssh alias still shows up", "db-box" in cands)
check("two devices with the same OS-reported HostName don't collide onto one name",
      "pixel-9" in cands and "ipad" in cands)
check("phones/tablets are still marked viewer_only",
      cands.get("pixel-9", {}).get("viewer_only") and cands.get("ipad", {}).get("viewer_only"))
check("a real machine keeps its own ip", cands.get("nimbus", {}).get("ip") == "192.0.2.20")
check("nothing named 'localhost' leaked into the candidates",
      "localhost" not in cands)

# -- without tailscale (mesh = none), a ~/.ssh/config self-alias by
# hostname is still caught (nothing to compare an IP-only alias against,
# since there's no tailscale ip and it isn't in the fake "hostname -I") --
cands2, me2, self_ip2 = init.discover(False)
check("no tailscale: me is None", me2 is None)
check("no tailscale: self_ip is None", self_ip2 is None)
check("no tailscale: the hostname-based self alias is still filtered",
      "home" not in cands2)
check("no tailscale: an unrelated ssh alias still shows up", "db-box" in cands2)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
