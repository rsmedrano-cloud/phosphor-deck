#!/usr/bin/env python3
"""phosphor panel: the DECK tab's action keys, especially the two that pick
a host first (triage, tail) -- no real terminal, no real subprocess.

    python3 tests/panel-actions-check.py
"""
import builtins, io, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import panel

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# ACTIONS: every key is unique, "g" and "j" are the new ones, both free
keys = [a[0] for a in panel.ACTIONS]
check("no duplicate action keys", len(keys) == len(set(keys)))
check("g (triage) is in the action list", "g" in keys)
check("j (tail) is in the action list", "j" in keys)

real_run, real_load, real_hosts = panel.subprocess.run, panel.deckconf.load, panel.deckconf.hosts
real_input = builtins.input
ran = []
panel.subprocess.run = lambda cmd, **kw: ran.append(cmd)

import edit
real_edit_pick = edit.pick

def run_act(k, st=None):
    saved = sys.stdout
    sys.stdout = io.StringIO()
    try:
        panel.act(k, st or {})
    finally:
        sys.stdout = saved

try:
    # g: no host picking of its own -- triage does that internally.
    # pause() afterwards is a bare input() too (so the AI's answer isn't
    # wiped by the next redraw before anyone reads it) -- mocked the same way.
    builtins.input = lambda *a, **kw: ""
    ran.clear()
    run_act("g")
    check("g runs phosphor triage with no host", ran and ran[-1][-1:] == ["triage"])

    # j: no hosts in the profile at all -- says so, never touches edit.pick
    panel.deckconf.load = lambda: ({}, "t")
    panel.deckconf.hosts = lambda prof: []
    edit.pick = lambda *a, **kw: fails.append("edit.pick called with no hosts")
    ran.clear()
    run_act("j")
    check("j with no hosts: never runs anything", not ran)

    # j: hosts exist, pick one, give a service name
    panel.deckconf.hosts = lambda prof: [{"name": "nimbus", "role": "desktop"},
                                          {"name": "relay", "role": "storage"}]
    edit.pick = lambda title, items: items[0]        # picks "nimbus"
    builtins.input = lambda *a, **kw: "docker/jellyfin"
    ran.clear()
    run_act("j")
    check("j: runs phosphor tail HOST SERVICE from the picks",
          ran and ran[-1][-3:] == ["tail", "nimbus", "docker/jellyfin"])

    # j: hosts exist, pick one, leave the service blank -- no trailing empty arg
    builtins.input = lambda *a, **kw: ""
    ran.clear()
    run_act("j")
    check("j: a blank service means just HOST, no empty argument tacked on",
          ran and ran[-1][-2:] == ["tail", "nimbus"])

    # j: backs out of the picker -- nothing runs
    edit.pick = lambda title, items: None
    ran.clear()
    run_act("j")
    check("j: backing out of the picker runs nothing", not ran)

    # j: Ctrl-C at the service prompt -- treated like a blank service, not a crash
    edit.pick = lambda title, items: items[0]
    def raise_kb(*a, **kw): raise KeyboardInterrupt
    builtins.input = raise_kb
    ran.clear()
    run_act("j")
    check("j: Ctrl-C at the service prompt still runs tail with no service",
          ran and ran[-1][-2:] == ["tail", "nimbus"])

    # every action goes back the same way: the ones that end on their own
    # output wait on back() (q, Esc, Enter), never on an "Enter to go back"
    # input(); the rest open a TUI that takes q itself.
    import init, tunnels
    real_yes, real_tunnels, real_back = init.yes, tunnels.interactive, panel.back
    prompts, backs = [], []
    builtins.input = lambda *a, **kw: prompts.append(a[0] if a else "") or ""
    init.yes = lambda *a, **kw: True
    tunnels.interactive = lambda: None
    panel.back = lambda *a, **kw: backs.append(1)
    panel.getkey = lambda timeout=None: "q"
    edit.pick = lambda title, items: None
    waits = {"p", "k", "g", "d", "l", "u", "r", "h", "w"}
    try:
        for k in keys:
            backs.clear(); prompts.clear()
            run_act(k, {"web": False})
            check("%s: never asks 'Enter to go back' through input()" % k,
                  not any("go back" in p for p in prompts))
            if k in waits:
                check("%s: waits on back() (q, Esc, Enter) after its output" % k, backs == [1])
        # web already on: q at its t/o prompt goes straight back, nothing runs
        backs.clear(); ran.clear()
        run_act("w", {"web": True})
        check("w (web on): q at t/o goes back without running anything else",
              not backs and ran and ran[-1][-2:] == ["web", "status"])
    finally:
        init.yes, tunnels.interactive, panel.back = real_yes, real_tunnels, real_back
        panel.getkey = __import__("ui").getkey
finally:
    panel.subprocess.run, panel.deckconf.load, panel.deckconf.hosts = real_run, real_load, real_hosts
    edit.pick = real_edit_pick
    builtins.input = real_input

# ui.back() itself, on a real terminal: q, Esc and Enter go back, a stray key doesn't
import pty, select, subprocess, time
def back_on_pty(keys):
    m, s = pty.openpty()
    p = subprocess.Popen([sys.executable, "-c",
                          "import sys; sys.path.insert(0, %r); import ui; ui.back(); print('BACK')"
                          % os.path.join(ROOT, "lib")], stdin=s, stdout=s, stderr=s, close_fds=True)
    os.close(s)
    time.sleep(0.5)
    for key in keys:
        os.write(m, key); time.sleep(0.3)
    try:
        done = p.wait(timeout=3) == 0
    except subprocess.TimeoutExpired:
        done = False
        p.kill(); p.wait()
    out = b""
    while select.select([m], [], [], 0.1)[0]:
        try: out += os.read(m, 4096)
        except OSError: break
    done = done and b"BACK" in out
    os.close(m)
    return done
for name, key in (("q", b"q"), ("Esc", b"\x1b"), ("Enter", b"\r")):
    check("back(): %s goes back" % name, back_on_pty([key]))
check("back(): a stray key doesn't go back", not back_on_pty([b"x"]))

if fails:
    print("panel-actions-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("panel-actions-check ok")
