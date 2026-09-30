#!/usr/bin/env python3
"""Commands that ask instead of quitting: run with nothing on a terminal,
each opens its own small screen, and answering it does the real thing.

    python3 tests/asks-check.py

Every command runs for real, in a pseudo-terminal, against a throwaway
HOME, profile, data and cache; the assistant, less and yazi are stand-ins
on PATH that only say what they were given. Nothing of the real deck.
"""
import base64, os, pty, re, select, shutil, signal, subprocess, sys, tempfile, time
import urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOSPHOR = os.path.join(ROOT, "phosphor")

tmp = tempfile.mkdtemp()
BIN = os.path.join(tmp, "bin")
WORK = os.path.join(tmp, "work")
CACHE = os.path.join(tmp, "cache")
for d in (BIN, WORK, CACHE, os.path.join(tmp, ".config", "phosphor")):
    os.makedirs(d, exist_ok=True)
PROFILE = os.path.join(tmp, ".config", "phosphor", "deck.toml")
open(PROFILE, "w").write('[deck]\nsession = "asks-probe"\n\n'
                         '[[hosts]]\nname = "probe-brain"\nrole = "brain"\nlocal = true\n\n'
                         '[[hosts]]\nname = "db-box"\nrole = "storage"\nssh = "db-box"\n')

def stub(name, body):
    p = os.path.join(BIN, name)
    open(p, "w").write("#!/bin/sh\n" + body + "\n")
    os.chmod(p, 0o755)
stub("claude", 'echo "ANSWER-FROM-CLAUDE: $1"')               # ask's -p is $1... then the prompt
stub("less", "cat")
stub("yazi", 'echo "$1" > "%s/yazi-opened"' % tmp)

ENV = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
ENV.update(HOME=tmp, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_DATA=os.path.join(tmp, "data"),
           PHOSPHOR_CACHE=CACHE, PHOSPHOR_NOTES="", PATH=BIN + ":/usr/bin:/bin",
           TERM="xterm-256color", LINES="30", COLUMNS="100")
ENV.pop("PHOSPHOR_NOTES")

fails = []
def need(what, ok, out=""):
    if not ok:
        fails.append(what + ("\n" + out[-600:] if out else ""))


class Term:
    """One command on a pseudo-terminal: keys in, everything it printed out."""
    def __init__(self, *argv):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(WORK)
            os.execve(sys.executable, [sys.executable, PHOSPHOR] + list(argv), ENV)
        self.out = ""

    def read(self, quiet=0.3, limit=10):
        """Until nothing new has come for `quiet` seconds (or it ended)."""
        end = time.time() + limit
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], quiet)
            if not r:
                return self.out
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return self.out
            if not data:
                return self.out
            self.out += data.decode("utf-8", "replace")
        return self.out

    def wait_for(self, text, limit=15):
        end = time.time() + limit
        while text not in self.out and time.time() < end:
            self.read(0.2, 1)
        return text in self.out

    def keys(self, *ks):
        for k in ks:
            self.read()
            os.write(self.fd, k.encode())
        return self

    def done(self, limit=15):
        end = time.time() + limit
        while time.time() < end:
            self.read(0.2, 1)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                return os.waitstatus_to_exitcode(status)
        os.kill(self.pid, signal.SIGKILL)
        os.waitpid(self.pid, 0)
        return None


def plain(s):
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)", "", s)


# ask: a box for the question, the notebook or not, the answer in a pager
t = Term("ask").keys("what is two plus two", "\r", "\r", "q")
rc = t.done()
out = plain(t.out)
need("ask: the question reaches the assistant, the answer shows", rc == 0 and "ANSWER-FROM-CLAUDE: -p" in out
     and "what is two plus two" in out, out)

# broadcast: tick the brain, type the command, confirm, it runs there
t = Term("broadcast")
t.keys(" ", "\r", "echo hi-from-broadcast", "\r")
need("broadcast: still asks before running", t.wait_for("run it on 1 host"), plain(t.out))
t.keys("y\r")
rc = t.done()
out = plain(t.out)
need("broadcast: the ticked host ran the typed command", rc == 0 and "hi-from-broadcast" in out
     and "probe-brain" in out and "db-box" not in out.split("command:")[-1], out)

# broadcast, backed out of: nothing runs
t = Term("broadcast").keys("q")
need("broadcast: q on the hosts screen runs nothing", t.done() == 0 and "command:" not in plain(t.out))

# clip: pick a file, it goes out as OSC 52
open(os.path.join(WORK, "a-note.txt"), "w").write("clip me please")
t = Term("clip").keys("j", "\r")                         # .. first, then a-note.txt
rc = t.done()
need("clip: the picked file's contents went onto the clipboard",
     rc == 0 and base64.b64encode(b"clip me please").decode() in t.out, plain(t.out))

