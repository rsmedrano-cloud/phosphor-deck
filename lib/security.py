"""phosphor security - how exposed the deck is, not whether it works (that's doctor).

The brain keeps ssh keys into the whole fleet, a profile that says what every
pane runs, and the session itself: whoever reaches one of those reaches
everything. This reads, and only reads:

  - the brain's own files: the profile (and its backups), ~/.ssh, the
    folders that decide what the deck runs;
  - every ssh server of the fleet, the brain's included: root and password
    logins, empty passwords, StrictModes;
  - the network: a tunnel forward or zellij's web server listening beyond
    127.0.0.1, anything published with tailscale funnel;
  - the control sockets: zellij's (attaching is a shell) and FLEET's ssh
    masters (riding one is a login on that host).

Each finding says what to run; nothing is changed here.

    phosphor security            the whole audit
    phosphor security --local    the brain only, no ssh to the fleet
"""
import concurrent.futures, fnmatch, glob, grp, json, os, pwd, re, shutil, stat, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

HOME = os.path.expanduser("~")
BAD_, WARN_, OK_, SKIP_ = "bad", "warn", "ok", "skip"
WEB_PORT = 8082          # zellij web's own port (web.LOCAL)


def tilde(p):
    return p.replace(HOME, "~", 1) if p.startswith(HOME) else p


# ── who else can get at a file ────────────────────────────────────────────

def _group_others(gid):
    """Does anyone besides me belong to this group? A private group (the
    usual one per user) makes its bits harmless."""
    me = os.getuid()
    try:
        g = grp.getgrgid(gid)
    except KeyError:
        return True
    names = set(g.gr_mem)
    try:
        names |= {u.pw_name for u in pwd.getpwall() if u.pw_gid == gid}
        names.discard(pwd.getpwuid(me).pw_name)
    except KeyError:
        pass
    return bool(names)


def exposure(path, write=False, lstat=os.stat, group_others=_group_others):
    """Who besides me can read (or write) path: "" for nobody, else "every
    user" or "group NAME". A folder on the way that others can't enter
    (a 0700 home) shuts them out, whatever the file's own bits say."""
    try:
        st = lstat(path)
    except OSError:
        return ""
    if st.st_uid != os.getuid():
        return "its owner (uid %d)" % st.st_uid
    o_bit, g_bit = (stat.S_IWOTH, stat.S_IWGRP) if write else (stat.S_IROTH, stat.S_IRGRP)
    o_reach = g_reach = True
    d = os.path.dirname(os.path.abspath(path))
    while True:
        try:
            m = lstat(d).st_mode
        except OSError:
            break
        o_reach = o_reach and bool(m & stat.S_IXOTH)
        g_reach = g_reach and bool(m & (stat.S_IXGRP | stat.S_IXOTH))
        if d == "/":
            break
        d = os.path.dirname(d)
    if st.st_mode & o_bit and o_reach:
        return "every user"
    if st.st_mode & g_bit and g_reach and group_others(st.st_gid):
        try:
            return "group " + grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            return "group %d" % st.st_gid
    return ""


# ── the profile's secrets ─────────────────────────────────────────────────

def secrets_in(prof):
    """Names of what the profile holds that works as a password: a literal
    token (not env:VAR), or an ntfy topic on the public server, where
    knowing the name is all it takes to read the notices."""
    out = []
    prof = prof or {}
    push = prof.get("push") or {}
    tok = str(push.get("token", "") or "")
    if tok and not tok.startswith("env:"):
        out.append("[push] token")
    url = str(push.get("url", "https://ntfy.sh") or "https://ntfy.sh").rstrip("/")
    if push.get("topic") and re.match(r"https?://ntfy\.sh$", url):
        out.append("[push] topic (public ntfy.sh)")
    for p in ((prof.get("ci") or {}).get("pipelines") or []):
        t = str(p.get("token", "") or "")
        if t and not t.startswith("env:"):
            out.append("[ci] token of %s" % (p.get("name") or p.get("repo") or "a pipeline"))
    return out


