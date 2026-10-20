"""A throwaway zellij for tests: its own HOME, its own socket dir, a client
attached in a pty. Nothing it does can reach a live deck.

    with Probe(profile_toml) as z:
        z.action("list-tabs")
        z.text()                     # what the attached client was sent

The deck's layout and config come from gen, as a real install would get them.
"""
import os, pty, select, shutil, signal, struct, fcntl, subprocess, sys, tempfile, termios, time
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
        if not self.wait(lambda: self.session in self.run("list-sessions", "-n", "-s"), 20):
            text = self.text()[-2000:]
            self.__exit__()                   # no zellij server or scratch folder left behind
            raise RuntimeError("zellij didn't start:\n" + text)
        return self

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
        import re
        return re.findall(r'^\s*tab name="([^"]*)"', self.action("dump-layout"), re.M)

    def screen(self):
        """What the focused pane shows now (dump-screen), as lines."""
        out = os.path.join(self.home, "screen.txt")
        try: os.remove(out)
        except OSError: pass
        self.action("dump-screen", "--path", out)
        return open(out).read().splitlines() if os.path.exists(out) else []

def tap(z, label, timeout=10):
    """Tap the row of the focused pane that shows this text."""
    import json
    end = time.time() + timeout
    while time.time() < end:
        rows = z.screen()
        hit = [i for i, r in enumerate(rows) if 0 <= r.find(label) < 44] \
            or [i for i, r in enumerate(rows) if label in r]          # the list, not a preview beside it
        active = [t for t in json.loads(z.action("list-tabs", "-s", "-j") or "[]") if t.get("active")]
        tab_id = active[0].get("tab_id", active[0].get("id")) if active else None
        me = [p for p in json.loads(z.action("list-panes", "-a", "-j")) if p["is_focused"] and not p["is_plugin"]
              and not p["is_suppressed"] and p["tab_id"] == tab_id]     # every tab has a focused pane
        if hit and me:                  # on the text itself: a row may hold two buttons
            col = max(3, rows[hit[0]].find(label))
            x, y = me[0]["pane_content_x"] + col + 1, me[0]["pane_content_y"] + hit[0] + 1
            z.keys(b"\x1b[<0;%d;%dM" % (x, y), 0.1); z.keys(b"\x1b[<0;%d;%dm" % (x, y), 0.8)
            return True
        z.pump(0.3)
    return False
