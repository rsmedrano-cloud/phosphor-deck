"""A throwaway zellij for tests: its own HOME, its own socket dir, a client
attached in a pty. Nothing it does can reach a live deck.

    with Probe(profile_toml) as z:
        z.action("list-tabs")
        z.text()                     # what the attached client was sent

The deck's layout and config come from gen, as a real install would get them.
"""
import os, pty, re, select, shutil, signal, struct, fcntl, subprocess, sys, tempfile, termios, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def zellij():
    for p in (os.path.expanduser("~/.local/bin/zellij"), shutil.which("zellij")):
        if p and os.access(p, os.X_OK): return p
    return None

class Probe:
    def __init__(self, profile, rows=40, cols=140, session="probe", tweak=None):
        self.profile, self.rows, self.cols, self.session = profile, rows, cols, session
        self.tweak = tweak                  # config text -> config text, before zellij reads it
        self.zj = zellij()

    def __enter__(self):
        self.home = tempfile.mkdtemp(prefix="zjprobe-")
        # nothing of the deck this runs in: its session, nor its notebook, cache or data
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR_"))}
        self.env.update(HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                        XDG_CACHE_HOME=os.path.join(self.home, ".cache"),
                        XDG_DATA_HOME=os.path.join(self.home, ".local/share"),
                        XDG_RUNTIME_DIR=os.path.join(self.home, "run"),
                        ZELLIJ_SOCKET_DIR=os.path.join(self.home, "sock"),
                        PHOSPHOR_PROFILE=os.path.join(self.home, ".config/phosphor/deck.toml"),
                        TERM="xterm-256color", SHELL="/bin/sh",
                        # this checkout's phosphor, never an installed one
                        PATH=os.path.join(self.home, ".local/bin") + os.pathsep + os.environ.get("PATH", ""))
        for d in ("run", "sock", ".config/phosphor", ".local/bin"):
            os.makedirs(os.path.join(self.home, d), exist_ok=True)
        os.chmod(os.path.join(self.home, "run"), 0o700)
        os.symlink(self.zj, os.path.join(self.home, ".local/bin/zellij"))
        os.symlink(os.path.join(ROOT, "phosphor"), os.path.join(self.home, ".local/bin/phosphor"))
        open(self.env["PHOSPHOR_PROFILE"], "w").write(self.profile)
        self.layout, self.config = self.py("""
import os, sys, deckconf, gen
from ui import share
prof, _ = deckconf.load()
ctx = gen.Ctx(prof)
d = os.path.join(os.environ["HOME"], ".config/zellij"); os.makedirs(d + "/layouts", exist_ok=True)
open(d + "/layouts/deck.kdl", "w").write(gen.deck_kdl(prof, ctx, "zjprobe"))
for t in prof.get("tabs", []):
    open(d + "/layouts/tab-%s.kdl" % t["name"].lower(), "w").write(gen.tab_kdl(t, ctx, "zjprobe"))
import shortcuts
cfg = shortcuts.put(open(share("zellij-config.kdl")).read().replace('theme "phosphor"', ""), prof)[0]
open(d + "/config.kdl", "w").write(cfg)
print(d + "/layouts/deck.kdl"); print(d + "/config.kdl")
""").split()
        if self.tweak:
            text = self.tweak(open(self.config).read())
            open(self.config, "w").write(text)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.home)
            os.execve(self.zj, [self.zj, "--config", self.config, "--layout", self.layout,
                                "attach", "--create", self.session], self.env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
        self.out = b""
        # No zellij command, not even list-sessions, until the session runs
        # its panes: one that connects and leaves before the attaching
        # client has made the session panics zellij 0.45's server
        # (lib.rs:1462, RemoveClient unwraps the session's data, still None)
        # and the probe dies with no output (#123). A pane's process is seen
        # in /proc without connecting to anything.
        if not self.wait(self.panes_up, 20):
            text = self.text()[-2000:]
            self.__exit__()
            raise RuntimeError("zellij didn't start (no pane after 20s):\n" + text)
        # listed isn't ready: zellij 0.46 lists a session before it answers
        # queries (list-tabs comes back empty), so wait for its tabs too
        if not self.wait(lambda: self.session in self.run("list-sessions", "-n", "-s")
                         and self.tabs() and '"name"' in self.action("list-tabs", "--json"), 20):
            text = self.text()[-2000:]
            self.__exit__()                   # no zellij server or scratch folder left behind
            raise RuntimeError("zellij didn't start:\n" + text)
        return self

    def panes_up(self):
        """A process of this probe's session runs in a pane: the session
        exists. Read from /proc, never by asking zellij."""
        home, pane = ("HOME=%s" % self.home).encode(), b"ZELLIJ_PANE_ID="
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                env = open("/proc/%s/environ" % d, "rb").read().split(b"\0")
            except OSError:
                continue
            if home in env and any(e.startswith(pane) for e in env):
                return True
        return False

    def __exit__(self, *a):
        subprocess.run([self.zj, "kill-session", self.session], env=self.env, capture_output=True, timeout=10)
        try:
            os.kill(self.pid, signal.SIGKILL); os.waitpid(self.pid, 0)
        except OSError:
            pass
        for d in os.listdir("/proc"):          # whatever the session left running (no pkill in slim images)
            try:
                env = open("/proc/%s/environ" % d, "rb").read()
            except OSError:
                continue
            if self.home.encode() in env and int(d) != os.getpid():
                try: os.kill(int(d), signal.SIGKILL)
                except OSError: pass
        shutil.rmtree(self.home, ignore_errors=True)

    def py(self, code):
        """Python with lib/ on the path, in the probe's environment."""
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n" % os.path.join(ROOT, "lib") + code],
                           env=self.env, capture_output=True, text=True, timeout=60)
        if r.returncode: raise RuntimeError(r.stderr)
        return r.stdout

    def run(self, *args):
        self.pump()
        r = subprocess.run([self.zj] + list(args), env=self.env, capture_output=True, text=True, timeout=15)
        self.pump()
        return r.stdout + r.stderr

    def action(self, *args):
        return self.run("--session", self.session, "action", *args)

    def listing(self, *args, timeout=5.0):
        """A JSON listing (`list-tabs -j`, `list-panes -a -j`), parsed. Under
        load zellij's CLI now and then answers nothing at all, exit 0 (#113);
        a running session always has a tab and a pane, so an empty answer is
        asked again rather than read as "none". So is one that isn't JSON (an
        error on stderr); the last one is raised with what zellij said."""
        import json
        end = time.time() + timeout
        while True:
            out = self.action(*args).strip()
            try:
                if out:
                    return json.loads(out)
            except ValueError:
                if time.time() >= end:
                    raise RuntimeError("zellij action %s: %r" % (" ".join(args), out[:300]))
            if time.time() >= end:
                return []
            self.pump(0.2)

    def dumped(self, session=None, timeout=5.0):
        """`dump-layout`'s text. Like a listing, under load it can come back
        empty (#133); a running session's layout always has a tab, so one
        without is asked again, and after `timeout` returned as it came."""
        end = time.time() + timeout
        while True:
            out = self.run("--session", session or self.session, "action", "dump-layout")
            if re.search(r'^\s*tab\b', out, re.M) or time.time() >= end:
                return out
            self.pump(0.2)

    def clients(self, session=None, timeout=5.0):
        """The screens attached (list-clients' lines, header aside). Nobody
        is the header alone; an answer without it is zellij busy (#122),
        asked again, and after `timeout` None."""
        end = time.time() + timeout
        while True:
            lines = self.run("--session", session or self.session, "action", "list-clients").splitlines()
            if lines and lines[0].startswith("CLIENT_ID"):
                return [l for l in lines[1:] if l.strip()]
            if time.time() >= end:
                return None
            self.pump(0.2)

    def pump(self, t=0.0):
        end = time.time() + t
        while True:
            if select.select([self.fd], [], [], max(0.0, min(0.05, end - time.time())))[0]:
                try: self.out += os.read(self.fd, 65536)
                except OSError: return
            elif time.time() >= end:
                return

    def text(self):
        return self.out.decode("utf-8", "replace")

    def keys(self, data, settle=0.5):
        os.write(self.fd, data if isinstance(data, bytes) else data.encode())
        self.pump(settle)

    def wait(self, cond, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if cond(): return True
            self.pump(0.3)
        return False

    def tabs(self):
        """Tab names, in order (from the session's own layout)."""
        return re.findall(r'^\s*tab name="([^"]*)"', self.dumped(), re.M)

    def screen(self):
        """What the focused pane shows now (dump-screen), as lines."""
        out = os.path.join(self.home, "screen.txt")
        try: os.remove(out)
        except OSError: pass
        self.action("dump-screen", "--path", out)
        return open(out).read().splitlines() if os.path.exists(out) else []

def tap(z, label, timeout=10):
    """Tap the row of the focused pane that shows this text."""
    end = time.time() + timeout
    while time.time() < end:
        rows = z.screen()
        hit = [i for i, r in enumerate(rows) if 0 <= r.find(label) < 44] \
            or [i for i, r in enumerate(rows) if label in r]          # the list, not a preview beside it
        active = [t for t in z.listing("list-tabs", "-s", "-j") if t.get("active")]
        tab_id = active[0].get("tab_id", active[0].get("id")) if active else None
        me = [p for p in z.listing("list-panes", "-a", "-j") if p["is_focused"] and not p["is_plugin"]
              and not p["is_suppressed"] and p["tab_id"] == tab_id]     # every tab has a focused pane
        if hit and me:                  # on the text itself: a row may hold two buttons
            col = max(3, rows[hit[0]].find(label))
            x, y = me[0]["pane_content_x"] + col + 1, me[0]["pane_content_y"] + hit[0] + 1
            z.keys(b"\x1b[<0;%d;%dM" % (x, y), 0.1); z.keys(b"\x1b[<0;%d;%dm" % (x, y), 0.8)
            return True
        z.pump(0.3)
    return False

def reading_keys(z, arg):
    """The probe's program with this argument reads keys now (its tty out
    of canonical mode). A screen draws before getkey() runs, and getkey()
    drops what was typed before it (TCSAFLUSH): a key sent the moment the
    screen shows can land before its setraw, under load, and be lost.
    tcgetattr on the program's own tty (/proc/PID/fd/0) reads its modes."""
    import termios
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        try:
            if arg.encode() not in open("/proc/%s/cmdline" % d, "rb").read().split(b"\0")[1:] or \
               ("HOME=" + z.home).encode() not in open("/proc/%s/environ" % d, "rb").read().split(b"\0"):
                continue
            fd = os.open("/proc/%s/fd/0" % d, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                if not termios.tcgetattr(fd)[3] & termios.ICANON: return True
            finally:
                os.close(fd)
        except (OSError, termios.error):
            pass
    return False