def private_keys(sshdir):
    """The private keys in ~/.ssh: files that start like one."""
    out = []
    for f in sorted(glob.glob(os.path.join(sshdir, "*"))):
        if f.endswith(".pub") or not os.path.isfile(f):
            continue
        try:
            with open(f, "rb") as fh:
                head = fh.read(64)
        except OSError:
            continue
        if b"PRIVATE KEY" in head:
            out.append(f)
    return out


def check_files(prof, profile_path, sshdir=None, exposure=exposure):
    """[(level, label, value, fix)] for the brain's own files."""
    sshdir = sshdir or os.path.join(HOME, ".ssh")
    out = []
    secrets = secrets_in(prof)
    conf = os.path.dirname(profile_path)
    copies = [profile_path] + sorted(glob.glob(profile_path + ".bak*"))
    for f in copies:
        if not os.path.exists(f):
            continue
        name = tilde(f)
        w = exposure(f, write=True)
        r = exposure(f)
        if w:
            out.append((BAD_, name, "writable by " + w + ": it says what every pane runs",
                        "chmod 600 " + name))
        elif r and secrets:
            out.append((BAD_, name, "readable by %s, and it holds %s" % (r, ", ".join(secrets)),
                        "chmod 600 %s*" % tilde(profile_path)))
            break                  # the backups say the same; one fix covers them
        elif f == profile_path:
            out.append((OK_, name, ("readable by %s, no secret in it" % r) if r else "only yours", ""))
    for d in (conf, os.path.join(conf, "tabs.d"), os.path.join(conf, "apps.toml"),
              deckconf.data_dir(), deckconf.cache_dir()):
        w = exposure(d, write=True)
        if w:
            out.append((BAD_, tilde(d), "writable by %s: whoever writes there picks what the deck runs" % w,
                        "chmod go-w " + tilde(d)))
    if os.path.isdir(sshdir):
        bad = False
        w = exposure(sshdir, write=True)
        if w:
            out.append((BAD_, tilde(sshdir), "writable by " + w, "chmod 700 " + tilde(sshdir))); bad = True
        for k in private_keys(sshdir):
            r = exposure(k)
            if r:
                out.append((BAD_, tilde(k), "a private key readable by " + r, "chmod 600 " + tilde(k)))
                bad = True
        for f in ("authorized_keys", "config"):
            p = os.path.join(sshdir, f)
            w = exposure(p, write=True)
            if w:
                out.append((BAD_, tilde(p), "writable by " + w, "chmod 600 " + tilde(p))); bad = True
        if not bad:
            out.append((OK_, tilde(sshdir), "%d private key(s), only yours" % len(private_keys(sshdir)), ""))
    return out


# ── ssh servers ───────────────────────────────────────────────────────────

# sshd -T is the truth, but needs root; without it, the files (Include
# followed, first value wins, Match blocks left out) say nearly the same.
SSHD_SCRIPT = r"""
PATH="$PATH:/usr/sbin:/sbin"
if command -v sshd >/dev/null 2>&1; then
  if out=$(sshd -T 2>/dev/null) || { sudo -n true 2>/dev/null && out=$(sudo -n sshd -T 2>/dev/null); }; then
    echo "@@T"; printf '%s\n' "$out"; exit 0
  fi
fi
found=
for f in /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*; do
  [ -f "$f" ] || continue
  found=1
  if [ -r "$f" ]; then echo "@@F $f"; cat "$f"; echo; else echo "@@U $f"; fi
done
[ -n "$found" ] || echo "@@NONE"
"""

WANT = ("permitrootlogin", "passwordauthentication", "kbdinteractiveauthentication",
        "challengeresponseauthentication", "permitemptypasswords", "strictmodes", "usepam")
DEFAULTS = {"permitrootlogin": "prohibit-password", "passwordauthentication": "yes",
            "kbdinteractiveauthentication": "yes", "permitemptypasswords": "no",
            "strictmodes": "yes", "usepam": "no"}


