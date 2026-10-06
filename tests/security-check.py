#!/usr/bin/env python3
"""phosphor security: who else reaches a file (a 0700 folder on the way shuts
them out, a private group doesn't count), the profile's secrets, sshd settings
the way sshd itself reads them (sshd -T, else Include in order, first value
wins, Match left out), tunnel binds as ssh -G resolves them, funnels, and the
control sockets. All on made-up input: nothing here reads this machine.

    python3 tests/security-check.py
"""
import os, socket, stat, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import security as S

fails = []
def need(what, ok):
    if not ok: fails.append(what)

# ── exposure, on a made-up tree ───────────────────────────────
class St:
    def __init__(self, mode, uid=None, gid=12345):
        self.st_mode, self.st_uid, self.st_gid = mode, os.getuid() if uid is None else uid, gid

def tree(home_mode, file_mode):
    t = {"/": St(stat.S_IFDIR | 0o755), "/home": St(stat.S_IFDIR | 0o755),
         "/home/me": St(stat.S_IFDIR | home_mode), "/home/me/f": St(stat.S_IFREG | file_mode)}
    def ls(p):
        if p not in t: raise OSError(p)
        return t[p]
    return ls

shared = lambda gid: True
private = lambda gid: False
need("644 in a 755 home: every user reads it",
     S.exposure("/home/me/f", lstat=tree(0o755, 0o644), group_others=shared) == "every user")
need("644 in a 700 home: nobody",
     S.exposure("/home/me/f", lstat=tree(0o700, 0o644), group_others=shared) == "")
need("600: nobody", S.exposure("/home/me/f", lstat=tree(0o755, 0o600), group_others=shared) == "")
need("664 private group: nobody writes",
     S.exposure("/home/me/f", write=True, lstat=tree(0o755, 0o664), group_others=private) == "")
need("664 shared group: the group writes",
     S.exposure("/home/me/f", write=True, lstat=tree(0o750, 0o664), group_others=shared).startswith("group"))
need("666 in a 711 home: every user writes",
     S.exposure("/home/me/f", write=True, lstat=tree(0o711, 0o666), group_others=private) == "every user")
need("missing file: nobody", S.exposure("/home/me/nope", lstat=tree(0o755, 0o644)) == "")

# ── the profile's secrets ─────────────────────────────────────
need("no secrets", S.secrets_in({"deck": {}}) == [])
need("env: token isn't one", S.secrets_in({"push": {"token": "env:NTFY"}}) == [])
need("literal token is one", S.secrets_in({"push": {"token": "tk_x"}}) == ["[push] token"])
need("public topic is one", S.secrets_in({"push": {"topic": "deck-x"}}) == ["[push] topic (public ntfy.sh)"])
need("own server's topic isn't", S.secrets_in({"push": {"topic": "deck-x", "url": "http://relay:8080"}}) == [])
need("ci token", S.secrets_in({"ci": {"pipelines": [{"name": "web", "token": "ghp_x"},
                                                     {"name": "api", "token": "env:T"}]}}) == ["[ci] token of web"])

# ── sshd ──────────────────────────────────────────────────────
debian = ("@@F /etc/ssh/sshd_config\n"
          "Include /etc/ssh/sshd_config.d/*.conf\n"
          "PasswordAuthentication yes\n"
          "KbdInteractiveAuthentication no\nUsePAM yes\n"
          "Match User backup\n  PermitRootLogin yes\n"
          "@@F /etc/ssh/sshd_config.d/50-cloud.conf\nPasswordAuthentication no\n"
          "@@F /etc/ssh/sshd_config.d/10-x.conf\npermitrootlogin=no # inline\n")
s, src, unread = S.sshd_settings(debian)
need("files read", src == "files")
need("include wins over a later line", s["passwordauthentication"] == "no")
need("= and case work", s["permitrootlogin"] == "no")
need("Match block left out", s["permitrootlogin"] != "yes")
need("clean server: no findings", S.sshd_findings(s) == [])

s, _, _ = S.sshd_settings("@@F /etc/ssh/sshd_config\nUsePAM yes\n")
need("defaults: passwords on", any("passwords" in w for _, w, _ in S.sshd_findings(s)))

