#!/usr/bin/env python3
"""phosphor ask: picks an installed assistant, builds the right one-shot
command for it, and never actually shells out to a real one here.

    python3 tests/ask-check.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import ask

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# command(): the right headless flag per assistant, question last
check("claude -p", ask.command("claude", "hi") == ["claude", "-p", "hi"])
check("gemini -p", ask.command("gemini", "hi") == ["gemini", "-p", "hi"])
check("codex exec", ask.command("codex", "hi") == ["codex", "exec", "hi"])
check("opencode run", ask.command("opencode", "hi") == ["opencode", "run", "hi"])
check("aider --message", ask.command("aider", "hi") ==
      ["aider", "--yes-always", "--message", "hi"])

# pick(): first installed in ORDER, or the named one if it's installed and known
real_have = ask.newtab.have
try:
    ask.newtab.have = lambda b: b in ("gemini", "opencode")
    check("first installed in order wins", ask.pick() == "gemini")
    check("named + installed: that one", ask.pick("opencode") == "opencode")
    check("named but not installed: none", ask.pick("claude") is None)
    check("named but unknown to ask: none", ask.pick("aichat") is None)

    ask.newtab.have = lambda b: False
    check("nothing installed: none", ask.pick() is None)
finally:
    ask.newtab.have = real_have

# main(): CLI parsing, never shells out to a real assistant in this test
import contextlib, io
def run(argv):
    saved = sys.argv
    sys.argv = ["phosphor-ask"] + argv
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = ask.main()
    finally:
        sys.argv = saved
    return rc, out.getvalue()

real_have = ask.newtab.have
try:
    ask.newtab.have = lambda b: False
    rc, out = run(["a", "question"])
    check("no assistant installed: exits 1", rc == 1)
    check("no assistant installed: says so", "no assistant installed" in out)

    rc, out = run([])
    check("no question: exits 1", rc == 1 and "usage" in out)

    rc, out = run(["--assistant"])
    check("--assistant with no name: exits 1", rc == 1)

    ask.newtab.have = lambda b: b == "claude"
    rc, out = run(["--assistant", "gemini", "hi"])
    check("--assistant names one not installed: exits 1", rc == 1 and "gemini" in out)

    seen = []
    class FakeResult:
        returncode = 0
    real_run = ask.subprocess.run
    ask.subprocess.run = lambda cmd, **kw: (seen.append(cmd), FakeResult())[1]
    rc, out = run(["what", "was", "that", "command"])
    check("runs the picked assistant", rc == 0)
    check("joins the question", seen and seen[-1] == ["claude", "-p", "what was that command"])
finally:
    ask.newtab.have = real_have
    ask.subprocess.run = real_run

if fails:
    print("ask-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ask-check ok")
