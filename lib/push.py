"""phosphor push - status for [push], and a QR to subscribe on the phone.

The brain often sits in a rack with nobody near it, so a spoken notice goes
nowhere. `phosphor notify` (and anything that calls it: a fleet host down or
back, a chat mention) sends the same notice to an ntfy topic (ntfy.sh, or a
server of your own); the ntfy app on the phone rings, vibrates and shows it,
whether Termux is open or not. Plain HTTP POST, standard library only.

Off until [push] in the profile has enabled = true and a url + topic: the
message text leaves this machine, so nothing is sent by default.

    phosphor push           status: on/off, server, topic
    phosphor push --qr      the subscribe link as a QR (and on every clipboard):
                             scan it in the phone's ntfy app instead of typing
                             the server and topic in by hand
"""
import os, sys, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf
from ui import OK, WARN, BAD, DIM, RST, row

MAX_LEN = 500


def get_config(prof=None):
    """Read [push] settings from the profile."""
    if prof is None:
        prof, _ = deckconf.load()
    p = (prof or {}).get("push") or {}
    token = str(p.get("token", "") or "")
    if token.startswith("env:"):
        token = os.environ.get(token[4:].strip(), "")
    return {
        "enabled": bool(p.get("enabled", False)),
        "url": str(p.get("url", "https://ntfy.sh") or "").rstrip("/"),
        "topic": str(p.get("topic", "") or "").strip("/ "),
        "token": token,
        "priority": str(p.get("priority", "default") or "default"),
        "title": str(p.get("title", "phosphor") or "phosphor"),
        "open_web": p.get("open_web", True) is not False,
    }


def web_url(prof=None):
    """The deck's browser address, for the notice's "open the deck" button:
    only while [deck] web is on and tailscale serves it (a 127.0.0.1 address
    means nothing on a phone). "" otherwise, never raises."""
    try:
        if prof is None:
            prof, _ = deckconf.load()
        if not ((prof or {}).get("deck") or {}).get("web", False):
            return ""
        import web
        ok, _ = web.usable(prof)
        return web.url(prof) if ok else ""
    except Exception:
        return ""


def send(text, tab="", cfg=None, force=False, timeout=8, click=""):
    """POST the notice. Returns (ok, why): why says what went wrong, or "".
    click: an address the notice opens when tapped, with an "open the deck"
    button too. Never raises: a notice that can't be pushed must not break
    the caller."""
    cfg = cfg or get_config()
    if not (force or cfg["enabled"]):
        return False, "push is off"
    if not cfg["topic"]:
        return False, "no topic in [push]"
    if not cfg["url"].startswith(("http://", "https://")):
        return False, "url in [push] must start with http:// or https://"
    title = cfg["title"] + (" · " + tab if tab else "")
    headers = {"Title": title, "Priority": cfg["priority"]}
    if cfg["token"]:
        headers["Authorization"] = "Bearer " + cfg["token"]
    if click:
        headers["Click"] = click
        headers["Actions"] = "view, open the deck, %s" % click
    body = text.strip()[:MAX_LEN].encode("utf-8")
    req = urllib.request.Request("%s/%s" % (cfg["url"], cfg["topic"]),
                                 data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (200 <= r.status < 300), ("" if 200 <= r.status < 300 else "HTTP %d" % r.status)
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, str(getattr(e, "reason", e))


def notify_hook(text, tab="", force=False):
    """Called by `phosphor notify`: push if enabled (or forced by --push).
    With browser access on, tapping the notice opens the deck."""
    prof, _ = deckconf.load()
    cfg = get_config(prof)
    if not (force or cfg["enabled"]):
        return False, "push is off"
    return send(text, tab=tab, cfg=cfg, force=force,
                click=web_url(prof) if cfg["open_web"] else "")


def subscribe_url(cfg):
    """The link that subscribes to this topic: <server>/<topic>. Opening it
    (or scanning it in the ntfy app's own QR scanner) subscribes -- no
    typing the server and topic in by hand."""
    return "%s/%s" % (cfg["url"], cfg["topic"]) if cfg["topic"] else ""


def status(cfg=None):
    cfg = cfg or get_config()
    print(row(OK if cfg["enabled"] else WARN, "push", "on" if cfg["enabled"] else "off",
              note="[push] enabled in the profile" if not cfg["enabled"] else ""))
    print(row(OK, "server", cfg["url"]))
    print(row(OK if cfg["topic"] else WARN, "topic", cfg["topic"] or "(none set)"))
    if cfg["token"]:
        print(row(OK, "token", "set"))
    if cfg["open_web"]:
        u = web_url()
        print(row(OK if u else DIM + "·" + RST, "open the deck", u or "no button",
                  note="" if u else "phosphor web on adds one"))
    if not cfg["topic"]:
        print(DIM + "  set [push] topic in the profile, then phosphor push --qr" + RST)
        return 1
    print(DIM + "  try it: phosphor notify --push \"hello\"" + RST)
    return 0


def qr(cfg=None):
    cfg = cfg or get_config()
    if not cfg["topic"]:
        print(row(BAD, "push", "no topic", note="set [push] topic in the profile first")); return 1
    url = subscribe_url(cfg)
    at = row(OK, "subscribe", url, note="scan in the phone's ntfy app, or open the link")
    print(at.replace(url, "\x1b]8;;%s\x1b\\%s\x1b]8;;\x1b\\" % (url, url)))   # OSC 8: a tap/click opens it
    try:
        import qr as qrmod
        m = qrmod.encode(url)
        for l in (qrmod.render(m) if m else []):
            print("  " + l)
    except ImportError:
        pass
    try:
        import clip
        clip.send(url.encode())          # every screen's clipboard: paste into the ntfy app
    except Exception:
        pass
    if not cfg["enabled"]:
        print(row(WARN, "note", "push is off", note="[push] enabled = true to actually send"))
    return 0


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print("usage: phosphor push [--qr]"); return 0
    if "--qr" in a:
        return qr()
    return status()


if __name__ == "__main__":
    sys.exit(main() or 0)
