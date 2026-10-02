"""Screens that reach the deck through a tailscale relay (DERP), and the
animations that slow down for them.

A screen with no direct path to the brain goes through one of tailscale's
relay servers. That link is thin: a phone or a Pi behind it froze up while
pulse and the adjutant redrew ten times a second (seen on a Pi 4 whose peer
said "relay mad" and had no address of its own), and was fine over the LAN.
zellij sends every redraw to every client of the session, so one animated
pane is enough to clog it.

`Pace` asks, every so often, whether a screen attached to this pane's own
session (ZELLIJ_SESSION_NAME) is relayed, and an animation sleeps SLOW
between frames instead of its usual delay while one is. A per-kind deck
(`deck-tablet`) slows down only for its own screens. Nothing here changes
the network; `phosphor screens` marks those screens "relay".
"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf

SLOW = 1.0          # seconds between frames while a relayed screen looks on
EVERY = 20          # seconds between checks


def ts_status():
    """`tailscale status --json`, or None without tailscale or an answer."""
    ts = deckconf.exe("tailscale")
    if not ts:
        return None
    try:
        out = subprocess.run([ts, "status", "--json"], capture_output=True,
                             text=True, timeout=5).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def relayed(status):
    """The addresses and names of every peer that only reaches us through a
    relay: tailscale names a DERP region (Relay) but has no direct address
    (CurAddr) for it."""
    out = set()
    for p in ((status or {}).get("Peer") or {}).values():
        if p.get("CurAddr") or not p.get("Relay"):
            continue
        out.update(p.get("TailscaleIPs") or [])
        for n in (p.get("HostName"), (p.get("DNSName") or "").rstrip(".")):
            if n:
                out.add(n.lower())
                out.add(n.lower().split(".")[0])
    return out


def is_relayed(frm, addrs):
    """Whether `who`'s from column (an address, or a name with UseDNS) is one
    of `relayed`'s."""
    frm = (frm or "").lower()
    return bool(frm) and (frm in addrs or frm.split(".")[0] in addrs
                          and not frm.replace(".", "").isdigit())


def slow_screens(session, status=None):
    """The screens attached to `session` that come through a relay."""
    import screens
    rows = screens.screens(session) or []
    if not rows:
        return []
    addrs = relayed(status if status is not None else ts_status())
    return [r for r in rows if is_relayed(r["from"], addrs)]


class Pace:
    """delay(normal) -> how long to wait before the next frame."""

    def __init__(self, tool, check=None, now=time.time):
        self.tool, self.now = tool, now
        session = os.environ.get("ZELLIJ_SESSION_NAME", "")
        self.check = check or (lambda: bool(session) and bool(slow_screens(session)))
        self.slow, self.last = False, None

    def delay(self, normal):
        t = self.now()
        if self.last is None or t - self.last >= EVERY:
            self.last = t
            try:
                slow = bool(self.check())
            except Exception:
                slow = False
            if slow != self.slow:
                import dlog
                dlog.event(self.tool, "slow-link" if slow else "fast-link",
                           "a screen comes through a relay" if slow else "")
            self.slow = slow
        return max(normal, SLOW) if self.slow else normal
