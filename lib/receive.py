"""phosphor receive - one real file, from whatever device sends it first.

    phosphor receive [--dir FOLDER] [--timeout SECONDS]

The mirror of `phosphor send`: instead of a download link, this opens a
one-time upload link behind a random token, prints it with a QR to scan,
and shuts itself down the moment a file lands (or after the timeout,
default 3 minutes, if nobody sends one). For the case `send`/`clip` can't
cover -- getting a real file (a photo, a screenshot) from whatever device
you're actually holding onto the machine an AI assistant or anything else
here can read, without it already being mounted or synced. Deliberate
every time, never automatic: nothing is received until you run this.
Reachable on your tailnet if you have one, on your LAN otherwise -- never
the internet, and gone as soon as it's used. The file lands in ~/received
(or --dir), never overwriting one that's already there.
"""
import os, re, secrets, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import clip, deckconf, send

DEFAULT_TIMEOUT = 180
DEFAULT_DIR = os.path.expanduser("~/received")

FORM_HTML = """<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>phosphor receive</title>
<style>
body {background:#050b06; color:#a8e5b0; font-family:monospace; text-align:center; padding-top:20vh}
input, button {font-size:1.1em; padding:.6em 1em; margin-top:1.2em}
button {background:#33ff44; color:#050b06; border:none; border-radius:4px}
</style>
<h1>send a file here</h1>
<form method="post" enctype="multipart/form-data" action="%(upload)s">
<input type="file" name="file" required><br>
<button type="submit">upload</button>
</form>
"""

DONE_HTML = """<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>phosphor receive</title>
<style>body {background:#050b06; color:#a8e5b0; font-family:monospace; text-align:center; padding-top:30vh}</style>
<h1>done</h1><p>you can close this.</p>
"""


def tilde(p):
    home = os.path.expanduser("~")
    return p.replace(home, "~", 1) if p == home or p.startswith(home + "/") else p


def unique_name(dest_dir, name):
    """name, or name-2, name-3... if it's already there -- never overwrites."""
    base, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(dest_dir, candidate)):
        n += 1
        candidate = "%s-%d%s" % (base, n, ext)
    return candidate


def parse_multipart(body, boundary):
    """(filename, data) for the form's "file" part, or (None, None)."""
    marker = ("--" + boundary).encode()
    for part in body.split(marker):
        if b'name="file"' not in part:
            continue
        head_end = part.find(b"\r\n\r\n")
        if head_end == -1:
            continue
        m = re.search(r'filename="([^"]*)"', part[:head_end].decode("utf-8", "replace"))
        if not m or not m.group(1):
            continue
        data = part[head_end + 4:]
        if data.endswith(b"\r\n"):
            data = data[:-2]
        return m.group(1), data
    return None, None


def handler_for(path, upload_path, dest_dir, result):
    class OneShot(BaseHTTPRequestHandler):
        served = False

        def do_GET(self):
            if self.path != path:
                self.send_error(404)
                return
            body = (FORM_HTML % {"upload": upload_path}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != upload_path:
                self.send_error(404)
                return
            ctype = self.headers.get("Content-Type", "")
            m = re.search(r"boundary=([^;]+)", ctype)
            if "multipart/form-data" not in ctype or not m:
                self.send_error(400, "expected a multipart file upload")
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            filename, data = parse_multipart(body, m.group(1).strip('"'))
            if not filename or data is None:
                self.send_error(400, "no file in that upload")
                return
            os.makedirs(dest_dir, exist_ok=True)
            name = unique_name(dest_dir, os.path.basename(filename) or "upload")
            with open(os.path.join(dest_dir, name), "wb") as f:
                f.write(data)
            result["name"], result["size"] = name, len(data)
            reply = DONE_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)
            OneShot.served = True

        def log_message(self, *a):
            pass                       # our own status line covers this

    return OneShot


def receive(prof, dest_dir=DEFAULT_DIR, timeout=DEFAULT_TIMEOUT):
    secret = secrets.token_urlsafe(12)
    path, upload_path = "/%s" % secret, "/%s/upload" % secret
    ip, where = send.pick_address(prof)
    result = {}

    httpd = HTTPServer(("0.0.0.0", 0), handler_for(path, upload_path, dest_dir, result))
    url_ = "http://%s:%d%s" % (ip, httpd.server_port, path)

    print(row(OK, "waiting for", "a file", note="lands in %s" % tilde(dest_dir)))
    at = row(OK, "at", url_, note="%s, one upload, %ds" % (where, timeout))
    print(at.replace(url_, "\x1b]8;;%s\x1b\\%s\x1b]8;;\x1b\\" % (url_, url_)))   # OSC 8: a tap/click opens it
    for l in send.qr_lines(url_):
        print("  " + l)
    clip.send(url_.encode())           # on every screen's clipboard: paste it into a browser
    print(DIM + "  waiting..." + RST)

    httpd.timeout = 1
    deadline = time.time() + timeout
    while not httpd.RequestHandlerClass.served and time.time() < deadline:
        httpd.handle_request()
    httpd.server_close()

    if httpd.RequestHandlerClass.served:
        print(row(OK, "received", result["name"], note="%d bytes -> %s" % (result["size"], tilde(dest_dir))))
        return 0
    print(row(WARN, "timed out", "nobody sent anything")); return 1


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print("usage: phosphor receive [--dir FOLDER] [--timeout SECONDS]"); return 0
    timeout, dest = DEFAULT_TIMEOUT, DEFAULT_DIR
    if "--timeout" in a:
        i = a.index("--timeout")
        try:
            timeout = int(a[i + 1])
        except (IndexError, ValueError):
            print("usage: phosphor receive [--dir FOLDER] [--timeout SECONDS]"); return 1
        del a[i:i + 2]
    if "--dir" in a:
        i = a.index("--dir")
        if i + 1 >= len(a):
            print("usage: phosphor receive [--dir FOLDER] [--timeout SECONDS]"); return 1
        dest = os.path.expanduser(a[i + 1])
        del a[i:i + 2]
    prof, _ = deckconf.load()
    return receive(prof, dest, timeout)


if __name__ == "__main__":
    sys.exit(main() or 0)