def sshd_settings(out):
    """(settings, source, unreadable files) from SSHD_SCRIPT's answer.
    source: "sshd -T", "files", or "" when there's no ssh server."""
    files, unread, tee, cur = {}, [], None, None
    for line in out.splitlines():
        if line == "@@T":
            tee = {}
            continue
        if tee is not None:
            p = line.split(None, 1)
            if len(p) == 2:
                tee.setdefault(p[0].lower(), p[1].strip().lower())
            continue
        if line.startswith("@@F "):
            cur = line[4:].strip(); files[cur] = []; continue
        if line.startswith("@@U "):
            unread.append(line[4:].strip()); cur = None; continue
        if line == "@@NONE":
            return {}, "", []
        if cur is not None:
            files[cur].append(line)
    if tee is not None:
        s = dict(DEFAULTS); s.update({k: v for k, v in tee.items() if k in WANT})
        return s, "sshd -T", []
    if not files:
        return {}, "", unread
    got = {}

    def walk(path, depth=0):
        for raw in files.get(path, []):
            l = raw.split("#", 1)[0].strip()
            if not l:
                continue
            m = re.match(r"(\S+?)\s*(?:=\s*|\s+)(.*)", l)
            if not m:
                continue
            k, v = m.group(1).lower(), m.group(2).strip()
            if k == "match":
                return                 # a Match block runs to the file's end
            if k == "include" and depth < 8:
                for pat in v.split():
                    pat = pat if pat.startswith("/") else "/etc/ssh/" + pat
                    for f in sorted(x for x in files if fnmatch.fnmatch(x, pat)):
                        walk(f, depth + 1)
                continue
            if k in WANT:
                got.setdefault(k, v.split()[0].lower() if v else "")

    walk("/etc/ssh/sshd_config")
    if "kbdinteractiveauthentication" not in got and "challengeresponseauthentication" in got:
        got["kbdinteractiveauthentication"] = got["challengeresponseauthentication"]
    s = dict(DEFAULTS); s.update(got)
    return s, "files", unread


def sshd_findings(s):
    """[(level, what, fix)] for one server's settings."""
    if not s:
        return []
    out = []
    pw = s.get("passwordauthentication") == "yes" or \
        (s.get("kbdinteractiveauthentication") == "yes" and s.get("usepam") == "yes")
    if s.get("permitemptypasswords") == "yes":
        out.append((BAD_, "empty passwords log in", "PermitEmptyPasswords no"))
    root = s.get("permitrootlogin", "")
    if root == "yes":
        out.append((BAD_, "root logs in with a password", "PermitRootLogin prohibit-password") if pw else
                   (WARN_, "root can log in (keys only today)", "PermitRootLogin prohibit-password"))
    if pw:
        out.append((WARN_, "passwords are accepted", "PasswordAuthentication no, once your key works"))
    if s.get("strictmodes") == "no":
        out.append((WARN_, "StrictModes is off: a writable ~/.ssh still counts",
                    "StrictModes yes"))
    return out


def check_sshd(name, out, rc, local):
    """[(level, label, value, fix)] for one host."""
    if rc == -1 or (rc == 255 and not local):
        return [(WARN_, name, "unreachable: " + (out.strip().splitlines() or ["?"])[-1][:40],
                 "ssh %s has to work first (phosphor doctor)" % name)]
    s, source, unread = sshd_settings(out)
    if not source:
        if unread:
            return [(SKIP_, name, "only root reads its sshd config: not checked",
                     "sudo sshd -T there shows it")]
        if local:
            return [(OK_, name, "no ssh server here", "")]
        return [(SKIP_, name, "no sshd config found: not checked", "")]
    rows = []
    for lvl, what, fix in sshd_findings(s):
        rows.append((lvl, name, what, "in its sshd_config: " + fix))
    note = "" if source == "sshd -T" else " (read from the files%s)" % (
        ", %d unreadable" % len(unread) if unread else "")
    if not rows:
        rows.append((OK_, name, "keys only, root without a password" + note, ""))
    elif note:
        rows[-1] = rows[-1][:2] + (rows[-1][2] + note,) + rows[-1][3:]
    return rows


