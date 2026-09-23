"""phosphor web - the deck in a browser, only inside your tailnet. Optional
and off by default.

zellij's own web client listens on 127.0.0.1 and asks for a login token;
`tailscale serve` publishes it over HTTPS to your tailnet only, on a port
of its own so it doesn't touch anything you already serve there. Never
funnel (that would be the internet). Two locks: the tailnet and the token.

    phosphor web on       publish it, print the address and a login token
    phosphor web off      unpublish it and stop the web server
    phosphor web status   what's running and where
    phosphor web token    a new login token (shown once, revocable)
"""
import json, os, re, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, mesh

LOCAL = "http://127.0.0.1:8082"      # zellij web's default, localhost only

def _zj():
    p = os.path.expanduser("~/.local/bin/zellij")
    return p if os.path.exists(p) else (shutil.which("zellij") or "zellij")

def zj(*a):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
    return subprocess.run([_zj()] + list(a), capture_output=True, text=True, timeout=20, env=env)

def ts(*a):
    return subprocess.run(["tailscale"] + list(a), capture_output=True, text=True, timeout=20)

def port(prof):
    return int(((prof or {}).get("deck") or {}).get("web_port", 8443))

def dns_name():
    try:
        d = json.loads(ts("status", "--json").stdout)
        return (d.get("Self") or {}).get("DNSName", "").rstrip("."), bool(d.get("CertDomains"))
    except Exception as e:
        import dlog
        dlog.event("WEB", "dns-name-failed", str(e)[:60])
        return "", False

def usable(prof):
    """(ok, why): HTTPS inside the tailnet needs tailscale's certificates."""
    kind, _ = mesh.current(prof)
    if kind != "tailscale":
        return False, ("%s has no automatic HTTPS certificates" % kind) if kind == "headscale" \
            else "it needs tailscale (mesh = \"none\")"
    name, certs = dns_name()
    if not name or not certs:
        return False, "your tailnet has HTTPS certificates off (enable HTTPS in the tailscale admin)"
    return True, ""

def url(prof):
    name, _ = dns_name()
    return "https://%s:%d" % (name, port(prof)) if name else ""

def live(prof):
    """The truth, not the profile: is the address published, is the server up."""
    try:
        web = json.loads(ts("serve", "status", "--json").stdout or "{}").get("Web", {})
    except (ValueError, OSError, subprocess.SubprocessError):
        web = {}
    try:
        srv = "online" in (zj("web", "--status").stdout or "")
    except (OSError, subprocess.SubprocessError):
        srv = False
    return {"flag": bool(((prof or {}).get("deck") or {}).get("web", False)),
            "published": any(h.endswith(":%d" % port(prof)) for h in web),
            "server": srv}

def show_url(prof):
    """The address, and a QR of it: typing it on a phone is where people get lost
    (without https:// or with the short name, the browser never gets there)."""
    u = url(prof)
    print("  " + FG + "Open " + PH + u + RST + FG + " on a device in your tailnet" + RST)
    print("  " + DIM + "(the whole address, https:// and all; 'homelab' alone won't work)" + RST)
    try:
        import qr
        if qr.width(u) and qr.width(u) <= width():
            print("  " + DIM + "or scan it with the phone's camera:" + RST)
            for l in qr.render(qr.encode(u)):
                print("  " + l)
    except ImportError:
        pass

def set_flag(on):
    """`web = true|false` in the profile's [deck], as text (comments survive)."""
    p = os.environ.get("PHOSPHOR_PROFILE", deckconf.CONF)
    text = open(p).read()
    line = "web     = %s" % ("true" if on else "false")
    pat = re.compile(r"^\s*web\s*=\s*(true|false)\s*$", re.M)
    new = pat.sub(line, text, count=1) if pat.search(text) else \
        re.sub(r"^\[deck\]\s*$", "[deck]\n" + line, text, count=1, flags=re.M)
    deckconf.tomllib.loads(new)                 # never write a profile that doesn't parse
    open(p + ".bak", "w").write(text)
    open(p, "w").write(new)

def token():
    r = zj("web", "--create-token")      # 0.45 refuses --token-name alongside it
    out = (r.stdout + r.stderr).strip()
    print(row(OK if r.returncode == 0 else BAD, "login token", "shown once, keep it somewhere safe"))
    for l in out.splitlines():
        print("    " + PH + l + RST)
    words = re.findall(r"[A-Za-z0-9_-]{16,}", out)
    if r.returncode == 0 and words:
        import clip
        if clip.send(words[-1].encode()) == 0:
            print("  " + DIM + "it's on the clipboard of every screen looking at the deck: paste it" + RST)
    print("  " + DIM + "revoke one: zellij web --revoke-token NAME · list: zellij web --list-tokens" + RST)
    return r.returncode

def publish(prof):
    r = ts("serve", "--bg", "--https=%d" % port(prof), LOCAL)
    ok = r.returncode == 0
    print(row(OK if ok else BAD, "tailscale serve", url(prof) if ok else (r.stderr.strip()[:60] or "failed"),
              note="tailnet only, not the internet" if ok else ""))
    return ok

