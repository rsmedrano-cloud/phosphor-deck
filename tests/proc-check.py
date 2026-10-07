#!/usr/bin/env python3
"""lib/proc.py is how every module runs another program: zellij by its
real path, run()/sh() that never raise, ssh() that never asks. And no
module goes back to building its own.

    python3 tests/proc-check.py
"""
import glob, os, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp()
import proc

fails = []
def check(what, ok):
    if not ok: fails.append(what)

r = proc.run(["no-such-program-phosphor"])
check("a missing program is exit -1, not an exception", r.returncode == -1 and r.stderr)
r = proc.run(["sleep", "5"], timeout=0.2)
check("a timeout is exit -1, not an exception", r.returncode == -1)
r = proc.run(["cat"], input="hi")
check("input reaches the program, text comes back", r.returncode == 0 and r.stdout == "hi")
check("a string runs through sh", proc.sh("echo a | tr a b") == (0, "b"))
check("sh: stdout only", proc.sh("echo out; echo err >&2") == (0, "out"))
check("sh: stderr too with err=True", proc.sh("echo out; echo err >&2", err=True) == (0, "out\nerr"))
check("sh: the exit code", proc.sh(["sh", "-c", "exit 3"])[0] == 3)

a = proc.ssh("db-box", "sh -s")
check("ssh never asks: BatchMode", a[:3] == ["ssh", "-o", "BatchMode=yes"])
check("ssh: target and command last, as two args", a[-2:] == ["db-box", "sh -s"])
check("ssh: ConnectTimeout", "ConnectTimeout=10" in a and "ConnectTimeout=6" in proc.ssh("db-box", "true", 6))
check("ssh: no ControlMaster unless asked", not any("Control" in x for x in a))
p = proc.ssh("db-box", "sh -s", persist="60s")
ctrl = [x for x in p if x.startswith("ControlPath=")]
check("ssh persist: FLEET's ControlMaster socket", "ControlPersist=60s" in p and "ControlMaster=auto" in p
      and ctrl and os.path.isdir(os.path.dirname(ctrl[0][len("ControlPath="):])))

z = proc.zellij()
check("zellij(): a runnable path or None", z is None or os.access(z, os.X_OK))

# nobody builds their own again (ssh lines inside generated units, scripts
# and rclone configs are another program's text, not an argv we run)
for f in sorted(glob.glob(os.path.join(REPO, "lib", "*.py"))) + [os.path.join(REPO, "phosphor")]:
    if f.endswith(("proc.py", "deckconf.py")): continue
    src, name = open(f).read(), os.path.relpath(f, REPO)
    check("%s builds its own BatchMode ssh argv: use proc.ssh()" % name, '"BatchMode=yes"' not in src)
    check("%s runs a BatchMode ssh through a shell string: use proc.ssh()" % name,
          'sh("ssh -o BatchMode' not in src)
    check("%s looks zellij up itself: use proc.zellij()" % name,
          "local/bin/zellij" not in src and 'which("zellij")' not in src)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
