#!/usr/bin/env python3
"""phosphor solaros: the switch, pairing (nothing written without the
brain's Enter), the "open X next" hint and its whitelist, the panel key's
session, and the SolarOS app itself under a fake solaros module.

    python3 tests/solaros-check.py

No zellij: every deck lookup points at a session that isn't there, in a
runtime dir of its own, so nothing here can reach a live deck.
"""
import base64, fcntl, json, os, pty, select, signal, struct, subprocess, sys, tempfile
import termios, threading, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
sys.path.insert(0, LIB)
fails = []
def need(what, ok):
    if not ok: fails.append(what)
    return ok

home = tempfile.mkdtemp()
run_dir = tempfile.mkdtemp()
os.environ.update(HOME=home, XDG_RUNTIME_DIR=run_dir, ZELLIJ_SESSION_NAME="solaros-check-none")
os.environ.pop("ZELLIJ", None)
for v in ("PHOSPHOR_DATA", "PHOSPHOR_CACHE", "PHOSPHOR_NOTES"):
    os.environ.pop(v, None)                  # as check.sh does: the temp HOME, not yours
for d in (".config/phosphor", ".cache/phosphor", ".local/share/phosphor", ".ssh"):
    os.makedirs(os.path.join(home, d))
PROFILE = os.path.join(home, ".config/phosphor/deck.toml")
open(PROFILE, "w").write('''# my deck
[deck]
session = "solaros-check-none"

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name  = "AI"
panes = [ { cmd = "bash" } ]

[[tabs]]
name  = "NOTES"
panes = [ { cmd = "phosphor notes" } ]
''')

import deckconf, glance, solaros, mirror, profcheck
mirror.panes = lambda sess: []             # never ask a zellij from here
prof = deckconf.load()[0]

# ── the switch: profile, unit, gen ─────────────────────────────
need("nothing served at first", solaros.serve_mode(prof) is None)
solaros.set_serve("lan")
text = open(PROFILE).read()
prof = deckconf.load()[0]
need("on: [glance] serve = \"lan\" in the profile, comments kept",
     solaros.serve_mode(prof) == "lan" and text.startswith("# my deck") and text.count("[glance]") == 1)
solaros.set_serve("lan")
need("on twice: still one line", open(PROFILE).read().count("serve =") == 1)
u = solaros.unit(prof)
need("the unit serves glance on the LAN and comes back",
     "glance --serve --lan --port 8484" in u and "Restart=always" in u and "WantedBy=default.target" in u)
import gen
need("gen writes the same unit", gen.units(gen.Ctx(prof)).get(solaros.UNIT) == u)
need("profcheck takes [glance]", not [e for e in profcheck.check(prof) if "glance" in str(e)]
     if hasattr(profcheck, "check") else True)
solaros.set_serve(None)
prof = deckconf.load()[0]
need("off: serve = false, nothing served", solaros.serve_mode(prof) is None and "serve = false" in open(PROFILE).read())
need("gen: no unit when off", solaros.UNIT not in gen.units(gen.Ctx(prof)))
solaros.set_serve("lan")
prof = deckconf.load()[0]

# ── pairing ───────────────────────────────────────────────────
import hashlib, shutil, struct as _st
def make_key(comment):
    """An ed25519 public key line, in ssh's wire format (no ssh-keygen in CI)."""
    wire = b"".join(_st.pack(">I", len(x)) + x for x in (b"ssh-ed25519", os.urandom(32)))
    return "ssh-ed25519 %s %s" % (base64.b64encode(wire).decode(), comment)
kd = tempfile.mkdtemp()
panel_key = make_key("panel")
fp_real = "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(panel_key.split()[1])).digest()).decode().rstrip("=")
need("the fingerprint: sha256 of the key, base64 unpadded", solaros.fingerprint(panel_key) == fp_real)
if shutil.which("ssh-keygen"):
    open(os.path.join(kd, "k.pub"), "w").write(panel_key + "\n")
    out = subprocess.run(["ssh-keygen", "-l", "-f", os.path.join(kd, "k.pub")], capture_output=True, text=True).stdout.split()
    need("the fingerprint is ssh-keygen's", out[1:2] == [fp_real])
