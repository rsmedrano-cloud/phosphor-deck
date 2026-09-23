"""phosphor send - one real file, to whatever device grabs the link first.

    phosphor send FILE [--timeout SECONDS]

`phosphor clip` moves text onto every screen's clipboard; this moves an
actual file, of any size or type, onto one device's disk -- the way you'd
share a file with `qrcp` or a five-line Python http.server. It opens a
one-time link behind a random token, prints it with a QR to scan, and shuts
itself down the moment someone downloads it (or after the timeout, default
3 minutes, if nobody does). Reachable on your tailnet if you have one, on
your LAN otherwise -- never the internet, and gone as soon as it's used.
"""
import mimetypes, os, secrets, socket, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import clip, deckconf, mesh

DEFAULT_TIMEOUT = 180

def tailnet_ip():
    import shutil, subprocess
    if not shutil.which("tailscale"):
        return ""
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5).stdout
        return out.strip().splitlines()[0] if out.strip() else ""
    except Exception:
        return ""

def lan_ip():
    """The address this machine would use to reach the outside world --
    nothing is actually sent, connect() on a UDP socket just picks a route."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

def pick_address(prof):
    """(ip, where) -- the tailnet if you have one, else the LAN."""
    kind, _ = mesh.current(prof)
    if kind in ("tailscale", "headscale"):
        ip = tailnet_ip()
        if ip:
            return ip, "tailnet"
    return lan_ip(), "LAN"

def qr_lines(text):
    try:
        import qr
    except ImportError:
        return []
    m = qr.encode(text)
    return qr.render(m) if m else []

def handler_for(path, filename, data, ctype):
    class OneShot(BaseHTTPRequestHandler):
        served = False
        def do_GET(self):
            if self.path != path:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % filename)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            OneShot.served = True
        def log_message(self, *a):
            pass                       # our own status line covers this
    return OneShot

def send(file_path, prof, timeout=DEFAULT_TIMEOUT):
    if not os.path.isfile(file_path):
        print(row(BAD, file_path, "not a file")); return 1
    data = open(file_path, "rb").read()
    name = os.path.basename(file_path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    secret = secrets.token_urlsafe(12)
    path = "/%s/%s" % (secret, quote(name))
    ip, where = pick_address(prof)

    httpd = HTTPServer(("0.0.0.0", 0), handler_for(path, name, data, ctype))
    url_ = "http://%s:%d%s" % (ip, httpd.server_port, path)

    print(row(OK, "sharing", name, note="%d bytes" % len(data)))
    at = row(OK, "at", url_, note="%s, one download, %ds" % (where, timeout))
    print(at.replace(url_, "\x1b]8;;%s\x1b\\%s\x1b]8;;\x1b\\" % (url_, url_)))   # OSC 8: a tap/click opens it
    for l in qr_lines(url_):
        print("  " + l)
    clip.send(url_.encode())           # on every screen's clipboard: paste it into a browser
    print(DIM + "  waiting..." + RST)

    httpd.timeout = 1
    deadline = time.time() + timeout
    while not httpd.RequestHandlerClass.served and time.time() < deadline:
        httpd.handle_request()
    httpd.server_close()

    if httpd.RequestHandlerClass.served:
        print(row(OK, "sent", name)); return 0
    print(row(WARN, "timed out", "nobody came for it")); return 1

def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print("usage: phosphor send FILE [--timeout SECONDS]"); return 1
    timeout = DEFAULT_TIMEOUT
    if "--timeout" in a:
        i = a.index("--timeout")
        try:
            timeout = int(a[i + 1])
        except (IndexError, ValueError):
            print("usage: phosphor send FILE [--timeout SECONDS]"); return 1
        del a[i:i + 2]
    prof, _ = deckconf.load()
    return send(a[0], prof, timeout)

if __name__ == "__main__":
    sys.exit(main() or 0)
