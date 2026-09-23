"""phosphor tunnel - keep the ssh tunnels you already defined up, all the time.

Your ~/.ssh/config stays the source of truth: a host there with LocalForward
lines (`LocalForward 33307 127.0.0.1:3306`) gets a systemd unit that runs
`ssh -N <host>`, so ssh opens exactly those forwards and reconnects when the
link drops. The profile only lists which hosts: [[tunnels]] host = "...".

Two things to know: the forwards listen on this machine's 127.0.0.1, so its
other users can reach them too; and this machine keeps a key that logs into
those hosts.

    phosphor tunnel              list them (on a terminal: pick one to toggle)
    phosphor tunnel on HOST      keep HOST's tunnels up
    phosphor tunnel off HOST     stop them and forget them
"""
import os, re, shutil, socket, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

UDIR = os.path.expanduser("~/.config/systemd/user")
WARN_TEXT = ("the forwards listen on this machine's 127.0.0.1: other users of this machine can reach them",
             "this machine keeps a key that logs into those hosts")

def ssh_config_forwards(path=None):
    """{host alias: [(local port, target, label)]} for Host blocks with
    LocalForward. A comment right above a LocalForward labels it."""
    path = os.path.expanduser(path or "~/.ssh/config")
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return {}
    out, cur, label = {}, [], ""
    for raw in lines:
        l = raw.strip()
        if l.startswith("#"):
            label = l.lstrip("#").strip()
            continue
        m = re.match(r"(\w+)\s*[= ]\s*(.*)", l)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k in ("host", "match"):
                # one entry per Host line: its first plain name (the others are aliases)
                cur = [n for n in v.split() if not any(c in n for c in "*?!")][:1] if k == "host" else []
            elif k == "localforward" and cur:
                p = v.split()
                if len(p) >= 2:
                    for n in cur:
                        out.setdefault(n, []).append((p[0].rsplit(":", 1)[-1], p[1], label))
        label = ""
    return out

def unit_name(host):
    return "tunnel-%s.service" % re.sub(r"[^A-Za-z0-9_.-]", "_", host)

UNIT = """[Unit]
Description=Phosphor tunnel - %(host)s (its LocalForward lines in the ssh config)
After=network-online.target

[Service]
Type=simple
# ssh opens exactly the forwards the ssh config gives this host. BatchMode:
# never wait on a password prompt nobody is there to answer.
ExecStart=%(ssh)s -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3%(cfg)s %(host)s
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""

def unit(t):
    cfg = (" -F %s" % os.path.expanduser(t["config"])) if t.get("config") else ""
    return UNIT % {"host": t["host"], "ssh": shutil.which("ssh") or "/usr/bin/ssh", "cfg": cfg}

def listening(port):
    try:
        socket.create_connection(("127.0.0.1", int(port)), timeout=0.5).close()
        return True
    except (OSError, ValueError):
        return False

def active(host):
    return subprocess.run(["systemctl", "--user", "is-active", unit_name(host)],
                          capture_output=True, text=True).stdout.strip() == "active"

def kept(prof):
    return [t for t in deckconf.tunnels(prof)]

def warn():
    for w in WARN_TEXT:
        print("  " + WARN + " " + AMB + w + RST)

# ── the profile, as text (comments survive) ─────────────────
def _profile():
    return os.environ.get("PHOSPHOR_PROFILE", deckconf.CONF)

def add_block(host):
    p = _profile(); text = open(p).read()
    new = text.rstrip("\n") + '\n\n[[tunnels]]\nhost = "%s"\n' % host
    deckconf.tomllib.loads(new)
    open(p + ".bak", "w").write(text); open(p, "w").write(new)

def remove_block(host):
    p = _profile(); lines = open(p).read().split("\n")
    for i, l in enumerate(lines):
        if l.strip() == "[[tunnels]]" and i + 1 < len(lines) and \
                re.match(r'\s*host\s*=\s*"%s"\s*$' % re.escape(host), lines[i + 1]):
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].lstrip().startswith("["):
                j += 1
            s = i - 1 if i > 0 and not lines[i - 1].strip() else i
            new = "\n".join(lines[:s] + lines[j:])
            deckconf.tomllib.loads(new)
            open(p + ".bak", "w").write("\n".join(lines)); open(p, "w").write(new)
            return True
    return False

def sysd(*a):
    return subprocess.run(["systemctl", "--user"] + list(a), capture_output=True, text=True)

def gen_quiet():
    subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "gen"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ── commands ─────────────────────────────────────────────────
def show():
    prof, _ = deckconf.load()
    fw, keep = ssh_config_forwards(), {t["host"] for t in kept(prof)}
    if not fw and not keep:
        print("  " + DIM + "no LocalForward lines in ~/.ssh/config: nothing to keep up" + RST); return 0
    for host in sorted(set(fw) | keep):
        state = ("up" if active(host) else "down") if host in keep else "off"
        print(row(OK if state == "up" else (BAD if state == "down" else DIM + "·" + RST), host, state))
        for local, target, label in fw.get(host, []):
            mark = (OK if listening(local) else BAD) if host in keep else " "
            print("      %s %s → %s%s" % (mark, PH + local + RST, target, DIM + ("  " + label if label else "") + RST))
    return 0

def on(host):
    fw = ssh_config_forwards()
    if host not in fw:
        print(row(BAD, host, "no LocalForward lines for it in ~/.ssh/config")); return 1
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", host, "true"],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        print(row(BAD, host, "ssh can't log in with a key", note=(r.stderr.strip().splitlines() or ["?"])[-1][:40]))
        print("  " + DIM + "a tunnel runs unattended: it needs key login (ssh-copy-id %s)" % host + RST)
        return 1
    warn()
    prof, _ = deckconf.load()
    if host not in {t["host"] for t in kept(prof)}:
        add_block(host)
    gen_quiet()
    sysd("daemon-reload")
    sysd("enable", "--now", unit_name(host))
    time.sleep(3)
    ok = [listening(p) for p, _, _ in fw[host]]
    print(row(OK if all(ok) else WARN, host, "%d/%d forwards listening" % (sum(ok), len(ok)),
              note="" if all(ok) else "journalctl --user -u " + unit_name(host)))
    return 0

def off(host):
    sysd("disable", "--now", unit_name(host))
    p = os.path.join(UDIR, unit_name(host))
    if os.path.exists(p): os.remove(p)
    sysd("daemon-reload")
    removed = remove_block(host)
    print(row(OK, host, "tunnels stopped" + (" and forgotten" if removed else "")))
    return 0

def interactive():
    from init import pick
    while True:
        print()
        show()
        prof, _ = deckconf.load()
        fw, on_ = ssh_config_forwards(), {t["host"] for t in kept(prof)}
        hosts = sorted(set(fw) | on_)
        if not hosts: return 0
        opts = ["%-24s %s" % (h, "turn off" if h in on_ else "keep up") for h in hosts] + ["done"]
        k = pick("toggle which?", opts, len(opts) - 1)
        if k == len(opts) - 1: return 0
        (off if hosts[k] in on_ else on)(hosts[k])

def main():
    a = sys.argv[1:]
    if a[:1] == ["on"] and len(a) > 1: return on(a[1])
    if a[:1] == ["off"] and len(a) > 1: return off(a[1])
    if not a and sys.stdin.isatty(): return interactive()
    return show()

if __name__ == "__main__":
    sys.exit(main() or 0)
