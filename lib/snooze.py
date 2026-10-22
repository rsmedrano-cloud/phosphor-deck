#!/usr/bin/env python3
"""phosphor snooze - quiet an alert you already know about, for a while.

"I know vault is at 95%, don't tell me for 24h." A snooze is one machine
and one kind of problem, with how bad it was when you quieted it. While
it holds, that problem is out of the one list every screen reads
(glance.host_problems: the fleet card's !, glance and its light, fleet
--json, the SolarOS panel, triage), out of the adjutant's line, and a
fleet alert about it isn't pushed or spoken. It always expires (24 hours
unless you say, 7 days at most), and it ends early when the reading gets
worse than what you quieted: a disk from amber to red, a third service
failing after two.

    phosphor snooze                     what's snoozed, and until when
    phosphor snooze HOST                what's wrong on HOST now, for 24h
    phosphor snooze HOST KIND...        those kinds, even before they happen
                                        (a laptop you'll leave off: HOST down)
    phosphor snooze HOST --for 4h       30m, 4h, 2d; a bare number is hours
    phosphor snooze HOST --wake         its snoozes end now (no HOST: all of them)
    phosphor snooze --json              the list, for scripts and the deck's card

KIND is one of down, disk, services, checks, reboot, smart, temp,
battery, security. FLEET's z over a machine, Enter on it in glance and the SolarOS
panel's fleet menu snooze what's wrong on it for 24h; z again in FLEET, or
--wake, ends it.
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf
from sanitize import clean_tree

KINDS = ("down", "disk", "services", "checks", "reboot", "smart", "temp", "battery", "security")
DAY = 24 * 3600
MOST = 7 * DAY
_cache = {"key": None, "data": {}}

def path():
    return os.path.join(deckconf.data_dir(), "snooze.json")

def load():
    """{host: {kind: {"until", "level", "detail"}}}, what's still in time.
    Read again only when the file changes: the adjutant asks every tick."""
    p = path()
    try:
        st = os.stat(p)
        key = (st.st_ino, st.st_mtime_ns, st.st_size)     # each save is a new file
    except OSError:
        return {}
    if key != _cache["key"]:
        try:
            with open(p) as f:
                d = clean_tree(json.load(f))
        except (OSError, ValueError):
            d = {}
        _cache["key"], _cache["data"] = key, d if isinstance(d, dict) else {}
    now = time.time()
    out = {}
    for host, kinds in _cache["data"].items():
        for kind, e in (kinds.items() if isinstance(kinds, dict) else ()):
            try:
                if float(e["until"]) > now:
                    out.setdefault(host, {})[kind] = e
            except (KeyError, TypeError, ValueError):
                continue
    return out

def _level(e):
    try: return int(e.get("level", 1))
    except (TypeError, ValueError): return 1

def holds(quiet, host, kind, level):
    """True when a snooze in `quiet` (load()) keeps this problem out of sight:
    in time, and the problem no worse than when it was snoozed."""
    e = (quiet.get(host) or {}).get(kind)
    return bool(e) and level <= _level(e)

def worse(quiet, host, kind, level):
    """True when a snooze is there but the problem got worse: it ends now."""
    e = (quiet.get(host) or {}).get(kind)
    return bool(e) and level > _level(e)

def _save(d):
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp.%d" % os.getpid()
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
    os.replace(tmp, p)

def end(pairs):
    """End these (host, kind) snoozes; kind None ends all of that host's,
    host None everyone's. The (host, kind)s that were there."""
    d = load()
    gone = []
    for host, kind in pairs:
        for h in ([host] if host else list(d)):
            for k in ([kind] if kind else list(d.get(h, {}))):
                if d.get(h, {}).pop(k, None) is not None:
                    gone.append((h, k))
            if h in d and not d[h]:
                del d[h]
    if gone:
        _save(d)
    return gone

def readings():
    """{host: its latest poll}: fleet.json, the FLEET panel's cache."""
    import glance
    try:
        with open(glance.CACHE) as f:
            d = clean_tree(json.load(f))
        return d.get("hosts", {}) if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}

