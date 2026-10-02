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

With [tts] on too, a notice the brain speaks carries what it said: the same
clip, attached to the push (ntfy's attachments), so the phone plays the
words instead of a generic ring. [push] clip = false keeps it text only.
"""
import os, sys, urllib.parse, urllib.request, urllib.error

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
        "clip": p.get("clip", True) is not False,
    }


def wants_clip(force=False, cfg=None):
    """Would a notice now go out with its spoken clip attached? Push on (or
    forced) with a topic, and [push] clip not turned off."""
    cfg = cfg or get_config()
    return bool((force or cfg["enabled"]) and cfg["topic"] and cfg["clip"])


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


def send(text, tab="", cfg=None, force=False, timeout=8, click="", attach=""):
    """POST the notice. Returns (ok, why): why says what went wrong, or "".
    click: an address the notice opens when tapped, with an "open the deck"
    button too. attach: a wav file (the spoken notice) sent along as an
    attachment; a server that won't take one (a self-hosted ntfy without
    an attachment cache) still gets the text. Never raises: a notice that
    can't be pushed must not break the caller."""
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
    msg = text.strip()[:MAX_LEN]
    target = "%s/%s" % (cfg["url"], cfg["topic"])
    if attach:
        try:
            with open(attach, "rb") as f:
                data = f.read()
        except OSError:
            data = b""
        if data:
            # The file is the body, so the message rides in the query string
            # (ntfy reads ?message= and ?filename= the same as headers).
            q = urllib.parse.urlencode({"message": msg, "filename": "phosphor.wav"})
            ok, why = _post(urllib.request.Request(target + "?" + q, data=data,
                            headers=headers, method="PUT"), timeout)
            if ok or not why.startswith("HTTP 4"):
                return ok, why
            # 4xx: attachments not allowed there, or too big: the text alone
    return _post(urllib.request.Request(target, data=msg.encode("utf-8"),
                                        headers=headers, method="POST"), timeout)


def _post(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (200 <= r.status < 300), ("" if 200 <= r.status < 300 else "HTTP %d" % r.status)
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, str(getattr(e, "reason", e))


def notify_hook(text, tab="", force=False, attach=""):
    """Called by `phosphor notify`: push if enabled (or forced by --push).
    With browser access on, tapping the notice opens the deck; attach is
    the spoken clip, when [tts] made one."""
    prof, _ = deckconf.load()
    cfg = get_config(prof)
    if not (force or cfg["enabled"]):
        return False, "push is off"
    return send(text, tab=tab, cfg=cfg, force=force,
                click=web_url(prof) if cfg["open_web"] else "",
                attach=attach if cfg["clip"] else "")


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
    print(row(OK if cfg["clip"] else DIM + "·" + RST, "voice clip",
              "attached when [tts] speaks" if cfg["clip"] else "off",
              note="" if cfg["clip"] else "[push] clip = true attaches it"))
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


def set_enabled(on):
    """[push] enabled = on. Turning it on with no topic makes one up: long
    and random, since on a public server the name is the only lock."""
    cfg = get_config()
    if on and not cfg["topic"]:
        import secrets
        if not deckconf.set_key("push", "topic", '"deck-%s"' % secrets.token_hex(8)):
            print(row(BAD, "push", "no profile yet", note="phosphor init writes yours")); return 1
    if not deckconf.set_key("push", "enabled", "true" if on else "false"):
        print(row(BAD, "push", "no profile yet", note="phosphor init writes yours")); return 1
    print(row(OK, "push", "on" if on else "off", note=deckconf.path()))
    if on and not cfg["topic"]:
        print(DIM + "  a new topic: phosphor push --qr subscribes the phone to it" + RST)
    return 0


def interactive():
    """No arguments, on a terminal: the status, on/off and the QR one key away."""
    import form
    while True:
        cfg = get_config()
        status(cfg)
        opts = [("o", "turn it off" if cfg["enabled"] else "turn it on")]
        if cfg["topic"]:
            opts.append(("s", "subscribe a phone (QR)"))
        k = form.choice(opts)
        if k == "o":
            set_enabled(not cfg["enabled"])
        elif k == "s":
            print(); qr(cfg)
        else:
            return 0
        print()


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print("usage: phosphor push [--qr | on | off]"); return 0
    if "--qr" in a:
        return qr()
    if a and a[0] in ("on", "off"):
        return set_enabled(a[0] == "on")
    if not a and sys.stdin.isatty() and sys.stdout.isatty():
        return interactive()
    return status()


if __name__ == "__main__":
    sys.exit(main() or 0)