s, src, _ = S.sshd_settings("@@T\npermitrootlogin yes\npasswordauthentication yes\nstrictmodes no\nport 22\n")
need("sshd -T read", src == "sshd -T")
f = S.sshd_findings(s)
need("root with password is bad", any(l == S.BAD_ and "root" in w for l, w, _ in f))
need("strictmodes off warns", any("StrictModes" in w for _, w, _ in f))
need("root, keys only: a warning",
     any(l == S.WARN_ and "root" in w for l, w, _ in
         S.sshd_findings(dict(S.DEFAULTS, permitrootlogin="yes", passwordauthentication="no"))))
need("empty passwords bad", S.sshd_findings(dict(S.DEFAULTS, permitemptypasswords="yes"))[0][0] == S.BAD_)

need("no server here", S.sshd_settings("@@NONE\n")[1] == "")
rows = S.check_sshd("relay", "@@U /etc/ssh/sshd_config\n", 0, False)
need("unreadable: skipped, not a warning", rows[0][0] == S.SKIP_)
need("ssh never got there", S.check_sshd("relay", "ssh: connect timed out", 255, False)[0][0] == S.WARN_)
need("local, no server: fine", S.check_sshd("db-box", "@@NONE\n", 0, True)[0][0] == S.OK_)

# ── network ───────────────────────────────────────────────────
need("listeners parse", S.listeners("LISTEN 0 128 127.0.0.1:8082 0.0.0.0:*\nLISTEN 0 128 [::]:22 [::]:*\n")
     == [("127.0.0.1", "8082"), ("::", "22")])
need("loopback", S.loopback("127.0.0.1") and S.loopback("[::1]") and S.loopback("localhost"))
need("not loopback", not S.loopback("0.0.0.0") and not S.loopback("*") and not S.loopback("::"))
g = "gatewayports no\nlocalforward 33307 [127.0.0.1]:3306\nlocalforward [0.0.0.0]:4000 [127.0.0.1]:4000\n"
need("bare port is loopback, explicit bind kept",
     S.forward_binds(g) == [("127.0.0.1", "33307"), ("0.0.0.0", "4000")])
need("gatewayports opens a bare port",
     S.forward_binds("gatewayports yes\nlocalforward 33307 [127.0.0.1]:3306\n") == [("*", "33307")])
need("funnels", S.funnels('{"AllowFunnel": {"db-box.example.ts.net:8443": true, "x:443": false}}')
     == ["db-box.example.ts.net:8443"])
need("no funnel, bad json", S.funnels("") == [] and S.funnels("nope") == [])

# ── files and sockets, with a made-up exposure ────────────────
with tempfile.TemporaryDirectory() as d:
    conf = os.path.join(d, "phosphor"); os.makedirs(conf)
    prof = os.path.join(conf, "deck.toml")
    for f in (prof, prof + ".bak"):
        open(f, "w").write("x")
    ssh = os.path.join(d, "ssh"); os.makedirs(ssh)
    open(os.path.join(ssh, "id_ed25519"), "w").write("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    open(os.path.join(ssh, "id_ed25519.pub"), "w").write("ssh-ed25519 AAAA\n")
    readable = lambda p, write=False: "" if write else "every user"
    rows = S.check_files({"push": {"token": "tk"}}, prof, ssh, exposure=readable)
    need("readable profile with a token: bad, once", sum(1 for r in rows if r[0] == S.BAD_ and "deck.toml" in r[1]) == 1)
    need("readable private key: bad", any(r[0] == S.BAD_ and r[1].endswith("id_ed25519") for r in rows))
    need("the .pub is no private key", S.private_keys(ssh) == [os.path.join(ssh, "id_ed25519")])
    rows = S.check_files({}, prof, ssh, exposure=lambda p, write=False: "")
    need("all private: no findings", all(r[0] == S.OK_ for r in rows))
    rows = S.check_files({}, prof, ssh, exposure=lambda p, write=False: "every user" if write and p == conf else "")
    need("writable config folder: bad", any(r[0] == S.BAD_ and "picks what the deck runs" in r[2] for r in rows))

    sd = os.path.join(d, "sock"); os.makedirs(sd)
    sk = socket.socket(socket.AF_UNIX); sk.bind(os.path.join(sd, "s"))
    try:
        open_sock = lambda p, write=False: "every user" if p.endswith("/s") else ""
        need("connectable socket: bad", S.check_sockets([("x", sd, "y")], exposure=open_sock)[0][0] == S.BAD_)
        need("closed socket: fine", S.check_sockets([("x", sd, "y")], exposure=lambda p, write=False: "")[0][0] == S.OK_)
    finally:
        sk.close()

if fails:
    print("security-check FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("security-check ok")
