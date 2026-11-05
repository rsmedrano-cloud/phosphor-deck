"""phosphor clipsync - one clipboard across screens ([clipboard] sync).

Internal: nobody types it. Each screen's `deck` command asks the brain for
WATCHER (`phosphor clipsync --script`, nothing when sync is off) and runs
it beside its ssh loop, for as long as that deck runs:

    screen: clipboard -> WATCHER -> ssh -> `phosphor clipsync` (the link)
                                              |
    brain:                        the hub (a unix socket, memory only)
                                              |
    other screens: clipboard <- WATCHER <- ssh <- their link

The hub relays a copy to every other linked screen and keeps nothing: no
history, nothing on disk, and a screen that links later only gets what's
copied from then on. It starts with the first link and goes away a little
after the last one.

    phosphor clipsync --script    the screen's half, for its `deck` to run
    phosphor clipsync             the link: lines on stdin and stdout
    phosphor clipsync --status    the linked screens, as JSON (--json)

Lines, both ways: `H NAME` (the screen says who it is), `C BASE64` (one
clip, text only), and `X off` from the link when sync is off, so the
screen stops asking.
"""
import base64, fcntl, hashlib, json, os, selectors, socket, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf

MAX_KB = 256          # the default cap, [clipboard] max_kb
IDLE = 10             # seconds the hub waits, with no screen linked, before it goes


def conf(prof=None):
    if prof is None:
        prof = deckconf.load()[0]
    return (prof or {}).get("clipboard") or {}


def on(prof=None):
    return conf(prof).get("sync") is True


def cap(prof=None):
    """The largest clip, in bytes."""
    try:
        kb = int(conf(prof).get("max_kb", MAX_KB))
    except (TypeError, ValueError):
        kb = MAX_KB
    return max(1, kb) * 1024


def rundir():
    """A private place for the hub's socket: the login's runtime dir (tmpfs,
    gone at logout), else one of our own under ~/.cache."""
    rt = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    if not os.path.isdir(rt) or not os.access(rt, os.W_OK):
        rt = os.path.join(os.path.expanduser("~"), ".cache", "phosphor")
        os.makedirs(rt, mode=0o700, exist_ok=True)
    return rt


def sock_path():
    return os.path.join(rundir(), "phosphor-clip.sock")


# ── the screen's half ─────────────────────────────────────────────────────
# POSIX sh and the clipboard tool the screen already has: nothing installed.
# $1 is the deck's pid (it ends within a second or two of that deck), the
# rest is the command that reaches the link (ssh to the brain, or the link
# itself on the brain).
WATCHER = r"""D=$1; shift
MAX=@MAX@
R= W= WATCH= SECRET= NOPASTE=
TO=; command -v timeout >/dev/null 2>&1 && TO="timeout 10"   # a tool that hangs never holds up the next clip
if [ -d /data/data/com.termux ]; then
  # Android lets only the app in front read the clipboard: receive only.
  # Termux's commands wait forever for a Termux:API app that isn't there:
  # still linked, but the brain hears why nothing lands here.
  if ! command -v termux-clipboard-set >/dev/null 2>&1; then
    NOPASTE="pkg install termux-api"
  elif [ -n "$TO" ] && { timeout 5 termux-clipboard-get >/dev/null 2>&1; [ $? -eq 124 ]; }; then
    NOPASTE="the Termux:API app"
  else
    W=termux-clipboard-set
  fi
elif [ "$(uname -s)" = Darwin ]; then
  R=pbpaste W=pbcopy SECRET=mac
elif [ -n "$WAYLAND_DISPLAY" ] && command -v wl-paste >/dev/null 2>&1 && command -v wl-copy >/dev/null 2>&1; then
  R="wl-paste -n -t text" W=wl-copy WATCH=1 SECRET=wl
elif [ -n "$DISPLAY" ] && command -v xclip >/dev/null 2>&1; then
  R="xclip -o -selection clipboard" W="xclip -i -selection clipboard" SECRET=x
elif [ -n "$DISPLAY" ] && command -v xsel >/dev/null 2>&1; then
  R="xsel -ob" W="xsel -ib"
else
  exit 0
fi
B64D="base64 -d"; printf eA== | base64 -d >/dev/null 2>&1 || B64D="base64 -D"
d=$(mktemp -d 2>/dev/null) || exit 0
trap 'rm -rf "$d"' EXIT
trap 'exit 0' INT TERM HUP

alive() { kill -0 "$D" 2>/dev/null && [ ! -e "$d/gone" ]; }
look() { $R 2>/dev/null | cksum; }     # "CRC LENGTH" of what's on it now
secret() {                             # a password manager marked it: it stays here
  case $SECRET in
    x)   xclip -o -selection clipboard -t TARGETS 2>/dev/null | grep -q x-kde-passwordManagerHint ;;
    wl)  wl-paste -l 2>/dev/null | grep -q x-kde-passwordManagerHint ;;
    mac) osascript -l JavaScript -e 'ObjC.import("AppKit"); $.NSPasteboard.generalPasteboard.types.js.map(t => t.js).join("\n")' 2>/dev/null \
           | grep -q org.nspasteboard.ConcealedType ;;
    *)   false ;;
  esac
}
ticks() {                              # a line whenever it may have changed
  if [ -n "$WATCH" ]; then
    wl-paste -t text --watch sh -c 'cat >/dev/null; echo' & w=$!
    while alive; do sleep 1; done
    kill "$w" 2>/dev/null
  else
    while alive; do echo; sleep 1; done
  fi
}
up() {                                 # what this screen copies, to the brain
  printf 'H %s\n' "$(uname -n)"
  [ -n "$NOPASTE" ] && printf 'P %s\n' "$NOPASTE"
  if [ -z "$R" ]; then
    while alive; do sleep 2; done
    return
  fi
  seen=$(look)
  ticks | while read -r _; do
    now=$(look)
    [ "$now" = "$seen" ] && continue
    seen=$now
    [ "$now" = "$(cat "$d/got" 2>/dev/null)" ] && continue   # it just came from the brain
    n=${now##* }
    [ "$n" -gt 0 ] && [ "$n" -le "$MAX" ] || continue
    secret && continue
    printf 'C %s\n' "$($R 2>/dev/null | base64 | tr -d '\n')"
  done
}
down() {                               # what the other screens copy, onto this one
  while IFS= read -r line; do
    case $line in
      "C "*) [ -n "$W" ] || continue
             v=${line#C }
             printf %s "$v" | $B64D 2>/dev/null | cksum > "$d/got"
             printf %s "$v" | $B64D 2>/dev/null | $TO $W ;;
      "X off") : > "$d/off" ;;
    esac
  done
  : > "$d/gone"
}
while kill -0 "$D" 2>/dev/null && [ ! -e "$d/off" ]; do
  rm -f "$d/gone"
  up | "$@" | down
  i=0                                  # the link dropped: again in 10s, unless the deck went
  while [ $i -lt 10 ] && [ ! -e "$d/off" ] && kill -0 "$D" 2>/dev/null; do sleep 1; i=$((i + 1)); done
done
"""


