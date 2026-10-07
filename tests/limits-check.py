#!/usr/bin/env python3
"""One set of limits (lib/limits.py) for every panel:

- the same disk is the same color on a FLEET card and the same problem (or
  not) in glance, the adjutant, pulse and digest: amber at 85%, red and
  called out at 91%;
- [alerts] changes them for every host or for one, a single number keeps
  the warn above it, the battery counts down;
- profcheck names a bad [alerts] value, an unknown metric, an unknown host;
- no panel in lib/ carries its own cut again.

    python3 tests/limits-check.py
"""
import json, os, re, sys, tempfile, time
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = tempfile.mkdtemp(prefix="limits-")
PROF = os.path.join(HOME, "deck.toml")
os.environ.update(PHOSPHOR_PROFILE=PROF, PHOSPHOR_CACHE=HOME)
sys.path.insert(0, os.path.join(REPO, "lib"))
import limits, profcheck, deckconf

fails = []
def check(what, ok, got=""):
    if not ok: fails.append(what + ("\n      got: %r" % (got,) if got != "" else ""))

def profile(text):
    open(PROF, "w").write('[[hosts]]\nname = "box"\nrole = "brain"\nlocal = true\n\n'
                          '[[hosts]]\nname = "nimbus"\nrole = "storage"\n\n' + text)
    profile.n = getattr(profile, "n", 0) + 1   # a new mtime even inside the same second
    os.utime(PROF, (time.time(), time.time() + profile.n))

def fleet(disks):
    with open(os.path.join(HOME, "fleet.json"), "w") as f:
        json.dump({"t": time.time(), "hosts": {
            n: {"ok": True, "CPU": 5, "MEMU": 1, "MEMT": 8, "mnt": [("/", p, "1T")]}
            for n, p in disks.items()}}, f)
    fleet.n = getattr(fleet, "n", 0) + 1     # the adjutant re-reads on a new mtime
    os.utime(os.path.join(HOME, "fleet.json"), (time.time(), time.time() + fleet.n))

import glance, fleet as fleetmod, adjutant, pulse, digest, history
from ui import PH, AMB, RED

# 1. defaults: the same reading means the same thing everywhere
profile("")
fleet({"box": 85, "nimbus": 91})
card = "\n".join(fleetmod.card("box", 30, json.load(open(os.path.join(HOME, "fleet.json")))["hosts"]["box"])[1])
check("85% is amber on the card", AMB + " 85%" in card, card)
bad = glance.fleet_scan()[3]
check("85% isn't a glance problem, 91% is", [(n, d) for n, d, _ in bad] == [("nimbus", "disk 91%")], bad)
check("the adjutant: red at 91%", adjutant.fleet_health() == (2, "nimbus disk 91%"), adjutant.fleet_health())
check("pulse: red at 91%", pulse.read_state()[1:] == (2, "nimbus disk 91%"), pulse.read_state())
fleet({"box": 85})
check("the adjutant: amber at 85%", adjutant.fleet_health() == (1, "box disk 85%"), adjutant.fleet_health())
check("pulse: amber at 85%", pulse.read_state()[1:] == (1, "box disk 85%"), pulse.read_state())
step = history.STEP
now = 1000 * step
rows = {"box": [[999, [10, 10, 50, 85]]], "nimbus": [[999, [91, 10, 50, 91]]]}
got = digest.fleet(now - 3600, now, rows)
check("digest: only what's red", [l.split(" peaked")[0] for l in got] == ["nimbus: CPU", "nimbus: DISK"], got)

# 2. [alerts], for every host and for one
profile('[alerts]\ndisk = [70, 95]\nbattery = [40, 15]\n\n[alerts.nimbus]\ndisk = 97\n')
check("global pair", limits.get("disk", "box") == (70, 95), limits.get("disk", "box"))
check("a host's one number keeps the global warn", limits.get("disk", "nimbus") == (70, 97),
      limits.get("disk", "nimbus"))
check("what [alerts] doesn't name stays default", limits.get("temp", "nimbus") == limits.DEFAULTS["temp"])
check("battery counts down", [limits.level("battery", v) for v in (50, 40, 15, 5)] == [0, 1, 2, 2])
fleet({"box": 96, "nimbus": 96})
bad = glance.fleet_scan()[3]
check("96% is a problem on box, not on nimbus", [n for n, _, _ in bad] == ["box"], bad)
check("a profile read once, then again when it changes", limits.get("disk", "box") == (70, 95))
profile("")
check("...and its change is seen", limits.get("disk", "box") == limits.DEFAULTS["disk"])

# 3. profcheck says what's wrong
got = profcheck.problems(deckconf.tomllib.loads(
    '[[hosts]]\nname = "nimbus"\n[alerts]\ndsk = 90\nram = [95, 90]\nbattery = [10, 30]\n'
    'temp = "hot"\n[alerts.nimbs]\ncpu = 99\n'))
for want in [("[alerts]", "unknown key dsk: disk?"),
             ("[alerts]", "ram = [95, 90] is [warn, bad] (warn at or below bad) or one number"),
             ("[alerts]", "battery = [10, 30] is [warn, bad] (warn at or above bad: the battery counts down) or one number"),
             ("[alerts]", 'temp = "hot" is [warn, bad] (warn at or below bad) or one number'),
             ("[alerts.nimbs]", "no such host in [[hosts]]: nimbus?")]:
    check("profcheck: %s %s" % want, want in got, got)
check("profcheck: nothing else", len(got) == 5, got)
check("profcheck: a good [alerts] is clean", not profcheck.problems(deckconf.tomllib.loads(
    '[[hosts]]\nname = "nimbus"\n[alerts]\ndisk = [80, 90]\n[alerts.nimbus]\ntemp = 95\n')))

# 4. no panel keeps its own cut
CUT = re.compile(r"\b(pct|temp|p|v|used|cpu|mp|gu)\s*[<>]=?\s*(60|70|85|88|90|92|95)\b")
for f in sorted(os.listdir(os.path.join(REPO, "lib"))):
    if not f.endswith(".py") or f in ("limits.py", "usage.py"):   # usage: plan quotas, not hosts
        continue
    for i, line in enumerate(open(os.path.join(REPO, "lib", f)), 1):
        if CUT.search(line):
            fails.append("lib/%s:%d has its own limit: %s" % (f, i, line.strip()))

if fails:
    print("FAIL"); [print("  - " + f) for f in fails]; sys.exit(1)
print("ok")