# send: pick a file, download it once from the link it prints
t = Term("send").keys("j", "\r")
need("send: prints a one-time link", t.wait_for("/a-note.txt"), plain(t.out))
m = re.search(r"http://[0-9.]+:\d+/\S+?/a-note\.txt", plain(t.out))
got = b""
if m:
    try:
        got = urllib.request.urlopen(m.group(0), timeout=10).read()
    except OSError as e:
        need("send: the link answers (%s)" % e, False)
need("send: the picked file is what the link serves", got == b"clip me please" and t.done() == 0, plain(t.out))

# receive: its own screen, a real upload, then y opens it in yazi
t = Term("receive")
need("receive: prints an upload link", t.wait_for("waiting..."), plain(t.out))
m = re.search(r"http://[0-9.]+:\d+/[A-Za-z0-9_-]+", plain(t.out))
if m:
    body = (b"--XyZ\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo.txt\"\r\n"
            b"Content-Type: text/plain\r\n\r\nfrom the phone\r\n--XyZ--\r\n")
    req = urllib.request.Request(m.group(0) + "/upload", data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=XyZ"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except OSError as e:
        need("receive: the upload link answers (%s)" % e, False)
need("receive: offers yazi once the file lands", t.wait_for("open it in yazi"), plain(t.out))
t.keys("y")
rc = t.done()
landed = os.path.join(tmp, "received", "photo.txt")
opened = open(os.path.join(tmp, "yazi-opened")).read().strip() if os.path.exists(os.path.join(tmp, "yazi-opened")) else ""
need("receive: the file landed and yazi opened on it",
     rc == 0 and os.path.exists(landed) and opened == landed, plain(t.out))

# triage, nothing flagged: any host of the profile, then the assistant's answer
t = Term("triage")
need("triage: nothing flagged, it offers every host", t.wait_for("pick any host"), plain(t.out))
t.keys("\r")                                             # probe-brain: local, no ssh
rc = t.done(30)
need("triage: the picked host's snapshot went to the assistant",
     rc == 0 and "ANSWER-FROM-CLAUDE" in plain(t.out), plain(t.out))

# face: only images are offered, and the picked one is used
open(os.path.join(WORK, "pic.png"), "wb").write(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
t = Term("face")
t.read()
screen = plain(t.out)
need("face: images listed, other files not", "pic.png" in screen and "a-note.txt" not in screen, screen)
t.keys("j", "\r")
rc = t.done(60)
out = plain(t.out)
need("face: the picked image is the one it reads", "no such file" not in out and
     ("pic.png" in out.split("phosphor face")[-1] or "ImageMagick" in out), out)

# push: o turns it on, with a long random topic, and keeps a .bak
t = Term("push").keys("o", "q")
rc = t.done()
text = open(PROFILE).read()
need("push: o turns it on and makes up a topic", rc == 0 and re.search(r"\[push\][^\[]*enabled = true", text)
     and re.search(r'topic = "deck-[0-9a-f]{16}"', text), text + plain(t.out))
need("push: the profile before is kept as .bak", os.path.exists(PROFILE + ".bak"))

# tts: o turns it on
t = Term("tts").keys("o", "q")
rc = t.done()
need("tts: o turns it on", rc == 0 and re.search(r"\[tts\][^\[]*enabled = true", open(PROFILE).read()), plain(t.out))

# trace: t starts one of the tools deck.log knows, x stops it
open(os.path.join(CACHE, "deck.log"), "w").write("2026-09-30 10:00:00  FLEET      start\n")
t = Term("trace").keys("t", "\r", "q")
t.done()
need("trace: t starts the picked tool's trace", os.path.exists(os.path.join(CACHE, "trace-FLEET")), plain(t.out))
t = Term("trace").keys("x", "\r", "q")
t.done()
need("trace: x stops it", not os.path.exists(os.path.join(CACHE, "trace-FLEET")), plain(t.out))

# piped, nothing on a terminal: the old behavior, no screen
r = subprocess.run([sys.executable, PHOSPHOR, "send"], env=ENV, cwd=WORK, stdin=subprocess.DEVNULL,
                   capture_output=True, text=True, timeout=20)
need("send without a terminal: the usage line, as before", r.returncode == 1 and "usage" in r.stdout)

shutil.rmtree(tmp, ignore_errors=True)
if fails:
    print("asks-check FAIL:\n  " + "\n  ".join(fails)); sys.exit(1)
print("asks-check ok")