need("junk has no fingerprint", solaros.fingerprint("ssh-rsa not!base64") is None and solaros.fingerprint("hello") is None)
other = "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519" + b"x" * 36).decode() + " laptop"
AK = os.path.join(home, ".ssh/authorized_keys")
open(AK, "w").write(other + "\n" + 'command="phosphor glance",no-port-forwarding ' + panel_key + "\n")
before = open(AK).read()
need("no window: closed, nothing written", solaros.offer(panel_key)["state"] == "closed" and open(AK).read() == before)
need("not a key: bad", solaros.offer("rm -rf /")["state"] == "bad" and solaros.offer(None)["state"] == "bad")
need("a huge body: bad", solaros.offer("ssh-rsa " + "A" * 5000)["state"] == "bad")
solaros.write_private(solaros.data("pair.json"), json.dumps({"until": time.time() + 60}))
a = solaros.offer(panel_key, "192.0.2.7")
need("window open: pending, with the fingerprint, still nothing written",
     a == {"state": "pending", "fingerprint": fp_real} and open(AK).read() == before)
need("the pending key waits for the brain", json.load(open(solaros.data("pending.json")))["ip"] == "192.0.2.7")

# pair(): the brain's side, with a panel that sends its key meanwhile
solaros.active = lambda: True
def answer(ans):
    import builtins
    builtins.input = lambda prompt="": ans
def panel_sends():
    time.sleep(0.8); solaros.offer(panel_key, "192.0.2.7")
answer("n")
threading.Thread(target=panel_sends).start()
need("pair: n refuses, nothing written", solaros.pair(wait=10) == 1 and open(AK).read() == before)
need("pair: the window closes either way", not solaros.window_open())
answer("")
threading.Thread(target=panel_sends).start()
need("pair: Enter lets it in", solaros.pair(wait=10) == 0)
lines = open(AK).read().splitlines()
mine = [l for l in lines if solaros.MARK in l]
need("authorized_keys: the old hand-made line goes, the laptop stays, one forced line",
     len(lines) == 2 and lines[0] == other and len(mine) == 1)
need("the forced line: our session, restrict, a pty, the panel's key",
     mine and mine[0].startswith('command="') and "solaros session" in mine[0]
     and ",restrict,pty " in mine[0] and panel_key.split()[1] in mine[0])
need("authorized_keys stays 0600, the old one kept",
     os.stat(AK).st_mode & 0o777 == 0o600 and open(AK + ".bak.solaros").read() == before)
need("paired now: the server says so", solaros.offer(panel_key)["state"] == "paired")
need("status lists it", [fp for fp, _ in solaros.paired()] == [fp_real])
if shutil.which("ssh-keygen") and subprocess.run(["ssh-keygen", "-l", "-f", AK], capture_output=True).returncode != 0:
    need("ssh-keygen reads the new authorized_keys", False)
solaros.forget()
need("forget: only the panel's line goes", open(AK).read().splitlines() == [other])
solaros.authorize(panel_key)

import ui
need("getkey: two keys in one read come back one each (typeahead)",
     ui._first_key("\x1b[B\x1b[B", False, False) == ("\x1b[B", 3) and ui._first_key("\x1b\x1b", False, False) == ("\x1b", 1))

# ── what the panel can open ───────────────────────────────────
ids = [i for i, _ in solaros.entries(prof)]
need("the menu: glance, the deck's tabs, notes, a note, fleet",
     ids == ["glance", "tab:AI", "tab:NOTES", "notes", "note", "fleet"])
mirror.panes = lambda sess: [{"tab_name": "AI ●2"}, {"tab_name": "AI"}, {"tab_name": "SHOP"}]
need("a live deck's tabs win (a workspace opened since), without unread marks",
     [i for i, _ in solaros.entries(prof)][1:3] == ["tab:AI", "tab:SHOP"])
