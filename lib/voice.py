"""phosphor voice - talk into a pane: a screen records, the brain writes it down.

MIC (on the bar, or its key, Alt-m) opens in place of the pane you were in.
A screen that can record (a phone with Termux and termux-api) records; the
brain turns the audio into text with whisper.cpp, here, and types it into
that pane without Enter: read it, then press Enter yourself. The audio goes
from the screen to the brain over the deck's own ssh and nowhere else.

Which screen: every screen's `deck` links to the brain (beside the
clipboard's link, phosphor clipsync). One linked screen can record: that
one, without asking. Several: MIC lists them, a tap or a number picks.
None: MIC says what a screen needs.

    phosphor voice                is it ready: whisper, its model, the screens that can record (--json)
    phosphor voice install        build whisper.cpp here and download its model
    phosphor voice --here         what MIC opens in place of a pane
    phosphor voice --file F       write down a sound file, print the text

    [voice]
    enabled = true       # false hides MIC; unset, it's on once whisper is installed
    model = "base"       # tiny, base, small, medium: bigger is slower and better
    language = "auto"    # or "es", "en"...
    max_seconds = 120    # a recording stops itself after this
"""
import base64, json, os, selectors, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf

WHISPER_TAG = "v1.9.5"
WHISPER_GIT = "https://github.com/ggml-org/whisper.cpp"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-%s.bin"
MODELS = ("tiny", "base", "small", "medium")
MAX_SECONDS = 120
IDLE = 10                       # seconds the hub waits, with nobody linked, before it goes
LINE_MAX = 8 * 1024 * 1024      # the longest line a link may send: a recording, base64


# ── what's set and what's there ────────────────────────────────────────────
def conf(prof=None):
    if prof is None:
        prof = deckconf.load()[0]
    return (prof or {}).get("voice") or {}


def home():
    return os.path.join(deckconf.data_dir(), "whisper")


def whisper_bin(prof=None):
    """whisper.cpp's command line: [voice] whisper, else the one `voice
    install` built, else whisper-cli on PATH."""
    own = conf(prof).get("whisper")
    if own:
        return deckconf.exe(str(own))
    built = os.path.join(home(), "bin", "whisper-cli")
    return built if os.access(built, os.X_OK) else deckconf.exe("whisper-cli")


def model_name(prof=None):
    m = str(conf(prof).get("model") or "base")
    return m


def model_path(prof=None):
    m = model_name(prof)
    if os.sep in m:
        return os.path.expanduser(m)
    return os.path.join(home(), "models", "ggml-%s.bin" % m)


def max_seconds(prof=None):
    try:
        return max(5, min(600, int(conf(prof).get("max_seconds", MAX_SECONDS))))
    except (TypeError, ValueError):
        return MAX_SECONDS


def missing(prof=None):
    """What the brain lacks to write audio down, as words; [] when nothing."""
    out = []
    if not whisper_bin(prof):
        out.append("whisper.cpp (phosphor voice install)")
    if not os.path.isfile(model_path(prof)):
        out.append("its model %s (phosphor voice install)" % model_name(prof))
    if not deckconf.exe("ffmpeg"):
        out.append("ffmpeg (your package manager)")
    return out


def on(prof=None):
    """MIC is on the bar and screens link for it: [voice] enabled, or, unset,
    once whisper and its model are here."""
    e = conf(prof).get("enabled")
    if e is not None:
        return e is True
    return not missing(prof)