# ── the network ───────────────────────────────────────────────────────────

def listeners(ss_out):
    """[(address, port)] from `ss -ltnH`."""
    out = []
    for l in ss_out.splitlines():
        p = l.split()
        if len(p) < 4:
            continue
        addr, _, port = p[3].rpartition(":")
        out.append((addr.split("%")[0].strip("[]"), port))
    return out


def loopback(addr):
    a = addr.strip("[]").lower()
    return a in ("localhost", "::1") or a.startswith("127.")


def forward_binds(ssh_g):
    """[(bind address, port)] of every localforward in `ssh -G HOST`'s answer:
    a bare port listens on 127.0.0.1, unless gatewayports opens it to all."""
    gw = "no"
    fw = []
    for l in ssh_g.splitlines():
        p = l.split()
        if len(p) >= 2 and p[0] == "gatewayports":
            gw = p[1]
        elif len(p) >= 3 and p[0] == "localforward":
            m = re.match(r"\[(.*)\]:(\d+)$", p[1])
            fw.append((m.group(1), m.group(2)) if m else (None, p[1]))
    return [(b if b is not None else ("*" if gw == "yes" else "127.0.0.1"), port) for b, port in fw]


def funnels(serve_json):
    """The host:ports tailscale funnel puts on the internet."""
    try:
        d = json.loads(serve_json or "{}")
    except ValueError:
        return []
    return sorted(k for k, v in (d.get("AllowFunnel") or {}).items() if v)


def sh(argv, t=10):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=t)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def check_network(prof):
    out = []
    rc, ss_out = sh(["ss", "-ltnH"])
    live = listeners(ss_out) if rc == 0 else []
    for t in (prof or {}).get("tunnels", []) or []:
        h = t.get("host", "?")
        argv = ["ssh"] + (["-F", os.path.expanduser(t["config"])] if t.get("config") else []) + ["-G", h]
        _, g = sh(argv)
        wide = [(b, p) for b, p in forward_binds(g) if not loopback(b)]
        wide += [(a, p) for a, p in live if not loopback(a) and
                 any(p == fp for _, fp in forward_binds(g)) and (a, p) not in wide]
        if wide:
            out.append((BAD_, "tunnel " + h, "forwards beyond this machine: " +
                        ", ".join("%s:%s" % (b, p) for b, p in wide),
                        "LocalForward 127.0.0.1:PORT ... (and no GatewayPorts) in ~/.ssh/config"))
        else:
            out.append((OK_, "tunnel " + h, "127.0.0.1 only", ""))
    web_on = bool(((prof or {}).get("deck") or {}).get("web", False))
    web = [(a, p) for a, p in live if p == str(WEB_PORT)]
    wide = [a for a, _ in web if not loopback(a)]
    if wide:
        out.append((BAD_, "zellij web", "listens on %s:%d, not just 127.0.0.1" % (wide[0], WEB_PORT),
                    "phosphor web off; check web_server_ip in zellij's config.kdl"))
    elif web and not web_on:
        out.append((WARN_, "zellij web", "running, though web is off in the profile", "phosphor web off"))
    elif web:
        out.append((OK_, "zellij web", "127.0.0.1 only", ""))
    if shutil.which("tailscale"):
        _, j = sh(["tailscale", "serve", "status", "--json"])
        port = int(((prof or {}).get("deck") or {}).get("web_port", 8443))
        for hp in funnels(j):
            if hp.endswith(":%d" % port):
                out.append((BAD_, "tailscale funnel", "the deck is on the internet: " + hp,
                            "tailscale funnel --https=%d off" % port))
            else:
                out.append((WARN_, "tailscale funnel", "on the internet from this brain: " + hp,
                            "tailscale funnel status (yours on purpose? then fine)"))
        if not funnels(j):
            out.append((OK_, "tailscale funnel", "nothing on the internet", ""))
    return out


