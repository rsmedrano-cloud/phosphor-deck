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
    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        got.append((self.path, self.rfile.read(n), dict(self.headers), "PUT"))
        # /plain stands for a server with no attachment cache
        # /full one whose attachment store is out of space
        self.send_response(400 if self.path.startswith("/plain") else
                           507 if self.path.startswith("/full") else 200)
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

# the "open the deck" button: only a real tailnet address, only with web on
check("no button by default", "Click" not in got[-1][2] and "Actions" not in got[-1][2])
c = push.get_config({"push": {"enabled": True, "url": url, "topic": "deck"}})
check("open_web on by default", c["open_web"] is True)
push.send("host down", cfg=c, click="https://brain.tail0.ts.net:8443")
h = got[-1][2]
check("tap opens the deck", h.get("Click") == "https://brain.tail0.ts.net:8443")
check("button opens the deck", h.get("Actions") == "view, open the deck, https://brain.tail0.ts.net:8443")

import web
real = (web.usable, web.url)
web.url = lambda prof: "https://brain.tail0.ts.net:8443"
try:
    web.usable = lambda prof: (True, "")
    check("web off: no button", push.web_url({"deck": {"web": False}}) == "")
    check("no [deck]: no button", push.web_url({}) == "")
    check("web on, tailscale: the address",
          push.web_url({"deck": {"web": True}}) == "https://brain.tail0.ts.net:8443")
    web.usable = lambda prof: (False, "it needs tailscale")
    check("web on, local only: no button", push.web_url({"deck": {"web": True}}) == "")
    def boom(prof): raise OSError("tailscale gone")
    web.usable = boom
    check("tailscale failing: no button, no raise", push.web_url({"deck": {"web": True}}) == "")

    # notify_hook wires it in, and open_web = false keeps it out
    web.usable = lambda prof: (True, "")
    real_load = push.deckconf.load
    try:
        push.deckconf.load = lambda: ({"deck": {"web": True},
                                       "push": {"enabled": True, "url": url, "topic": "deck"}}, "t")
        ok, _ = push.notify_hook("mention", tab="COMMS")
        check("notify: sent with the button", ok and got[-1][2].get("Click") == "https://brain.tail0.ts.net:8443")
        push.deckconf.load = lambda: ({"deck": {"web": True},
                                       "push": {"enabled": True, "url": url, "topic": "deck", "open_web": False}}, "t")
        push.notify_hook("mention", tab="COMMS")
        check("open_web = false: no button", "Click" not in got[-1][2])
        push.deckconf.load = lambda: ({"deck": {"web": True}, "push": {"url": url, "topic": "deck"}}, "t")
        n = len(got)
        ok, why = push.notify_hook("x")
        check("notify: off stays off", not ok and len(got) == n)
    finally:
        push.deckconf.load = real_load
finally:
    web.usable, web.url = real

# the spoken clip rides along as an ntfy attachment
import tempfile, urllib.parse
wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
wav.write(b"RIFF" + b"\0" * 60); wav.close()
c = push.get_config({"push": {"enabled": True, "url": url, "topic": "deck"}})
check("clip on by default", c["clip"] is True and push.wants_clip(cfg=c))
check("clip = false: no clip", not push.wants_clip(cfg=push.get_config(
      {"push": {"enabled": True, "url": url, "topic": "deck", "clip": False}})))
check("push off: no clip", not push.wants_clip(cfg=push.get_config({"push": {"url": url, "topic": "deck"}})))
check("forced push: a clip", push.wants_clip(force=True, cfg=push.get_config({"push": {"url": url, "topic": "deck"}})))
ok, why = push.send("host down: db-box", tab="SYS", cfg=c, attach=wav.name)
last = got[-1]
check("attach: sent ok", ok and why == "")
check("attach: a PUT of the file", len(last) == 4 and last[1] == open(wav.name, "rb").read())
q = urllib.parse.parse_qs(urllib.parse.urlparse(last[0]).query)
check("attach: the text in ?message", q.get("message") == ["host down: db-box"])
check("attach: named phosphor.wav", q.get("filename") == ["phosphor.wav"])
check("attach: title kept", last[2].get("Title") == "phosphor · SYS")
c = push.get_config({"push": {"enabled": True, "url": url, "topic": "plain"}})
n = len(got)
ok, why = push.send("host down", cfg=c, attach=wav.name)
check("no attachments there: the text still goes", ok and len(got) == n + 2
      and len(got[-1]) == 3 and got[-1][1] == "host down")
n = len(got)
ok, why = push.send("disk down", cfg=push.get_config({"push": {"enabled": True, "url": url, "topic": "full"}}),
                    attach=wav.name)
check("attachment upload fails: the text still goes", ok and len(got) == n + 2
      and len(got[-1]) == 3 and got[-1][1] == "disk down")
ok, _ = push.send("gone file", cfg=c, attach="/nonexistent/x.wav")
check("missing clip: plain text", ok and len(got[-1]) == 3)
real_load = push.deckconf.load
try:
    push.deckconf.load = lambda: ({"push": {"enabled": True, "url": url, "topic": "deck", "clip": False}}, "t")
    push.notify_hook("mention", attach=wav.name)
    check("clip = false: notify sends text only", len(got[-1]) == 3)
    push.deckconf.load = lambda: ({"push": {"enabled": True, "url": url, "topic": "deck"}}, "t")
    push.notify_hook("mention", attach=wav.name)
    check("notify carries the clip", len(got[-1]) == 4)
finally:
    push.deckconf.load = real_load
os.remove(wav.name)

srv.shutdown()
if fails:
    print("push-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("push-check ok")
