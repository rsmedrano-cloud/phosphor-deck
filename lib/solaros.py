#!/usr/bin/env python3
"""phosphor solaros - a SolarOS panel as a face of the deck.

One switch, like `phosphor web on`: `on` keeps `phosphor glance --serve`
running as a user service (on the LAN, where a panel on the home Wi-Fi
finds it), prints the two lines to type on the panel and puts them on the
clipboard of every screen looking at the deck. The panel fetches the
Phosphor app from the brain and runs it: a menu of the deck's tabs, and
a tab opens the panel's own deck over ssh (`session`): the tab bar on
top, one tab below, Ctrl-arrows between them.

What the panel reads (the glance, which tabs it can open) comes over
HTTP, behind the token. What writes -- typing to an assistant, a note,
an upgrade -- only ever goes over ssh, with the panel's own key: the
token crosses the LAN in the clear, and a sniffed token must never be
able to type into a pane. That key is paired once: the panel sends it,
`phosphor solaros pair` shows its fingerprint (the panel shows the same
one) and waits for your Enter. It lands in authorized_keys with a forced
command: the panel gets this module's session, whatever it asks to run --
though the deck's tabs the menu opens take what's typed, a shell's
included, so pairing a panel is handing it the deck.

SolarOS's ssh can't send a remote command (it always asks for a shell),
so the app says over HTTP what it's about to open ("the AI tab") just
before it connects; the session takes that once, within a minute, if it
is still on the menu's list. Without one the session starts on the menu.

    phosphor solaros [status]   the service, the address, the paired panels
    phosphor solaros on         start serving, print + copy the panel's lines
    phosphor solaros off        stop serving (the panel's key stays)
    phosphor solaros pair       let one panel in: its key, your Enter
    phosphor solaros forget     take every paired panel's key out again
"""
import base64, getpass, hashlib, json, os, re, select, shlex, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, FG, PH, AMB, RED, RST, OK, BAD, WARN, row
import deckconf
import dlog
import ui

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOSPHOR = os.path.join(REPO, "phosphor")
UNIT = "phosphor-glance.service"
UDIR = os.path.expanduser("~/.config/systemd/user")
MARK = "phosphor-solaros"            # the comment on a paired panel's authorized_keys line
WINDOW = 600                         # seconds a pairing window stays open
INTENT_TTL = 60                      # seconds an "open X next" from the panel stays good
INV = "\x1b[7m"
USAGE = "usage: phosphor solaros [status | on | off | pair | forget]"
KEYLINE = re.compile(r"^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp(?:256|384|521)) ([A-Za-z0-9+/]+={0,3})(?: .*)?$")

def data(name):
    return os.path.join(deckconf.data_dir(), "solaros-" + name)

