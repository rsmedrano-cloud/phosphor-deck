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
finally:
    panel.subprocess.run, panel.deckconf.load, panel.deckconf.hosts = real_run, real_load, real_hosts
    edit.pick = real_edit_pick
    builtins.input = real_input

if fails:
    print("panel-actions-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("panel-actions-check ok")
