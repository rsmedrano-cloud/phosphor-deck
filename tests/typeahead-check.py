#!/usr/bin/env python3
"""Screens that poll keep a key typed between two polls (#120).

Each screen runs in a pty with its getkey wrapped: before every read it
writes a marker and sleeps, as a slow gather or paint does on a busy brain.
The quit key goes in during the second stretch, after the screen has read
once: a screen that flushes on each read (TCSAFLUSH) drops it every time and
never leaves; one that keeps typeahead leaves at once.

    python3 tests/typeahead-check.py
"""
import os, select, shutil, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
sys.path.insert(0, LIB)
import pty

fails = 0
def check(what, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + what)
    fails += not ok

# getkey's own parsing: a long sequence comes back whole, nothing left over
import ui
check("PgUp is one key, no stray ~", ui._first_key("\x1b[5~x", False, False) == ("\x1b[5~", 4))
check("Ctrl-Up is one key", ui._first_key("\x1b[1;5A", False, False) == ("\x1b[1;5A", 6))
check("an arrow is still three chars", ui._first_key("\x1b[Bj", False, False) == ("\x1b[B", 3))
check("SS3 arrow is three chars", ui._first_key("\x1bOAj", False, False) == ("\x1bOA", 3))

tmp = tempfile.mkdtemp(prefix="typeahead-check-")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR", "SSH_"))}
ENV.update(HOME=tmp, TERM="xterm-256color", COLUMNS="100", LINES="30", PHOSPHOR_SCREEN="1",
           PHOSPHOR_PROFILE=os.path.join(tmp, "none.toml"), PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=os.path.join(tmp, "cache"), PHOSPHOR_NOTES=os.path.join(tmp, "NOTES.md"))
open(ENV["PHOSPHOR_NOTES"], "w").write("# Notes\n\n## 2026-09-18 20:00 · todo · nova · a todo\nbody\n")

MARK = "<<GK>>"
# wrap(mod): mod.getkey writes MARK, then the slow stretch, then reads
WRAP = ("import os, sys, time; sys.path.insert(0, %r)\n"
        "def wrap(mod):\n"
        "    real = mod.getkey\n"
        "    def gk(*a, **k):\n"
        "        os.write(1, %r.encode()); time.sleep(0.8); return real(*a, **k)\n"
        "    mod.getkey = gk\n" % (LIB, MARK))
TUI = ("import tui\n"
       "class P(tui.ListPanel):\n"
       "    TITLE = 'PROBE'\n"
       "    def fetch(self): return ['a', 'b']\n"
       "    def lines(self, w, sel): return [r for r in self.rows]\n")
SCREENS = [
    ("mem", "import mem; wrap(mem); sys.argv = ['mem']; sys.exit(mem.main())", b"q"),
    ("fleet", "import fleet; wrap(fleet); sys.argv = ['fleet']; sys.exit(fleet.main())", b"q"),
    ("dash", "import card; card.fetch = lambda n, said=False: (True, 'on', None) + ((None,) if said else ());"
             " import dash; wrap(dash); sys.argv = ['dash', 'ci']; sys.exit(dash.main())", b"q"),
    ("dash's gallery", "import card; card.fetch = lambda n, said=False: (True, 'on', None) + ((None,) if said else ());"
             " import dash; wrap(dash); print('PICKED', dash.gallery([])); sys.exit(0)", b"q"),
    ("home", "import home; wrap(home); sys.argv = ['home']; sys.exit(home.main())", b"q"),
    ("mentions", "import mentions; wrap(mentions); sys.argv = ['mentions']; sys.exit(mentions.main())", b"q"),
    ("notes", "import notes; wrap(notes); sys.argv = ['notes']; sys.exit(notes.main())", b"q"),
    ("panel", "import panel; wrap(panel); sys.argv = ['panel']; sys.exit(panel.main())", b"q"),
    ("a ListPanel", TUI + "wrap(tui); P().run(); sys.exit(0)", b"q"),
    ("rescue", "import rescue; wrap(rescue); rescue.holders = lambda s, me=None: [];"
               " rescue.state = lambda s: None; rescue.log_tail = lambda: '';"
               " r = rescue.screen('zellij', 'probe', {}, lambda: False); sys.exit(0 if r is False else 3)", b"q"),
]

def run(name, code, key, at=2, leaves=True):
    """Send key once the screen wrote MARK `at` times; leaves: it must exit 0
    soon after, else it must still be up 3 s later."""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(tmp)
        os.execve(sys.executable, [sys.executable, "-c", WRAP + code], ENV)
    seen, code_, sent = "", None, False
    end = time.time() + 30
    while time.time() < end and code_ is None:
        if select.select([fd], [], [], 0.05)[0]:
            try: data = os.read(fd, 65536)
            except OSError: data = b""
            seen += data.decode("utf-8", "replace")
        if not sent and seen.count(MARK) >= at:     # at 2: read once already, now in the slow stretch
            os.write(fd, key); sent, end = True, time.time() + (6 if leaves else 3)
        p_, st = os.waitpid(pid, os.WNOHANG)
        if p_: code_ = os.waitstatus_to_exitcode(st)
    if code_ is None:
        os.kill(pid, 9); os.waitpid(pid, 0)
    os.close(fd)
    ok = sent and (code_ == 0 if leaves else code_ is None) and "Traceback" not in seen
    check(name if not leaves else "%s: a key typed between two polls is read" % name, ok)
    if not ok:
        print("     sent=%s exit=%s, last of the screen:" % (sent, code_))
        print("     " + seen[-600:].replace("\n", "\n     "))

for name, code, key in SCREENS:
    run(name, code, key)
# rescue's k and digits close processes: a key typed before it first read
# (before it showed) isn't for it
run("rescue: a key typed before its first read is dropped", SCREENS[-1][1], b"q", at=1, leaves=False)

shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)
