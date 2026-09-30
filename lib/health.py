"""What a host's sensors say (collect.sh's TEMP, BAT and SMART), read the
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

HOT, LOW_BAT = 90, 10   # past these a host shows up in glance, not just on its card

def sensor_problems(d):
    """What glance calls out about a host's sensors, as short phrases."""
    temp, bat, smart = sensors(d)
    out = []
    if smart and smart[0]:
        out.append("%d disk%s failing SMART" % (smart[0], "" if smart[0] == 1 else "s"))
    if temp is not None and temp >= HOT:
        out.append("cpu %d°C" % temp)
    if bat and bat[1] == "Discharging" and bat[0] <= LOW_BAT:
        out.append("battery %d%%" % bat[0])
    return out
