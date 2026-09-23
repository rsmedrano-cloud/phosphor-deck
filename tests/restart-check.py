#!/usr/bin/env python3
"""phosphor's own poll_until()/session_gone(): down/up/restart used to
spend a fixed handful of seconds (sleep(2), sleep(1)...) waiting on things
that are almost always already done well before the deadline -- kill-session,
delete-session, a SIGTERM/SIGKILL round, the deck coming back up. Polling
instead keeps the same worst case but resolves in a fraction of the time
the common case actually needs.

    python3 tests/restart-check.py

No zellij, no systemd: session_live()/session_gone() are the only things
that touch a real subprocess, and they're not exercised here -- see
tests/hotswap-live-check.py and, for the live deck itself, a real
`phosphor restart` timed before and after (not something a test does).
"""
import os, runpy, sys, time, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
# run_name != "__main__": its own `if __name__ == "__main__": sys.exit(main())`
# at the bottom never fires -- this only wants poll_until()/session_live()/
# session_gone(), not a real dispatch.
phosphor_cli = types.SimpleNamespace(**runpy.run_path(os.path.join(ROOT, "phosphor"), run_name="phosphor_cli"))

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# 1. poll_until(): returns as soon as the check passes, not at the deadline.
calls = []
def becomes_true_on_third_try():
    calls.append(1)
    return len(calls) >= 3

t0 = time.time()
ok = phosphor_cli.poll_until(becomes_true_on_third_try, timeout=5, interval=0.05)
elapsed = time.time() - t0
check("returns True once the condition is met", ok)
check("returns well before the timeout, not at it", elapsed < 1.0)
check("checked at least 3 times", len(calls) >= 3)

# 2. poll_until(): a condition that never comes true still respects the
#    timeout (the same worst case a blind sleep(timeout) always had).
t0 = time.time()
ok = phosphor_cli.poll_until(lambda: False, timeout=0.3, interval=0.05)
elapsed = time.time() - t0
check("a condition that never passes returns False", ok is False)
check("but never blocks past its own timeout", elapsed < 0.6)

# 3. poll_until(): true on the very first check returns immediately.
t0 = time.time()
ok = phosphor_cli.poll_until(lambda: True, timeout=5, interval=1)
check("an already-true condition needs no polling at all", ok and time.time() - t0 < 0.2)

# 4. session_gone()/session_live(): real zellij list-sessions output, no
#    real zellij process -- deckconf.exe swapped for a tiny fake script.
import tempfile, stat
fd, fake_zj = tempfile.mkstemp(prefix="fake-zellij-")
os.write(fd, b'#!/bin/sh\necho "deck"\necho "old-session EXITED"\n')
os.close(fd)
os.chmod(fake_zj, os.stat(fake_zj).st_mode | stat.S_IEXEC)
try:
    check("session_live() sees a real, non-exited session", phosphor_cli.session_live(fake_zj, "deck"))
    check("session_live() is false for one marked EXITED", not phosphor_cli.session_live(fake_zj, "old-session"))
    check("session_live() is false for one that isn't listed at all", not phosphor_cli.session_live(fake_zj, "nope"))
    check("session_gone() is false for a live one", not phosphor_cli.session_gone(fake_zj, "deck"))
    check("session_gone() is still false for a merely EXITED one (it's cache, not gone)",
          not phosphor_cli.session_gone(fake_zj, "old-session"))
    check("session_gone() is true for one not listed at all", phosphor_cli.session_gone(fake_zj, "nope"))
finally:
    os.unlink(fake_zj)

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
