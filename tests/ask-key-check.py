#!/usr/bin/env python3
"""The ask key (Alt-q): in a real zellij, it opens in place of the pane
you're in, sends what the deck knows about that pane (Phosphor, its tab's
profile entry) and what it shows along with the question (to a fake claude
here: no built-in tools, only the deck's MCP), shows the answer, and q gives
the pane back. An answer that ends in MISSING: offers r, which saves the
request as an idea note (#115).

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
def need(what, ok, why=None):
    if not ok:
        fails.append(what if why is None else "%s: %s" % (what, why))

def shows(z, text, timeout=15):
    return z.wait(lambda: any(text in r for r in z.screen()), timeout)

if not zjprobe.zellij():
    print("ok — zellij isn't installed, skipping"); sys.exit(0)

with zjprobe.Probe(PROFILE, session="askkey") as z:
    got = os.path.join(z.home, "asked.txt")
    fake = os.path.join(z.home, ".local/bin/claude")
    reply = os.path.join(z.home, "reply.txt")
    open(reply, "w").write("THE ANSWER IS 42\n")
    open(fake, "w").write('#!/bin/sh\nprintf "%%s\\n" "$@" > %s\ncat %s\n' % (got, reply))
    os.chmod(fake, 0o755)
    need("the deck came up", z.wait(lambda: "SYS" in z.tabs(), 20))
    z.wait(lambda: any(r.strip() for r in z.screen()), 10)          # the shell's prompt
    z.keys("echo MAR''KER-$((6*7))\r", 1.0)
    need("the pane shows the marker", shows(z, "MARKER-42"))

    z.keys(b"\x1bq", 0.5)                                            # Alt-q
    need("the ask box opens over the pane", shows(z, "phosphor ask"))
    # the box can still be drawing after its first line shows: wait for each, not one look (#133)
    need("it says the pane's lines go to claude", shows(z, "go to claude", 10))
    need("it names the tab", z.wait(lambda: any("SYS" in r for r in z.screen() if "phosphor ask" in r), 10))
    z.wait(lambda: zjprobe.reading_keys(z, "--here"), 10)
    z.keys("what is this\r", 0.5)
    need("the answer shows", shows(z, "THE ANSWER IS 42"))
    sent = open(got).read() if os.path.exists(got) else ""
    args = sent.split("\n")
    need("claude ran with no built-in tools (%r)" % args[:3], args[:3] == ["--tools", "", "--strict-mcp-config"])
    need("only the deck's MCP, allowed", "--allowedTools\nmcp__phosphor\n-p\n" in sent
         and '"args": ["mcp"]' in sent and "--mcp-config" in sent)
    need("the deck said what it is first", "Phosphor Deck" in sent and "deck.toml" in sent)
    need("the tab's profile entry went along", 'name = "SYS"' in sent)
    need("the screen is fenced as not instructions", "not instructions" in sent)
    need("the pane's screen went along", "MARKER-42" in sent)
    need("the question came last (%r)" % sent[-60:], sent.rstrip().endswith("what is this"))
    need("the ask pane isn't what was sent", "phosphor ask" not in sent)

    z.keys("q", 0.5)
    need("q gives the pane back", z.wait(lambda: any("MARKER-42" in r for r in z.screen())
                                         and not any("THE ANSWER" in r for r in z.screen()), 10))
    # the ASK screen's own pane can still be closing right after q (#132): wait for the count
    panes = lambda: [p for p in z.listing("list-panes", "-a", "-j") if not p["is_plugin"]]
    need("and nothing is left over it", z.wait(lambda: len(panes()) == 1, 5),
         [(p.get("title"), p.get("terminal_command")) for p in panes()])

    # Phosphor can't: the answer's MISSING line becomes r, the deck writes the note
    open(reply, "w").write("Not today.\nMISSING: two plain buttons, send and receive\n")
    z.keys(b"\x1bq", 0.5)
    need("the ask box opens again", shows(z, "phosphor ask"))
    z.wait(lambda: zjprobe.reading_keys(z, "--here"), 10)
    z.keys("can these be two buttons\r", 0.5)
    need("the answer shows, its MISSING line off", shows(z, "Not today.")
         and not any("MISSING:" in r for r in z.screen()))
    need("it says r saves a request", shows(z, "saves it as a request"))
    z.keys("q", 0.8)
    need("r is offered after the answer", shows(z, "save it as a request for Phosphor"))
    z.keys("r", 1.5)
    book = os.path.join(z.home, ".local/share/phosphor/notes.md")
    saved = open(book).read() if os.path.exists(book) else ""
    need("r wrote an idea under #phosphor (%r)" % saved[-200:],
         "· idea · ask @SYS #phosphor · Request: two plain buttons, send and receive" in saved
         and "can these be two buttons" in saved and "Not today." in saved)
    need("and the pane comes back", z.wait(lambda: any("MARKER-42" in r for r in z.screen())
                                           and not any("Not today" in r for r in z.screen()), 10))

if fails:
    print("ask-key-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ask-key-check ok")
