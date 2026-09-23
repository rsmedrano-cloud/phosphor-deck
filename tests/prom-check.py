#!/usr/bin/env python3
"""Prometheus gauges against a fake Prometheus.

    python3 tests/prom-check.py

A local HTTP server answers the instant-query API. phosphor prom --once reads
[prometheus] from a throwaway profile: every card is exactly as wide as the
screen, values and thresholds show (OK, WARN, CRIT), a query with no data or
an error says why, an unreachable server says so, and the + menu offers the
panel only to a profile that has [prometheus].
"""
import json, os, re, subprocess, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(what, ok):
    if not ok: fails.append(what)

ANSWERS = {"low": 10, "mid": 75, "high": 95, "mem": 12.5}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("query", [""])[0]
        if q == "broken(":
            body = {"status": "error", "error": "parse error at char 8"}
        elif q in ANSWERS:
            body = {"status": "success", "data": {"result": [{"value": [0, str(ANSWERS[q])]}]}}
        else:
            body = {"status": "success", "data": {"result": []}}
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)

srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = "http://127.0.0.1:%d" % srv.server_port

tmp = tempfile.mkdtemp()
def profile(body):
    p = os.path.join(tmp, "deck%d.toml" % len(os.listdir(tmp)))
    open(p, "w").write('[deck]\nsession = "probe"\n' + body)
    return p

gauges = '''
[prometheus]
url = "%s"
[[prometheus.gauges]]
name = "low one"
query = "low"
[[prometheus.gauges]]
name = "middle arc"
type = "arc"
query = "mid"
warn = 70
crit = 90
[[prometheus.gauges]]
name = "a high sparkline with a name far too long for a narrow screen"
type = "sparkline"
query = "high"
[[prometheus.gauges]]
name = "memory"
query = "mem"
unit = "MB"
[[prometheus.gauges]]
name = "empty"
query = "nothing"
[[prometheus.gauges]]
name = "typo"
query = "broken("
''' % url

def run(prof, cols):
    env = dict(os.environ, PHOSPHOR_PROFILE=prof, COLUMNS=str(cols), LINES="50")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "prom", "--once"],
                       capture_output=True, text=True, env=env, timeout=30)
    check("prom --once exits 0 (%s)" % r.stderr.strip()[-200:], r.returncode == 0)
    return [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in r.stdout.splitlines()]

p = profile(gauges)
for cols in (80, 40, 20):
    lines = run(p, cols)
    text = "\n".join(lines)
    wide = [l for l in lines if len(l) > cols]
    check("at %d columns no line is wider: %r" % (cols, wide[:2]), not wide)
    boxes = [l for l in lines if l[:1] in "╭│╰"]
    check("at %d columns every box is %d wide" % (cols, cols), all(len(l) == cols for l in boxes))
    check("at %d columns every box closes on the right" % cols,
          boxes and all(l[-1] in "╮│╯" for l in boxes))
    check("at %d columns: six cards" % cols, text.count("╭") >= 6)

text = "\n".join(run(p, 80))
check("a low value is OK and shows 10", re.search(r"low one.* OK ", text) and " 10 " in text)
check("75 over warn 70 is WARN", re.search(r"middle arc.* WARN ", text) and "75" in text)
check("95 over the default crit 90 is CRIT", re.search(r"sparkline.* CRIT ", text))
check("a unit follows the value", "12.5MB" in text)
check("a query with no data says so", re.search(r"empty.* ERR ", text) and "no data" in text)
check("a broken query says why", "parse error at char 8" in text)

text = "\n".join(run(profile('[prometheus]\nurl = "http://127.0.0.1:9"\n'), 80))
check("an unreachable server: every default card is ERR and says why",
      text.count(" ERR ") == 4 and "refused" in text.lower())

sys.path.insert(0, os.path.join(ROOT, "lib"))
import newtab
labels = lambda prof: [e[0] for e in newtab.entries(prof)]
check("+ menu: no prometheus without [prometheus]", "prometheus" not in labels({"deck": {}}))
check("+ menu: prometheus with [prometheus]", "prometheus" in labels({"prometheus": {"url": url}}))

srv.shutdown()
if fails:
    print("\n".join("FAIL " + f for f in fails)); sys.exit(1)
print("ok")
