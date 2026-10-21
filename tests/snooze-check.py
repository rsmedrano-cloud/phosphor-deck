#!/usr/bin/env python3
"""phosphor snooze: a snoozed problem leaves the one list every screen
reads (glance.host_problems), the adjutant's line and a fleet alert's
push; it always expires, and getting worse than what was quieted wakes
it for good. The keys that do it (FLEET's z, glance's host page, the
SolarOS fleet menu) and the command itself. Nothing real is touched: a
temp HOME, a fake fleet.json, push patched.

    python3 tests/snooze-check.py
"""
import io, json, os, re, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
for v in ("PHOSPHOR_DATA", "PHOSPHOR_CACHE", "PHOSPHOR_NOTES", "ZELLIJ"):
    os.environ.pop(v, None)
home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.makedirs(os.path.join(home, ".cache/phosphor"))
prof = os.path.join(home, "deck.toml")
open(prof, "w").write('[deck]\nsession = "probe"\n\n'
                      '[[hosts]]\nname = "vault"\nssh = "vault"\n\n'
                      '[[hosts]]\nname = "laptop"\nssh = "laptop"\n')
os.environ["PHOSPHOR_PROFILE"] = prof

fails = []
def need(what, ok):
    if not ok: fails.append(what)
def strip(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

import snooze, glance, fleet, adjutant, solaros

POLLS = [0]
def poll(**hosts):
    with open(glance.CACHE, "w") as f:
        json.dump({"t": time.time(), "hosts": hosts}, f)
    POLLS[0] += 1                       # a real poll is 15s on: the adjutant reads on mtime
    os.utime(glance.CACHE, (time.time() + POLLS[0], time.time() + POLLS[0]))

def ok_host(**kw):
    d = {"ok": True, "CPU": 5, "MEMU": 100, "MEMT": 1000, "mnt": [["/", 50, "1T"]]}
    d.update(kw)
    return d

def problems():
    return [(n, d) for n, d, _ in glance.fleet_scan()[3]]

# a red disk and two failed services: both listed, then both snoozed
poll(vault=ok_host(mnt=[["/srv", 95, "4T"]], SVCFAIL=2), laptop=ok_host())
need("before: vault's disk and services are listed",
     problems() == [("vault", "disk 95%"), ("vault", "2 services failed")])
got = snooze.snooze("vault")
need("snooze HOST takes what's wrong now", [k for k, _ in got] == ["disk", "services"])
need("snoozed: out of the list", problems() == [])
need("snoozed: out of fleet --json's why", fleet.why(json.load(open(glance.CACHE))["hosts"]) is None)
need("glance's light is green again", glance.payload()["status"] == "green")
need("glance --json names it", glance.payload()["fleet"]["snoozed"] == ["vault"])
lines = [strip(l) for l in glance.frame(60, 30)]
need("glance says what's snoozed", any("z vault snoozed" in l for l in lines))
js = fleet.as_json([("vault", "vault"), ("laptop", "laptop")])
need("fleet --json lists the snoozes", sorted(e["kind"] for e in js["snoozed"]) == ["disk", "services"]
     and all(e["when"].startswith("till ") for e in js["snoozed"]))
head, body = fleet.card("vault", 30, json.load(open(glance.CACHE))["hosts"]["vault"])
need("the FLEET card says it's snoozed, and till when", any("z snoozed till" in strip(l) for l in body))

# worse than what was quieted: a third service wakes that one, for good
poll(vault=ok_host(mnt=[["/srv", 95, "4T"]], SVCFAIL=3), laptop=ok_host())
need("worse: the services come back", problems() == [("vault", "3 services failed")])
need("worse: that snooze is gone from the file", "services" not in snooze.load().get("vault", {}))
poll(vault=ok_host(mnt=[["/srv", 95, "4T"]], SVCFAIL=2), laptop=ok_host())
need("woken stays woken when it gets better again", problems() == [("vault", "2 services failed")])
need("the disk's snooze held meanwhile", "disk" in snooze.load().get("vault", {}))

# a kind snoozed ahead: a laptop you'll leave off
need("nothing wrong now: HOST alone snoozes nothing", snooze.snooze("laptop") == [])
snooze.snooze("laptop", ["down"], secs=3600)
poll(vault=ok_host(), laptop={"ok": False, "err": "timeout"})
need("down, snoozed ahead: not listed", ("laptop", "timeout") not in problems())
need("down, snoozed ahead: not red", glance.payload()["status"] != "red")
need("adjutant: a snoozed down host isn't an alert", adjutant.fleet_alert() is None)
need("adjutant's line says nominal", adjutant.fleet_health() == (0, "nominal"))
# an amber disk snoozed ahead, then red: worse, it wakes
snooze.snooze("vault", ["disk"])
poll(vault=ok_host(mnt=[["/srv", 85, "4T"]]), laptop=ok_host())
need("adjutant: an amber disk snoozed ahead is quiet", adjutant.fleet_health() == (0, "nominal"))
poll(vault=ok_host(mnt=[["/srv", 97, "4T"]]), laptop=ok_host())
need("amber to red wakes it", problems() == [("vault", "disk 97%")])
need("adjutant: red after amber is an alert again", adjutant.fleet_alert() == (2, "vault disk 97%"))

# it always expires
snooze.end([(None, None)])
snooze.snooze("vault", secs=60, now=time.time() - 3600)
need("an expired snooze holds nothing", problems() == [("vault", "disk 97%")] and snooze.active() == [])
snooze.snooze("vault", secs=30 * 24 * 3600)
need("7 days at most", snooze.until("vault") <= time.time() + snooze.MOST + 5)
snooze.end([("vault", None)])

# fleet alerts, the same texts from either poller
rust = open(os.path.join(ROOT, "rust/fleet-poll/src/main.rs")).read()
py = open(os.path.join(ROOT, "lib/fleet.py")).read()
for t in ('"{} is back"', '"{} is unreachable"', '"{}: {} {} failed"', '"{}: services back to normal"',
          '"{}: {} {} failing SMART"'):
    need("rust/fleet-poll still says %s" % t, t in rust)
for t in ('"%s is back"', '"%s is unreachable"', '"%s: %d service%s failed"', '"%s: services back to normal"',
          '"%s: %d disk%s failing SMART"'):
    need("lib/fleet.py still says %s" % t, t in py)
snooze.snooze("laptop", ["down"])
snooze.snooze("vault", ["services"])
need("quiet: a snoozed host going down", snooze.quiets("laptop is unreachable"))
need("quiet: and coming back", snooze.quiets("laptop is back"))
need("quiet: one service, snoozed ahead", snooze.quiets("vault: 1 service failed"))
need("loud: two is worse", not snooze.quiets("vault: 2 services failed"))
need("loud: another host", not snooze.quiets("db-box is unreachable"))
need("loud: a kind not snoozed", not snooze.quiets("vault: 1 disk failing SMART"))
need("loud: not a fleet alert", not snooze.quiets("build done"))

# phosphor notify --fleet-alert: the event line stays, no push, no voice
import notify, push, tts
pushed = []
push.notify_hook = lambda txt, **kw: (pushed.append(txt), (True, ""))[1]
push.wants_clip = lambda **kw: False
tts.notify_hook = lambda txt, **kw: pushed.append("tts " + txt)
notify.proc.zellij = lambda: None       # no tab mark: never a real zellij
def run_notify(text):
    sys.argv = ["phosphor-notify", "--tab", "SYS", "--fleet-alert", text]
    return notify.main()
pushed.clear(); run_notify("laptop is unreachable")
events = open(os.path.join(home, ".cache/phosphor/events")).read()
need("notify: a snoozed alert isn't pushed or spoken", pushed == [])
need("notify: its event line says snoozed", "laptop is unreachable (snoozed)" in events)
pushed.clear(); run_notify("db-box is unreachable")
need("notify: an alert not snoozed is pushed", pushed[:1] == ["db-box is unreachable"])
pushed.clear()
sys.argv = ["phosphor-notify", "--tab", "SYS", "laptop is unreachable"]
notify.main()
need("notify: a message by hand is never snoozed", pushed[:1] == ["laptop is unreachable"])
snooze.end([(None, None)])

# the keys: FLEET's z and the SolarOS menu toggle; glance's page snoozes
poll(vault=ok_host(mnt=[["/srv", 95, "4T"]]), laptop=ok_host())
m = snooze.toggle("vault")
need("toggle snoozes, saying what and till when", m.startswith("vault: disk 95% snoozed till"))
m = snooze.toggle("vault")
need("toggle again wakes it", "awake" in m and not snooze.load())
need("toggle on a fine host says so", snooze.toggle("laptop") == "nothing wrong on laptop to snooze")
need("FLEET's z is in its footer", ("z", "snooze") == fleet.SNOOZE and "z" not in [a for a, _ in fleet.ACTIONS])
page = [strip(l) for l in glance.page(("host", "vault", ["disk 95%"]), 40, 12, 1)]
need("glance's host page offers snooze 24h, back under the cursor",
     "snooze 24h" in page[-1] and glance.actions("host")[-1] == "back")
glance.do(("host", "vault", ["disk 95%"]), "snooze 24h")
need("glance's snooze 24h snoozes it", "disk" in snooze.load().get("vault", {}))
need("SolarOS's fleet rows say it", dict(solaros.fleet_rows())["vault"].startswith("snoozed till"))
snooze.end([(None, None)])

# the command
def cli(*argv):
    sys.argv = ["phosphor-snooze"] + list(argv)
    out, err = io.StringIO(), io.StringIO()
    so, se = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try: rc = snooze.main()
    finally: sys.stdout, sys.stderr = so, se
    return rc, strip(out.getvalue()), strip(err.getvalue())
rc, out, _ = cli()
need("bare: nothing snoozed", rc == 0 and "nothing snoozed" in out)
rc, _, err = cli("db-box")
need("a host not in the fleet is refused", rc == 2 and "isn't one of the fleet's machines" in err)
rc, _, err = cli("vault", "cpu")
need("a kind that isn't one is refused", rc == 2 and "not a kind" in err)
rc, _, err = cli("vault", "--for", "soon")
need("--for wants a duration", rc == 2)
rc, out, _ = cli("vault", "--for", "4h")
need("snooze HOST --for 4h", rc == 0 and "disk 95% snoozed till" in out
     and abs(snooze.until("vault") - time.time() - 4 * 3600) < 10)
rc, out, _ = cli("--json")
d = json.loads(out)
need("--json: the list and a line", d["line"] == "1 snoozed" and d["snoozed"][0]["host"] == "vault")
rc, out, _ = cli("vault", "--wake")
need("--wake ends it", rc == 0 and "awake" in out and not snooze.load())
rc, out, _ = cli("laptop")
need("nothing wrong: says to name a kind", rc == 1 and "name a kind" in out)
need("durations", [snooze.duration(x) for x in ("30m", "4h", "2d", "3", "x")] == [1800, 14400, 172800, 10800, None])

# a broken file is no snooze at all, never a crash
open(snooze.path(), "w").write("{not json")
need("a broken snooze.json holds nothing", snooze.load() == {} and problems() == [("vault", "disk 95%")])

if fails:
    print("FAIL snooze-check:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ok snooze-check")
