#!/usr/bin/env python3
"""lib/tui.py's ListPanel, the picker several panels share, with
no terminal: keys and taps go straight to key(), the screen comes from
frame(). j/k and the wheel pick, a tap on a row picks it, a tap on the key
bar presses that key, a question runs its action only on y, a tap while it
waits says no, rows that don't fit scroll with the pick, a problem line
can't be picked or acted on, q quits. Then the real panels on it:
services, containers, screens, review, store, tunnels, trace, keys.
Last, ui.getkey itself, the one keyboard reader every screen shares,
through a pty.

    python3 tests/tui-check.py
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.environ["HOME"] = tempfile.mkdtemp()
for k in [k for k in os.environ if k.startswith("ZELLIJ")]:
    del os.environ[k]                      # outside zellij: a title with no zoom mark
import tui, ui
from ui import HEAD

fails = []
def need(what, ok):
    if not ok: fails.append(what)

def tap(x, y):
    return ("MOUSE", 0, x, y, True)

class Fake(tui.ListPanel):
    KEYS = [("l", "logs"), ("r", "restart"), ("q", "quit")]
    def __init__(self, n=5):
        super().__init__()
        self.n, self.done, self.paged = n, [], []
    def fetch(self):
        return ["row%d" % i for i in range(self.n)]
    def header(self, w):
        return ["HEAD"] * HEAD
    def lines(self, w, sel):
        return [("> " if i == sel else "  ") + r for i, r in enumerate(self.rows)]
    def act(self, k, row):
        if k == "l":
            self.paged.append(row); return
        self.confirm("restart %s?" % row, lambda: (self.done.append(row) or True, "restarted " + row))

p = Fake(); p.update(); p.frame(80, 24)
need("fetch fills rows", p.rows == ["row%d" % i for i in range(5)])
need("j moves down", p.key("j") and p.sel == 1)
p.key("\x1b[B"); need("down arrow moves down", p.sel == 2)
p.key("k"); need("k moves up", p.sel == 1)
p.key(("MOUSE", 65, 1, 1, True)); need("wheel down moves", p.sel == 2)
p.key(("MOUSE", 64, 1, 1, True)); p.key(("MOUSE", 64, 1, 1, True)); p.key(("MOUSE", 64, 1, 1, True))
need("wheel up stops at the first row", p.sel == 0)
for _ in range(9): p.key("j")
need("j stops at the last row", p.sel == 4)

out = p.frame(80, 24)
need("frame: header, rows, key bar", out[:HEAD] == ["HEAD"] * HEAD and out[HEAD] == "  row0"
     and "logs" in out[HEAD + 5])
p.key(tap(5, HEAD + 1 + 3)); need("a tap on a row picks it", p.sel == 3)
p.key(("MOUSE", 0, 5, HEAD + 1 + 3, False)); need("a release does nothing", p.sel == 3)

# the key bar: " l logs  r restart  q quit", spans from column 2
bar = HEAD + 1 + 5
p.key(tap(3, bar)); need("a tap on 'l logs' pages row3", p.paged == ["row3"])
p.key(tap(10, bar)); need("a tap on 'r restart' asks", p.ask and p.ask[0] == "restart row3?" and not p.done)
need("the question shows", "restart row3?" in p.frame(80, 24)[-1])
p.key("n"); need("any other key says no", p.ask is None and not p.done and "left alone" in p.msg)
p.key("r"); p.key(tap(5, HEAD + 1)); need("a tap while asking says no", p.ask is None and not p.done)
p.key("r"); p.last = 123.0; p.key("y")
need("y runs it, says so and refetches", p.done == ["row3"] and "restarted row3" in p.msg and p.last == 0.0)
p.key("x"); need("a key not in KEYS does nothing", p.ask is None and p.paged == ["row3"])
need("q quits", p.key("q") is False and p.key("\x03") is False)
need("q on the bar quits too", p.key(tap(22, bar)) is False)

# more rows than room: the pick stays on screen
p = Fake(40); p.update()
for _ in range(30): p.key("j")
out = p.frame(80, 24)
first, top, n, _, _ = p.layout
need("scrolls with the pick", top > 0 and "> row30" in out[HEAD:HEAD + n])
p.key(tap(5, first)); need("a tap after scrolling picks the right row", p.sel == top)

# a problem replaces the rows, and nothing acts on it
class Down(Fake):
    def fetch(self):
        self.problem = "couldn't reach the host"; return []
p = Down(); p.update(); out = p.frame(80, 24)
need("a problem shows instead of rows", "couldn't reach the host" in out[HEAD])
p.key("r"); p.key(tap(5, HEAD + 1)); need("a problem can't be acted on", p.ask is None and p.sel == 0)
p.key("j"); need("j with no rows stays at 0", p.sel == 0)

# ── the real panels ───────────────────────────────────────────
import services as S, containers as C

prof = {"deck": {"session": "deck"}}
sp = S.Panel(prof)
sp.rows = [("user", "deck.service", {"LoadState": "loaded", "ActiveState": "active"}),
           ("system", "gone.service", {"LoadState": "not-found"}),
           ("user", "fleet-db-box.service", {"LoadState": "loaded", "ActiveState": "active", "SubState": "running"})]
sp.frame(80, 24)
sp.key("r"); need("services: the deck's own unit isn't restarted from here", sp.ask is None and "phosphor restart" in sp.msg)
sp.key("j"); sp.key("s"); need("services: a missing unit says so", sp.ask is None and "isn't installed" in sp.msg)
sp.key("j"); sp.key("s"); need("services: s on an active unit asks to stop", sp.ask and sp.ask[0].startswith("stop "))
need("services: keys", [k for k, _ in sp.KEYS] == ["l", "r", "s", "q"])

cp = C.Panel("nebula", "ops@nebula", demo=True); cp.update(); cp.frame(80, 24)
need("containers: the demo's rows", cp.engine == "docker" and cp.rows and cp.rows[0][0])
cp.key("r"); need("containers: the demo touches nothing", cp.ask is None and "aren't real" in cp.msg)
cp = C.Panel("db-box", "ops@db-box")
cp.rows, cp.engine = [("web", "running", "Up 3 days", "nginx"), ("job", "exited", "Exited (0) 1 hour ago", "x")], "docker"
cp.frame(80, 24)
cp.key("s"); need("containers: s on a running one asks to stop", cp.ask and cp.ask[0] == "stop web on db-box?")
cp.key("n"); cp.key("j"); cp.key("s"); need("containers: s on an exited one asks to start", cp.ask and cp.ask[0] == "start job on db-box?")
need("containers: header counts", "1/2 up" in "".join(cp.header(80)))

import screens as SC
kicked = []
SC.kick = lambda pid, mine=None: (kicked.append(pid) or True, "kicked %d" % pid)
sc = SC.Panel(prof)
sc.rows = [{"tty": "pts/3", "from": "db-box", "idle": "now", "pid": 4242, "session": "deck", "said": ""},
           {"tty": "pts/4", "from": "nimbus", "idle": "2:00", "pid": 4343, "session": "deck-phone", "said": "phone"}]
out = sc.frame(80, 24)
need("screens: rows and kinds", "db-box" in out[HEAD] and "phone" in out[HEAD + 1])
sc.key("x"); need("screens: x asks, nothing kicked yet", sc.ask and "kick db-box" in sc.ask[0] and not kicked)
need("screens: the question says what it costs", "reconnects" in "".join(sc.frame(80, 24)))
sc.key("y"); need("screens: y kicks", kicked == [4242] and "kicked 4242" in sc.msg)
sc.key("o"); need("screens: o on a screen with no kind only hints", sc.ask is None and "--as KIND" in sc.msg)
sc.key("j"); sc.key("o"); need("screens: o on a kind's own deck asks to share", sc.ask and sc.ask[0] == "every phone shares this deck again?"
                               and "deck-phone" in sc.ask[2])
sc.key("n"); need("screens: n leaves the profile alone", sc.ask is None and "left alone" in sc.msg)
sc.rows, sc.problem = [], ""
need("screens: none attached says so", "no screens attached" in "".join(sc.frame(80, 24)))
sc.here = 1
need("screens: a terminal on the brain still counts", "1 attached here on the brain, none over ssh" in "".join(sc.frame(80, 24))
     and "1 · deck" in "".join(sc.header(80)))
sc.rows, sc.here = [{"tty": "pts/3", "from": "db-box", "idle": "now", "pid": 4242, "session": "deck", "said": ""}], 2
need("screens: the local ones under the ssh ones", "and 1 here on the brain" in "".join(sc.frame(80, 24)))

import review as RV
RV.ci_tag = lambda prov, it, repo, cache: (ui.DIM, "no CI")
dropped = []
RV.drop_branch = lambda prov, it: (dropped.append(it["id"]) or True, "removed the worktree")
rv = RV.Panel("gitlab", "owner/repo")
rv.rows = [{"id": 4, "title": "tts support", "author": "db-box", "src": "feature/tts", "dst": "dev",
            "conflicts": False, "draft": False, "url": ""},
           {"id": 5, "title": "widget", "author": "nimbus", "src": "widget", "dst": "dev",
            "conflicts": True, "draft": True, "url": ""}]
out = rv.frame(100, 24)
need("review: rows", "!4" in out[HEAD] and "conflicts" in out[HEAD + 1] and "draft" in out[HEAD + 1])
RV.worktree_dir = lambda prov, it: "/nonexistent/review-%d" % it["id"]
rv.key("x"); need("review: x with nothing checked out only says so", rv.ask is None and "nothing checked out" in rv.msg)
RV.worktree_dir = lambda prov, it: ROOT
rv.key("x"); need("review: x asks first, says what's lost", rv.ask and "feature/tts" in rv.ask[0]
                  and "is lost" in rv.ask[2] and not dropped)
rv.key("y"); need("review: y drops", dropped == [4] and "removed" in rv.msg)
need("review: keys", [k for k, _ in rv.KEYS] == ["d", "c", "t", "x", "r", "q"])

# ── a Head among the rows: never picked, taps skip it, the pick scrolls past it
class Grouped(tui.ListPanel):
    KEYS = [("enter", "open"), ("q", "quit")]
    def __init__(self):
        super().__init__(); self.opened = []
    def fetch(self): return ["a1", "a2", "b1"]
    def lines(self, w, sel):
        out = []
        for i, r in enumerate(self.rows):
            if r.endswith("1"): out.append(tui.Head(r[0].upper()))
            out.append(("> " if i == sel else "  ") + r)
        return out
    def act(self, k, row): self.opened.append((k, row))
gp = Grouped(); gp.update(); gp.frame(80, 24)
gp.key(tap(3, HEAD + 1 + 3)); need("Head: a tap on a title picks nothing", gp.sel == 0)
gp.key(tap(3, HEAD + 1 + 4)); need("Head: a tap on the row under it picks it", gp.sel == 2)
gp.key("g"); need("g: first row", gp.sel == 0)
gp.key("G"); need("G: last row", gp.sel == 2)
gp.key("\r"); need("Enter reaches act() as enter", gp.opened == [("enter", "b1")])
out = gp.frame(80, HEAD + 5)          # room for 2 lines: B and b1
need("Head: the pick scrolls into view", any(l == "> b1" for l in out))

# ── store: the catalog by category, i and / narrow it, d asks first
import json, store as ST
cat = os.path.join(os.environ["HOME"], "store.json")
json.dump([{"n": "zz-top", "c": "chat", "d": "a chat", "r": "x/y", "m": "."},
           {"n": "aa-mon", "c": "monitor", "d": "a monitor", "r": "x/y", "m": "."}], open(cat, "w"))
ST.CATALOG = cat
ST.installed = lambda a: a["n"] == "aa-mon"
gone = []
ST.remove = lambda a: ("remove %s?" % a["n"], lambda: (gone.append(a["n"]) or True, "removed " + a["n"]))
sp = ST.Panel(""); sp.update(); out = sp.frame(100, 24)
need("store: categories are titles", "CHAT" in out[HEAD] and isinstance(sp.lines(100, 0)[0], tui.Head))
need("store: enter installs what isn't there", sp.KEYS[0] == ("enter", "install"))
sp.key("j"); need("store: enter opens what is", sp.KEYS[0] == ("enter", "open in a tab"))
sp.key("i"); need("store: i shows installed only", [a["n"] for a in sp.rows] == ["aa-mon"])
sp.key("\x1b"); need("store: esc gives everything back", len(sp.rows) == 2)
sp.line = lambda label, text="": "chat"
sp.key("/"); need("store: / filters", [a["n"] for a in sp.rows] == ["zz-top"] and "chat" in "".join(sp.frame(100, 24)[:HEAD]))
sp.key("d"); need("store: d asks first", sp.ask and "zz-top" in sp.ask[0] and not gone)
sp.key("y"); need("store: y removes", gone == ["zz-top"] and "removed" in sp.msg)
sp.line = lambda label, text="": "nomatch"
sp.key("/"); need("store: nothing matches, and says so", sp.rows == [] and "nothing matches" in "".join(sp.frame(100, 24)))

# ── workspace: git state per row, x asks y/n first, n works with none
import workspace as WS
WS.root = lambda prof=None: "/nonexistent/projects"
removed = []
WS.remove = lambda n: (removed.append(n) or True, "folder in the trash")
wp = WS.Panel()
wp.rows = [("alpha", "/p/alpha", (False, 0, 0)), ("beta", "/p/beta", (True, 2, 0))]
out = wp.frame(100, 24)
need("workspace: rows and state", "alpha" in out[HEAD] and "clean" in out[HEAD]
     and "dirty ↑2" in out[HEAD + 1] and "1 to look at" in out[0])
wp.key("j"); wp.key("x")
need("workspace: x asks, says what's lost", wp.ask and "beta" in wp.ask[0] and "committed" in wp.ask[2] and not removed)
wp.key("n"); need("workspace: anything but y leaves it", wp.ask is None and not removed and "left alone" in wp.msg)
wp.key("x"); wp.key("y"); need("workspace: y removes", removed == ["beta"] and "trash" in wp.msg)
os.environ.pop("ZELLIJ", None)
wp.key("\r"); need("workspace: Enter outside the deck says how", "workspace open beta" in wp.msg)
need("workspace: keys", [k for k, _ in wp.KEYS] == ["enter", "d", "n", "x", "q"])
wp.rows = []
need("workspace: none says n makes one", "n makes one" in "".join(wp.frame(80, 24)))

# ── tabs: open or closed per row, f asks y/n, J/K follow the tab, o reopens
import tabs as TB
forgot, moved, opened = [], [], []
TB.forget = lambda n: forgot.append(n)
TB.move = lambda n, step: moved.append((n, step))
TB.reopen = lambda n: opened.append(n)
tp = TB.Panel(); tp.draw = lambda: None
tp.rows = [("SYS", True, "", False), ("LOGS", False, "", False), ("SHARED", True, "shared.toml", False)]
out = tp.frame(100, 24)
need("tabs: rows, open and closed", "SYS" in out[HEAD] and "open" in out[HEAD]
     and "closed now" in out[HEAD + 1] and "tabs.d/shared.toml" in out[HEAD + 2] and "1 closed now" in out[0])
tp.key("f")
need("tabs: f asks first", tp.ask and "forget SYS" in tp.ask[0] and "deck.toml.bak" in tp.ask[2] and not forgot)
tp.key("y"); need("tabs: y forgets", forgot == ["SYS"] and "forgotten" in tp.msg)
tp.key("K"); need("tabs: the first can't go left", not moved and "first" in tp.msg)
tp.key("J"); need("tabs: J moves it and the pick follows", moved == [("SYS", 1)] and tp.sel == 1 and "moved" in tp.msg)
tp.key("o"); need("tabs: o reopens a closed one", opened == ["LOGS"] and "opened" in tp.msg)
tp.key("j"); tp.key("o"); need("tabs: o on an open one says so", opened == ["LOGS"] and "open already" in tp.msg)
tp.key("f"); need("tabs: an unplaced tabs.d tab can't be forgotten", tp.ask is None and "tabs.d" in tp.msg)
tp.rows[2] = ("SHARED", True, "shared.toml", True)
tp.key("f"); need("tabs: a placed one asks to un-place", tp.ask and "un-place SHARED" in tp.ask[0])
tp.key("y"); need("tabs: y un-places", forgot == ["SYS", "SHARED"] and "un-placed" in tp.msg)
need("tabs: keys", [k for k, _ in tp.KEYS] == ["f", "K", "J", "o", "q"])

# ── tunnels: a host per row, its forwards under it; Enter asks, the warning as its note
import tunnels as TN
toggled = []
TN.listing = lambda: [{"host": "db-box", "state": "off", "forwards": [{"local": "33307", "target": "127.0.0.1:3306",
                                                                      "label": "mysql", "listening": None}]},
                      {"host": "nimbus", "state": "up", "forwards": []}]
TN.on = lambda h: (toggled.append(("on", h)), print("  ✓ db-box 1/1 forwards listening"))[0] or 0
TN.off = lambda h: (toggled.append(("off", h)), print("  ✓ nimbus tunnels stopped"))[0] or 0
tn = TN.Panel(); tn.draw = lambda: None; tn.update(); out = tn.frame(80, 24)
need("tunnels: a row per host, forwards under it", "db-box" in out[HEAD] and "33307" in out[HEAD + 1] and "nimbus" in out[HEAD + 2])
tn.key("j"); need("tunnels: forwards are never picked", tn.sel == 1)
tn.key("k"); tn.key("\r")
need("tunnels: enter asks first, and says what it costs", tn.ask and "keep db-box" in tn.ask[0] and not toggled
     and "other users" in "".join(tn.frame(80, 24)))
tn.key("y"); need("tunnels: y keeps it up, its output as one line", toggled == [("on", "db-box")] and "forwards listening" in tn.msg
                  and "\x1b[" not in tn.msg.replace(ui.PH, "").replace(ui.RST, ""))
tn.key("j"); tn.key("\r"); tn.key("n"); need("tunnels: n leaves it", toggled == [("on", "db-box")] and "left alone" in tn.msg)
tn.key("\r"); tn.key("y"); need("tunnels: an up one turns off", toggled[-1] == ("off", "nimbus"))
TN.listing = lambda: []
tn = TN.Panel(); tn.update()
need("tunnels: none says so", "no LocalForward lines" in "".join(tn.frame(80, 24)) and tn.key("\r") and tn.ask is None)

# ── trace: what's on first, then what deck.log has seen; enter toggles, / names one
import trace as TR, dlog
on_now = {"RUN": 12}
dlog.active_traces = lambda: list(on_now.items())
dlog.tools_seen = lambda: ["FLEET", "RUN"]
dlog.start_trace = lambda t, m=30: on_now.__setitem__(t, m)
dlog.stop_trace = lambda t: on_now.pop(t, None) is not None
tr = TR.Panel(); tr.draw = lambda: None; tr.update(); out = tr.frame(80, 24)
need("trace: what's on comes first", "RUN" in out[HEAD] and "12 min left" in out[HEAD] and "FLEET" in out[HEAD + 1])
tr.key("\r"); need("trace: enter stops one that's on", "RUN" not in on_now and "stopped" in tr.msg)
tr.update()
tr.sel = [t for t, _ in tr.rows].index("FLEET"); tr.key("\r")
need("trace: enter starts one for 30 minutes", on_now.get("FLEET") == 30 and "phosphor logs fleet" in tr.msg)
typed = iter(["p", "r", "o", "m", "\r"])
real_getkey, tui.getkey = tui.getkey, (lambda *a, **kw: next(typed))
tr.key("/"); need("trace: / names another", on_now.get("PROM") == 30)
dlog.tools_seen, on_now = (lambda: []), {}
tr = TR.Panel(); tr.draw = lambda: None; tr.update()
need("trace: none seen says so", "/ names one" in "".join(tr.frame(80, 24)))
typed = iter(["x", "\r"]); tr.key("/"); need("trace: / works with no rows", "X" in on_now)
tui.getkey = real_getkey

# ── keys: a section's title is never picked, every key a row, s runs setup
import keys as KY
kdb = os.path.join(os.environ["HOME"], "keys.json")
json.dump({"_tool": {"t": "TOOL", "always": True, "k": [["Alt a", "one"], ["", "a note"], ["Alt b", "two"]]},
           "gone": {"t": "GONE", "k": [["x", "never shown"]]}}, open(kdb, "w"))
KY.DB, setups = kdb, []
KY.run_setup = lambda: setups.append(1)
ky = KY.Panel(); ky.update(); out = ky.frame(80, 24)
need("keys: installed tools only", "TOOL" in "".join(out) and "GONE" not in "".join(out) and "1 tools" in "".join(out[:HEAD]))
need("keys: the keys are the rows", [k for _, k in ky.rows] == ["Alt a", "Alt b"])
ky.key("j"); need("keys: j skips the note", ky.sel == 1 and "\x1b[7m" in [l for l in ky.frame(80, 24) if "two" in l][0])
ky.key("s"); need("keys: s runs setup", setups == [1])
need("keys: no tty prints it plain", "Alt b" in "\n".join(KY.build(KY.load(), 78)[0]))

# ── --select NAME: the panel opens on that row (a card's shortcut, a script's)
need("selected: --select NAME", tui.selected(["--select", "pts/3"]) == "pts/3"
     and tui.selected(["--json", "--select=web"]) == "web" and tui.selected(["--once"]) is None)
need("unselected: the rest of the command line",
     tui.unselected(["db-box", "--select", "web", "--once"]) == ["db-box", "--once"]
     and tui.unselected(["--select=web", "db-box"]) == ["db-box"])
class Named(Fake):
    def row_name(self, row):
        return row.upper()
real_argv = sys.argv
try:
    sys.argv = ["phosphor-x", "--select", "row3"]
    n = Named(); n.update()
    need("--select: picked on the first fetch", n.sel == 3 and not n.msg)
    n.key("k"); n.refresh(); n.update()
    need("--select: only once, the pick is yours after", n.sel == 2)
    sys.argv = ["phosphor-x", "--select", "ROW"]
    n = Named(); n.update()
    need("--select: a prefix, any case, takes the first", n.sel == 0)
    sys.argv = ["phosphor-x", "--select", "nimbus"]
    n = Named(); n.update()
    need("--select: no such row says so, the pick stays", n.sel == 0 and "no nimbus here" in n.msg)
    sys.argv = ["phosphor-x", "--select", "row1"]
    f = Fake(); f.update()
    need("--select: a panel with no names ignores it", f.sel == 0 and not f.msg)
finally:
    sys.argv = real_argv
need("--select: screens by tty", sc.row_name({"tty": "pts/3", "from": "db-box"}) == "pts/3")
need("--select: services by unit", S.Panel(prof).row_name(("user", "deck.service", {})) == "deck.service")
need("--select: containers by name", cp.row_name(("web", "running", "")) == "web")
need("--select: tunnels by host", tn.row_name({"host": "db-box", "state": "up"}) == "db-box")

# ── run() on a real terminal (a pty, no zellij): draws, takes j, quits on q
import pty, select, subprocess, time
SCRIPT = """
import sys; sys.path.insert(0, %r)
import tui
class P(tui.ListPanel):
    KEYS = [("q", "quit")]
    def fetch(self): return ["alpha", "beta"]
    def lines(self, w, sel): return [("> " if i == sel else "  ") + r for i, r in enumerate(self.rows)]
