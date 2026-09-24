#!/usr/bin/env python3
"""phosphor web on: never restarts the live deck on its own without either
a human at a tty (Enter) or an explicit --yes -- see GitLab #38.

    python3 tests/web-check.py
"""
import io, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import web

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# Stub out everything `on()` touches besides the restart decision itself:
# no real profile, tailscale, zellij or clipboard here.
web.deckconf.load = lambda: ({"deck": {"session": "deck"}}, "t")
web.usable = lambda prof: (False, "it needs tailscale")
web.set_flag = lambda on: None
web.publish = lambda prof: True
web.zj = lambda *a: type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
web.token = lambda: 0
web.local_help = lambda why: None
web.show_url = lambda prof: None

calls = []
real_run = web.subprocess.run
def fake_run(cmd, **kw):
    calls.append(cmd)
    return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
web.subprocess.run = fake_run

def restarted():
    return any(c[-1] == "restart" for c in calls)

real_isatty = sys.stdin.isatty
import builtins
real_input = builtins.input

def with_tty(isatty, input_fn, fn):
    sys.stdin.isatty = lambda: isatty
    builtins.input = input_fn
    try:
        return fn()
    finally:
        sys.stdin.isatty = real_isatty
        builtins.input = real_input

not_reached = lambda *a: fails.append("input() shouldn't be called without a tty") or ""

import contextlib
try:
    with contextlib.redirect_stdout(io.StringIO()):
        # a tty, human presses Enter: restarts
        calls.clear()
        with_tty(True, lambda *_: "", lambda: web.on(yes=False))
        check("tty + Enter: restarts", restarted())

        # no tty, no --yes: does NOT restart on its own
        calls.clear()
        with_tty(False, not_reached, lambda: web.on(yes=False))
        check("no tty, no --yes: doesn't restart", not restarted())

        # no tty, --yes: restarts (the explicit opt-in)
        calls.clear()
        with_tty(False, not_reached, lambda: web.on(yes=True))
        check("no tty, --yes: restarts", restarted())

        # main(): --yes / -y are parsed out of argv and never reach `cmd`
        calls.clear()
        saved_argv = sys.argv
        try:
            sys.argv = ["phosphor-web", "on", "--yes"]
            with_tty(False, not_reached, lambda: web.main())
        finally:
            sys.argv = saved_argv
        check("main(): `web on --yes` restarts", restarted())
finally:
    web.subprocess.run = real_run

if fails:
    print("web-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("web-check ok")
