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

# no assistant installed as far as these checks know: commands by their bare names
import tempfile, newtab
newtab.BIN, os.environ["PATH"] = tempfile.mkdtemp(), tempfile.mkdtemp()

# command(): the right headless flag per assistant, question last
check("claude -p", ask.command("claude", "hi") == ["claude", "-p", "hi"])
check("gemini -p", ask.command("gemini", "hi") == ["gemini", "-p", "hi"])
check("codex exec", ask.command("codex", "hi") == ["codex", "exec", "hi"])
check("opencode run", ask.command("opencode", "hi") == ["opencode", "run", "hi"])
check("aider --message", ask.command("aider", "hi") ==
      ["aider", "--yes-always", "--message", "hi"])
check("agy -p", ask.command("agy", "hi") == ["agy", "-p", "hi"])
check("agy is in the picking order too", "agy" in ask.ORDER)

# readonly (triage): every assistant has a no-tools/read-only form, question last
check("readonly: every assistant ask knows has one", set(ask.READONLY) == set(ask.ONESHOT))
check("readonly claude: no tools at all", ask.command("claude", "hi", readonly=True) ==
      ["claude", "--tools", "", "-p", "hi"])
check("readonly: the question is always the last argument",
      all(ask.command(a, "hi", readonly=True)[-1] == "hi" for a in ask.READONLY))
check("readonly aider: never touches files", "--dry-run" in ask.command("aider", "hi", readonly=True))
check("readonly codex: read-only sandbox", ask.command("codex", "hi", readonly=True)[2:4] ==
      ["--sandbox", "read-only"])

# prompt(): piped text as context, the question, or both together
check("just a question", ask.prompt(["hi", "there"], "") == "hi there")
check("just piped text (no question)", ask.prompt([], "the diff") == "the diff")
check("both: piped first, then the question",
      ask.prompt(["what", "changed"], "the diff") == "the diff\n\nwhat changed")
check("neither: empty", ask.prompt([], "") == "")

# recent_notes() / prompt() with -c: decisions and summaries only, newest
# first, capped, and in front of everything else
def note(kind, title, body=""):
    return {"kind": kind, "raw": "## 2026-01-01 10:00 · %s · me · %s%s" % (kind, title, "\n\n" + body if body else "")}
ents = [note("todo", "buy disks"), note("decision", "drop X", "because Y"), note("idea", "maybe"),
        note("summary", "shipped 1.0")] + [note("decision", "old %d" % i) for i in range(10)]
block = ask.recent_notes(ents)
check("-c: decisions and summaries kept", "drop X" in block and "shipped 1.0" in block)
check("-c: todos and ideas left out", "buy disks" not in block and "maybe" not in block)
check("-c: newest first", block.index("drop X") < block.index("shipped 1.0"))
check("-c: at most NOTE_COUNT", block.count("## ") == ask.NOTE_COUNT)
check("-c: nothing to add is empty", ask.recent_notes([note("todo", "t")]) == "")
long = ask.recent_notes([note("summary", "long", "z" * 5000)])
check("-c: a long note is cut", len(long) < 2000 and long.endswith("[...]"))
check("-c: notes, then piped, then question",
      ask.prompt(["why"], "the diff", "NOTES") == "NOTES\n\nthe diff\n\nwhy")
check("-c: notes with no question still need one", ask.prompt([], "", "NOTES") == "")

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

    ask.newtab.have = lambda b: b if b == "claude" else None   # its path: the bare name, here
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
    real_notes = os.environ.get("PHOSPHOR_NOTES")
    import tempfile
    nb = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
    nb.write("## 2026-01-01 10:00 · decision · me · keep one deck\n\nno per-screen sessions\n\n"
             "## 2026-01-02 10:00 · todo · me · buy disks\n")
    nb.close()
    os.environ["PHOSPHOR_NOTES"] = nb.name
    try:
        rc, out = run(["--assistant", "claude", "-c", "why", "one", "deck"])
        sent = seen[-1][-1] if seen else ""
        check("-c after --assistant: runs", rc == 0 and seen[-1][:2] == ["claude", "-p"])
        check("-c: the notebook's decision goes along", "keep one deck" in sent and sent.endswith("why one deck"))
        check("-c: its todo doesn't", "buy disks" not in sent)
        seen.clear()
        rc, out = run(["-c"])
        check("-c alone, no question: usage, nothing run", rc == 1 and "usage" in out and not seen)
    finally:
        os.unlink(nb.name)
        if real_notes is None: os.environ.pop("PHOSPHOR_NOTES", None)
        else: os.environ["PHOSPHOR_NOTES"] = real_notes

    seen.clear()
    rc, out = run([], piped="")
    check("piped but empty, no question: still refuses", rc == 1 and "usage" in out)
    check("empty pipe: never runs anything", not seen)
