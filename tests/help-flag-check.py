#!/usr/bin/env python3
"""`phosphor CMD --help` explains and does nothing else, for every command.

It used to fall through to the command itself: `note --help` wrote a note
titled "--help", and `restart --help` would have restarted the deck. Each
command runs in a throwaway HOME, with zellij, systemctl, ssh, tailscale
and the rest stubbed to leave a mark if anything calls them.

    python3 tests/help-flag-check.py
"""
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import commands

fails = []
tmp = tempfile.mkdtemp(prefix="phosphor-help-")
home, stubs, mark = os.path.join(tmp, "home"), os.path.join(tmp, "bin"), os.path.join(tmp, "called")
os.makedirs(home); os.makedirs(stubs)
for name in ("zellij", "systemctl", "ssh", "tailscale", "rclone", "fusermount", "journalctl",
             "loginctl", "git", "glab", "gh", "claude", "gemini", "sudo", "notify-send"):
    p = os.path.join(stubs, name)
    with open(p, "w") as f:
        f.write('#!/bin/sh\necho "%s $*" >> %s\n' % (name, mark))
    os.chmod(p, 0o755)
notes = os.path.join(tmp, "notes.md")
# A session name nothing runs under: if --help ever falls through to
# restart/down again, their reaper walks /proc (no stub stops that) and
# would kill the live deck's panes -- it did, once, on the brain.
prof = os.path.join(tmp, "deck.toml")
with open(prof, "w") as f:
    f.write('[deck]\nsession = "help-probe-%d"\n\n[[hosts]]\nname = "probe"\nrole = "brain"\nlocal = true\n'
            % os.getpid())
env = {"HOME": home, "PHOSPHOR_PROFILE": prof, "PATH": stubs + ":/usr/bin:/bin", "PHOSPHOR_NOTES": notes,
       "PHOSPHOR_DATA": os.path.join(tmp, "data"), "PHOSPHOR_CACHE": os.path.join(tmp, "cache"),
       "TERM": "dumb", "LANG": "C.UTF-8"}

cmds = [c for _, cs in commands.CATEGORIES for c, _, _ in cs]
cmds += ["deck", "tunnels", "new", "screen"]
for cmd in cmds:
    for flag in ("--help", "-h"):
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), cmd, flag], env=env,
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            fails.append("%s %s: still running after 20s" % (cmd, flag)); continue
        out = r.stdout + r.stderr
        if "phosphor" not in out.lower():
            fails.append("%s %s: says nothing about itself: %r" % (cmd, flag, out[:120]))
        if os.path.exists(mark):
            fails.append("%s %s: called %s" % (cmd, flag, open(mark).read().strip()))
            os.remove(mark)
        if os.path.exists(notes):
            fails.append("%s %s: wrote the notebook" % (cmd, flag))
            os.remove(notes)

if fails:
    print("\n".join(fails)); sys.exit(1)
print("ok: %d commands answer --help and -h without running" % len(cmds))
