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
stub("zellij", 'case "$1" in attach) exec "%s" -c "%s";; esac' % (sys.executable, (
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

def attach(key_after=None, env=None):
    """Run it; optionally press a key after that many seconds. (output, seconds until zellij)"""
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, [sys.executable, PHOSPHOR, "attach"], dict(ENV, **(env or {})))
    out, t0, sent, at = b"", time.time(), False, None
    while time.time() - t0 < 10:
        if key_after is not None and not sent and time.time() - t0 >= key_after:
            os.write(fd, b"x\r"); sent = True
        r, _, _ = select.select([fd], [], [], 0.02)
        if r:
            try: data = os.read(fd, 4096)
            except OSError: break
            if not data: break
            out += data
            if at is None and b"ZELLIJ-ATTACHED" in out:
                at = time.time() - t0
        elif b"KEY-REACHED" in out:
            break
    took = at if at is not None else time.time() - t0
    try: os.close(fd)
    except OSError: pass
    os.waitpid(pid, 0)
    return out.decode("utf-8", "replace"), took

def shown(out): return "█▀█" in out

profile()
out, _ = attach()
need("a returning screen gets the warm-up", shown(out), out)
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
out, took = attach(key_after=0.15)
need("any key skips it, straight in", "ZELLIJ-ATTACHED" in out and took < 0.6, "took %.2fs\n%s" % (took, out))
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
need("no terminal, no warm-up", not shown(r.stdout) and "ZELLIJ-ATTACHED" in r.stdout, r.stdout + r.stderr)

subprocess.run(["rm", "-rf", tmp])
if fails:
    print("\n".join("FAIL: " + f for f in fails)); sys.exit(1)
print("ok")
