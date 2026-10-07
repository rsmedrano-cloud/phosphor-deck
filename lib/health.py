"""What a host's sensors say (collect.sh's TEMP, BAT, SMART and UPD), read the
same way by the FLEET card and by glance. Its own module so fleet.py stays
nobody else's import (see hotswap)."""

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
    import limits
    temp, bat, smart = sensors(d)
    out = []
    if smart and smart[0]:
        out.append("%d disk%s failing SMART" % (smart[0], "" if smart[0] == 1 else "s"))
    if temp is not None and limits.red("temp", temp, host):
        out.append("cpu %d°C" % temp)
    if bat and bat[1] == "Discharging" and limits.red("battery", bat[0], host):
        out.append("battery %d%%" % bat[0])
    upd = updates(d)
    if upd and upd[1]:
        out.append("%d security update%s" % (upd[1], "" if upd[1] == 1 else "s"))
    return out
