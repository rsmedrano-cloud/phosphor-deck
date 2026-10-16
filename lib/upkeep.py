#!/usr/bin/env python3
"""phosphor upkeep - upgrade or reboot a machine of the fleet, where you see it.

FLEET already says when a host has updates pending or wants a reboot.
This does the one thing about it, in the open: it says what it's about to
run and on which machine, waits for you, then runs it over `ssh -t` in
this very terminal, so sudo asks you for its password and you watch every
line. Nothing runs on a watched host behind your back; FLEET's u and b
keys open it in a tab of its own; a SolarOS panel's fleet runs it in place.

    phosphor upkeep upgrade HOST   the host's own package manager: apt, dnf,
                                   pacman, zypper or apk, whichever it has
    phosphor upkeep reboot HOST    sudo systemctl reboot, once you type its name

HOST is a name from the profile's [[hosts]] (what FLEET shows on a card).
"""
import os, shlex, subprocess, sys, termios
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, FG, PH, AMB, RST, OK, BAD
import deckconf

USAGE = "usage: phosphor upkeep (upgrade | reboot) HOST"

# Run on the host by sh: the first package manager it has, its upgrade asking
# as usual (apt and dnf still say what they'll change and wait for a y).
UPGRADE = ("if command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get upgrade; "
           "elif command -v dnf >/dev/null 2>&1; then sudo dnf upgrade; "
           "elif command -v pacman >/dev/null 2>&1; then sudo pacman -Syu; "
           "elif command -v zypper >/dev/null 2>&1; then sudo zypper update; "
           "elif command -v apk >/dev/null 2>&1; then sudo apk upgrade; "
           "else echo 'no package manager phosphor knows (apt, dnf, pacman, zypper, apk)'; exit 3; fi")
REBOOT = "sudo systemctl reboot"

def where(name, prof=None):
    """(name, ssh target | None for this machine), or None for a name the
    fleet doesn't watch."""
    prof = prof if prof is not None else (deckconf.load()[0] or {})
    for n, t in deckconf.fleet_hosts(prof):
        if n == name:
            return n, t
    return None

def argv(what, target):
    """What runs: over ssh -t to target, or here for this machine."""
    script = UPGRADE if what == "upgrade" else REBOOT
    if target:
        return ["ssh", "-t", target, "sh -c %s" % shlex.quote(script)]
    return ["sh", "-c", script]

def ask(prompt):
    """input(), after dropping whatever was typed before the question (a
    wheel's Enter that bounced must not answer it)."""
    try:
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (termios.error, OSError, ValueError, AttributeError):
        pass
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return None

def run(what, name, prof=None):
    got = where(name, prof)
    if not got:
        print(BAD + " " + FG + "%s isn't a machine the fleet watches (phosphor fleet --json lists them)" % name + RST)
        return 2
    name, target = got
    if not sys.stdin.isatty():
        print(BAD + " " + FG + "upkeep waits for you at a terminal: it never runs unattended" + RST)
        return 2
    cmd = argv(what, target)
    print(FG + ("upgrade " if what == "upgrade" else "reboot ") + PH + name + RST +
          DIM + ("  (this machine)" if not target else "  (ssh %s)" % target) + RST)
    print(DIM + "  runs: " + " ".join(shlex.quote(c) for c in cmd) + RST)
    if what == "reboot":
        if not target:
            print(AMB + "  this is the brain: the deck and every screen on it go down with it" + RST)
        a = ask(FG + "  type " + PH + name + RST + FG + " to reboot it, anything else leaves: " + RST)
        if a is None or a.strip() != name:
            print(DIM + "  left alone" + RST); return 1
    else:
        a = ask(FG + "  Enter runs it, q leaves: " + RST)
        if a is None or a.strip().lower().startswith("q"):
            print(DIM + "  left alone" + RST); return 1
    try:
        rc = subprocess.call(cmd)
    except KeyboardInterrupt:
        rc = 130
    except OSError as e:
        print(BAD + " " + FG + str(e) + RST); rc = 127
    print((OK if rc == 0 else BAD) + " " + FG + "%s %s: %s" % (what, name, "done" if rc == 0 else "exit %d" % rc) + RST)
    return rc

def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print(USAGE); return 0
    if len(a) != 2 or a[0] not in ("upgrade", "reboot"):
        print(USAGE); return 2
    return run(a[0], a[1])

if __name__ == "__main__":
    sys.exit(main() or 0)
