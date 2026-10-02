#!/usr/bin/env python3
"""Animations slow down for a screen that comes through a tailscale relay.

    python3 tests/relay-check.py

Verifies:
- relayed() picks the peers with a DERP region and no direct address, by
  address and by name, and leaves direct and relay-less ones out
- is_relayed() matches who's from column (an address, or a name) and never
  a LAN address that merely shares a first octet-looking label
- slow_screens() only counts screens of the session asked for
- Pace slows to SLOW while a check says so, rechecks only every EVERY
  seconds, goes back to the normal delay, and survives a check that raises
- pulse and the adjutant both pace their frames with it
"""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp()     # dlog never writes the real deck.log
import relay, screens

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

STATUS = {"Peer": {
    "a": {"HostName": "Pixel", "DNSName": "pixel.tail1234.ts.net.", "TailscaleIPs": ["203.0.113.2", "fd7a::1"],
          "CurAddr": "", "Relay": "lhr"},
    "b": {"HostName": "relay", "TailscaleIPs": ["203.0.113.3"], "CurAddr": "192.168.1.13:41641", "Relay": "lhr"},
    "c": {"HostName": "nimbus", "TailscaleIPs": ["203.0.113.9"], "CurAddr": "", "Relay": ""},
}}
r = relay.relayed(STATUS)
check("relayed peer by address", "203.0.113.2" in r and "fd7a::1" in r)
check("relayed peer by name", "pixel" in r and "pixel.tail1234.ts.net" in r)
check("direct peer left out", "203.0.113.3" not in r and "relay" not in r)
check("peer with no relay region left out", "203.0.113.9" not in r)
check("no tailscale: nothing relayed", relay.relayed(None) == set())

check("from an address", relay.is_relayed("203.0.113.2", r))
check("from a name (UseDNS)", relay.is_relayed("Pixel.tail1234.ts.net", r))
check("a LAN screen isn't", not relay.is_relayed("192.168.1.16", r))
check("a local login isn't", not relay.is_relayed("local", r) and not relay.is_relayed("", r))
check("an address never matches by its first label", not relay.is_relayed("203.1.1.1", {"203"}))

rows = [{"from": "203.0.113.2", "session": "deck-phone"}, {"from": "192.168.1.16", "session": "deck"}]
real = screens.screens
asked = []
screens.screens = lambda s: (asked.append(s), [x for x in rows if x["session"] == s])[1]
try:
    check("relayed screen of its session", len(relay.slow_screens("deck-phone", STATUS)) == 1)
    check("no relayed screen in another", relay.slow_screens("deck", STATUS) == [])
    check("asked for that session only", asked == ["deck-phone", "deck"])
finally:
    screens.screens = real

clock, state, calls = [1000.0], [False], [0]
def probe():
    calls[0] += 1
    return state[0]
p = relay.Pace("TEST", check=probe, now=lambda: clock[0])
check("fast by default", p.delay(0.09) == 0.09 and calls[0] == 1)
state[0] = True
check("not rechecked before EVERY", p.delay(0.09) == 0.09 and calls[0] == 1)
clock[0] += relay.EVERY
check("slow once a relayed screen shows", p.delay(0.09) == relay.SLOW and calls[0] == 2)
check("a longer delay is kept", p.delay(5.0) == 5.0)
state[0] = False; clock[0] += relay.EVERY
check("fast again when it's gone", p.delay(0.09) == 0.09)
def boom(): raise RuntimeError("tailscale went away")
q = relay.Pace("TEST", check=boom, now=lambda: clock[0])
check("a failing check means fast", q.delay(0.1) == 0.1)

for tool in ("pulse", "adjutant"):
    src = open(os.path.join(ROOT, "lib", tool + ".py")).read()
    check("%s paces its frames" % tool, "relay.Pace(" in src and "pace.delay(" in src)

if fails:
    print("relay-check: FAIL")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("relay-check: ok")
