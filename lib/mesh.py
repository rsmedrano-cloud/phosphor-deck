"""How the machines reach each other: tailscale, headscale, or plain ssh.

Headscale is a self-hosted control server for the same tailscale client, so
both are driven through the `tailscale` CLI. What differs is where clients
log in (the ControlURL), and a phone joining the deck needs to know that.
"""
import json, shutil, subprocess
from urllib.parse import urlparse

KINDS = ("tailscale", "headscale", "none")

def detect():
    """(kind, control_url) from the local tailscale client."""
    if not shutil.which("tailscale"):
        return "none", None
    try:
        out = subprocess.run(["tailscale", "debug", "prefs"], capture_output=True,
                             text=True, timeout=5).stdout
        url = json.loads(out).get("ControlURL") or ""
    except Exception as e:
        import dlog
        dlog.event("MESH", "detect-failed", str(e)[:60])
        url = ""
    host = urlparse(url).hostname or ""
    if not host or host == "tailscale.com" or host.endswith(".tailscale.com"):
        return "tailscale", url or None
    return "headscale", url

def current(prof):
    """What the profile says (`mesh` in [deck]), or what's detected when it
    says "auto" or nothing."""
    want = ((prof or {}).get("deck") or {}).get("mesh", "auto")
    kind, url = detect()
    if want in KINDS:
        return want, (url if want != "none" else None)
    return kind, url
