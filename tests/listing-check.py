#!/usr/bin/env python3
"""Every zellij listing in lib/ is read through proc.listing/proc.layout,
and every pane's screen through proc.screen, which ask again on an empty,
unreadable or crossed answer (#134, #135; zellij 0.45 hands one action
another's answer, #122). Against a fake zellij:
    python3 tests/listing-check.py
"""
import glob, os, re, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import tempfile
os.environ["PHOSPHOR_CACHE"] = tempfile.mkdtemp(prefix="listing-check-")   # act's log, never the deck's
import deckconf, proc
deckconf.session_started = lambda sess: None   # no zellij server here, whatever runs on this machine

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

TABS = '[{"tab_id": 0, "position": 0, "name": "AI"}]'
PANES = '[{"id": 1, "is_plugin": false, "tab_id": 0}]'
LAYOUT = 'layout {\n    tab name="AI" {\n        pane\n    }\n}\n'

def answers(*seq):
    """A fake proc.action giving (exit code, stdout) from seq, the last
    one for good; it counts what it was asked."""
    asked = []
    def action(sess, args, timeout=15):
        asked.append((sess,) + tuple(args))
        rc, out, *err = seq[min(len(asked), len(seq)) - 1]
        return subprocess.CompletedProcess(args, rc, out, err[0] if err else "")
    proc.action = action
    return asked

