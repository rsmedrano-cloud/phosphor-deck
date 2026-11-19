#!/usr/bin/env python3
"""The warm-up screen `deck` shows on the way in (issue #47).

    python3 tests/splash-check.py

`phosphor attach` runs for real in a pseudo-terminal against a throwaway
HOME and profile; zellij and systemctl are stand-ins on PATH (the zellij
one says it attached and what key, if any, reached it). Nothing of the
real deck.
"""
import os, pty, select, subprocess, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOSPHOR = os.path.join(ROOT, "phosphor")

tmp = tempfile.mkdtemp()
BIN = os.path.join(tmp, "bin")
os.makedirs(BIN)
os.makedirs(os.path.join(tmp, ".config", "phosphor"))
os.makedirs(os.path.join(tmp, ".local", "share", "phosphor"))
open(os.path.join(tmp, ".local", "share", "phosphor", ".welcomed"), "w").close()
PROFILE = os.path.join(tmp, ".config", "phosphor", "deck.toml")
HOSTS = ('[[hosts]]\nname = "probe-brain"\nrole = "brain"\nlocal = true\n\n'
         '[[hosts]]\nname = "db-box"\nrole = "storage"\nssh = "db-box"\n')
def profile(deck_extra=""):
    open(PROFILE, "w").write('[deck]\nsession = "splash-probe"\n%s\n' % deck_extra + HOSTS)

def stub(name, body):
    p = os.path.join(BIN, name)
    open(p, "w").write("#!/bin/sh\n" + body + "\n")
    os.chmod(p, 0o755)
# the deck is up (list-sessions lists it): with none, attach would stop at
# the recovery screen (lib/rescue.py) instead of going in
stub("zellij", 'case "$1" in list-sessions) echo "splash-probe [Created 1s ago]";; attach) exec "%s" -c "%s";; esac' % (sys.executable, (
    "import os, select, sys; print('ZELLIJ-ATTACHED', flush=True); "
    "r = select.select([0], [], [], 0.5)[0]; "
    "print('KEY-REACHED:[%s]' % (os.read(0, 16).decode().strip() if r else ''), flush=True)")))
stub("systemctl", "exit 3")

CACHE = os.path.join(tmp, "cache")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("ZELLIJ", "PHOSPHOR", "SSH_"))}
ENV.update(HOME=tmp, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=CACHE, PATH=BIN + ":/usr/bin:/bin",
           TERM="xterm-256color", LINES="30", COLUMNS="100")

fails = []
def need(what, ok, out=""):
    if not ok:
        fails.append(what + ("\n" + out[-500:] if out else ""))

def attach(key=False, env=None):
    """Run it; with key, press one as soon as the warm-up's first frame is
    out. (output, seconds the warm-up held the screen: from entering the
    alternate screen to leaving it, None if it never did)"""
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, PHOSPHOR, "attach"], dict(ENV, **(env or {})))
    out, t0, sent, start, span = b"", time.time(), False, None, None
    while time.time() - t0 < 20:
        r, _, _ = select.select([fd], [], [], 0.02)
        if r:
            try: data = os.read(fd, 4096)
            except OSError: break
            if not data: break
            out += data
            if start is None and b"\x1b[?1049h" in out:
                start = time.time()
            if start is not None and span is None and b"\x1b[?1049l" in out:
                span = time.time() - start
            if key and not sent and start is not None and span is None and "·".encode() in out:
                os.write(fd, b"x\r"); sent = True
        elif b"KEY-REACHED" in out:
            break
    try: os.close(fd)
    except OSError: pass
    os.waitpid(pid, 0)
    return out.decode("utf-8", "replace"), span

def shown(out): return "█▀█" in out

profile()
out, full = attach()
need("a returning screen gets the warm-up", shown(out) and full is not None, out)
need("the warm-up says which deck and version",
     "splash-probe · v" in out and "2 machines" in out, out)
need("then it attaches", "ZELLIJ-ATTACHED" in out, out)
need("and leaves the alternate screen before zellij", out.rfind("\x1b[?1049l") < out.find("ZELLIJ-ATTACHED"), out)

out, _ = attach()
need("the same screen back within a minute skips it (a reconnect loop)", not shown(out) and "ZELLIJ-ATTACHED" in out, out)

subprocess.run(["rm", "-rf", os.path.join(CACHE, "splash")])
out, _ = attach(env={"SSH_CONNECTION": "192.0.2.7 50000 192.0.2.1 22"})
need("another screen still gets it", shown(out), out)

subprocess.run(["rm", "-rf", os.path.join(CACHE, "splash")])
out, cut = attach(key=True)
# relative to the run with no key, not a wall clock: a loaded check.sh
# stretches python's start, never the key's effect
need("any key skips it, straight in",
     "ZELLIJ-ATTACHED" in out and cut is not None and cut < full / 2,
     "held %s s with a key, %.2fs without\n%s" % (cut and "%.2f" % cut, full, out))
need("and that key never reaches the deck", "KEY-REACHED:[]" in out, out)

for extra, why in (('theme = "paper"', "paper (e-ink) stays plain"),
                   ("splash = false", "splash = false turns it off")):
    subprocess.run(["rm", "-rf", os.path.join(CACHE, "splash")])
    profile(extra)
    out, _ = attach()
    need(why, not shown(out) and "ZELLIJ-ATTACHED" in out, out)

subprocess.run(["rm", "-rf", os.path.join(CACHE, "splash")])
profile()
r = subprocess.run([sys.executable, PHOSPHOR, "attach"], env=ENV, input="",
                   capture_output=True, text=True, timeout=20)
# No terminal: no warm-up, and zellij isn't even called -- an orphaned
# screen loop knocking every few seconds made every screen flicker. Exit 0
# so an older screen's `ssh ... && break` loop stops.
need("no terminal: no warm-up, no zellij, exit 0",
     not shown(r.stdout) and "ZELLIJ-ATTACHED" not in r.stdout and r.returncode == 0
     and "no terminal" in r.stdout, r.stdout + r.stderr)

subprocess.run(["rm", "-rf", tmp])
if fails:
    print("\n".join("FAIL: " + f for f in fails)); sys.exit(1)
print("ok")