# ── control sockets ───────────────────────────────────────────────────────

def socket_dirs():
    rt = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return [("zellij sessions", d, "attaching to one is a shell")
            for d in (os.path.join(rt, "zellij"), "/tmp/zellij-%d" % os.getuid()) if os.path.isdir(d)] + \
           [("FLEET's ssh masters", os.path.join(deckconf.cache_dir(), "ssh"),
             "riding one is a login on that host")]


def check_sockets(dirs=None, exposure=exposure):
    out = []
    for label, d, why in (socket_dirs() if dirs is None else dirs):
        if not os.path.isdir(d):
            continue
        socks = []
        for root, _, names in os.walk(d):
            for n in names:
                p = os.path.join(root, n)
                try:
                    if stat.S_ISSOCK(os.lstat(p).st_mode) and exposure(p, write=True):
                        socks.append(p)
                except OSError:
                    pass
        w = exposure(d, write=True)
        if socks:
            out.append((BAD_, label, "%d socket(s) others can connect to: %s" % (len(socks), why),
                        "chmod 700 " + tilde(d)))
        elif w:
            out.append((BAD_, label, "its folder is writable by " + w, "chmod 700 " + tilde(d)))
        else:
            out.append((OK_, label, "only yours: " + tilde(d), ""))
    return out


# ── the whole audit ───────────────────────────────────────────────────────

SYM = {BAD_: BAD, WARN_: WARN, OK_: OK, SKIP_: MUTE + "·" + RST}


def show(title, rows, w, fixes):
    print("\n" + rule(title, w))
    for lvl, label, value, fix in rows:
        print(row(SYM[lvl], label, value, w))
        if fix and lvl != OK_:
            print(" " * 31 + DIM + "→ " + fix + RST)
        if lvl in (BAD_, WARN_):
            fixes.append(lvl)


def run(prof, profile_path, local_only=False):
    w = width()
    fixes = []
    print()
    print(BLOOM + "  PHOSPHOR DECK · security" + RST)
    print(DIM + "  the brain holds keys to every machine: how far does it reach, and who else does" + RST)
    show("this brain's files", check_files(prof, profile_path), w, fixes)
    demo = bool(((prof or {}).get("deck") or {}).get("demo", False))
    hosts = [] if demo else deckconf.fleet_hosts(prof)
    if local_only:
        hosts = [(n, t) for n, t in hosts if t is None]
    if not any(t is None for _, t in hosts):
        hosts = [(os.uname().nodename, None)] + hosts
    import containers
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda nt: containers.run(nt[1], SSHD_SCRIPT, timeout=25), hosts))
    rows = []
    for (name, target), (rc, out) in zip(hosts, res):
        rows += check_sshd(name, out, rc, target is None)
    show("ssh servers", rows, w, fixes)
    if demo:
        print("      " + DIM + "the demo's machines aren't real: only this one is checked" + RST)
    show("network", check_network(prof), w, fixes)
    show("control sockets", check_sockets(), w, fixes)
    print("\n" + rule("summary", w))
    bad, warn = fixes.count(BAD_), fixes.count(WARN_)
    if not bad and not warn:
        print("  " + OK + " " + PH + "nothing exposed that this checks" + RST)
    else:
        print("  %s %s" % (BAD if bad else WARN,
              (RED if bad else AMB) + "%d to fix, %d worth a look: each says how above" % (bad, warn) + RST))
    print("  " + DIM + "it reads only; the fleet's keys: narrow them with from= in authorized_keys (phosphor help privacy)" + RST)
    print()
    return 2 if bad else (1 if warn else 0)


def main():
    prof, path = deckconf.load()
    return run(prof, path or deckconf.path(), local_only="--local" in sys.argv)


if __name__ == "__main__":
    sys.exit(main() or 0)