real = proc.action
try:
    asked = answers((0, PANES))
    check("a good answer is read at once", proc.listing("s", "list-panes", "-a", "-j") == [
        {"id": 1, "is_plugin": False, "tab_id": 0}] and len(asked) == 1)
    check("the session and the flags reach zellij", asked[0] == ("s", "list-panes", "-a", "-j"))

    asked = answers((0, ""), (0, "not json"), (0, PANES))
    check("busy (empty, unreadable) is asked again", len(proc.listing(None, "list-panes", "-a", "-j")) == 1
          and len(asked) == 3)

    asked = answers((0, TABS), (0, PANES))
    got = proc.listing(None, "list-panes", "-a", "-j")
    check("list-panes handed the tabs is asked again (#122)", got and "is_plugin" in got[0] and len(asked) == 2)
    asked = answers((0, PANES), (0, TABS))
    got = proc.listing(None, "list-tabs", "-j")
    check("list-tabs handed the panes is asked again", got and "position" in got[0] and len(asked) == 2)

    answers((0, "[1, 2]"))
    t0 = time.time()
    check("never readable: [] once the wait is up", proc.listing(None, "list-tabs", "-j", wait=0.5) == [])
    check("... not before it", time.time() - t0 >= 0.5)

    asked = answers((1, ""))
    check("zellij failing (no such session) is believed at once",
          proc.listing("gone", "list-tabs", "-j") == [] and len(asked) == 1)

    # #113: inside a session, under load, zellij's CLI says it isn't there
    GONE = (1, "", "There is no active session!\n")
    os.environ["ZELLIJ_SESSION_NAME"] = "probe"
    asked = answers(GONE, (0, PANES))
    check("inside a session, 'no active session' about it is asked again (#113)",
          len(proc.listing(None, "list-panes", "-a", "-j")) == 1 and len(asked) == 2)
    asked = answers(GONE)
    check("... the same about a session named is believed at once",
          proc.listing("gone", "list-tabs", "-j") == [] and len(asked) == 1)
    asked = answers((1, "", "some other error\n"))
    check("... another failure is believed at once", proc.listing(None, "list-tabs", "-j") == [] and len(asked) == 1)
    asked = answers(GONE, (0, LAYOUT))
    check("... dump-layout asks again", proc.layout() == LAYOUT and len(asked) == 2)
    asked = answers(GONE, (0, "$ \n"))
    check("... dump-screen asks again", proc.screen(None, "terminal_3") == "$ \n" and len(asked) == 2)
    asked = answers(GONE)
    check("... dump-screen never answering: '' (no answer), not None (no pane)",
          proc.screen(None, "terminal_3", wait=0.3) == "")
    asked = answers(GONE, (0, "done"))
    check("an action that didn't reach zellij is sent again", proc.act("focus-last-pane") == "done" and len(asked) == 2)
    asked = answers((1, "", "no pane\n"))
    check("... one that failed there is not", proc.act("close-pane") == "" and len(asked) == 1)
    del os.environ["ZELLIJ_SESSION_NAME"]
    asked = answers(GONE)
    t0 = time.time()
    check("outside a session, 'no active session' is believed at once",
          proc.listing(None, "list-tabs", "-j") == [] and len(asked) == 1 and time.time() - t0 < 0.5)

    # #137: under load, about a named session that's there, zellij's CLI says
    # it isn't (exit 0), listing it among the active ones: the action never got there
    MISSED = (0, "\x1b[32;1mdeck-phone\x1b[m [Created 5s ago] \n\x1b[32;1mdeck\x1b[m [Created 9s ago] \n",
              "Session 'deck' not found. The following sessions are active:\n")
    asked = answers(MISSED, (0, "7\n"))
    check("a named session that's there but 'not found' gets the action again (#137)",
          proc.act("new-tab", sess="deck") == "7\n" and len(asked) == 2 and asked[1][0] == "deck")
    asked = answers(MISSED, (0, TABS))
    check("... and its listing is asked again", len(proc.listing("deck", "list-tabs", "-j")) == 1 and len(asked) == 2)
    asked = answers((1, "", "Session 'gone' not found. The following sessions are active:\ndeck\n"))
    check("... one that really isn't among them is believed at once",
          proc.act("new-tab", sess="gone") == "" and len(asked) == 1)
    asked = answers((1, "", "Session 'dec' not found. The following sessions are active:\ndeck\n"))
    check("... a name only the start of another's is not there", proc.act("new-tab", sess="dec") == "" and len(asked) == 1)
    asked = answers((1, "", "Session 'deck' not found. The following sessions are active:\n"), (0, "7\n"))
    deckconf.session_started = lambda sess: 1.0 if sess == "deck" else None
    check("... left out of that list too, while its server runs: sent again",
          proc.act("new-tab", sess="deck") == "7\n" and len(asked) == 2)
    asked = answers((1, "", "Session 'gone' not found. The following sessions are active:\n"))
    check("... no server of that name: believed at once", proc.act("new-tab", sess="gone") == "" and len(asked) == 1)
    deckconf.session_started = lambda sess: None
    asked = answers(MISSED)
    t0 = time.time()
    check("... never reached: '' once the wait is up", proc.act("new-tab", sess="deck", wait=0.5) == ""
          and 0.5 <= time.time() - t0 < 2)

    asked = answers((0, ""), (0, TABS), (0, LAYOUT))
    check("dump-layout: busy and crossed answers asked again", proc.layout() == LAYOUT and len(asked) == 3)
    answers((0, TABS))
    check("dump-layout never real: ''", proc.layout(wait=0.3) == "")

    SCREEN = "$ ls\nhidden-42\n$ \n"
    asked = answers((0, SCREEN))
    check("dump-screen: a screen is read at once", proc.screen("s", "terminal_3") == SCREEN and len(asked) == 1)
    check("dump-screen: the session, pane and flags reach zellij",
          asked[0] == ("s", "dump-screen", "-p", "terminal_3"))
    asked = answers((0, SCREEN))
    proc.screen(None, "terminal_3", "--full")
    check("dump-screen: --full reaches zellij", asked[0] == (None, "dump-screen", "-p", "terminal_3", "--full"))
    asked = answers((0, ""), (0, SCREEN))
    check("dump-screen: an empty answer (busy) is asked again (#135)",
          proc.screen("s", "terminal_3") == SCREEN and len(asked) == 2)
    asked = answers((0, PANES), (0, LAYOUT), (0, "CLIENT_ID ZELLIJ_PANE_ID\n1 terminal_0\n"), (0, SCREEN))
    check("dump-screen: another action's answer is asked again, never the screen",
          proc.screen("s", "terminal_3") == SCREEN and len(asked) == 4)
    asked = answers((0, "\n"))
    check("dump-screen: a blank pane (a newline) is believed at once", proc.screen("s", "terminal_3") == "\n"
          and len(asked) == 1)
    asked = answers((0, '$ cat x.json\n{"a": 1}\n$ \n'))
    check("dump-screen: JSON on a screen with more on it is the screen",
          proc.screen("s", "terminal_3").startswith("$ cat") and len(asked) == 1)
    answers((0, ""))
    t0 = time.time()
    check("dump-screen never answered: '' once the wait is up", proc.screen("s", "terminal_3", wait=0.4) == "")
    check("... not before it", time.time() - t0 >= 0.4)
    asked = answers((1, ""))
    check("dump-screen: zellij failing (no such pane) is None at once",
          proc.screen("s", "terminal_9") is None and len(asked) == 1)
finally:
    proc.action = real
    import shutil
    shutil.rmtree(os.environ["PHOSPHOR_CACHE"], ignore_errors=True)

# nothing in lib/ asks zellij for a listing or a screen by itself
LISTS = re.compile(r"""["'](list-tabs|list-panes|dump-layout)["']""")
for f in sorted(glob.glob(os.path.join(ROOT, "lib", "*.py"))):
    if os.path.basename(f) == "proc.py":
        continue
    for n, line in enumerate(open(f), 1):
        if LISTS.search(line) and not re.search(r"\b(listing|layout)\(", line):
            check("%s:%d reads a zellij listing itself; use proc.listing/proc.layout"
                  % (os.path.relpath(f, ROOT), n), False)
        # dump-screen to a file (--path) leaves the text to whoever reads the file
        if re.search(r"""["']dump-screen["']""", line) and "--path" not in line:
            check("%s:%d reads a pane's screen itself; use proc.screen"
                  % (os.path.relpath(f, ROOT), n), False)

for f in fails:
    print("FAIL:", f)
print("listing-check", "ok" if not fails else "FAILED")
sys.exit(1 if fails else 0)