def local_help(why):
    """Without the tailnet the web client still serves this machine: nothing to
    tunnel here, and other machines need an ssh server on this one."""
    me = "%s@%s" % (os.environ.get("USER") or "you", os.uname().nodename)
    print("  " + FG + "Open " + PH + LOCAL + RST + FG + " in a browser on this machine." + RST)
    print("  " + DIM + "From another machine: ssh -L 8082:127.0.0.1:8082 " + me +
          " (needs an ssh server here), then http://localhost:8082 there." + RST)
    print("  " + DIM + "Across your tailnet it isn't offered: " + why + RST)

def on(restart=True):
    prof, _ = deckconf.load()
    tail, why = usable(prof)
    set_flag(True)
    subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "gen"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if tail and not publish(prof):
        return 1
    if not tail:
        print(row(OK, "browser access", "this machine only", note="127.0.0.1, with a login token"))
    zj("web", "--start", "--daemonize")
    token()
    print()
    if tail:
        show_url(prof)
    else:
        local_help(why)
    print("  " + FG + "Paste the token there and pick the session \"" +
          ((prof or {}).get("deck") or {}).get("session", "deck") + "\"." + RST)
    if restart:
        print("  " + DIM + "The deck restarts so its session can be shared in the browser." + RST)
        if sys.stdin.isatty():
            try: input("  " + FG + "Copy the token first (it's on your clipboard too): Enter restarts " + RST)
            except (EOFError, KeyboardInterrupt): print()
        subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "restart"])
    return 0

def off():
    prof, _ = deckconf.load()
    import dlog
    # every step on its own: one that fails must not leave the others undone
    steps = [("tailscale serve off", lambda: ts("serve", "--https=%d" % port(prof), "off")),
             ("zellij web --stop", lambda: zj("web", "--stop")),
             ("clear the profile flag", lambda: set_flag(False)),
             ("phosphor gen", lambda: subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "gen"],
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))]
    for label, step in steps:
        try:
            step()
        except Exception as e:
            dlog.event("WEB", "off-step-failed", "%s: %s" % (label, e))
    st = live(deckconf.load()[0])
    print(row(BAD if st["published"] else OK, "tailnet address", "still published" if st["published"] else "unpublished"))
    print(row(BAD if st["server"] else OK, "web server", "still running" if st["server"] else "stopped"))
    print(row(BAD if st["flag"] else OK, "profile", "web = %s" % ("true" if st["flag"] else "false"),
              note="the watchdog won't start it again" if not st["flag"] else ""))
    return 1 if (st["published"] or st["server"] or st["flag"]) else 0

def status():
    prof, _ = deckconf.load()
    st = live(prof)
    dot = DIM + "·" + RST
    print(row(OK if st["published"] else dot, "tailnet address",
              url(prof) if st["published"] else "not published", note="tailnet only, not the internet"))
    print(row(OK if st["server"] else dot, "web server", "running on 127.0.0.1" if st["server"] else "stopped"))
    print(row(OK if st["flag"] else dot, "profile", "web = %s" % ("true" if st["flag"] else "false")))
    running = st["published"] or st["server"]
    if st["flag"] != running:
        print(row(WARN, "half on", "the profile and what runs disagree",
                  note="phosphor web on, or off, puts them straight"))
    tail, why = usable(prof)
    if st["published"]:
        print()
        show_url(prof)
        print("  " + DIM + "no token at hand? DECK tab, w, then t (or phosphor web token)" + RST)
    elif st["server"] and st["flag"]:
        print()
        local_help(why if not tail else "phosphor web off, then on, publishes it there")
        print("  " + DIM + "no token at hand? DECK tab, w, then t (or phosphor web token)" + RST)
    else:
        print("  " + FG + "Turn it on with " + PH + "phosphor web on" + RST +
              (DIM + "   (this machine only: " + why + ")" + RST if not tail else ""))
    return 0

def on_brain(args):
    """A viewer has no web server of its own (its zellij may not even have web
    support): the deck, and its tokens, live on the brain."""
    prof, _ = deckconf.load()
    loc = next((h for h in (prof or {}).get("hosts", []) if h.get("local")), None)
    if not loc or loc.get("role") == "brain":
        return None
    b = next((h for h in prof.get("hosts", []) if h.get("role") == "brain"), None)
    if not b:
        print(row(BAD, "browser access", "no brain in the profile")); return 1
    tgt = deckconf.target(b)
    print("  " + DIM + "the deck's web server lives on %s: asking it there" % b["name"] + RST)
    return subprocess.run(["ssh", "-t", tgt, "~/.local/bin/phosphor web " + " ".join(args)]).returncode

def main():
    r = on_brain(sys.argv[1:] or ["status"])
    if r is not None:
        return r
    cmd = (sys.argv[1:] or ["status"])[0]
    return {"on": on, "off": off, "status": status, "token": token}.get(cmd, status)()

if __name__ == "__main__":
    sys.exit(main() or 0)
