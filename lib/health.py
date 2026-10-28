"""What a host's sensors say (collect.sh's TEMP, BAT, SMART and UPD) and
which of its units failed (SVCFAIL, SVCFAILED), read the same way by the
FLEET card, glance and the alerts. Its own module so fleet.py stays nobody
else's import (see hotswap)."""
import re

# A systemd unit's name, as collect.sh sends it: anything else in SVCFAILED
# (an old or odd host) is left out, never shown or put in a command line.
UNIT = re.compile(r"^[A-Za-z0-9@._:\\-]{1,128}$")

def sensors(d):
    """(cpu temp °C, (battery %, status), (disks failing SMART, checked))
    from one host's poll, each None when that machine doesn't say. Never
    trusts a type: fleet.json can come from either poller, of any age."""
    def num(v):
        try: return int(v)
        except (TypeError, ValueError): return None
    temp = num(d.get("TEMP"))
    bat = None
    if d.get("BAT"):
        p, _, st = str(d["BAT"]).partition("|")
        if num(p) is not None:
            bat = (num(p), st.strip())
    smart = None
    if d.get("SMART"):
        f, _, n = str(d["SMART"]).partition("|")
        if num(f) is not None and num(n):
            smart = (num(f), num(n))
    return temp, bat, smart

def failed(d):
    """(how many units failed, the names collect.sh sent, at most 8 of
    them): (0, []) with none. Names can be missing (a poller or a host
    older than SVCFAILED): the count still stands."""
    try: n = int(d.get("SVCFAIL") or 0)
    except (TypeError, ValueError): n = 0
    if n <= 0:
        return 0, []
    return n, [u for u in str(d.get("SVCFAILED") or "").split(",") if UNIT.match(u)][:n]

def failed_text(d, width=None):
    """What failed, short: "media-remount failed", "getty@tty1,
    media-remount failed", "a +3 failed" when the names don't fit in width,
    "2 services failed" with no names (as before SVCFAILED); "" with none.
    A .service suffix goes."""
    n, names = failed(d)
    if not n:
        return ""
    short = [u[:-8] if u.endswith(".service") else u for u in names]
    for k in range(len(short), 0, -1):
        s = ", ".join(short[:k]) + (" +%d" % (n - k) if n > k else "") + " failed"
        if width is None or len(s) <= width:
            return s
    s = "%d service%s failed" % (n, "" if n == 1 else "s")
    return s if width is None or len(s) <= width else ("%d failed" % n)[:width]

def updates(d):
    """(pending updates, how many are security ones or None when the
    package manager can't tell) from collect.sh's UPD, or None."""
    if not d.get("UPD"):
        return None
    a, _, s = str(d["UPD"]).partition("|")
    try: a = int(a)
    except ValueError: return None
    try: s = int(s)
    except ValueError: s = None
    return a, s

def sensor_problems(d, host=None):
    """What glance calls out about a host's sensors, as short phrases:
    past their red line (lib/limits.py), not just colored on its card."""
    return [p for _, _, p in sensor_findings(d, host)]

def sensor_findings(d, host=None):
    """sensor_problems() as (kind, how bad, phrase): what a snooze holds
    (lib/snooze.py). How bad is a count, or the limit's level."""
    import limits
    temp, bat, smart = sensors(d)
    out = []
    if smart and smart[0]:
        out.append(("smart", smart[0], "%d disk%s failing SMART" % (smart[0], "" if smart[0] == 1 else "s")))
    if temp is not None and limits.red("temp", temp, host):
        out.append(("temp", 2, "cpu %d°C" % temp))
    if bat and bat[1] == "Discharging" and limits.red("battery", bat[0], host):
        out.append(("battery", 2, "battery %d%%" % bat[0]))
    upd = updates(d)
    if upd and upd[1]:
        out.append(("security", upd[1], "%d security update%s" % (upd[1], "" if upd[1] == 1 else "s")))
    return out
