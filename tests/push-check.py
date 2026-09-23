#!/usr/bin/env python3
"""Push notifications (ntfy) against a local HTTP server; nothing leaves the machine.

    python3 tests/push-check.py
"""
import http.server, os, sys, threading
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import push

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

got = []
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        got.append((self.path, self.rfile.read(n).decode(), dict(self.headers)))
        self.send_response(500 if self.path == "/broken" else 200)
        self.end_headers()
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = "http://127.0.0.1:%d" % srv.server_port

# config defaults: off, and nothing to send to
c = push.get_config({})
check("off by default", c["enabled"] is False)
check("no topic by default", c["topic"] == "")
ok, why = push.send("hi", cfg=c)
check("off: nothing sent", not ok and not got)

# enabled but no topic
c = push.get_config({"push": {"enabled": True, "url": url}})
ok, why = push.send("hi", cfg=c)
check("no topic: refused", not ok and "topic" in why and not got)

# a real send
os.environ["PH_TOKEN"] = "s3cret"
c = push.get_config({"push": {"enabled": True, "url": url + "/", "topic": "deck", "token": "env:PH_TOKEN", "priority": "high"}})
ok, why = push.send("nightly build failed", tab="SYS", cfg=c)
check("send ok", ok and why == "")
check("posted to /deck", got and got[-1][0] == "/deck")
check("body is the message", got and got[-1][1] == "nightly build failed")
h = got[-1][2] if got else {}
check("title carries the tab", h.get("Title") == "phosphor · SYS")
check("priority header", h.get("Priority") == "high")
check("token resolved from env", h.get("Authorization") == "Bearer s3cret")

# long text is capped
push.send("x" * 2000, cfg=c)
check("capped at MAX_LEN", len(got[-1][1]) == push.MAX_LEN)

# force sends even when disabled (phosphor notify --push)
c = push.get_config({"push": {"url": url, "topic": "deck"}})
n = len(got)
ok, _ = push.send("forced", cfg=c, force=True)
check("force overrides enabled=false", ok and len(got) == n + 1)

# failures come back as a reason, never raise
c = push.get_config({"push": {"enabled": True, "url": url, "topic": "broken"}})
ok, why = push.send("x", cfg=c)
check("HTTP error reported", not ok and "500" in why)
c = push.get_config({"push": {"enabled": True, "url": "http://127.0.0.1:1", "topic": "t"}})
ok, why = push.send("x", cfg=c, timeout=2)
check("unreachable reported, no raise", not ok and why)
c = push.get_config({"push": {"enabled": True, "url": "ntfy.sh", "topic": "t"}})
ok, why = push.send("x", cfg=c)
check("url without scheme refused", not ok and "http" in why)

# subscribe_url: <server>/<topic>, empty without a topic
check("no topic: no subscribe url", push.subscribe_url({"url": "https://ntfy.sh", "topic": ""}) == "")
check("subscribe url joins server and topic",
      push.subscribe_url({"url": "https://ntfy.sh", "topic": "deck-abc"}) == "https://ntfy.sh/deck-abc")
check("works with a self-hosted server too", push.subscribe_url(
      {"url": "http://ntfy.example:8080", "topic": "t"}) == "http://ntfy.example:8080/t")

# `phosphor push` / `--qr` CLI: never raises, says the right thing either way
import contextlib, io
def run(argv):
    saved = sys.argv
    sys.argv = ["phosphor-push"] + argv
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = push.main()
    finally:
        sys.argv = saved
    return rc, out.getvalue()

# the CLI reads deckconf.load() itself: never trust whatever profile
# happens to be on this machine, mock it either way
real_load = push.deckconf.load
push.deckconf.load = lambda: ({"push": {}}, "t")
try:
    rc, out = run([])
    check("status with no topic exits 1 and says so", rc == 1 and "none set" in out)
finally:
    push.deckconf.load = real_load

real_load = push.deckconf.load
push.deckconf.load = lambda: ({"push": {"enabled": True, "url": "https://ntfy.sh", "topic": "test-topic"}}, "t")
try:
    rc, out = run([])
    check("status with a topic exits 0", rc == 0)
    check("status shows the topic", "test-topic" in out)

    rc, out = run(["--qr"])
    check("--qr exits 0", rc == 0)
    check("--qr prints the subscribe link", "https://ntfy.sh/test-topic" in out)
finally:
    push.deckconf.load = real_load

srv.shutdown()
if fails:
    print("push-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("push-check ok")
