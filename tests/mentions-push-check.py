#!/usr/bin/env python3
"""A chat notification reaches the phone/TTS too: `mentions.hook()` still
writes the feed and the SYS event synchronously (unchanged), and now also
fires `phosphor notify --no-event` off a detached process, so the hook
itself returns at once. Nothing spawned for real: subprocess.Popen is
patched, and PHOSPHOR_DATA/PHOSPHOR_CACHE point at a throwaway folder.

    python3 tests/mentions-push-check.py
"""
import contextlib, io, json, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

td = tempfile.mkdtemp()
os.environ["PHOSPHOR_DATA"] = os.path.join(td, "data")
os.environ["PHOSPHOR_CACHE"] = os.path.join(td, "cache")

import mentions

calls = []
mentions.subprocess.Popen = lambda argv, **kw: calls.append(argv) or type("P", (), {})()

def call_hook(payload):
    calls.clear()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = mentions.hook()
    finally:
        sys.stdin = real_stdin
    return rc, out.getvalue()

rc, out = call_hook({"from": "leandro", "message": "che, mirá esto", "mention": True})
check("hook returns 0", rc == 0)
check("hook prints nothing (matterhorn shows any output as an error)", out == "")
check("the feed got the entry", any(e.get("from") == "leandro" for e in mentions.entries()))
check("the SYS event was written synchronously, not by the spawned process",
      "leandro" in open(mentions.EVENTS).read())

check("exactly one process spawned for push/tts", len(calls) == 1)
argv = calls[0]
check("it's phosphor notify", argv[2] == "notify")
check("no second event line: --no-event", "--no-event" in argv)
check("tab is COMMS", argv[argv.index("--tab") + 1] == "COMMS")
check("carries who and what", argv[-1] == "@leandro: che, mirá esto")
check("not marked as a fleet alert", "--fleet-alert" not in argv)

# a broken spawn (e.g. python3 missing) must never surface: the hook already
# did the part that matters (feed + event) before push_it runs
def boom(argv, **kw):
    raise OSError("no such file")
mentions.subprocess.Popen = boom
rc, out = call_hook({"from": "x", "message": "y", "mention": False})
check("a failed spawn still returns 0 and prints nothing", rc == 0 and out == "")

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