# ── writing it down ────────────────────────────────────────────────────────
def transcribe(audio, prof=None):
    """(text, None) or (None, why): the sound file as words. ffmpeg makes the
    16 kHz mono wav whisper wants, from whatever the screen recorded."""
    lack = missing(prof)
    if lack:
        return None, "missing: " + ", ".join(lack)
    with tempfile.TemporaryDirectory(prefix="phosphor-voice-") as d:
        wav = os.path.join(d, "a.wav")
        r = subprocess.run([deckconf.exe("ffmpeg"), "-nostdin", "-loglevel", "error", "-y", "-i", audio,
                            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.isfile(wav):
            return None, "ffmpeg couldn't read the recording: " + (r.stderr.strip().splitlines() or ["?"])[-1]
        lang = str(conf(prof).get("language") or "auto")
        threads = str(max(1, min(8, (os.cpu_count() or 2) // 2)))
        r = subprocess.run([whisper_bin(prof), "-m", model_path(prof), "-f", wav, "-l", lang,
                            "-t", threads, "-nt", "-np"],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return None, "whisper failed: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    return clean(r.stdout), None


def clean(out):
    """whisper's lines into one line of text: no [BLANK_AUDIO], (music) or
    other bracketed sounds, no control characters."""
    import re
    text = " ".join(l.strip() for l in out.splitlines() if l.strip())
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = "".join(c for c in text if c.isprintable())
    return " ".join(text.split())


# ── the screen's half ──────────────────────────────────────────────────────
# Run beside the clipboard's (clipsync.script puts them together). Termux
# only, for now: it records with termux-microphone-record when the brain
# asks, and sends the file back up the same link. $1 is the deck's pid; the
# rest is the command that reaches the brain's clipsync, to which `voice`
# is added.
WATCHER = r"""D=$1; shift
[ -d /data/data/com.termux ] || exit 0
TO=; command -v timeout >/dev/null 2>&1 && TO="timeout 10"
WHY=
if ! command -v termux-microphone-record >/dev/null 2>&1; then
  WHY="pkg install termux-api"
elif [ -n "$TO" ] && { timeout 5 termux-microphone-record -i >/dev/null 2>&1; [ $? -eq 124 ]; }; then
  WHY="the Termux:API app"
fi
d=$(mktemp -d 2>/dev/null) || exit 0
trap 'termux-microphone-record -q >/dev/null 2>&1; rm -rf "$d"' EXIT
trap 'exit 0' INT TERM HUP
alive() { kill -0 "$D" 2>/dev/null && [ ! -e "$d/gone" ]; }
up() {                                 # who this is, then what it recorded
  printf 'H %s\n' "$(uname -n)"
  if [ -n "$WHY" ]; then printf 'M no %s\n' "$WHY"; else printf 'M ok\n'; fi
  while alive; do
    for f in "$d"/out.*; do [ -e "$f" ] && cat "$f" && rm -f "$f"; done
    sleep 1
  done
}
say() { n=$((n + 1)); printf '%s\n' "$1" > "$d/tmp"; mv "$d/tmp" "$d/out.$n"; }
down() {                               # what the brain asks
  n=0
  while IFS= read -r line; do
    case $line in
      "R "*) $TO termux-microphone-record -q >/dev/null 2>&1
             rm -f "$d/a.m4a"
             $TO termux-microphone-record -f "$d/a.m4a" -l "${line#R }" -e aac -r 16000 -c 1 >/dev/null 2>&1 \
               || say "E the microphone didn't start" ;;
      S)     $TO termux-microphone-record -q >/dev/null 2>&1; sleep 1
             if [ -s "$d/a.m4a" ]; then
               n=$((n + 1)); { printf 'A '; base64 < "$d/a.m4a" | tr -d '\n'; echo; } > "$d/tmp"; mv "$d/tmp" "$d/out.$n"
             else
               say "E nothing was recorded: is the microphone allowed for Termux:API?"
             fi
             rm -f "$d/a.m4a" ;;
      Q)     $TO termux-microphone-record -q >/dev/null 2>&1; rm -f "$d/a.m4a" ;;
      "X off") : > "$d/off" ;;
    esac
  done
  : > "$d/gone"
}
while kill -0 "$D" 2>/dev/null && [ ! -e "$d/off" ]; do
  rm -f "$d/gone"
  up | "$@" voice | down
  i=0
  while [ $i -lt 10 ] && [ ! -e "$d/off" ] && kill -0 "$D" 2>/dev/null; do sleep 1; i=$((i + 1)); done
done
"""


# ── the hub: screens that can record, and the MIC panes asking ─────────────
def sock_path():
    import clipsync
    return os.path.join(clipsync.rundir(), "phosphor-voice.sock")


class Hub:
    """Screens send H NAME, M ok | M no WHY, then A BASE64 (a recording) or
    E WHY. A MIC pane sends W (I'm asking), L (the screens, answered with
    J [json]), R ID (record there), S (stop and send it), Q (forget it); it
    gets the screen's A or E back. A MIC pane that goes cancels its
    recording."""

    def __init__(self):
        self.sel = selectors.DefaultSelector()
        self.peers = {}          # conn -> {"buf", "skip", "id", "name", "from", "mic", "asker", "on"}
        self.n = 0
        self.empty = time.time()

    def accept(self, srv):
        c, _ = srv.accept()
        c.setblocking(False)
        self.n += 1
        self.peers[c] = {"buf": b"", "skip": False, "id": self.n, "name": "", "from": "", "mic": None}
        self.sel.register(c, selectors.EVENT_READ)

    def send(self, c, data):
        try:
            c.setblocking(True)
            c.settimeout(5)
            c.sendall(data)
            c.setblocking(False)
            return True
        except OSError:
            return False

    def drop(self, c):
        p = self.peers.pop(c, None)
        try:
            self.sel.unregister(c)
        except (KeyError, ValueError):
            pass
        c.close()
        if p is None:
            return
        for o, q in list(self.peers.items()):
            if q.get("on") is c and p.get("asker"):       # the asker went: forget the recording
                q["on"] = None
                self.send(o, b"Q\n")
            if p.get("on") is o and q.get("asker"):       # its screen went: tell the asker
                self.send(o, b"E the screen's link dropped\n")
        if not self.screens():
            self.empty = time.time()

    def screens(self):
        return [(c, p) for c, p in self.peers.items() if p.get("mic") is not None]

    def listing(self):
        return [{"id": p["id"], "name": p["name"], "from": p["from"], "mic": p["mic"] is True,
                 **({"why": p["why"]} if p.get("why") else {})} for _, p in self.screens()]

    def handle(self, c, line):
        p = self.peers[c]
        kind, _, rest = line.partition(b" ")
        word = "".join(ch for ch in rest.decode("utf-8", "replace") if ch.isprintable())[:120]
        if kind == b"F":
            p["from"] = word[:64]
        elif kind == b"H":
            p["name"] = word[:64]
        elif kind == b"M":
            p["mic"] = word == "ok"
            p["why"] = word[3:] if word.startswith("no ") else ""
        elif kind == b"W":
            p["asker"] = True
        elif kind == b"L":
            self.send(c, ("J " + json.dumps(self.listing()) + "\n").encode())
        elif kind == b"R" and p.get("asker"):
            sid, _, secs = word.partition(" ")
            scr = next((o for o, q in self.screens() if str(q["id"]) == sid and q["mic"]), None)
            if scr is None:
                self.send(c, b"E that screen isn't linked anymore\n")
                return
            p["on"] = scr
            self.peers[scr]["on"] = c
            secs = int(secs) if secs.isdigit() else MAX_SECONDS
            self.send(scr, ("R %d\n" % max(5, min(600, secs))).encode())
        elif kind in (b"S", b"Q") and p.get("asker") and p.get("on") in self.peers:
            self.send(p["on"], kind + b"\n")
        elif kind in (b"A", b"E") and p.get("on") in self.peers:
            asker = p["on"]
            p["on"] = None
            self.peers[asker]["on"] = None
            self.send(asker, line + b"\n")

    def read(self, c):
        try:
            data = c.recv(262144)
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
                if len(p["buf"]) > LINE_MAX:
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
            if not self.peers and time.time() - self.empty > IDLE:
                return


def connect(start=True):
    import clipsync
    return clipsync.dial(sock_path(), [sys.executable, os.path.abspath(__file__), "--hub"], start)


def link():
    """A screen's voice link: stdin/stdout (ssh) <-> the hub."""
    import clipsync
    if not on():
        sys.stdout.buffer.write(b"X off\n"); sys.stdout.flush()
        return 0
    s = connect()
    if not s:
        return 1
    s.sendall(("F %s\n" % clipsync.came_from()).encode())
    return clipsync.pump(s)


class Asker:
    """The MIC pane's line to the hub."""

    def __init__(self, s):
        self.s, self.buf = s, b""
        s.sendall(b"W\n")

    def say(self, line):
        self.s.sendall(line.encode() + b"\n")

    def line(self, timeout):
        """The next line, or None by the timeout (or "" when the hub went)."""
        end = time.time() + timeout
        while b"\n" not in self.buf:
            left = end - time.time()
            if left <= 0:
                return None
            self.s.settimeout(left)
            try:
                d = self.s.recv(262144)
            except OSError:
                return None
            if not d:
                return ""
            self.buf += d
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("ascii", "replace")

    def screens(self):
        self.say("L")
        for _ in range(5):
            l = self.line(3)
            if l is None or l == "":
                return []
            if l.startswith("J "):
                try:
                    return json.loads(l[2:])
                except ValueError:
                    return []
        return []


def linked():
    """The screens linked for voice right now, or [] (no hub: none)."""
    s = connect(start=False)
    if not s:
        return []
    try:
        return Asker(s).screens()
    except OSError:
        return []
    finally:
        s.close()


# ── MIC: the pane in place of yours ────────────────────────────────────────
def zj(*a):
    import proc
    z = proc.zellij() or "zellij"
    try:
        return subprocess.run([z, "action"] + list(a), capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def covered():
    """The pane this one stands in for: "terminal_N", or None."""
    import edit
    try:
        at = edit.where_am_i() if os.environ.get("ZELLIJ_PANE_ID") else None
    except (OSError, ValueError, KeyError):
        at = None
    return "terminal_%d" % at[3] if at and at[3] is not None else None


def type_later(pane, text):
    """Type text into pane once this one is gone: zellij drops what's
    written to a hidden pane, so a child of its own waits for it to show."""
    code = ("import sys, time; sys.path.insert(0, %r); import voice, json\n"
            "t = sys.stdin.read(); pane = %r\n"
            "for _ in range(50):\n"
            "    ps = json.loads(voice.zj('list-panes', '-a', '-j') or '[]')\n"
            "    p = next((p for p in ps if not p.get('is_plugin') and 'terminal_%%d' %% p.get('id', -1) == pane), None)\n"
            "    if p is None: sys.exit(0)\n"
            "    if not p.get('is_suppressed'): break\n"
            "    time.sleep(0.1)\n"
            "voice.zj('write-chars', '--pane-id', pane, t)\n" % (os.path.dirname(os.path.abspath(__file__)), pane))
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    p.stdin.write(text.encode()); p.stdin.close()


def here(pane=None):
    """MIC: pick a screen, record, write it down, type it into the pane."""
    from ui import FG, DIM, PH, AMB, RED, RST, topbar, getkey
    import dlog
    prof = deckconf.load()[0]
    import edit
    pane = pane or covered()
    back = edit.back_line()
    out = sys.stdout

    def show(*lines, col=FG):
        out.write("\x1b[2J\x1b[H" + back + "\n" + "\n".join(topbar("MIC", "talk into the pane")) + "\n\n")
        for l in lines:
            out.write("  " + col + l + RST + "\n")
        out.flush()

    def wait_back(*lines, col=AMB):
        show(*lines, col=col)
        out.write("\n  " + DIM + "any key: back" + RST + "\n"); out.flush()
        getkey()
        return 1

    lack = missing(prof)
    if lack:
        return wait_back("MIC can't write audio down yet; the brain needs:", *("  " + l for l in lack))
    if not pane:
        return wait_back("MIC types into the pane it opened over, and found none.")
    s = connect()
    if not s:
        return wait_back("MIC couldn't start its hub (phosphor voice --json says more).")
    ask = Asker(s)
    try:
        rows = ask.screens()
        can = [r for r in rows if r.get("mic")]
        if not can:
            why = ["  %s: %s" % (r["name"] or r["from"], r.get("why", "")) for r in rows]
            return wait_back("No screen linked to the deck can record.",
                             "A phone with Termux records: pkg install termux-api, the Termux:API",
                             "app, then leave and come back with deck.", *why)
        scr = can[0]
        if len(can) > 1:
            show("Which screen records?", "", *("%d  %s  (%s)" % (i + 1, r["name"], r["from"])
                                                for i, r in enumerate(can[:9])))
            while True:
                k = getkey(mouse=True)
                if k in ("\x1b", "q", "\x03"):
                    return 0
                if isinstance(k, str) and k.isdigit() and 1 <= int(k) <= len(can[:9]):
                    scr = can[int(k) - 1]; break
                if isinstance(k, tuple) and k[0] == "TAP" and 1 <= k[2] - 6 <= len(can[:9]):
                    scr = can[k[2] - 7]; break
        dlog.event("VOICE", "record on %s" % scr["name"])
        ask.say("R %d %d" % (scr["id"], max_seconds(prof)))
        start, got = time.time(), None
        while got is None:
            secs = int(time.time() - start)
            show(PH + "● " + RST + FG + "recording on %s   %d:%02d" % (scr["name"], secs // 60, secs % 60),
                 "", DIM + "Enter or a tap: stop and write it down   Esc: forget it" + RST)
            k = getkey(timeout=1, mouse=True)
            if k in ("\x1b", "q", "\x03"):
                ask.say("Q")
                return 0
            if k in ("\r", "\n", " ") or (isinstance(k, tuple) and k[0] == "TAP") \
                    or secs > max_seconds(prof) + 2:
                ask.say("S")
                show("sending it from %s..." % scr["name"])
                got = ask.line(60)
                while got is not None and got[:2] not in ("A ", "E ") and got != "":
                    got = ask.line(60)
                break
        if not got or got.startswith("E "):
            return wait_back(got[2:] if got else "The screen didn't send the recording.", col=RED)
        show("writing it down...")
        with tempfile.TemporaryDirectory(prefix="phosphor-voice-") as d:
            f = os.path.join(d, "a.m4a")
            try:
                with open(f, "wb") as fh:
                    fh.write(base64.b64decode(got[2:]))
            except ValueError:
                return wait_back("The recording came broken.", col=RED)
            text, why = transcribe(f, prof)
        if why:
            return wait_back(why, col=RED)
        if not text:
            return wait_back("Nothing heard in it.")
        type_later(pane, text)
        dlog.event("VOICE", "typed %d chars" % len(text))
        return 0
    finally:
        s.close()


# ── install ────────────────────────────────────────────────────────────────
def install(prof=None):
    """whisper.cpp built under home(), and the model downloaded."""
    import tts
    root = home()
    os.makedirs(os.path.join(root, "bin"), exist_ok=True)
    print("voice: whisper.cpp %s and the %s model, into %s" % (WHISPER_TAG, model_name(prof), root))
    if not deckconf.exe("ffmpeg"):
        print("  ffmpeg is missing: install it with your package manager (apt install ffmpeg)")
    for tool in ("git", "make"):
        if not deckconf.exe(tool):
            print("  %s is missing: install it first (apt install %s)" % (tool, tool)); return 1
    if not (deckconf.exe("c++") or deckconf.exe("g++") or deckconf.exe("clang++")):
        print("  a C++ compiler is missing: apt install g++"); return 1
    built = os.path.join(root, "bin", "whisper-cli")
    if os.access(built, os.X_OK):
        print("  whisper-cli: already built")
    else:
        cmake = deckconf.exe("cmake")
        if not cmake:
            venv = os.path.join(root, "venv")
            print("  cmake: none here, so a private one (pip, in %s)" % venv)
            if subprocess.run([sys.executable, "-m", "venv", venv]).returncode != 0 or \
               subprocess.run([os.path.join(venv, "bin", "pip"), "install", "-q", "cmake"]).returncode != 0:
                print("  couldn't get cmake: apt install cmake, then again"); return 1
            cmake = os.path.join(venv, "bin", "cmake")
        src = os.path.join(root, "src")
        if not os.path.isdir(os.path.join(src, ".git")):
            if subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", WHISPER_TAG, WHISPER_GIT, src]).returncode:
                print("  couldn't clone %s" % WHISPER_GIT); return 1
        b = os.path.join(src, "build")
        jobs = str(os.cpu_count() or 2)
        print("  building (a few minutes)...")
        if subprocess.run([cmake, "-S", src, "-B", b, "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
                           "-DWHISPER_BUILD_TESTS=OFF", "-DWHISPER_BUILD_EXAMPLES=ON"],
                          stdout=subprocess.DEVNULL).returncode or \
           subprocess.run([cmake, "--build", b, "-j", jobs, "--target", "whisper-cli"],
                          stdout=subprocess.DEVNULL).returncode:
            print("  the build failed: the lines above say why"); return 1
        shutil.copy2(os.path.join(b, "bin", "whisper-cli"), built)
        print("  whisper-cli: built")
    m = model_path(prof)
    if os.path.isfile(m):
        print("  model %s: already here" % model_name(prof))
    elif os.sep in model_name(prof) or model_name(prof) not in MODELS:
        print("  model %s: not one to download (%s); put the file there yourself" % (model_name(prof), ", ".join(MODELS)))
        return 1
    elif not tts.download_file_with_progress(MODEL_URL % model_name(prof), m):
        return 1
    lack = missing(prof)
    if lack:
        print("  still missing: " + ", ".join(lack)); return 1
    print("ready: MIC shows on the bar after phosphor gen && phosphor restart; a phone records once its deck reconnects")
    return 0


# ── the command ────────────────────────────────────────────────────────────
def status(prof=None):
    lack = missing(prof)
    return {"enabled": on(prof), "ready": not lack, "missing": lack, "whisper": whisper_bin(prof),
            "model": model_name(prof), "model_path": model_path(prof),
            "screens": linked() if on(prof) else []}


def main():
    args = sys.argv[1:]
    if args[:1] in (["-h"], ["--help"]):
        print(__doc__.strip()); return 0
    if "--hub" in args:
        import clipsync
        return clipsync.serve(sock_path(), Hub())
    if "--link" in args:
        return link()
    if args[:1] == ["install"]:
        return install()
    if "--here" in args:
        pane = args[args.index("--pane") + 1] if "--pane" in args and args.index("--pane") + 1 < len(args) else None
        return here(pane)
    if "--file" in args:
        i = args.index("--file")
        if i + 1 >= len(args):
            print("phosphor voice --file F: which file", file=sys.stderr); return 2
        text, why = transcribe(args[i + 1])
        if why:
            print("phosphor voice: " + why, file=sys.stderr); return 1
        print(text); return 0
    st = status()
    if "--json" in args:
        from ui import emit
        return emit(st)
    from ui import PH, AMB, DIM, RST
    print("voice: " + ("on" if st["enabled"] else "off") + ("" if st["ready"] else " (not ready)"))
    print("  whisper  " + (st["whisper"] or AMB + "missing: phosphor voice install" + RST))
    print("  model    %s  %s" % (st["model"], DIM + st["model_path"] + RST))
    for l in st["missing"]:
        print("  " + AMB + "missing  " + RST + l)
    if st["enabled"]:
        if not st["screens"]:
            print("  screens  none linked (a phone with Termux and termux-api, its deck reconnected)")
        for s in st["screens"]:
            print("  screen   %s (%s): %s" % (s["name"], s["from"], PH + "can record" + RST if s["mic"] else s.get("why", "can't record")))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
