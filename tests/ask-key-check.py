#!/usr/bin/env python3
"""The ask key (Alt-q): in a real zellij, it opens in place of the pane
you're in, sends what that pane shows along with the question (to a fake
claude here, no tools), shows the answer, and q gives the pane back.

    python3 tests/ask-key-check.py

Needs zellij; without it, it says so and passes (same as edit-check.py).
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zjprobe

PROFILE = '''
[deck]
session = "askkey"

[[hosts]]
name = "box"
role = "brain"
local = true

[[tabs]]
name = "SYS"
panes = [ { cmd = "" } ]
'''

fails = []
def need(what, ok):
    if not ok:
        fails.append(what)

def shows(z, text, timeout=15):
    return z.wait(lambda: any(text in r for r in z.screen()), timeout)

if not zjprobe.zellij():
    print("ok — zellij isn't installed, skipping"); sys.exit(0)

with zjprobe.Probe(PROFILE, session="askkey") as z:
    got = os.path.join(z.home, "asked.txt")
    fake = os.path.join(z.home, ".local/bin/claude")
    open(fake, "w").write('#!/bin/sh\nprintf "%%s\\n" "$@" > %s\necho "THE ANSWER IS 42"\n' % got)
    os.chmod(fake, 0o755)
    need("the deck came up", z.wait(lambda: "SYS" in z.tabs(), 20))
    z.wait(lambda: any(r.strip() for r in z.screen()), 10)          # the shell's prompt
    z.keys("echo MAR''KER-$((6*7))\r", 1.0)
    need("the pane shows the marker", shows(z, "MARKER-42"))

    z.keys(b"\x1bq", 0.5)                                            # Alt-q
    need("the ask box opens over the pane", shows(z, "phosphor ask"))
    rows = z.screen()
    need("it says the pane's lines go to claude", any("go to claude" in r for r in rows))
    need("it names the tab", any("SYS" in r for r in rows if "phosphor ask" in r))
    z.wait(lambda: zjprobe.reading_keys(z, "--here"), 10)
    z.keys("what is this\r", 0.5)
    need("the answer shows", shows(z, "THE ANSWER IS 42"))
    sent = open(got).read() if os.path.exists(got) else ""
    need("claude ran with no tools", sent.startswith("--tools\n\n-p\n"))
    need("the pane's screen went along", "MARKER-42" in sent)
    need("the question came last (%r)" % sent[-60:], sent.rstrip().endswith("what is this"))
    need("the ask pane isn't what was sent", "phosphor ask" not in sent)

    z.keys("q", 0.5)
    need("q gives the pane back", z.wait(lambda: any("MARKER-42" in r for r in z.screen())
                                         and not any("THE ANSWER" in r for r in z.screen()), 10))
    panes = [p for p in json.loads(z.action("list-panes", "-a", "-j") or "[]") if not p["is_plugin"]]
    need("and nothing is left over it", len(panes) == 1)

if fails:
    print("ask-key-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ask-key-check ok")