sys.exit(P().run())
""" % os.path.join(ROOT, "lib")
mfd, sfd = pty.openpty()
proc = subprocess.Popen([sys.executable, "-c", SCRIPT], stdin=sfd, stdout=sfd, stderr=sfd, close_fds=True)
os.close(sfd)
def read_for(secs):
    buf, end = b"", time.time() + secs
    while time.time() < end:
        if select.select([mfd], [], [], 0.1)[0]:
            try: buf += os.read(mfd, 65536)
            except OSError: break
    return buf.decode("utf-8", "replace")
seen = read_for(1.0)
need("run: alt screen and mouse on", tui.ON in seen and "> alpha" in seen)
os.write(mfd, b"j"); seen = read_for(0.6)
need("run: j redraws with the pick moved", "> beta" in seen)
os.write(mfd, b"q")
try: rc = proc.wait(5)
except subprocess.TimeoutExpired: proc.kill(); rc = None
seen = read_for(0.3)
need("run: q exits 0 and gives the screen back", rc == 0 and tui.OFF in seen)

# a terminal in, a pipe out (`phosphor keys | head`): the plain listing, never the panel
for mod in ("keys", "tunnels", "tabs", "screens", "store", "dash"):
    mfd2, sfd2 = pty.openpty()
    try:                                     # the panel would sit waiting for a key
        p = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); sys.argv = [%r]; import %s; sys.exit(%s.main() or 0)"
                            % (os.path.join(ROOT, "lib"), mod, mod, mod)],
                           stdin=sfd2, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        rc, out = p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        rc, out = None, ""
    os.close(sfd2); os.close(mfd2)
    need(mod + ": tty in, pipe out prints it plain", rc in ((1,) if mod == "dash" else (0, 1)) and tui.ON not in out and "Traceback" not in out)

# ui.getkey through a pty: raw events, and mouse=True's simplified ones
import pty as _pty
gm, gs = _pty.openpty()
real_stdin = sys.stdin
sys.stdin = os.fdopen(gs, "r")
import threading
def got(data, **kw):
    # written once getkey waits: setraw flushes whatever was typed before
    threading.Timer(0.1, os.write, (gm, data)).start(); return ui.getkey(1, **kw)
try:
    need("getkey: a plain key", got(b"j") == "j")
    need("getkey: an arrow is one key", got(b"\x1b[B") == "\x1b[B")
    need("getkey: a raw tap", got(b"\x1b[<0;7;3M") == ("MOUSE", 0, 7, 3, True))
    need("getkey: mouse=True tap", got(b"\x1b[<0;7;3M", mouse=True) == ("TAP", 7, 3))
    need("getkey: mouse=True wheel", got(b"\x1b[<64;1;1M", mouse=True) == "WUP"
         and got(b"\x1b[<65;1;1M", mouse=True) == "WDN")
    need("getkey: mouse=True drops a release", got(b"\x1b[<0;7;3m", mouse=True) is None)
    need("getkey: text=True keeps a paste", got(b"hello", text=True) == "hello")
    need("getkey: timeout gives None", ui.getkey(0.05) is None)
finally:
    sys.stdin = real_stdin; os.close(gm)

if fails:
    print("tui-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("tui-check ok")
