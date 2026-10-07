"""Where a reading turns amber and where it turns red: the one place every
panel asks. FLEET's cards, its 24h history, glance, digest, the adjutant
and pulse all used to carry their own cuts, so the same disk at 88% was
red on a card and nowhere in glance.

Each metric has two limits, warn and bad. Below warn it's fine; from warn
it's amber; from bad it's red, and red is what glance, digest, the
adjutant and pulse call out. The battery counts down: it warns at or
below its first number and is bad at or below its second.

The profile's [alerts] changes them, for every host or for one:

    [alerts]
    disk = [80, 90]          # [warn, bad]
    [alerts.nimbus]
    disk = [90, 97]          # a backup disk that lives full
    temp = 95                # one number: bad only, warn stays below it
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {"cpu": (60, 90), "ram": (60, 90), "gpu": (60, 90), "disk": (80, 90),
            "temp": (70, 85), "battery": (30, 10)}
DOWN = {"battery"}              # lower is worse

_cache = {"key": None, "table": {}}


def _pair(metric, v, base=None):
    """A profile value as (warn, bad), or None when it isn't one. One
    number keeps the warn of base (the [alerts] above it, else the default)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        w = (base or DEFAULTS[metric])[0]
        bad = v
        warn = (max(w, bad) if metric in DOWN else min(w, bad))
        return warn, bad
    if isinstance(v, list) and len(v) == 2 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        warn, bad = v
        if (warn < bad) if metric in DOWN else (warn > bad):
            return None
        return warn, bad
    return None


def problem(metric, v):
    """What's wrong with a profile value for metric, or None (profcheck says it)."""
    if metric not in DEFAULTS:
        return "isn't one of " + ", ".join(sorted(DEFAULTS))
    if _pair(metric, v) is None:
        return ("is [warn, bad] (warn at or above bad: the battery counts down) or one number"
                if metric in DOWN else "is [warn, bad] (warn at or below bad) or one number")
    return None


def table(prof):
    """{None: {metric: (warn, bad)}, host: {...}} from a profile's [alerts],
    what's missing or wrong left at its default."""
    sec = (prof or {}).get("alerts")
    sec = sec if isinstance(sec, dict) else {}
    every = dict(DEFAULTS)
    for k, v in sec.items():
        if k in DEFAULTS and _pair(k, v):
            every[k] = _pair(k, v)
    out = {None: every}
    for host, t in sec.items():
        if isinstance(t, dict):
            own = dict(every)
            for k, v in t.items():
                if k in DEFAULTS and _pair(k, v, every[k]):
                    own[k] = _pair(k, v, every[k])
            out[host] = own
    return out


def _loaded():
    """table() of the profile on disk, read again only when it changes:
    the adjutant and pulse ask many times a second."""
    import deckconf
    p = deckconf.path()
    try:
        st = os.stat(p)
        key = (p, st.st_mtime, st.st_size)
    except OSError:
        key = (p, None, None)
    if key != _cache["key"]:
        _cache["key"] = key
        _cache["table"] = table(deckconf.load()[0] if key[1] else None)
    return _cache["table"]


def get(metric, host=None, prof=None):
    """(warn, bad) for metric on host. prof: a profile already in hand,
    else the one on disk."""
    t = table(prof) if prof is not None else _loaded()
    return t.get(host, t[None])[metric]


def level(metric, v, host=None, prof=None):
    """0 fine, 1 warn, 2 bad."""
    warn, bad = get(metric, host, prof)
    if metric in DOWN:
        return 2 if v <= bad else 1 if v <= warn else 0
    return 2 if v >= bad else 1 if v >= warn else 0


def red(metric, v, host=None, prof=None):
    """Past the red line: what glance and digest call out."""
    return level(metric, v, host, prof) == 2


def color(metric, v, host=None, prof=None):
    from ui import PH, AMB, RED
    return (PH, AMB, RED)[level(metric, v, host, prof)]