finally:
    ask.newtab.have = real_have
    ask.subprocess.run = real_run

# a pane of the deck runs with systemd's PATH, without ~/.local/bin: the
# assistant ask found there runs by its full path (it failed with
# "couldn't run claude" from the ask and digest cards)
bin_ = tempfile.mkdtemp()
fake = os.path.join(bin_, "claude")
open(fake, "w").write("#!/bin/sh\n"); os.chmod(fake, 0o755)
_bin, _path = newtab.BIN, os.environ.get("PATH", "")
newtab.BIN, os.environ["PATH"] = bin_, "/usr/bin:/bin"
try:
    check("the assistant runs by its full path", ask.command("claude", "hi")[0] == fake
          and ask.command("claude", "hi", readonly=True)[0] == fake)
finally:
    newtab.BIN, os.environ["PATH"] = _bin, _path

# gemini headless refuses a folder it doesn't trust (#118): it runs in an
# empty folder of the deck's, trusted for that run only; never the pane's
_cache, _env_cache = tempfile.mkdtemp(), os.environ.get("PHOSPHOR_CACHE")
os.environ["PHOSPHOR_CACHE"] = _cache
calls, _run = [], ask.subprocess.run
ask.subprocess.run = lambda argv, **kw: calls.append((argv, kw)) or "done"
try:
    here = os.getcwd()
    for readonly in (True, False):
        calls.clear()
        os.makedirs(os.path.join(_cache, "ask", "gemini"), exist_ok=True)
        open(os.path.join(_cache, "ask", "gemini", "left.txt"), "w").write("x")
        ask.run("gemini", "hi", readonly=readonly, stdout=-1)
        argv, kw = calls[0]
        tag = "gemini%s: " % (" readonly" if readonly else "")
        check(tag + "argv as command() builds it", argv == ask.command("gemini", "hi", readonly=readonly))
        check(tag + "runs in the deck's own folder", kw.get("cwd") == os.path.join(_cache, "ask", "gemini")
              and kw["cwd"] != here and os.path.isdir(kw["cwd"]))
        check(tag + "that folder starts empty", os.listdir(kw["cwd"]) == [])
        check(tag + "trusted for this run, by the variable", (kw.get("env") or {}).get(
              "GEMINI_CLI_TRUST_WORKSPACE") == "true" and "--skip-trust" not in argv)
        check(tag + "the rest of the environment goes along", (kw.get("env") or {}).get("PATH") == os.environ["PATH"])
        check(tag + "the caller's own options pass through", kw.get("stdout") == -1)
    check("gemini: the trust stays in the child", "GEMINI_CLI_TRUST_WORKSPACE" not in os.environ)
    calls.clear()
    ask.run("claude", "hi", readonly=True)
    check("claude: runs where it's asked from, environment untouched",
          calls[0][1].get("cwd") is None and calls[0][1].get("env") is None)
    check("every caller asks through ask.run", not [f for f in ("ask", "triage", "digest", "read")
          if "subprocess.run(" + ("" if f == "ask" else "ask.") + "command(" in
          open(os.path.join(ROOT, "lib", f + ".py")).read().replace("subprocess.run(command(assistant", "")])
finally:
    ask.subprocess.run = _run
    if _env_cache is None: os.environ.pop("PHOSPHOR_CACHE", None)
    else: os.environ["PHOSPHOR_CACHE"] = _env_cache

# MENTIONS draws a notification whose notes are being prepared (it crashed: STATE_TXT)
import mentions
cache = tempfile.mkdtemp()
mentions.FEED, mentions.PREP = os.path.join(cache, "feed.jsonl"), os.path.join(cache, "prep")
open(mentions.FEED, "w").write('{"t": 1.0, "from": "nova", "message": "hi", "mention": true}\n')
mentions.set_state(1.0, "running")
try:
    lines, _ = mentions.render(80, 0)
    check("mentions: a note being prepared says so", any("preparing notes" in l for l in lines))
except NameError as e:
    check("mentions: draws a note being prepared (%s)" % e, False)

# --here (the ask key): the covered pane's last lines go along, with no tools
screen = "\n".join("line %d" % i for i in range(300)) + "\n\n\n   \n"
t = ask.last_lines(screen)
check("here: trailing blank rows off", t.endswith("line 299"))
check("here: only the last lines", len(t.splitlines()) == ask.CONTEXT_LINES and "line 179" not in t)
check("here: capped in characters too", len(ask.last_lines("x" * 500 + "\n" + "y" * 80, chars=100)) <= 100)
check("here: an empty pane is nothing", ask.last_lines("\n  \n\n") == "")
c = ask.screen_context("SYS", "htop", "load 9.1")
check("here: the context names the tab and the pane", "tab SYS, pane htop" in c and "load 9.1" in c)
check("here: and how many lines", "last 1 lines" in c)
check("here: the question goes after the screen",
      ask.prompt(["why so loaded"], c).endswith("why so loaded") and ask.prompt(["q"], c).startswith("This is"))