mirror.panes = lambda sess: []
need("open: anything off the menu is refused", solaros.want("bash")["ok"] is False
     and solaros.want("tab:rm -rf")["ok"] is False and not os.path.exists(solaros.data("intent.json")))
need("open: an entry is taken once", solaros.want("tab:AI", prof)["ok"] and solaros.take_intent() == "tab:AI"
     and solaros.take_intent() is None)
solaros.write_private(solaros.data("intent.json"), json.dumps({"open": "notes", "t": time.time() - 120}))
need("open: a stale hint is dropped", solaros.take_intent() is None)

# ── the HTTP side ─────────────────────────────────────────────
import send
send.lan_ip = lambda: "127.0.0.1"
httpd, url_, where = glance.bind(0, lan=True)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % httpd.server_port
secret = glance.token()
def req(path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=5) as f:
            return f.status, json.loads(f.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
need("POST without the token: 401", req("/open", {"open": "glance"})[0] == 401)
need("POST elsewhere: 404", req("/run?token=" + secret, {})[0] == 404)
need("POST not JSON: 400", req("/open?token=" + secret, raw=b"open=glance")[0] == 400)
code, ans = req("/menu?token=" + secret)
need("GET /menu: the entries and where ssh goes",
     code == 200 and ans["entries"][0] == {"id": "glance", "label": "glance"}
     and ans["ssh"].endswith("@127.0.0.1"))
need("POST /open: on the menu", req("/open?token=" + secret, {"open": "fleet"}) == (200, {"ok": True}))
need("POST /pair: a paired key", req("/pair?token=" + secret, {"key": panel_key}) == (200, {"state": "paired"}))
os.remove(solaros.data("intent.json"))

# ── the session the panel's key runs (a pty: the panel's terminal) ──
ENV = dict(os.environ, TERM="xterm-mono")
class Pty:
    def __init__(self, args, env, rows=17, cols=60):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execve(sys.executable, [sys.executable, os.path.join(ROOT, "phosphor")] + args, env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.out = b""
    def pump(self, t):
        end = time.time() + t
        while time.time() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                try: self.out += os.read(self.fd, 65536)
                except OSError: return
    def wait(self, s, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if s.encode() in self.out: return True
            self.pump(0.2)
        return False
    def type(self, s):
        os.write(self.fd, s.encode())
    def done(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.1)
            pid, st = os.waitpid(self.pid, os.WNOHANG)
            if pid: return os.waitstatus_to_exitcode(st)
        os.kill(self.pid, signal.SIGKILL); os.waitpid(self.pid, 0)
        return None

s = Pty(["solaros", "session"], dict(ENV, SSH_ORIGINAL_COMMAND="bash -i"))
need("session: a command off the menu shows the menu instead", s.wait("write a note") and s.wait("fleet"))
need("session: no color on xterm-mono", b"\x1b[38;2" not in s.out)
s.type("\x1b")
need("session: Esc on the menu ends it", s.done() == 0)

# write a note from the panel: the 5th entry, kind note, no project here
s = Pty(["solaros", "session"], ENV)
s.wait("write a note")
s.type("5"); s.wait("what kind")
s.type("\r"); s.wait("text, Enter saves")
s.type("hello from the panel\r"); s.wait("saved", 10)
s.type("\x1b")
need("session: a note written from the panel", s.done() == 0 and
     "hello from the panel" in open(os.path.join(home, ".local/share/phosphor/notes.md")).read())

# the hint: the session opens fleet first, then its menu
json.dump({"t": 9999999999, "hosts": {"box": {"ok": True, "mnt": [], "UPD": "4|1", "REBOOT": "1"}}},
          open(os.path.join(home, ".cache/phosphor/fleet.json"), "w"))
solaros.want("fleet", prof)
s = Pty(["solaros", "session"], ENV)
need("session: the hint opens fleet, with what it flags",
     s.wait("fleet: a machine") and s.wait("4 updates (1 security), reboot pending"))
s.type("\r"); s.wait("upgrade")
s.type("\x1b"); s.wait("fleet: a machine")
s.type("\x1b"); s.wait("write a note")
s.type("\x1b")
need("session: Esc goes back up and out, nothing upgraded", s.done() == 0 and b"Enter runs it" not in s.out)
need("session: the hint was used once", not os.path.exists(solaros.data("intent.json")))

r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "solaros", "session"],
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, env=ENV, timeout=20)
need("session: no terminal, no menu", r.returncode == 2)

# ── the app, under a fake solaros module ──────────────────────
code = urllib.request.urlopen(base + "/solaros.py?token=" + secret, timeout=5).read()
need("the app comes with its URL and token in", ('URL = "%s"' % url_).encode() in code)
fake = tempfile.mkdtemp()
open(os.path.join(fake, "phosphor.py"), "wb").write(code)
open(os.path.join(fake, "solaros.py"), "w").write(r'''
import json, os, subprocess, sys, time as _t, urllib.request, urllib.error
LOG, KEYS, _n, _f = os.environ["FAKE_LOG"], json.loads(os.environ["FAKE_KEYS"]), [0], []
KEYFILE, STORE = os.environ["FAKE_KEYFILE"], os.environ["FAKE_STORE"]
_bye = [False]
def _log(o): open(LOG, "a").write(json.dumps(o) + "\n")
def write(t): _log({"write": t})
def should_exit(): return _bye[0] or _n[0] > len(KEYS)
def _req(method, url, body=None, headers=None, timeout_ms=10000, max_bytes=65536):
    r = urllib.request.Request(url, data=body.encode() if isinstance(body, str) else body,
                               headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout_ms / 1000) as f:
            code, b = f.status, f.read()
    except urllib.error.HTTPError as e:
        code, b = e.code, e.read()
    except OSError:
        raise OSError("ESP_ERR_HTTP_CONNECT")
    return {"status_code": code, "body": b[:max_bytes], "truncated": len(b) > max_bytes}
class http:
    get = staticmethod(lambda url, headers=None, t=10000, m=65536, f=True: _req("GET", url, None, headers, t, m))
    post = staticmethod(lambda url, body=None, headers=None, t=10000, m=65536, f=True: _req("POST", url, body, headers, t, m))
class ssh_keys:
    default_exists = staticmethod(lambda: os.path.exists(KEYFILE))
    public_key = staticmethod(lambda: open(KEYFILE).read().strip())
    @staticmethod
    def generate(bits=2048, overwrite=False):
        _log({"generate": True}); open(KEYFILE, "w").write(os.environ["FAKE_PUB"])
class apps:
    @staticmethod
    def launch(name, args=[]):
        _log({"launch": [name, list(args)]}); _bye[0] = True
class storage:
    exists = staticmethod(lambda p: os.path.exists(STORE + p))
    read_file = staticmethod(lambda p, m=65536: open(STORE + p, "rb").read()[:m])
    @staticmethod
    def write_file(p, data, append=False):
        open(STORE + p, "ab" if append else "wb").write(data.encode() if isinstance(data, str) else data)
    makedirs = staticmethod(lambda p, exist_ok=True: os.makedirs(STORE + p, exist_ok=exist_ok))
    remove = staticmethod(lambda p: os.remove(STORE + p))
    @staticmethod
    def rename(a, b):
        if os.path.exists(STORE + b):
            raise OSError("EEXIST")         # FAT: no rename over a file
        os.rename(STORE + a, STORE + b)
class tui:
    NORMAL, BOLD, INVERSE, KEY_UP, KEY_DOWN, KEY_ESCAPE = 0, 1, 2, 0x101, 0x102, 27
    size = staticmethod(lambda: (17, 60))
    clear = staticmethod(lambda: _f.clear())
    @staticmethod
    def addstr(r, c, t, a=0):
        _f[:] = [x for x in _f if x[0] != r] + [[r, t, a]]
    refresh = staticmethod(lambda: _log({"frame": sorted(_f)}))
    @staticmethod
    def getch(ms):
        k = KEYS[_n[0]] if _n[0] < len(KEYS) else None
        _n[0] += 1
        if k == "brain-enter":          # the brain's Enter in phosphor solaros pair
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            subprocess.run([sys.executable, "-c", "import sys, json; sys.path.insert(0, %r); import solaros as s; "
                            "s.authorize(json.load(open(s.data('pending.json')))['key'])" % os.environ["FAKE_LIB"]],
                           env=env, check=True)
            return None
        return k
''')
STORE = tempfile.mkdtemp()
def app(keys, keyfile, store=None):
    log = os.path.join(fake, "log.jsonl"); open(log, "w").close()
    r = subprocess.run([sys.executable, os.path.join(fake, "phosphor.py")], capture_output=True, text=True,
                       timeout=60, cwd=fake,
                       env=dict(os.environ, PYTHONPATH=fake, FAKE_LOG=log, FAKE_KEYS=json.dumps(keys),
                                FAKE_KEYFILE=keyfile, FAKE_STORE=store or STORE, FAKE_PUB=new_key, FAKE_LIB=LIB))
    need("the app runs (%s)" % r.stderr.strip()[-300:], r.returncode == 0)
    return [json.loads(l) for l in open(log)]
def texts(ev):
    return [t for e in ev for _, t, _ in e.get("frame", [])]
def last_frame(ev):
    fr = [e["frame"] for e in ev if "frame" in e and e["frame"]]
    return [t for _, t, _ in fr[-1]] if fr else []
UP, DOWN = 0x101, 0x102
new_key = make_key("panel2")
nokey = os.path.join(tempfile.mkdtemp(), "id.pub")

# a panel with no key yet: the menu, the glance, and "pair first"
ev = app([13, 27, ord("q")], nokey)
t = texts(ev)
need("app: the menu shows the light and the deck's entries",
     any("PHOSPHOR" in x for x in t) and any("AI" in x for x in t) and any("write a note" in x for x in t))
need("app: unpaired, it offers pairing and marks ssh entries", any("pair with the brain" in x for x in t)
     and any("(pair first)" in x for x in t))
need("app: Enter on glance shows the glance", any("Enter reads again" in x for x in t))
need("app: no key is made just by looking", not any("generate" in e for e in ev) and not os.path.exists(nokey))
need("app: nothing wider than the screen", all(len(x) <= 60 for x in t))
need("app: nothing launched", not any("launch" in e for e in ev))
need("app: the first run adds phosphor to the shell, and says so",
     open(STORE + "/.shell/alias").read() == "phosphor python /phosphor.py\n"
     and any("type phosphor in the SolarOS shell" in x for x in t))
need("app: nothing to update when the brain's build is this one",
     not os.path.exists(STORE + "/phosphor.py") and not any("updating" in x for x in t))

# pairing from the panel: the window open on the brain, its Enter there
solaros.write_private(solaros.data("pair.json"), json.dumps({"until": time.time() + 60}))
items = ["glance", "AI", "NOTES", "notes", "write a note", "fleet", "pair with the brain"]
go_pair = [DOWN] * items.index("pair with the brain") + [13]
ev = app(go_pair + [None, "brain-enter", None, None, None, None, None, None, 13, ord("q")], nokey)
t = texts(ev)
need("app: pairing makes the key once", sum(1 for e in ev if "generate" in e) == 1)
need("app: pairing shows the panel's own fingerprint", any(solaros.fingerprint(new_key) in x for x in t))
need("app: then the brain's Enter pairs it", any("paired: the brain lets this panel in" in x for x in t))
need("app: the key is in, forced to the menu",
     any(new_key.split()[1] in l and solaros.MARK in l for l in open(AK).read().splitlines()))
os.remove(solaros.data("pair.json"))

# paired: AI opens over ssh, the brain told first
ev = app([DOWN, 13], nokey)
need("app: paired, no pairing entry", not any("pair with the brain" in x for x in texts(ev)))
need("app: AI hands the screen to ssh, to the brain's user",
     [e["launch"] for e in ev if "launch" in e] == [["ssh", [ans["ssh"]]]])
need("app: the brain knows what to open", json.load(open(solaros.data("intent.json")))["open"] == "tab:AI")
os.remove(solaros.data("intent.json"))

# the alias: never twice, someone else's lines kept
ev = app([ord("q")], nokey)
need("app: the alias goes in once, and the notice with it",
     open(STORE + "/.shell/alias").read().count("phosphor") == 2
     and not any("type phosphor" in x for x in texts(ev)))
open(STORE + "/.shell/alias", "w").write("ll ls -l")
app([ord("q")], nokey)
need("app: an alias file without a last newline keeps its line",
     open(STORE + "/.shell/alias").read() == "ll ls -l\nphosphor python /phosphor.py\n")
open(STORE + "/.shell/alias", "w").write("phosphor python /sd/phosphor.py\n")
app([ord("q")], nokey)
need("app: the owner's own phosphor alias stays",
     open(STORE + "/.shell/alias").read() == "phosphor python /sd/phosphor.py\n")

# the launcher: asked once, Enter puts Phosphor in its free cell
cells = {"layout": {"columns": 2, "rows": 1},
         "items": [{"name": "Files", "icon": "folder", "command": "files", "column": 0, "row": 0}]}
json.dump(cells, open(STORE + "/launcher.json", "w"))
ev = app([13, 13, ord("q")], nokey)
conf = json.load(open(STORE + "/launcher.json"))
need("app: the first run with room asks about the launcher",
     any("put Phosphor in the launcher?" in x for x in texts(ev)))
need("app: Enter puts Phosphor in the launcher's free cell",
     len(conf["items"]) == 2 and conf["items"][1]["command"] == "python /phosphor.py"
     and (conf["items"][1]["column"], conf["items"][1]["row"]) == (1, 0))
ev = app([ord("q")], nokey)
need("app: and the offer goes once it's there", not any("launcher" in x for x in texts(ev)))
json.dump(cells, open(STORE + "/launcher.json", "w"))
ev = app([UP, 13, 13, ord("q")], nokey)
need("app: taken out again, it isn't asked twice; the menu entry still puts it back",
     not any("launcher?" in x for x in texts(ev))
     and len(json.load(open(STORE + "/launcher.json"))["items"]) == 2)
os.remove(STORE + "/.phosphor.json")
json.dump(cells, open(STORE + "/launcher.json", "w"))
ev = app([27, ord("q")], nokey)
need("app: Esc says no, and that's remembered too",
     len(json.load(open(STORE + "/launcher.json"))["items"]) == 1
     and json.load(open(STORE + "/.phosphor.json")) == {"launcher_asked": True})

# an older copy: it fetches the brain's, writes it over /phosphor.py, starts it
build = glance.client_build()
need("the app comes with its build in", ('BUILD = "%s"' % build).encode() in code)
need("GET /menu says which build it hands out", req("/menu?token=" + secret)[1]["app"] == build)
old = code.replace(('BUILD = "%s"' % build).encode(), b'BUILD = "0ld"')
open(os.path.join(fake, "phosphor.py"), "wb").write(old)
open(STORE + "/phosphor.py", "wb").write(old)
ev = app([ord("q")], nokey)
need("app: an older build updates itself and starts the new one",
     open(STORE + "/phosphor.py", "rb").read() == code and not os.path.exists(STORE + "/phosphor.py.new")
     and [e["launch"] for e in ev if "launch" in e] == [["python", ["/phosphor.py"]]]
     and any("updating" in x for x in texts(ev)))
real_client = glance.CLIENT
glance.CLIENT = os.path.join(fake, "edited-app.py")
open(glance.CLIENT, "w").write(open(real_client).read() + "\n# edited\n")
need("an edited app is served at once, under a new build",
     glance.client_build() != build and req("/menu?token=" + secret)[1]["app"] == glance.client_build())
glance.CLIENT = real_client
open(os.path.join(fake, "phosphor.py"), "wb").write(code)

# the brain gone: it says so and still leaves
httpd.shutdown(); httpd.server_close()
ev = app([27], nokey)
need("app: a brain that's gone says so", any("no answer from the brain" in x for x in texts(ev)))

print("\n".join("FAIL: " + f for f in fails) or "ok")
sys.exit(1 if fails else 0)
