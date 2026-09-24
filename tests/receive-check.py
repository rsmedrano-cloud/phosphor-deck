#!/usr/bin/env python3
"""phosphor receive: the upload-direction mirror of phosphor send -- a
one-time link, a real file lands on disk, then it's gone.

    python3 tests/receive-check.py

Drives the real `phosphor receive` subprocess against localhost with a real
multipart upload; address picking (tailnet vs LAN) is already covered by
tests/send-check.py, since receive.py reuses send.pick_address directly.
"""
import os, re, subprocess, sys, tempfile, time, urllib.error, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import receive

fails = []
def need(what, ok):
    if not ok: fails.append(what)

# unique_name(): never overwrites, counts up instead
d = tempfile.mkdtemp()
open(os.path.join(d, "photo.jpg"), "w").close()
need("first collision gets -2", receive.unique_name(d, "photo.jpg") == "photo-2.jpg")
open(os.path.join(d, "photo-2.jpg"), "w").close()
need("keeps counting", receive.unique_name(d, "photo.jpg") == "photo-3.jpg")
need("no collision: name unchanged", receive.unique_name(d, "new.png") == "new.png")

# parse_multipart(): pulls the file part's name and bytes back out
def build(filename, data, boundary="XBOUNDARYX"):
    body = (("--%s\r\n" % boundary).encode() +
            ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % filename).encode() +
            b"Content-Type: application/octet-stream\r\n\r\n" + data + b"\r\n" +
            ("--%s--\r\n" % boundary).encode())
    return body, boundary

body, boundary = build("captura.png", b"\x89PNG\x00fake")
name, data = receive.parse_multipart(body, boundary)
need("parsed filename", name == "captura.png")
need("parsed bytes", data == b"\x89PNG\x00fake")
name2, data2 = receive.parse_multipart(b"nothing here", "X")
need("no file part: (None, None)", name2 is None and data2 is None)

# the server itself: one real upload, then it's gone
def strip(text):
    return re.sub(r"\x1b\]8;;[^\x1b]*\x1b\\|\x1b\[[0-9;]*m", "", text)

def drain(p, timeout):
    end = time.time() + timeout
    while p.stdout.readline() and time.time() < end:
        pass
    p.wait(timeout=max(0.1, end - time.time()))

def run_receive(dest, timeout):
    return subprocess.Popen([sys.executable, os.path.join(ROOT, "phosphor"), "receive",
                             "--dir", dest, "--timeout", str(timeout)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            cwd=ROOT, env=dict(os.environ))

def wait_for_url(p, timeout=5):
    deadline = time.time() + timeout
    out = ""
    while time.time() < deadline:
        line = p.stdout.readline()
        if not line:
            time.sleep(0.05); continue
        out += line
        m = re.search(r"http://\S+", strip(line))
        if m:
            return m.group(0), out
    return None, out

dest = tempfile.mkdtemp()
p = run_receive(dest, 8)
url, out = wait_for_url(p)
need("printed a url", url is not None)
need("the url is an OSC 8 hyperlink", "\x1b]8;;http://" in out)

# GET the link: an actual upload form, not a bare file
form = b""
if url:
    with urllib.request.urlopen(url, timeout=5) as r:
        form = r.read()
        need("html form", b"<form" in form and b"multipart/form-data" in form)

# a wrong token: 404, and doesn't count as served (the real upload still works after)
if url:
    bad = re.sub(r"/[^/]+$", "/not-the-token", url)
    try:
        urllib.request.urlopen(bad, timeout=3)
        fails.append("a guessed path was served")
    except urllib.error.HTTPError as e:
        need("wrong token: 404", e.code == 404)

# the real upload, multipart, to <url>/upload
if url:
    body, boundary = build("informe más largo.png", b"hola bytes\x00\x01\x02")
    req = urllib.request.Request(url + "/upload", data=body, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            need("upload answers 200", r.status == 200)
            need("a plain done page, not the file bounced back", b"done" in r.read().lower())
    except urllib.error.URLError as e:
        fails.append("upload failed: %s" % e)

drain(p, 5)
need("exits 0 once something's been received", p.returncode == 0)
landed = [f for f in os.listdir(dest) if f != ".gitkeep"]
need("exactly one file landed", len(landed) == 1)
if landed:
    need("original filename kept", landed[0] == "informe más largo.png")
    need("real bytes on disk", open(os.path.join(dest, landed[0]), "rb").read() == b"hola bytes\x00\x01\x02")

# a second upload doesn't overwrite the first -- gets its own name
dest2 = tempfile.mkdtemp()
open(os.path.join(dest2, "shot.png"), "wb").write(b"already here")
p2 = run_receive(dest2, 8)
url2, _ = wait_for_url(p2)
if url2:
    body, boundary = build("shot.png", b"the new one")
    req = urllib.request.Request(url2 + "/upload", data=body, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    urllib.request.urlopen(req, timeout=5).read()
drain(p2, 5)
need("existing file untouched", open(os.path.join(dest2, "shot.png"), "rb").read() == b"already here")
need("the new one got its own name", open(os.path.join(dest2, "shot-2.png"), "rb").read() == b"the new one")

# nobody sends anything: times out, exits non-zero, nothing written
dest3 = tempfile.mkdtemp()
p3 = run_receive(dest3, 2)
drain(p3, 6)
need("exits non-zero when nobody ever sends anything", p3.returncode != 0)
need("nothing written on timeout", os.listdir(dest3) == [])

if fails:
    print("receive-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("receive-check ok")