def script(prof=None):
    """The watcher for a screen's `deck`, or "" when sync is off."""
    return WATCHER.replace("@MAX@", str(cap(prof))) if on(prof) else ""


SSH = "ssh -T -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=2"


def launch(target, phosphor, heredoc=False):
    """The line a remote screen's `deck` runs before its ssh loop: fetch the
    watcher from the brain and run it in the background, away from the
    terminal (its stdin is /dev/null: the deck's own ssh owns the keys).
    heredoc: for a script written through an unquoted heredoc, $ escaped."""
    line = ("( w=$(%s -o ConnectTimeout=10 %s '%s clipsync --script' 2>/dev/null) && [ -n \"$w\" ] && "
            "exec sh -c \"$w\" clipsync $$ %s %s '%s clipsync' ) </dev/null >/dev/null 2>&1 &"
            % (SSH, target, phosphor, SSH, target, phosphor))
    return line.replace("$", "\\$") if heredoc else line


def launch_local(phosphor):
    """The same, for `deck` on the brain itself: no ssh. A screen that ssh'd
    in runs its own watcher, so this one is only for a terminal on the brain."""
    return ("[ -z \"$SSH_CONNECTION\" ] && ( w=$(%s clipsync --script 2>/dev/null) && [ -n \"$w\" ] && "
            "exec sh -c \"$w\" clipsync $$ %s clipsync ) </dev/null >/dev/null 2>&1 &"
            % (phosphor, phosphor))