for k in ("ZELLIJ", "ZELLIJ_PANE_ID"):
    os.environ.pop(k, None)
check("here: outside the deck there's no pane to send", ask.covered_pane() is None)
asked = []
ask.pick = lambda name=None: "claude"
ask.interactive = lambda a, n: asked.append(("plain", a, n)) or 0
sys.argv = ["ask", "--here"]
ask.main()
check("here: outside the deck it's the plain ask, without the notebook", asked == [("plain", None, False)])
# what the deck knows, before the screen (#115): over a dash pane, the
# preamble, the tab's profile entry, the command's line and the manual's
# [[tabs]] section, under a budget; over a shell, only the preamble
DASH = ["/usr/bin/python3", "/opt/x/phosphor", "run", "--name", "CARDS", "--",
        "/opt/x/phosphor", "dash", "--tab", "SYS", "send", "receive"]
entry = {"name": "SYS", "panes": [{"dash": ["send", "receive"], "size": 5}, {"cmd": "htop"}]}
check("here: the program past phosphor run", ask.program(DASH) == DASH[6:] and ask.program(["/bin/bash"]) == [])
d = ask.deck_context("SYS", DASH, entry)
check("here: a dash pane gets the preamble", "Phosphor Deck" in d and "deck.toml" in d
      and "runs: `phosphor dash --tab SYS send receive`" in d)
check("here: its tab's entry, as TOML", '[[tabs]]\nname = "SYS"' in d and '{ dash = ["send", "receive"], size = 5 },' in d)
check("here: its command's line and the manual's [[tabs]]", "`phosphor dash`:" in d and "The manual on it" in d
      and "## [[tabs]]" in d)
check("here: under the budget (%d)" % len(d), len(d) < ask.MANUAL_CHARS + 2500)
check("here: and how to say Phosphor lacks it", "MISSING: " in d)
sh = ask.deck_context("AI", ["/bin/bash"], None)
check("here: a shell pane gets only the preamble", "runs: a shell" in sh and "manual on it" not in sh
      and "[[tabs]]" not in sh and len(sh) < 1000)
check("here: the tools line only when there are tools", "phosphor mcp" not in sh
      and "phosphor mcp" in ask.deck_context("AI", [], None, with_tools=True))
check("missing: the last line is the request, cut from the answer",
      ask.missing("No.\n\n**MISSING: two buttons**\n") == ("No.\n", "two buttons"))
check("missing: none, the answer as it was", ask.missing("Yes: dash = [...]\n") == ("Yes: dash = [...]\n", None))
check("missing: only near the end", ask.missing("MISSING: x\n1\n2\n3\n4\n")[1] is None)
check("claude gets the deck's MCP and nothing else", ask.mcp_flags("claude")[:2] == ["--strict-mcp-config", "--mcp-config"]
      and ask.mcp_flags("claude")[-2:] == ["--allowedTools", "mcp__phosphor"] and ask.mcp_flags("gemini") == [])

ask.covered_pane = lambda: ("SYS", "htop", "load 9.1", DASH)
import mcp
mcp.profile_tab = lambda name, prof=None: entry if name == "SYS" else None
import form
ran, shown = [], []
form.line = lambda title, hint, initial="": shown.append((title, hint)) or "why"
form.leave = lambda: None
form.pager = lambda text: shown.append(text)
class R: returncode, stdout = 0, b"because"
_run = ask.subprocess.run
ask.subprocess.run = lambda argv, **k: ran.append(argv) or R()
ask.main()
ask.subprocess.run = _run
check("here: the box says what goes where", shown and "SYS" in shown[0][0] and "1 lines and its tab's profile entry go to claude" in shown[0][1]
      and "read-only tools" in shown[0][1])
check("here: no tools of its own for text the deck didn't write", ran and ran[0][:3] == [ran[0][0], "--tools", ""])
check("here: the deck's MCP, read-only", ran and "mcp__phosphor" in ran[0] and "--strict-mcp-config" in ran[0])
check("here: the screen and the question in one prompt", ran and "load 9.1" in ran[0][-1] and ran[0][-1].endswith("why"))
check("here: the deck's part first, then the screen", ran and ran[0][-1].index("Phosphor Deck") < ran[0][-1].index("load 9.1")
      and 'name = "SYS"' in ran[0][-1])
check("here: no MISSING line, no r offered", not any("saves it as a request" in str(x) for x in shown))
check("here: the answer in the pager", shown[-1:] and "because" in shown[-1])

if fails:
    print("ask-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("ask-check ok")
