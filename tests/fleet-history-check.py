#!/usr/bin/env python3
"""FLEET's history: every 5 minutes, each host's peaks go into history.json
(lib/history.py), and `h` over a card draws the last 24 hours.

    python3 tests/fleet-history-check.py
"""
import os, re, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp()
import history, fleet

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)
plain = lambda s: re.sub(r"\x1b\[[0-9;]*m", "", s)

# reading(): one poll -> [cpu, ram %, temp, fullest disk], down -> None
up = {"ok": True, "CPU": 40, "MEMU": 2048, "MEMT": 8192, "TEMP": "61",
      "mnt": [["/", 41, "512G"], ["/data", 88, "4T"]]}
need("a poll's reading", history.reading(up) == [40, 25, 61, 88])
need("a down host reads None", history.reading({"ok": False}) is None)
need("strings and missing fields don't break it",
     history.reading({"ok": True, "CPU": "x", "MEMT": 0, "TEMP": None}) == [0, 0, None, None])

# peak(): the higher of each; down only when both were
need("peaks", history.peak([10, 50, None, 3], [20, 40, 60, None]) == [20, 50, 60, 3])
need("a down poll and an ok one: ok", history.peak(None, [1, 2, 3, 4]) == [1, 2, 3, 4])

# Recorder: peaks of a slot, written once the slot is over; a stale file records nothing
S = history.STEP
t0 = 1000 * S
r = history.Recorder()
r.feed({"db-box": up}, t0 + 1, now=t0 + 2)
r.feed({"db-box": dict(up, CPU=90), "relay": {"ok": False}}, t0 + 20, now=t0 + 21)
r.feed({"db-box": dict(up, CPU=5)}, t0 + 20, now=t0 + 30)     # same fleet.json: not counted again
need("nothing written mid-slot", history.load() == {})
r.feed({"db-box": dict(up, CPU=1)}, t0 - 500, now=t0 + S + 1)   # next slot, stale file
h = history.load()
need("the slot's peak went in", h.get("db-box") == [[1000, [90, 25, 61, 88]]])
need("a host down all slot is recorded down", h.get("relay") == [[1000, None]])
need("a stale fleet.json adds nothing to the new slot", r.acc == {})

# a second writer of the same slot keeps the higher reading
history.save(history.merge(history.load(), 1000, {"db-box": [95, 10, 50, 80]}))
need("two writers: peaks kept", history.load()["db-box"] == [[1000, [95, 25, 61, 88]]])

# merge(): older than a day goes
hosts = history.merge({"db-box": [[1, [1, 1, 1, 1]]]}, 1 + history.KEEP, {"db-box": [2, 2, 2, 2]})
need("a day's worth only", hosts["db-box"] == [[1 + history.KEEP, [2, 2, 2, 2]]])

# columns() + spark(): the day squeezed into a width, down shows as ·
ns = 5000
rows = [[ns - 1, [100, 50, 70, 10]], [ns, None]]
cols = history.columns(rows, ns, 144)
need("144 columns", len(cols) == 144)
need("no data is ''", cols[0] == "")
need("the last column: two slots, one up -> the up one", cols[-1] == [100, 50, 70, 10])
ticks = history.spark([[100, 0, None, 0], None, ""], 0, 100)
need("full, down, nothing", [c for c, _ in ticks] == ["█", "·", " "])

# view(): every line fits, says the peak and when
history.save({})
v = [plain(l) for l in history.view("db-box", rows, 60, 30, now=ns * S)]
need("no line wider than the pane", all(len(l) <= 60 for l in v))
need("names the host", "DB-BOX" in v[0])
need("CPU's peak", any("peak 100%" in l for l in v))
need("the outage", any("down about 5 min" in l for l in v))
need("nothing yet says so", any("nothing recorded yet" in plain(l) for l in history.view("x", [], 60, 30)))
need("a tiny pane: few lines", len(history.view("db-box", rows, 30, 3, now=ns * S)) <= 3)

# seed_demo(): a day for `phosphor demo`, the overnight build and relay's outage
history.seed_demo(list(fleet.DEMO_BASE), fleet.DEMO_BASE, now=ns * S)
h = history.load()
need("every demo host gets a day", all(len(h[n]) == history.KEEP - 1 for n in fleet.DEMO_BASE))
need("forge ran hot", max(r[0] for _, r in h["forge"] if r) > 90)
need("relay went down", any(r is None for _, r in h["relay"]))

# FLEET: h shows in the footer with a card picked, and its own footer taps
fleet.HOSTS = [("box", None), ("db-box", "db-box-alias")]
line, taps = fleet.footer(2, 1, "")
need("h history in the footer", "h history" in plain(line) and "h" in taps.values())
line, taps = fleet.history_footer("db-box")
need("history footer: another host, back", set(taps.values()) == {"\t", "\x1b"})
for (a, b), k in taps.items():
    need("tap %r lands on its hint" % k, plain(line)[a - 1:b].strip() != "")

if fails:
    print("FAIL:\n  " + "\n  ".join(fails)); sys.exit(1)
print("fleet history ok")