# ── the hub ───────────────────────────────────────────────────────────────
class Hub:
    def __init__(self, limit):
        self.limit = limit
        self.sel = selectors.DefaultSelector()
        self.peers = {}           # conn -> {"buf", "skip", "name", "from", "since", "status"}
        self.last = None          # hash of the last clip relayed: the same clip twice goes once
        self.empty = time.time()

    def line_max(self):
        return 4 * (self.limit // 3 + 1) + 64

    def accept(self, srv):
        c, _ = srv.accept()
        c.setblocking(False)
        self.peers[c] = {"buf": b"", "skip": False, "name": "", "from": "", "since": int(time.time())}
        self.sel.register(c, selectors.EVENT_READ)

    def drop(self, c):
        self.sel.unregister(c)
        self.peers.pop(c, None)
        c.close()
        if not self.screens():
            self.empty = time.time()

    def screens(self):
        return [p for p in self.peers.values() if not p.get("status")]

    def send(self, c, data):
        try:
            c.setblocking(True)
            c.settimeout(5)
            c.sendall(data)
            c.setblocking(False)
            return True
        except OSError:
            return False

    def handle(self, c, line):
        p = self.peers[c]
        kind, _, rest = line.partition(b" ")
        if kind == b"F":
            p["from"] = rest.decode("utf-8", "replace")[:64]
        elif kind == b"H":
            p["name"] = "".join(ch for ch in rest.decode("utf-8", "replace") if ch.isprintable())[:64]
        elif kind == b"P":
            # linked, but it can't paste: what it needs
            p["nopaste"] = "".join(ch for ch in rest.decode("utf-8", "replace") if ch.isprintable())[:64]
        elif kind == b"S":
            p["status"] = True
            out = [dict({"name": q["name"], "from": q["from"], "since": q["since"]},
                        **({"nopaste": q["nopaste"]} if q.get("nopaste") else {})) for q in self.screens()]
            self.send(c, (json.dumps(out) + "\n").encode())
            self.drop(c)
        elif kind == b"C":
            rest = rest.strip()
            try:
                size = len(base64.b64decode(rest, validate=True))
            except ValueError:
                return
            if not size or size > self.limit:
                return
            h = hashlib.sha256(rest).digest()
            if h == self.last:
                return
            self.last = h
            for o in list(self.peers):
                if o is not c and not self.peers[o].get("status") and not self.send(o, b"C " + rest + b"\n"):
                    self.drop(o)

    def read(self, c):
        try:
            data = c.recv(65536)
        except OSError:
            data = b""
        if not data:
            self.drop(c)
            return
        p = self.peers[c]
        p["buf"] += data
        while c in self.peers:
            i = p["buf"].find(b"\n")
            if i < 0:
                if len(p["buf"]) > self.line_max():     # too big: skip to its end
                    p["buf"], p["skip"] = b"", True
                return
            line, p["buf"] = p["buf"][:i], p["buf"][i + 1:]
            if p["skip"]:
                p["skip"] = False
                continue
            self.handle(c, line)

    def run(self, srv):
        self.sel.register(srv, selectors.EVENT_READ)
        while True:
            for key, _ in self.sel.select(timeout=1):
                if key.fileobj is srv:
                    self.accept(srv)
                elif key.fileobj in self.peers:
                    self.read(key.fileobj)
            if not self.screens() and time.time() - self.empty > IDLE:
                return


def hub():
    """Serve until no screen has been linked for IDLE seconds. One at a time:
    the lock decides, a second one just goes."""
    path = sock_path()
    lock = open(path + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o077)
    try:
        srv.bind(path)
    finally:
        os.umask(old)
    srv.listen(16)
    srv.setblocking(False)
    try:
        Hub(cap()).run(srv)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        srv.close()
    return 0


def connect(start=True):
    """A connection to the hub; started first when there's none (start)."""
    path = sock_path()
    for i in range(30):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(path)
            return s
        except OSError:
            s.close()
        if not start:
            return None
        if i == 0:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "--hub"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(0.1)
    return None


def linked():
    """The screens linked right now, [{name, from, since[, nopaste]}] (nopaste:
    what one that can't paste needs); None when no hub
    is running (nobody linked, or sync off)."""
    s = connect(start=False)
    if not s:
        return None
    try:
        s.settimeout(3)
        s.sendall(b"S\n")
        buf = b""
        while not buf.endswith(b"\n"):
            d = s.recv(65536)
            if not d:
                break
            buf += d
        return json.loads(buf.decode() or "[]")
    except (OSError, ValueError):
        return None
    finally:
        s.close()


def link():
    """stdin/stdout (the screen, through ssh) <-> the hub, until either ends."""
    out = sys.stdout.buffer
    if not on():
        out.write(b"X off\n"); out.flush()
        return 0
    s = connect()
    if not s:
        return 1
    sc = os.environ.get("SSH_CONNECTION", "").split()
    s.sendall(("F %s\n" % (sc[0] if sc else "local")).encode())
    inp = sys.stdin.fileno()
    sel = selectors.DefaultSelector()
    sel.register(inp, selectors.EVENT_READ)
    sel.register(s, selectors.EVENT_READ)
    try:
        while True:
            for key, _ in sel.select():
                if key.fileobj is s:
                    d = s.recv(65536)
                    if not d:
                        return 0
                    out.write(d); out.flush()
                else:
                    d = os.read(inp, 65536)
                    if not d:
                        return 0
                    s.sendall(d)
    except OSError:
        return 0
    finally:
        s.close()


def main():
    args = sys.argv[1:]
    if "--hub" in args:
        return hub()
    if "--script" in args:
        sys.stdout.write(script())
        return 0
    if "--status" in args or "--json" in args:
        print(json.dumps({"sync": on(), "screens": linked() or []}))
        return 0
    return link()


if __name__ == "__main__":
    sys.exit(main())
