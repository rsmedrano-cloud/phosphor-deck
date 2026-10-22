#!/usr/bin/env python3
"""Service checks ([[hosts.checks]], lib/checks.py): a URL or a TCP port,
polled from the brain. Against servers of its own on 127.0.0.1 (one that
answers, one that answers 502, a port nobody listens on), never a real
host: two misses in a row before it's down, an alert only on a change,
none for a host that's down itself; then the why list (glance, FLEET's
card, fleet --json, the adjutant), snooze and the profile's warnings.
A temp HOME; nothing real is touched.

    python3 tests/checks-check.py
"""
import http.server, json, os, re, socket, sys, tempfile, threading, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
for v in ("PHOSPHOR_DATA", "PHOSPHOR_CACHE", "PHOSPHOR_NOTES", "ZELLIJ"):
    os.environ.pop(v, None)
home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.makedirs(os.path.join(home, ".cache/phosphor"))

fails = []
def need(what, ok):
    if not ok: fails.append(what)
def strip(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

class Answer(http.server.BaseHTTPRequestHandler):
    code = 200
    def do_GET(self):
        self.send_response(self.server.code); self.end_headers()
    def log_message(self, *a): pass

def serve(code):
    s = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    s.code = code
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s

up, broken = serve(200), serve(502)
nobody = socket.socket(); nobody.bind(("127.0.0.1", 0))
closed = nobody.getsockname()[1]; nobody.close()       # free again: refused

prof = os.path.join(home, "deck.toml")
open(prof, "w").write(
    '[deck]\nsession = "probe"\n\n'
    '[[hosts]]\nname = "db-box"\nssh = "db-box"\nip = "127.0.0.1"\n\n'
    '[[hosts.checks]]\nname = "web"\nurl = "http://127.0.0.1:%d/health"\n\n'
    '[[hosts.checks]]\nname = "api"\nurl = "http://127.0.0.1:%d/"\n\n'
    '[[hosts.checks]]\nname = "pg"\nport = %d\n\n'
    '[[hosts.checks]]\nport = %d\n\n'
    '[[hosts]]\nname = "phone"\nrole = "viewer"\n\n'
    '[[hosts.checks]]\nport = 22\n'
    % (up.server_port, broken.server_port, closed, up.server_port))
os.environ["PHOSPHOR_PROFILE"] = prof

import checks, deckconf, glance, fleet, snooze, adjutant, profcheck

p = deckconf.load()[0]
sp = checks.specs(p)
need("specs: only polled hosts", list(sp) == ["db-box"])
need("specs: a url, a port on the host's ip, a name of its own",
     [n for n, _ in sp["db-box"]] == ["web", "api", "pg", "port %d" % up.server_port]
     and sp["db-box"][2][1] == ("port", ("127.0.0.1", closed)))
need("profile: no warning for good checks", profcheck.problems(p) == [])

need("probe: answers", checks.probe(("url", "http://127.0.0.1:%d/" % up.server_port)) is None)
need("probe: a 502 isn't answering", checks.probe(("url", "http://127.0.0.1:%d/" % broken.server_port)) == "HTTP 502")
need("probe: a closed port", checks.probe(("port", ("127.0.0.1", closed))) == "refused")
need("probe: an open port", checks.probe(("port", ("127.0.0.1", up.server_port))) is None)

said, host_down = [], [False]
ck = checks.Checker(lambda h, ok, t: said.append((ok, t)), lambda h: host_down[0])
def rnd():
    r = ck.round(checks.specs(deckconf.load()[0]))
    st = os.stat(checks.path())                 # same-tick writes: load() reads on mtime
    os.utime(checks.path(), ns=(st.st_atime_ns, st.st_mtime_ns + rnd.n)); rnd.n += 1000
    return r
rnd.n = 1000

rnd()
need("one miss isn't down", checks.failing("db-box") == [] and not said)
rnd()
need("two misses are", checks.failing("db-box") == [("api", "HTTP 502"), ("pg", "refused")])
need("no alert for what was already failing when it started", not said)

def h_ok():
    return {"ok": True, "CPU": 3, "MEMU": 100, "MEMT": 1000, "mnt": []}
with open(glance.CACHE, "w") as f:
    json.dump({"t": time.time(), "hosts": {"db-box": h_ok()}}, f)

f = glance.findings("db-box", h_ok())
need("glance: in the why list", ("checks", 2, "api, pg not answering", False) in f)
need("glance: not on a host that's down", glance.findings("db-box", {"ok": False}) == [("down", 1, "unreachable", True)])
need("fleet --json: why and each check",
     "db-box: api, pg not answering" in (fleet.why({"db-box": h_ok()}) or "")
     and fleet.with_checks("db-box", {"ok": True})["checks"][1] == {"name": "api", "ok": False, "error": "HTTP 502"})
head, body = fleet.card("db-box", 34, h_ok())
lines = [strip(l) for l in body]
need("card: says which and why", "✗ api: HTTP 502" in lines and "✗ pg: refused" in lines)
need("card: within its width", all(len(l) <= 30 for l in lines))
need("adjutant: amber", adjutant.fleet_health() == (1, "db-box api not answering"))

# snooze: quiet everywhere, a third check failing wakes it
need("snooze level counts them", snooze.level("checks", "db-box", h_ok()) == 2)
snooze.snooze("db-box", ["checks"])
need("snoozed: out of the why list", glance.host_problems({"db-box": h_ok()})[1] == [])
need("snoozed: adjutant nominal", adjutant.fleet_health() == (0, "nominal"))
need("snoozed: its alert quiet", snooze.quiets("db-box: api not answering")
     and snooze.quiets("db-box: api answering again"))
snooze.end([("db-box", None)])
need("awake: its alert speaks", not snooze.quiets("db-box: api not answering"))

# changes: down, then back -- not while the host itself is down
broken.code = 200
rnd()
need("back: alerted", said == [(True, "db-box: api answering again")])
broken.code = 503
rnd(); rnd()
need("down again: alerted once", said[-1] == (False, "db-box: api not answering") and len(said) == 2)
broken.code = 200
host_down[0] = True
rnd()
need("host down: its own alert says it", len(said) == 2)
host_down[0] = False

# taken out of the profile: gone at once
open(prof, "w").write('[deck]\nsession = "probe"\n\n[[hosts]]\nname = "db-box"\nssh = "db-box"\n')
r = ck.round(checks.specs(deckconf.load()[0]))
need("no checks left: an empty round", r == {} and checks.results("db-box") == [])

# stale: a worker that stopped says nothing
checks.write({"t": time.time() - 600, "hosts": {"db-box": [{"name": "x", "ok": False, "err": "refused"}]}})
need("stale checks.json: nothing failing", checks.failing("db-box") == [])

# the profile's warnings
bad = profcheck.problems({"hosts": [{"name": "db-box", "checks": [
    {"name": "a", "url": "ftp://x"}, {"name": "b", "port": 70000}, {"name": "c"},
    {"name": "d", "url": "http://x", "port": 1}, {"name": "e", "prot": 22}]}]})
need("profile: each bad check named", [w for _, w in bad] == [
    'check "a": url starts with http:// or https://', 'check "b": port is a number, 1 to 65535',
    'check "c": a url or a port, one of them', 'check "d": a url or a port, one of them',
    "unknown key prot: port?", 'check "e": a url or a port, one of them'])
need("snooze: a kind of its own", "checks" in snooze.KINDS)

if fails:
    print("checks-check: FAIL"); [print("  - " + x) for x in fails]; sys.exit(1)
print("checks-check: ok")