def write_private(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(p + ".tmp", p)

def read_json(p):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def rm(p):
    try: os.remove(p)
    except OSError: pass

# ── the profile and the service ───────────────────────────────

def serve_mode(prof):
    """"lan", "tailnet", or None when nothing is served."""
    v = ((prof or {}).get("glance") or {}).get("serve")
    return v if v in ("lan", "tailnet") else None

def port(prof):
    try: return int(((prof or {}).get("glance") or {}).get("port") or 8484)
    except (TypeError, ValueError): return 8484

def unit(prof):
    """The user service that keeps `glance --serve` up (gen writes it too,
    from the profile's [glance] serve). It binds to the address it finds
    at start: Restart brings it back once the network is."""
    lan = " --lan" if serve_mode(prof) == "lan" else ""
    return """[Unit]
Description=Phosphor glance for gadgets - the SolarOS panel's door (%(where)s, token)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%(py)s %(phosphor)s glance --serve%(lan)s --port %(port)d
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
""" % {"where": "LAN" if lan else "tailnet", "py": shlex.quote(sys.executable),
       "phosphor": shlex.quote(PHOSPHOR), "lan": lan, "port": port(prof)}

def set_serve(value):
    """`serve = "lan"` (or false) in the profile's [glance], as text, so
    its comments survive; the section is made when it isn't there."""
    p = os.environ.get("PHOSPHOR_PROFILE", deckconf.CONF)
    text = open(p).read()
    line = 'serve = %s' % ('"%s"' % value if value else "false")
    sec = re.search(r"(?m)^\[glance\][ \t]*$", text)
    if sec:
        nxt = re.search(r"(?m)^\[", text[sec.end():])
        end = sec.end() + (nxt.start() if nxt else len(text) - sec.end())
        body = text[sec.end():end]
        pat = re.compile(r'(?m)^[ \t]*serve[ \t]*=.*$')
        body = pat.sub(line, body, count=1) if pat.search(body) else "\n" + line + body
        new = text[:sec.end()] + body + text[end:]
    else:
        new = text.rstrip("\n") + "\n\n[glance]\n" + line + "\n"
    err = deckconf.write_profile(new, expect=text, p=p)
    if err: raise RuntimeError(err)

def systemctl(*a):
    try:
        return subprocess.run(["systemctl", "--user"] + list(a), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(a, 1, "", str(e))

def active():
    return systemctl("is-active", UNIT).stdout.strip() == "active"

CODE = "23456789abcdefghjkmnpqrstuvwxyz"   # nothing to misread on a panel (0/o, 1/l/i), no Shift
MISSES = 20                                 # wrong codes before the window closes

def panel_lines(prof):
    """The two lines a panel types. The first carries a short code, not
    the token: good once, for WINDOW seconds (it opens a new window)."""
    import secrets, send
    ip = send.lan_ip() if serve_mode(prof) == "lan" else send.pick_address(prof)[0]
    code = "".join(secrets.choice(CODE) for _ in range(5))
    write_private(data("bootstrap.json"), json.dumps({"code": code, "until": time.time() + WINDOW, "misses": 0}))
    return ["curl -o /phosphor.py http://%s:%d/p/%s" % (ip, port(prof), code), "python /phosphor.py"]

def take_code(code):
    """GET /p/CODE: True once, while the window is open. MISSES wrong
    guesses close it, so a code can't be walked through on the LAN."""
    import hmac
    b = read_json(data("bootstrap.json"))
    if not b or time.time() > b.get("until", 0):
        rm(data("bootstrap.json")); return False
    if hmac.compare_digest(code.encode(), str(b.get("code", "")).encode()):
        rm(data("bootstrap.json")); return True
    b["misses"] = b.get("misses", 0) + 1
    if b["misses"] >= MISSES:
        rm(data("bootstrap.json"))
    else:
        write_private(data("bootstrap.json"), json.dumps(b))
    return False

# ── pairing: the panel's key, your Enter ──────────────────────

def auth_keys():
    return os.path.expanduser("~/.ssh/authorized_keys")

def blob(line):
    m = KEYLINE.match(line.strip())
    return m.group(2) if m else None

def fingerprint(key):
    """SHA256:... as ssh-keygen -l prints it, or None for something
    that isn't a public key line."""
    b = blob(key)
    if not b:
        return None
    try:
        raw = base64.b64decode(b, validate=True)
    except ValueError:
        return None
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")

def forced(line):
    """True for an authorized_keys line that runs our session."""
    return MARK in line or "solaros session" in line

def key_lines():
    try:
        with open(auth_keys()) as f:
            return f.read().splitlines()
    except OSError:
        return []

def where_key(key):
    """"paired" when the key already runs our session, "other" when it's in
    authorized_keys some other way (a panel set up by hand), else None."""
    b = blob(key)
    for l in key_lines():
        if b and (" " + b + " " in " " + l + " " or l.endswith(" " + b)):
            return "paired" if forced(l) else "other"
    return None

def paired():
    """[(fingerprint, comment)] of the keys that run the panel's session."""
    out = []
    for l in key_lines():
        if forced(l):
            m = re.search(r"((?:ssh-rsa|ssh-ed25519|ecdsa-\S+) \S+.*)$", l)
            if m:
                out.append((fingerprint(m.group(1)), m.group(1).split(" ", 2)[-1] if m.group(1).count(" ") > 1 else ""))
    return out

def launcher():
    """The phosphor a forced command runs: ~/.local/bin's, which follows the
    channel (`phosphor update`), else this checkout's."""
    p = os.path.expanduser("~/.local/bin/phosphor")
    return p if os.path.exists(p) else PHOSPHOR

def keyline(key):
    """key's authorized_keys line: no forwarding of any kind, a pty, and
    our session in place of whatever it asks to run."""
    m = KEYLINE.match(key.strip())
    cmd = "%s solaros session" % launcher()
    return 'command="%s",restrict,pty %s %s %s' % (cmd.replace('"', '\\"'), m.group(1), m.group(2), MARK)

def authorize(key):
    """The key into authorized_keys, forced to the session: any line it
    already had (a panel set up by hand, a pairing before) goes, the old
    file stays as authorized_keys.bak.solaros."""
    p, b = auth_keys(), blob(key)
    old = key_lines()
    if old:
        write_private(p + ".bak.solaros", "\n".join(old) + "\n")
    keep = [l for l in old if not (b and (" " + b + " " in " " + l + " " or l.endswith(" " + b)))]
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    write_private(p, "\n".join(keep + [keyline(key)]) + "\n")

def forget():
    old = key_lines()
    keep = [l for l in old if not forced(l)]
    if len(keep) == len(old):
        print(row(DIM + "·" + RST, "paired panels", "none")); return 0
    write_private(auth_keys() + ".bak.solaros", "\n".join(old) + "\n")
    write_private(auth_keys(), "\n".join(keep) + ("\n" if keep else ""))
    print(row(OK, "paired panels", "%d key%s taken out" % (len(old) - len(keep), "" if len(old) - len(keep) == 1 else "s"),
              note="the old file: ~/.ssh/authorized_keys.bak.solaros"))
    return 0

def window_open():
    w = read_json(data("pair.json")) or {}
    return w.get("until", 0) > time.time()

def offer(key, ip=""):
    """What the server answers a panel that sends its key: paired, pending
    (a window is open: it waits for your Enter on the brain), or closed.
    It never writes authorized_keys itself."""
    if not isinstance(key, str) or len(key) > 4096 or not fingerprint(key):
        return {"state": "bad", "why": "not an ssh public key"}
    if where_key(key) == "paired":
        return {"state": "paired"}
    if not window_open():
        return {"state": "closed", "why": "run phosphor solaros pair on the brain"}
    write_private(data("pending.json"), json.dumps({"key": key.strip(), "ip": ip, "t": time.time()}))
    return {"state": "pending", "fingerprint": fingerprint(key)}

def pair(wait=WINDOW):
    """Open a window, wait for one panel's key, show its fingerprint and ask."""
    prof = deckconf.load()[0] or {}
    if not active():
        print(row(BAD, "pairing", "nothing is serving", note="phosphor solaros on first")); return 1
    rm(data("pending.json"))
    write_private(data("pair.json"), json.dumps({"until": time.time() + wait}))
    print(row(OK, "pairing", "open for %d minutes" % (wait // 60), note="Ctrl-C closes it"))
    print("  " + FG + "On the panel, open Phosphor (" + PH + "python /phosphor.py" + RST + FG +
          ") and pick " + PH + "pair with the brain" + RST + FG + ": it sends its key." + RST)
    try:
        t0, got = time.time(), None
        while time.time() - t0 < wait:
            got = read_json(data("pending.json"))
            if got and got.get("key"):
                break
            time.sleep(0.5)
        else:
            print(row(WARN, "pairing", "no panel came: closed")); return 1
        fp = fingerprint(got["key"])
        print()
        print("  " + FG + "a panel%s sent its key:" % (" at " + got["ip"] if got.get("ip") else "") + RST)
        print("    " + PH + fp + RST)
        if where_key(got["key"]) == "other":
            print("  " + AMB + "that key is already in authorized_keys without the menu: pairing replaces its line" + RST)
        print("  " + DIM + "the panel shows its own; the same means nobody swapped it on the way." + RST)
        print("  " + DIM + "it gets the panel's deck over ssh (the deck's tabs, notes, fleet), not a login;" + RST)
        print("  " + AMB + "  what it types in a tab of the deck goes there: pair only a panel you'd hand the deck to." + RST)
        try:
            import termios                  # an Enter typed before the question doesn't answer it
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except (termios.error, OSError, ValueError, AttributeError):
            pass
        try:
            a = input("  " + FG + "Same on both? Enter lets it in, n refuses: " + RST)
        except EOFError:
            a = "n"
        if a.strip().lower().startswith("n"):
            print(row(DIM + "·" + RST, "pairing", "refused, nothing changed")); return 1
        authorize(got["key"])
        dlog.event("SOLAROS", "paired", fp)
        print(row(OK, "paired", fp, note="phosphor solaros forget takes it out"))
        return 0
    except KeyboardInterrupt:
        print(); print(row(DIM + "·" + RST, "pairing", "closed")); return 1
    finally:
        rm(data("pair.json")); rm(data("pending.json"))

# ── what the panel can open: the whitelist ────────────────────

VIEWERS = {"yazi", "btop", "ctop", "htop", "gping", "lazydocker", "lazygit"}   # nothing in them but what they show

def own_screen(cmd):
    """The argv to run here for a pane of the deck, so it fits the panel
    instead of being copied at the size of the screen that last looked at
    the deck: one of phosphor's own screens, or a viewer that keeps
    nothing (VIEWERS). None for anything else -- a shell, an assistant, a
    chat -- which lives in that pane and is mirrored."""
    try:
        words = shlex.split(cmd or "")
    except ValueError:
        return None
    if "--" in words:                       # phosphor run --name X -- CMD
        words = words[words.index("--") + 1:]
    if not words:
        return None
    exe = os.path.basename(words[0])
    if exe in VIEWERS:
        return words
    if exe != "phosphor" or len(words) < 2 or words[1] in ("solaros", "mirror", "run", "adjutant"):
        return None                         # adjutant speaks: a second one would say everything twice
    if words[1] == "fleet":                 # upgrade and reboot right here, not in a new tab of the deck
        return [PHOSPHOR, "solaros", "fleet"]
    return [PHOSPHOR] + words[1:]

def runs(v, *sub):
    return bool(v.argv) and v.argv[0] == PHOSPHOR and v.argv[1:1 + len(sub)] == list(sub)

class View:
    """One pane the panel's deck shows: `argv` runs here (one of
    phosphor's screens), else `pane` (or the tab's focused one) is
    mirrored from the deck."""
    def __init__(self, tab, title, argv=None, pane=None, focused=False):
        self.tab, self.title, self.argv, self.pane, self.focused = tab, title, argv, pane, focused
    @property
    def key(self):
        return (self.tab, self.title, self.pane, tuple(self.argv or ()))

def views(prof=None):
    """The deck's tabs as they are now (a workspace opened since counts),
    or the profile's when the deck isn't up, pane by pane; NOTES and
    FLEET at the end when no tab has them."""
    prof = prof if prof is not None else (deckconf.load()[0] or {})
    out = []
    try:
        import mirror
        ps = [p for p in mirror.panes(mirror.session()) if not p.get("is_plugin")]
    except Exception:
        ps = []
    for p in sorted(ps, key=lambda p: (p.get("tab_position", 0), p.get("pane_y", 0), p.get("pane_x", 0), p.get("id", 0))):
        name = mirror.tab_name(p)
        if name:
            out.append(View(name, (p.get("title") or name).strip(), own_screen(p.get("pane_command") or p.get("terminal_command")),
                            "terminal_%d" % p["id"], bool(p.get("is_focused"))))
    if not out:
        for t in prof.get("tabs", []):
            for pane in t.get("panes", []) if t.get("name") else []:
                cmd = pane.get("cmd") if isinstance(pane, dict) else None
                out.append(View(t["name"], (pane.get("name") if isinstance(pane, dict) else None) or t["name"], own_screen(cmd)))
    if not any(runs(v, "notes") for v in out):
        out.append(View("NOTES", "NOTES", [PHOSPHOR, "notes"]))
    if not any(runs(v, "solaros", "fleet") for v in out):
        out.append(View("FLEET", "FLEET", [PHOSPHOR, "solaros", "fleet"]))
    return out

def tab_names(views_):
    names = []
    for v in views_:
        if v.tab not in names:
            names.append(v.tab)
    return names

def entries(prof=None):
    """[(id, label)], in the menu's order: what a panel can start on."""
    out = [("glance", "glance")]
    out += [("tab:" + n, n) for n in tab_names(views(prof))]
    out += [("note", "write a note")]
    return out

def menu(ip="", prof=None):
    """GET /menu: what the panel shows and where its ssh goes."""
    return {"entries": [{"id": i, "label": l} for i, l in entries(prof)],
            "ssh": "%s@%s" % (getpass.getuser(), ip) if ip else getpass.getuser()}

def want(what, prof=None):
    """POST /open: the session that connects next starts on `what` (one
    of entries). It's only a hint: the session checks it again."""
    if what not in [i for i, _ in entries(prof)] + ["notes", "fleet"]:     # those two: a copy of the app from before tabs
        return {"ok": False, "why": "not on the menu"}
    write_private(data("intent.json"), json.dumps({"open": what, "t": time.time()}))
    return {"ok": True}

def take_intent():
    """The panel's "open X next", once, while it's fresh."""
    w = read_json(data("intent.json"))
    rm(data("intent.json"))
    if w and time.time() - w.get("t", 0) <= INTENT_TTL:
        return w.get("open")
    return None

# ── the session: what the panel's key runs ────────────────────

def screen(lines, prev):
    sys.stdout.write(ui.paint(lines, prev)); sys.stdout.flush()
    return lines

def pick(title, items, foot="↑↓ Enter · Esc back", sel=0):
    """items: [label]. The index picked, or None (Esc, q, Ctrl-C). Paints
    only the lines that changed: an e-ink panel flashes what reaches it."""
    prev = None
    sys.stdout.write("\x1b[2J")
    while True:
        cols, rows = shutil.get_terminal_size((60, 20))
        room = max(1, rows - 3)
        top = max(0, min(sel - room + 1, len(items) - room)) if sel >= room else 0
        out = [INV + (" " + title)[:cols].ljust(cols) + RST, ""]
        for i, label in enumerate(items[top:top + room], top):
            text = ("%s %s" % (">" if i == sel else " ", label))[:cols]
            out.append(INV + text + RST if i == sel else text)
        out += [""] * (rows - 1 - len(out)) + [foot[:cols]]
        prev = screen(out, prev)
        k = ui.getkey(None, typeahead=True)
        if k in ("\x1b[A", "k", "WUP"):
            sel = (sel - 1) % len(items)
        elif k in ("\x1b[B", "j", "\t", "WDN"):
            sel = (sel + 1) % len(items)
        elif k in ("\r", "\n", " "):
            return sel
        elif k in ("\x1b", "q", "\x03", "\x04", None):
            return None
        elif k and k.isdigit() and 0 < int(k) <= len(items):
            return int(k) - 1

def say(lines):
    sys.stdout.write("\x1b[2J\x1b[H" + "\n".join(lines) + "\n"); sys.stdout.flush()

def ask(prompt):
    sys.stdout.write("\x1b[?25h"); sys.stdout.flush()
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None
    finally:
        sys.stdout.write("\x1b[?25l"); sys.stdout.flush()

def phosphor(*a):
    """Another phosphor screen, in this same terminal, back here when it ends."""
    return subprocess.call([sys.executable, PHOSPHOR] + list(a))

def write_note():
    import notes
    kinds = ["note", "todo", "idea"]
    k = pick("write a note: what kind", kinds)
    if k is None: return
    projects = notes.projects_in(notes.PATH)
    try:
        import workspace
        projects += [w for w in workspace.names() if w not in projects]
    except Exception:
        pass
    project = None
    if projects:
        p = pick("write a note: which project", projects)
        if p is None: return
        project = projects[p]
    say(["", " %s%s" % (kinds[k], " in #" + project if project else ""), ""])
    text = ask(" text, Enter saves (empty leaves): ")
    if not text or not text.strip():
        return
    argv = ["note", "--kind", kinds[k], "--by", "panel"] + (["--project", project] if project else []) + [text.strip()]
    rc = subprocess.call([sys.executable, PHOSPHOR] + argv, stdout=subprocess.DEVNULL)
    say(["", " saved" if rc == 0 else " not saved (exit %d)" % rc, ""])
    time.sleep(1.5)

def fleet_rows():
    """[(name, what it says)] from FLEET's own cache: nothing new runs."""
    import glance, health
    try:
        with open(glance.CACHE) as f:
            hosts = json.load(f).get("hosts", {})
    except (OSError, ValueError):
        hosts = {}
    prof = deckconf.load()[0] or {}
    out = []
    for name, _ in deckconf.fleet_hosts(prof):
        h = hosts.get(name) or {}
        bits = []
        if h and not h.get("ok"):
            bits.append("down")
        u = health.updates(h) if h else None
        if u and u[0]:
            bits.append("%d update%s%s" % (u[0], "" if u[0] == 1 else "s",
                                           " (%d security)" % u[1] if u[1] else ""))
        if h.get("REBOOT"):
            bits.append("reboot pending")
        out.append((name, ", ".join(bits) or ("ok" if h else "no data")))
    return out

def fleet():
    import upkeep
    sel = 0
    while True:
        rows = fleet_rows()
        if not rows: return
        w = max(len(n) for n, _ in rows)
        i = pick("fleet: a machine", ["%-*s  %s" % (w, n, s) for n, s in rows], sel=sel)
        if i is None: return
        sel = i
        name = rows[i][0]
        a = pick("fleet: %s" % name, ["upgrade", "reboot", "back"])
        if a in (0, 1):
            say([""])
            upkeep.run(("upgrade", "reboot")[a], name)
            ask("\n Enter goes back ")

# ── the panel's deck: its tabs, over one ssh session ──────────

LEAVE = b"\x1d"                    # Ctrl-] (and Ctrl-q): the whole session, as EXIT on the panel
PACE = 0.3                          # a paint reaches the panel at most this often
EVERY = 1.0                         # a mirrored pane is read again this often
ECHO = 0.3                          # ...and this soon after a key, so what was typed shows up
REREAD = 10.0                       # the deck's tabs are listed again this often
KEEP = 4                            # screens of phosphor's kept running, the last ones looked at
# SolarOS keeps Alt-Left/Right and Alt-Tab for its own sessions, and a
# keyboard with only AltGr sends no Alt at all: Ctrl and the arrows get through
KEYS = {b"\x1b[1;5D": "prev", b"\x1b[1;5C": "next", b"\x1b[1;5A": "pane-prev", b"\x1b[1;5B": "pane",
        b"\x1b\x1b[A": "prev", b"\x1b\x1bOA": "prev", b"\x1b[1;3A": "prev",
        b"\x1b\x1b[B": "next", b"\x1b\x1bOB": "next", b"\x1b[1;3B": "next",
        b"\x1bp": "pane", LEAVE: "leave", b"\x11": "leave"}      # Ctrl-q: as in the deck
KEYS.update({b"\x1b" + str(n).encode(): n for n in range(1, 10)})
KEYS[b"\x1b0"] = 10
SPLIT = re.compile(b"(" + b"|".join(re.escape(k) for k in sorted(KEYS, key=len, reverse=True)) + b")")

def term_size():
    try:
        s = os.get_terminal_size(sys.stdout.fileno())
        return max(20, s.columns), max(4, s.lines)
    except OSError:
        return 60, 17

class Own:
    """One of phosphor's screens, run here in a pty of its own at the
    panel's size; what it writes lands in a vt.Screen, not on the panel."""
    def __init__(self, argv, cols, rows):
        import pty, vt
        self.screen, self.code = vt.Screen(cols, rows), None
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ["TERM"] = "xterm-mono"
            try:
                os.execvp(argv[0], list(argv))
            finally:
                os._exit(127)
        self.size(cols, rows)
    def size(self, cols, rows):
        import fcntl, struct, termios
        if (cols, rows) != (self.screen.cols, self.screen.rows):
            self.screen.resize(cols, rows)
        try: fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError: pass
    def read(self):
        try:
            got = os.read(self.fd, 65536)
        except OSError:
            got = b""
        if got:
            self.screen.feed(got)
        else:
            self.reap(wait=True)
    def reap(self, wait=False):
        if self.code is None:
            try:
                pid, st = os.waitpid(self.pid, 0 if wait else os.WNOHANG)
            except ChildProcessError:
                pid, st = self.pid, 0
            if pid:
                self.code = os.waitstatus_to_exitcode(st)
                try: os.close(self.fd)
                except OSError: pass
        return self.code
    def write(self, data):
        if self.code is None:
            try: os.write(self.fd, data)
            except OSError: pass
    def stop(self):
        if self.code is None:
            try: os.kill(self.pid, 15)
            except OSError: pass
            self.reap(wait=True)

def bar(names, cur, cols, sub=""):
    """The top line: the tabs, the one shown in inverse, scrolled so it
    shows; the pane's name when the tab has more than one, and how to
    leave when there's room."""
    right = (" " + sub) if sub else ""
    cells = [" %d %s " % (i + 1, n) if i < 10 else " %s " % n for i, n in enumerate(names)]
    hinted = right + (" ·" if sub else "") + " Ctrl-q leaves"
    if sum(len(c) for c in cells) + len(hinted) <= cols:
        right = hinted
    room = max(8, cols - len(right))
    start, width = 0, sum(len(c) for c in cells[:cur + 1])
    while start < cur and width > room:
        width -= len(cells[start]); start += 1
    out, n = "", 0
    for i, c in enumerate(cells[start:], start):
        if n + len(c) > room:
            c = c[:max(0, room - n)]
        out += (INV + c + RST) if i == cur else c
        n += len(c)
        if n >= room: break
    return out + " " * max(0, cols - n - len(right)) + right

class Deck:
    def __init__(self, prof=None):
        self.prof, self.tab, self.pane = prof, 0, {}
        self.own, self.used = {}, []
        self.prev, self.size, self.listed = None, None, 0
        self.mirror_due, self.mirror_lines, self.mirror_pid = 0.0, [], None
        self.reread()

    def reread(self):
        cur = self.current().key if getattr(self, "all", None) else None
        self.all = views(self.prof)
        self.names = tab_names(self.all)
        self.listed = time.time()
        if cur:
            for v in self.all:
                if v.key == cur:
                    self.tab = self.names.index(v.tab)
                    self.pane[v.tab] = self.panes(v.tab).index(v)
                    break
        self.tab = min(self.tab, len(self.names) - 1)

    def panes(self, tab):
        return [v for v in self.all if v.tab == tab]

    def current(self):
        ps = self.panes(self.names[self.tab])
        if self.names[self.tab] not in self.pane:   # first time on a tab: its focused pane, as in the deck
            self.pane[self.names[self.tab]] = next((i for i, v in enumerate(ps) if v.focused), 0)
        return ps[min(self.pane[self.names[self.tab]], len(ps) - 1)]

    def goto(self, what):
        """Start on what the panel's menu picked: a tab, or notes/fleet."""
        for i, n in enumerate(self.names):
            if what == "tab:" + n:
                self.tab = i; return
        sub = {"notes": ["notes"], "fleet": ["solaros", "fleet"]}.get(what)
        for v in self.all:
            if sub and runs(v, *sub):
                self.tab = self.names.index(v.tab)
                self.pane[v.tab] = self.panes(v.tab).index(v)
                return

    def show(self, v):
        self.mirror_due, self.mirror_pid = 0.0, None
        if v.argv:
            self.child(v)

    def child(self, v):
        cols, rows = term_size()
        o = self.own.get(v.key)
        if o is None:
            o = self.own[v.key] = Own(v.argv, cols, rows - 1)
            dlog.event("SOLAROS", "run", os.path.basename(v.argv[0]) + " " + " ".join(v.argv[1:2]))
        if v.key in self.used: self.used.remove(v.key)
        self.used.append(v.key)
        while len(self.used) > KEEP:
            old = self.used.pop(0)
            if old in self.own: self.own.pop(old).stop()
        return o

    def key(self, k):
        n = len(self.names)
        if k == "prev": self.tab = (self.tab - 1) % n
        elif k == "next": self.tab = (self.tab + 1) % n
        elif k in ("pane", "pane-prev"):
            t = self.names[self.tab]
            self.current()                  # the tab's pane is known before it moves
            self.pane[t] = (self.pane[t] + (1 if k == "pane" else -1)) % len(self.panes(t))
        elif isinstance(k, int) and k <= n: self.tab = k - 1
        else: return
        self.show(self.current())

    def typed(self, keys):
        """Keys the panel sent: ours change the tab, the rest go to it."""
        for part in SPLIT.split(keys):
            if not part:
                continue
            k = KEYS.get(part)
            if k == "leave":
                raise SystemExit("key")
            if k is not None:
                self.key(k); continue
            v = self.current()
            if v.argv:
                o = self.child(v)
                if o.code is not None and part in (b"\r", b"\n"):
                    self.own.pop(v.key, None); self.child(v)      # it ended: Enter starts it again
                else:
                    o.write(part)
            elif self.mirror_pid:
                import mirror
                mirror.send(mirror.session(), self.mirror_pid, part)
                self.mirror_due = min(self.mirror_due, time.time() + ECHO)

    def body(self, v, cols, rows):
        if v.argv:
            o = self.child(v)
            o.size(cols, rows)
            lines = o.screen.lines()
            if o.code is not None:
                lines = lines[:rows - 1] + [INV + (" %s ended · Enter starts it again" % v.title)[:cols] + RST]
            return lines
        import mirror
        if time.time() >= self.mirror_due:
            sess = mirror.session()
            hit = mirror.find(sess, pane=v.pane) if v.pane else mirror.find(sess, tab=v.tab)
            text = mirror.zj(sess, "dump-screen", "-p", hit[0]) if hit else None
            self.mirror_pid = hit[0] if hit else None
            self.mirror_lines = mirror.view(text, cols, rows) if text is not None else \
                [ui.cut("%s isn't in the deck right now: waiting for it" % v.tab, cols)]
            self.mirror_due = time.time() + EVERY
        return self.mirror_lines

    def frame(self):
        cols, rows = term_size()
        v = self.current()
        ps = self.panes(v.tab)
        sub = "%s %d/%d" % (v.title, ps.index(v) + 1, len(ps)) if len(ps) > 1 else ""
        out = [bar(self.names, self.tab, cols, sub)] + self.body(v, cols, rows - 1)[:rows - 1]     # both already fit cols
        out += [""] * (rows - len(out))
        fresh = (cols, rows) != self.size
        self.size = (cols, rows)
        paint = ui.paint(out, None if fresh else self.prev)
        self.prev = out
        return paint

    def run(self):
        """Keys in, the panel painted at most every PACE: only the lines
        that changed reach it (ui.paint), however often the screen behind
        them redraws."""
        self.show(self.current())
        painted = 0.0
        while True:
            if time.time() - self.listed > REREAD:
                self.reread()
            v = self.current()
            o = self.own.get(v.key) if v.argv else None
            fds = [sys.stdin] + ([o.fd] if o and o.code is None else [])
            r = select.select(fds, [], [], max(0.0, painted + PACE - time.time()))[0]
            if sys.stdin in r:
                keys = os.read(sys.stdin.fileno(), 4096)
                if not keys:
                    raise SystemExit("end of input")
                self.typed(keys)
            if o and o.code is None:
                if o.fd in r:
                    o.read()
                o.reap()
            if time.time() - painted >= PACE:
                paint = self.frame()
                painted = time.time()
                if paint:
                    os.write(sys.stdout.fileno(), paint.encode())

    def stop(self):
        for o in self.own.values():
            o.stop()

def session():
    """The forced command of a paired panel's key: the deck's tabs, one at
    a time, in this ssh session. EXIT on the panel ends it."""
    if not sys.stdin.isatty():
        print("phosphor solaros session: needs the panel's terminal"); return 2
    import mirror, signal
    os.environ.setdefault("TERM", "xterm-mono")
    local = os.path.expanduser("~/.local/bin")     # a forced ssh command's PATH: where yazi and the rest are
    if local not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = local + ":" + os.environ.get("PATH", "/usr/bin:/bin")
    ui.mono_stdout()                    # upkeep and the menu paint in color: not on e-ink
    dlog.event("SOLAROS", "session", "TERM=%s" % os.environ.get("TERM"))
    first = take_intent() or (os.environ.get("SSH_ORIGINAL_COMMAND") or "").strip() or None
    if first == "note":
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        write_note()
    def hangup(*_): raise SystemExit("hangup")
    signal.signal(signal.SIGHUP, hangup)
    signal.signal(signal.SIGTERM, hangup)
    deck, why = Deck(), "?"
    deck.goto(first)
    undo = mirror.raw_input()
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[2J"); sys.stdout.flush()
    try:
        deck.run()
    except SystemExit as e:
        why = str(e) or "exit"
    except KeyboardInterrupt:
        why = "interrupt"
    except OSError as e:
        why = "screen gone (%s)" % type(e).__name__
    finally:
        dlog.event("SOLAROS", "end", why)
        deck.stop()
        undo()
        try:
            sys.stdout.write("\x1b[?1049l\x1b[?25h"); sys.stdout.flush()
        except OSError:                 # the panel hung up: nothing left to flush at exit either
            sys.stdout = open(os.devnull, "w")
    return 0

# ── on / off / status ─────────────────────────────────────────

def copy(text):
    try:
        import clip
        return clip.send(text.encode()) == 0
    except Exception:
        return False

def show_lines(prof):
    lines = panel_lines(prof)
    print("  " + FG + "On the panel's SolarOS prompt:" + RST)
    for l in lines:
        print("    " + PH + l + RST)
    if copy("\n".join(lines) + "\n"):
        print("  " + DIM + "they're on the clipboard of every screen looking at the deck: paste them" + RST)
    print("  " + DIM + "once (its code works one time, for 10 minutes): then it's phosphor at that prompt, and the app updates itself" + RST)
    if serve_mode(prof) == "lan":
        print("  " + DIM + "on the LAN the token crosses it in the clear: it only reads; writing goes over ssh" + RST)

def on(mode="lan"):
    prof = deckconf.load()[0] or {}
    if serve_mode(prof) != mode:
        try:
            set_serve(mode)
        except (OSError, RuntimeError) as e:
            print(row(BAD, "profile", "not written", note=str(e))); return 1
        prof = deckconf.load()[0] or {}
        print(row(OK, "profile", '[glance] serve = "%s"' % mode))
    os.makedirs(UDIR, exist_ok=True)
    with open(os.path.join(UDIR, UNIT), "w") as f:
        f.write(unit(prof))
    systemctl("daemon-reload")
    r = systemctl("enable", "--now", UNIT)
    systemctl("restart", UNIT)                  # a port or a mode that changed
    time.sleep(0.5)
    if not active():
        print(row(BAD, "service", UNIT, note=(r.stderr.strip() or "journalctl --user -u " + UNIT)[:70])); return 1
    print(row(OK, "service", UNIT, note="comes back after a reboot (with linger)"))
    show_lines(prof)
    if not paired():
        print()
        print("  " + FG + "No panel is paired yet: " + PH + "phosphor solaros pair" + RST + FG +
              " lets one in (its key, your Enter)." + RST)
    return 0

def off():
    prof = deckconf.load()[0] or {}
    systemctl("disable", "--now", UNIT)
    rm(os.path.join(UDIR, UNIT))
    systemctl("daemon-reload")
    if serve_mode(prof):
        try:
            set_serve(None)
        except (OSError, RuntimeError) as e:
            print(row(BAD, "profile", "not written", note=str(e))); return 1
    print(row(OK, "glance --serve", "stopped", note="paired panels keep their key: phosphor solaros forget"))
    return 0

def status():
    prof = deckconf.load()[0] or {}
    mode = serve_mode(prof)
    up = active()
    print(row(OK if up else (WARN if mode else DIM + "·" + RST), "service",
              ("serving on the %s" % ("LAN" if mode == "lan" else "tailnet")) if up else ("down" if mode else "off"),
              note="" if up else ("phosphor solaros on" if not mode else "journalctl --user -u " + UNIT)))
    if up:
        show_lines(prof)
    ps = paired()
    print(row(OK if ps else DIM + "·" + RST, "paired panels", str(len(ps)) if ps else "none",
              note="" if ps else "phosphor solaros pair"))
    for fp, comment in ps:
        print("    " + MUTE + (fp or "?") + RST)
    return 0

def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print(USAGE); return 0
    cmd = a[0] if a else "status"
    if cmd == "status": return status()
    if cmd == "on": return on()
    if cmd == "off": return off()
    if cmd == "pair": return pair()
    if cmd == "forget": return forget()
    if cmd == "session": return session()
    if cmd == "fleet": return fleet() or 0            # the FLEET tab of a panel's session
    print(USAGE); return 2

if __name__ == "__main__":
    sys.exit(main() or 0)
