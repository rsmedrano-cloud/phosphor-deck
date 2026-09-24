#!/usr/bin/env python3
"""phosphor new --here refuses when nobody's attached to the session (#39):
the exact "zellij action new-tab with no client attached" AGENTS.md warns
against, for the one call path that doesn't already prove a client is there
(a real Alt-n keypress or a tap on + does, by construction).

    python3 tests/newtab-attach-check.py

Runs a throwaway session (tests/zjprobe.py) with a client attached in a pty.
"""
import os, signal, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import zjprobe

PROFILE = '''
[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name  = "SH"
panes = [ { cmd = "" } ]
'''

fails = []
def need(what, ok):
    if not ok: fails.append(what)
    return ok

def call_here(z):
    """Runs newtab.attached()/here() as a real pane of z's session would --
    z.py() strips ZELLIJ_* for launching the client itself, so set ZELLIJ and
    ZELLIJ_SESSION_NAME back the way a pane inside the session actually has them."""
    env = dict(z.env, ZELLIJ="0", ZELLIJ_SESSION_NAME=z.session)
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, %r)\n"
                        "import newtab\n"
                        "print(newtab.attached())\n"
                        "sys.exit(newtab.here())" % os.path.join(ROOT, "lib")],
                       env=env, capture_output=True, text=True, timeout=30)
    return r.stdout.strip().splitlines()[:1], r.returncode

def main():
    if not zjprobe.zellij():
        print("no zellij here: skipped"); return 0
    with zjprobe.Probe(PROFILE) as z:
        z.pump(2)
        before = len(z.tabs())

        out, rc = call_here(z)
        need("attached() true with a real client", out == ["True"])
        need("--here exits 0 while attached", rc == 0)
        z.pump(1)
        need("--here added a tab while attached", len(z.tabs()) == before + 1)

        # no pane context at all (no $ZELLIJ): must refuse outright, never fall
        # back to zellij's own "only one session running" default -- this is
        # the exact real mistake a bare, out-of-band `phosphor new --here`
        # invocation (no env, on a box with one real session up) can make.
        after_first = len(z.tabs())
        r = subprocess.run([sys.executable, "-c",
                            "import sys; sys.path.insert(0, %r)\n"
                            "import newtab; sys.exit(newtab.here())" % os.path.join(ROOT, "lib")],
                           env={k: v for k, v in z.env.items() if not k.startswith("ZELLIJ")},
                           capture_output=True, text=True, timeout=30)
        need("--here with no $ZELLIJ at all: refuses", r.returncode != 0)
        need("--here with no $ZELLIJ at all: no new tab", len(z.tabs()) == after_first)

        # detach: kill the pty client, leave the server running (same as a dropped ssh link)
        try:
            os.kill(z.pid, signal.SIGKILL); os.waitpid(z.pid, 0)
        except OSError:
            pass
        deadline = time.time() + 10
        while time.time() < deadline:
            n = len([l for l in z.action("list-clients").splitlines() if l.strip()])
            if n <= 1:
                break
            time.sleep(0.3)
        need("session survives the client dying", z.session in z.run("list-sessions", "-n"))
        need("really nobody attached now", n <= 1)

        after = len(z.tabs())
        out, rc = call_here(z)
        need("attached() false with nobody attached", out == ["False"])
        need("--here refuses: exits non-zero", rc != 0)
        need("--here refused: no new tab", len(z.tabs()) == after)

    if fails:
        print("newtab-attach-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
    print("newtab-attach-check ok")

if __name__ == "__main__":
    main()