def level(kind, host, h):
    """How bad `kind` is on this poll, whether or not it's past its red
    line: a count, or a limit's level (lib/limits.py). 0 is fine."""
    import health, limits
    if not h:
        return 0
    if kind == "down":
        return 0 if h.get("ok") else 1
    if not h.get("ok"):
        return 0
    if kind == "disk":
        return max([limits.level("disk", m[1], host) for m in h.get("mnt", []) if len(m) == 3] or [0])
    if kind == "services":
        try: return int(h.get("SVCFAIL") or 0)
        except (TypeError, ValueError): return 0
    if kind == "checks":
        import checks
        return len(checks.failing(host))
    if kind == "reboot":
        return 1 if h.get("REBOOT") else 0
    temp, bat, smart = health.sensors(h)
    if kind == "smart":
        return smart[0] if smart else 0
    if kind == "temp":
        return limits.level("temp", temp, host) if temp is not None else 0
    if kind == "battery":
        return limits.level("battery", bat[0], host) if bat and bat[1] == "Discharging" else 0
    if kind == "security":
        upd = health.updates(h)
        return (upd[1] or 0) if upd else 0
    return 0

def snooze(host, kinds=None, secs=DAY, now=None):
    """Snooze what's wrong on `host` now, or these kinds, for secs (at most
    7 days). A kind that's fine now is snoozed at its first step: one
    service, amber, down. [(kind, what it was)] snoozed, [] for nothing."""
    import glance
    now = now or time.time()
    h = readings().get(host)
    if kinds is None:
        got = [(k, n, d) for k, n, d, _ in glance.findings(host, h)] if h else []
    else:
        found = {k: d for k, _, d, _ in (glance.findings(host, h) if h else [])}
        got = [(k, max(1, level(k, host, h)), found.get(k, k + " (ahead)")) for k in kinds]
    if not got:
        return []
    d = load()
    ends = now + max(60, min(int(secs), MOST))
    for k, n, detail in got:
        d.setdefault(host, {})[k] = {"until": int(ends), "level": int(n), "detail": detail}
    _save(d)
    return [(k, detail) for k, _, detail in got]

def toggle(host, secs=DAY):
    """What a key does over a machine (FLEET's z, glance, SolarOS): wake
    it when something on it is snoozed, else snooze what's wrong now.
    A message saying which."""
    if load().get(host):
        end([(host, None)])
        return "%s: awake, its alerts show again" % host
    got = snooze(host, secs=secs)
    if not got:
        return "nothing wrong on %s to snooze" % host
    return "%s: %s snoozed till %s" % (host, ", ".join(d for _, d in got), when(time.time() + secs))

def until(host):
    """When the latest snooze on host ends, or None."""
    t = [float(e["until"]) for e in load().get(host, {}).values()]
    return max(t) if t else None

def active():
    """What's snoozed now, as `--json` lists it."""
    out = []
    for host, kinds in sorted(load().items()):
        for kind, e in sorted(kinds.items()):
            out.append({"host": host, "kind": kind, "detail": e.get("detail") or kind,
                        "level": _level(e), "until": int(float(e["until"])),
                        "when": "till " + when(float(e["until"]))})
    return out

def when(t, now=None):
    """18:30 today, 'tomorrow 18:30', 'Tue 18:30' further on."""
    now = now or time.time()
    a, b = time.localtime(now), time.localtime(t)
    if (a.tm_year, a.tm_yday) == (b.tm_year, b.tm_yday):
        return time.strftime("%H:%M", b)
    if (time.localtime(now + DAY).tm_year, time.localtime(now + DAY).tm_yday) == (b.tm_year, b.tm_yday):
        return time.strftime("tomorrow %H:%M", b)
    return time.strftime("%a %H:%M", b)

