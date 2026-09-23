#!/usr/bin/env python3
"""phosphor send: one real file, a one-time link and QR, gone after it's
used or after its timeout.

    python3 tests/send-check.py

Drives the real `phosphor send` subprocess against localhost -- the address
it advertises (tailnet vs LAN) is unit-tested separately with mesh.current
monkeypatched, no real tailscale needed.
"""
import os, re, subprocess, sys, tempfile, time, urllib.error, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import send

fails = []
def need(what, ok):
    if not ok: fails.append(what)

# address picking: tailnet when there's one, else the LAN -- no real network
class FakeMesh:
    kind = "none"
    def current(self, prof):
        return self.kind, None
fm = FakeMesh()
send.mesh = fm
send.tailnet_ip = lambda: "203.0.113.10"     # RFC 5737 TEST-NET-3: never a real address
send.lan_ip = lambda: "192.168.1.50"

fm.kind = "tailscale"
need("tailnet address when there's a tailnet", send.pick_address(None) == ("203.0.113.10", "tailnet"))
fm.kind = "none"
need("LAN address otherwise", send.pick_address(None) == ("192.168.1.50", "LAN"))
send.tailnet_ip = lambda: ""            # tailscale client present but no IP yet
fm.kind = "tailscale"
need("falls back to LAN if the tailnet IP can't be read", send.pick_address(None) == ("192.168.1.50", "LAN"))

# the server itself: one real request, then it's gone
d = tempfile.mkdtemp()
path = os.path.join(d, "informe más largo.md")
open(path, "w", encoding="utf-8").write("hola mundo\n")

def strip(text):
    return re.sub(r"\x1b\]8;;[^\x1b]*\x1b\\|\x1b\[[0-9;]*m", "", text)

def drain(p, timeout):
    """Finish reading a process's output through the same readline() we
    already used, then wait for it. communicate() reads the pipe's raw
    fd directly -- mixed with our own readline() calls on the same
    TextIOWrapper, it can split a multi-byte UTF-8 character (the QR's
    block glyphs) right down the middle and crash on decode."""
    end = time.time() + timeout
    while p.stdout.readline() and time.time() < end:
        pass
    p.wait(timeout=max(0.1, end - time.time()))

def run_send(fpath, timeout):
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "phosphor"), "send", fpath,
                          "--timeout", str(timeout)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         cwd=ROOT, env=dict(os.environ))
    return p

p = run_send(path, 8)
url = None
deadline = time.time() + 5
out = ""
while time.time() < deadline:
    line = p.stdout.readline()
    if not line:
        time.sleep(0.05); continue
    out += line
    m = re.search(r"http://\S+", strip(line))
    if m:
        url = m.group(0); break
need("printed a url", url is not None)
need("the url is an OSC 8 hyperlink (a tap/click opens it)", "\x1b]8;;http://" in out)

body, ctype, cdisp = b"", "", ""
if url:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            body = r.read()
            ctype = r.headers.get("Content-Type", "")
            cdisp = r.headers.get("Content-Disposition", "")
    except urllib.error.URLError as e:
        fails.append("fetch failed: %s" % e)

need("served the real bytes", body == b"hola mundo\n")
need("markdown content-type", ctype == "text/markdown")
need("filename offered for download", "informe m" in cdisp and ".md" in cdisp)

drain(p, 5)
need("exits 0 once it's been fetched", p.returncode == 0)

# a wrong token never gets the file, and doesn't count as served
p2 = run_send(path, 2)
url2 = None
deadline = time.time() + 5
while time.time() < deadline:
    line = p2.stdout.readline()
    if not line:
        time.sleep(0.05); continue
    m = re.search(r"http://\S+", strip(line))
    if m:
        url2 = m.group(0); break
if url2:
    bad = re.sub(r"/[^/]+$", "/not-the-token/file.md", url2)
    try:
        urllib.request.urlopen(bad, timeout=3)
        fails.append("a guessed path was served")
    except urllib.error.HTTPError as e:
        need("wrong token: 404", e.code == 404)
drain(p2, 5)
need("exits non-zero when nobody ever fetches it", p2.returncode != 0)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
print("ok")
