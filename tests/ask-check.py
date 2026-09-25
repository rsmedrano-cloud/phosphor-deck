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
check("agy -p", ask.command("agy", "hi") == ["agy", "-p", "hi"])
check("agy is in the picking order too", "agy" in ask.ORDER)

# prompt(): piped text as context, the question, or both together
check("just a question", ask.prompt(["hi", "there"], "") == "hi there")
check("just piped text (no question)", ask.prompt([], "the diff") == "the diff")
check("both: piped first, then the question",
      ask.prompt(["what", "changed"], "the diff") == "the diff\n\nwhat changed")
check("neither: empty", ask.prompt([], "") == "")

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

# main(): CLI parsing, never shells out to a real assistant in this test.
# Every call pins down stdin explicitly (a tty with nothing piped, by
# default) -- main() reads stdin whenever isatty() is false, and this
# process's own real stdin, inherited from whatever ran the test, must never
# be the thing it reads: piped or not, closed or not, is not ours to assume.
import contextlib, io
class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty
    def isatty(self):
        return self._tty

def run(argv, piped=None):
    saved_argv, saved_stdin = sys.argv, sys.stdin
    sys.argv = ["phosphor-ask"] + argv
    sys.stdin = FakeStdin(piped, tty=False) if piped is not None else FakeStdin(tty=True)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = ask.main()
    finally:
        sys.argv, sys.stdin = saved_argv, saved_stdin
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

    seen.clear()
    rc, out = run(["what", "changed"], piped="the diff")
    check("piped + question: combined, runs", rc == 0)
    check("piped text comes first", seen and seen[-1] == ["claude", "-p", "the diff\n\nwhat changed"])

    seen.clear()
    rc, out = run([], piped="just the piped text")
    check("piped only, no question: still runs", rc == 0)
    check("piped text alone is the prompt", seen and seen[-1] == ["claude", "-p", "just the piped text"])

    seen.clear()
    rc, out = run([], piped="")
    check("piped but empty, no question: still refuses", rc == 1 and "usage" in out)
    check("empty pipe: never runs anything", not seen)
finally:
    ask.newtab.have = real_have
    ask.subprocess.run = real_run

if fails:
    print("ask-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ask-check ok")