# A fleet alert's text, the same from either poller (lib/fleet.py's
# update_host, rust/fleet-poll): which host, which kind, how bad.
ALERTS = ((re.compile(r"^(.+) is unreachable$"), "down", lambda m: 1),
          (re.compile(r"^(.+) is back$"), "down", lambda m: 0),
          (re.compile(r"^(.+): (\d+) services? failed$"), "services", lambda m: int(m.group(2))),
          (re.compile(r"^(.+): services back to normal$"), "services", lambda m: 0),
          (re.compile(r"^(.+): (\d+) disks? failing SMART$"), "smart", lambda m: int(m.group(2))),
          (re.compile(r"^(.+?): .+ not answering$"), "checks", lambda m: max(1, _failing(m.group(1)))),
          (re.compile(r"^(.+?): .+ answering again$"), "checks", lambda m: 0))

def _failing(host):
    import checks
    return len(checks.failing(host))

def quiets(text):
    """True when a fleet alert is about something snoozed: phosphor notify
    then neither pushes nor speaks it. A recovery of it is quiet too."""
    for pat, kind, lvl in ALERTS:
        m = pat.match(text)
        if m:
            return holds(load(), m.group(1), kind, lvl(m))
    return False

def duration(s):
    """Seconds from 30m, 4h, 2d or a bare number of hours, else None."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([mhd]?)", (s or "").strip().lower())
    if not m:
        return None
    return int(float(m.group(1)) * {"m": 60, "h": 3600, "d": DAY, "": 3600}[m.group(2)])

def main():
    from ui import DIM, FG, AMB, PH, RST
    argv = sys.argv[1:]
    js, wake = "--json" in argv, "--wake" in argv
    argv = [a for a in argv if a not in ("--json", "--wake")]
    secs = DAY
    if "--for" in argv:
        i = argv.index("--for")
        secs = duration(argv[i + 1] if i + 1 < len(argv) else "")
        del argv[i:i + 2]
        if not secs:
            print("--for takes 30m, 4h, 2d or a number of hours", file=sys.stderr); return 2
        if secs > MOST:
            print(DIM + "a snooze lasts 7 days at most: 7d it is" + RST)
    if any(a.startswith("-") for a in argv):
        print("usage: phosphor snooze [HOST [KIND...]] [--for 4h] [--wake] [--json]", file=sys.stderr); return 2
    if not argv and not wake:
        rows = active()
        if js:
            line = ("%d snoozed" % len(rows)) if rows else "nothing snoozed"
            print(json.dumps({"snoozed": rows, "line": line}, indent=1)); return 0
        if not rows:
            print(DIM + "nothing snoozed: every alert shows. phosphor snooze HOST quiets one" + RST); return 0
        w = max(len(r["host"]) for r in rows)
        for r in rows:
            print("  " + FG + r["host"].ljust(w) + RST + "  " + AMB + r["detail"] + RST
                  + DIM + "  " + r["when"] + RST)
        print(DIM + "  it wakes early if it gets worse; phosphor snooze HOST --wake ends it now" + RST)
        return 0
    host, kinds = (argv[0] if argv else None), argv[1:]
    names = [n for n, _ in deckconf.fleet_hosts(deckconf.load()[0])]
    if host and host not in names:
        print("%s isn't one of the fleet's machines: %s" % (host, ", ".join(names) or "none yet"), file=sys.stderr)
        return 2
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        print("not a kind of alert: %s (%s)" % (" ".join(bad), ", ".join(KINDS)), file=sys.stderr); return 2
    if wake:
        gone = end([(host, k) for k in kinds] if kinds else [(host, None)])
        print((PH + "awake: " + ", ".join("%s %s" % g for g in gone) + RST) if gone
              else DIM + "nothing was snoozed there" + RST)
        return 0
    got = snooze(host, kinds or None, secs)
    if not got:
        print(DIM + "nothing wrong on %s right now: name a kind to snooze it ahead (%s)"
              % (host, ", ".join(KINDS)) + RST)
        return 1
    print(PH + "%s: %s snoozed till %s" % (host, ", ".join(d for _, d in got), when(time.time() + min(secs, MOST)))
          + RST + DIM + "  (it wakes early if it gets worse)" + RST)
    return 0

if __name__ == "__main__":
    sys.exit(main())
