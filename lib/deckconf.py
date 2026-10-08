"""The deck's profile, read in one place.

Everything that needs to know which machines exist (fleet, path, gen, setup)
asks here: the profile is the only source of truth, and no host list is
written into the code.
"""
import os, re, shutil, subprocess

# tomllib is 3.11+. Ubuntu 22.04, Debian 11 and older Raspberry Pi OS ship
# 3.9/3.10, and that's exactly the hardware this project wants to reuse.
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.expanduser("~/.config/phosphor/deck.toml")
EXAMPLE = os.path.join(REPO, "profiles", "example.toml")
ERR  = ""   # why the last load failed

def path():
    p = os.environ.get("PHOSPHOR_PROFILE", CONF)
    if not os.path.exists(p):
        p = EXAMPLE
    return p

def example():
    """True while there's no profile and the repo's example stands in for it."""
    return path() == EXAMPLE

def backup(p, old_text):
    """Write `old_text` (the profile as it was, before the write that's
    about to happen) to p.bak, rotating what's already there down to
    .bak.2 and .bak.3 first (oldest dropped) instead of overwriting the
    only undo depth a profile write had -- `phosphor setup` then a recipe,
    back to back, used to lose the setup-time backup. The copy keeps the
    profile's mode: a chmod 600 profile holding a token makes a 600 .bak."""
    b1, b2, b3 = p + ".bak", p + ".bak.2", p + ".bak.3"
    if os.path.exists(b2): shutil.move(b2, b3)
    if os.path.exists(b1): shutil.move(b1, b2)
    mode = os.stat(p).st_mode & 0o777 if os.path.exists(p) else 0o644
    with os.fdopen(os.open(b1, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "w") as f:
        f.write(old_text)
    os.chmod(b1, mode)

class _locked:
    """One writer at a time: deck.toml.lock, the same flock the notebook's
    notes.md.lock uses."""
    def __init__(self, p): self.path = p + ".lock"
    def __enter__(self):
        import fcntl
        self.f = open(self.path, "a"); fcntl.flock(self.f, fcntl.LOCK_EX); return self
    def __exit__(self, *a):
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()

def write_profile(new, check=None, expect=None, p=None, keep=True):
    """The only way the profile gets written. None when it's written, else
    why not (and nothing was touched). `new` must parse, and pass
    `check(profile)` when given; `expect` is the text the caller started
    from, and when the file no longer holds it (another phosphor command
    wrote it meanwhile) nothing is written rather than undo that write. The
    old text goes to .bak first (`keep=False` skips that, for a session
    that already made one), then the new one lands whole through a temp
    file and os.replace: a kill or a full disk mid-write leaves the old
    profile, never half of one. A symlinked profile is written through
    the link, keeping its mode."""
    p = p or path()
    if os.path.abspath(p) == os.path.abspath(EXAMPLE):
        return "there's no profile yet: phosphor init"
    if tomllib is not None:
        try:
            prof = tomllib.loads(new)
        except Exception as e:
            return "the profile wouldn't parse: %s" % str(e)[:50]
        if check and not check(prof):
            return "the result didn't look right"
    elif check:
        return "no TOML parser: pip install --user tomli"
    real = os.path.realpath(p)
    d = os.path.dirname(real)
    import tempfile
    try:
        os.makedirs(d, exist_ok=True)
        with _locked(real):
            old = open(real).read() if os.path.exists(real) else None
            if expect is not None and old != expect:
                return "the profile changed meanwhile: nothing written, try again"
            if old is not None and keep:
                backup(real, old)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".deck.toml.")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(new); f.flush(); os.fsync(f.fileno())
                os.chmod(tmp, os.stat(real).st_mode & 0o7777 if old is not None else 0o644)
                os.replace(tmp, real)
            except BaseException:
                try: os.unlink(tmp)
                except OSError: pass
                raise
    except OSError as e:
        return "can't write the profile: %s" % str(e)[:50]
    return None

def header(line):
    """A table header as "[deck]" or "[[tabs]]", whatever spaces or trailing
    comment it was written with; None for any other line."""
    m = re.match(r"\s*(\[\[?)\s*([\w.-]+)\s*(\]\]?)\s*(#.*)?$", line)
    return m.group(1) + m.group(2) + m.group(3) if m else None

def with_key(text, section, key, value):
    """The profile's text with `key = value` in [section] (value a TOML
    literal, quoted already): that line replaced, or added first in the
    table, and the table added at the end if it's missing. Nothing written."""
    lines = text.split("\n")
    line = "%s = %s" % (key, value)
    start = next((i for i, l in enumerate(lines) if header(l) == "[%s]" % section), None)
    if start is None:
        return text.rstrip("\n") + "\n\n[%s]\n%s\n" % (section, line)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    at = next((i for i in range(start + 1, end) if re.match(r"\s*%s\s*=" % re.escape(key), lines[i])), None)
    if at is None:
        lines.insert(start + 1, line)
    else:
        lines[at] = line
    return "\n".join(lines)

def set_key(section, key, value):
    """with_key() written into the profile; the profile as it was goes to
    .bak first. False when there's no profile yet (the example is never
    written)."""
    if example():
        return False
    p = path()
    text = open(p).read()
    return write_profile(with_key(text, section, key, value), expect=text, p=p) is None

def load():
    """(profile, path). profile is None when there's no parser or it can't be read."""
    global ERR
    p = path()
    if tomllib is None:
        ERR = "no TOML parser: pip install --user tomli"
        return None, p
    try:
        with open(p, "rb") as f:
            return tomllib.load(f), p
    except Exception as e:
        ERR = str(e)
        return None, p

ORDER = {"brain": 0, "work": 1, "desktop": 2, "storage": 3, "node": 4, "viewer": 5}

def hosts(prof):
    """The profile's hosts, brain first, then by role."""
    return sorted((prof or {}).get("hosts", []),
                  key=lambda h: (ORDER.get(h.get("role"), 9), h.get("name", "")))

def target(h):
    """Where ssh goes: user@alias when the profile has a user."""
    t = h.get("ssh") or h.get("ip") or h["name"]
    return "%s@%s" % (h["user"], t) if h.get("user") else t

def fleet_hosts(prof):
    """[(name, ssh target | None for this machine)]: what fleet polls.

    Viewers (phones, tablets) aren't polled. `fleet = false` on a host takes
    it off the panel without taking it out of the deck."""
    out = []
    for h in hosts(prof):
        if h.get("fleet") is False:
            continue
        if h.get("local"):
            out.append((h["name"], None))
        elif h.get("role") != "viewer":
            out.append((h["name"], target(h)))
    return out or [(os.uname().nodename, None)]

def tunnels(prof):
    """[[tunnels]] entries: {"host": ssh alias, optional "config": ssh config file}."""
    return [t for t in (prof or {}).get("tunnels", []) if t.get("host")]

# ── tabs you can share: single-file tab definitions, dropped in ─────
def tabs_d_path():
    return os.environ.get("PHOSPHOR_TABS_D") or os.path.join(os.path.dirname(CONF), "tabs.d")

def tabs_d():
    """[(tab, its file)] from every *.toml in tabs.d, sorted by file name.
    A file that fails to parse is skipped, not fatal to gen."""
    out, d = [], tabs_d_path()
    if tomllib is None or not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".toml"): continue
        p = os.path.join(d, name)
        try:
            with open(p, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue
        for t in data.get("tabs", []):
            if t.get("name"): out.append((t, p))
    return out

def tabs_d_names():
    return {t.get("name"): src for t, src in tabs_d()}

def is_real_tab(t):
    """A tab with its own content, not a stub pointing at tabs.d."""
    return "panes" in t or "split" in t

def pinned_tabs_d(prof):
    """{name} of tabs.d tabs your profile has explicitly placed: a
    [[tabs]] block with just a name, no panes -- `phosphor tabs` moving
    one there for the first time writes exactly this."""
    return {t.get("name") for t in (prof or {}).get("tabs", []) if not is_real_tab(t)}

def effective_tabs(prof):
    """What gen actually builds: the profile's own tabs, in their own
    order, then tabs.d's -- dropped in, not edited by hand, appended in
    file-name order unless a name-only stub in the profile pins one
    somewhere else. A name your profile already gives real content to
    wins: yours over one you were handed."""
    own = list((prof or {}).get("tabs", []))
    shared = {}
    for t, _ in tabs_d():
        shared.setdefault(t.get("name"), t)
    out, placed = [], set()
    for t in own:
        name = t.get("name")
        if not is_real_tab(t) and name in shared:
            out.append(shared[name])       # a stub: this position is tabs.d's tab
        else:
            out.append(t)
        placed.add(name)
    out += [t for name, t in shared.items() if name not in placed]
    return out

# ── the shell and the editor every pane gets ─────────────────
EDITORS = ["nano", "micro", "hx", "nvim", "vim", "emacs", "vi"]
SHELLS  = ["bash", "zsh", "fish", "nu", "sh"]

def data_dir():
    """Where phosphor keeps its data (mentions, work notes, steps). PHOSPHOR_DATA points it
    elsewhere: `phosphor demo` uses that so it never reads or writes the real ones."""
    return os.environ.get("PHOSPHOR_DATA") or os.path.expanduser("~/.local/share/phosphor")

def cache_dir():
    """The same for what's only cached (events, the fleet's readings, the log): PHOSPHOR_CACHE."""
    return os.environ.get("PHOSPHOR_CACHE") or os.path.expanduser("~/.cache/phosphor")

def _gen_stamp():
    return os.path.join(data_dir(), "gen-profile")

def profile_fingerprint():
    """A hash of what `phosphor gen` reads: the profile and every tabs.d file.
    None while the repo's example stands in for a profile."""
    if example():
        return None
    import hashlib
    h = hashlib.sha256()
    files = [path()]
    d = tabs_d_path()
    if os.path.isdir(d):
        files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".toml")]
    for f in files:
        try:
            h.update(f.encode() + b"\0" + open(f, "rb").read() + b"\0")
        except OSError:
            pass
    return h.hexdigest()

def mark_generated():
    """gen calls this once it has written everything: the profile as it was then."""
    fp = profile_fingerprint()
    if not fp:
        return
    try:
        os.makedirs(data_dir(), exist_ok=True)
        open(_gen_stamp(), "w").write(fp + "\n")
    except OSError:
        pass

def profile_changed():
    """True when the profile (or tabs.d) changed since the last `phosphor gen`,
    e.g. a hand edit: it doesn't show until gen and a restart. False when
    gen never recorded one (an install older than this), so it never nags
    about nothing."""
    try:
        stamp = open(_gen_stamp()).read().strip()
    except OSError:
        return False
    fp = profile_fingerprint()
    return bool(stamp and fp and fp != stamp)

def _apply_mark():
    return os.path.join(data_dir(), "apply-pending")

def session_started(sess):
    """When the zellij server of that session started (epoch seconds), or None."""
    try:
        boot = next(float(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
        hz = os.sysconf("SC_CLK_TCK")
    except (OSError, StopIteration, ValueError):
        return None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            args = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")
            if b"--server" not in args or not any(a.endswith(b"/" + sess.encode()) for a in args):
                continue
            stat = open("/proc/%s/stat" % pid).read()
            return boot + int(stat.rsplit(")", 1)[1].split()[19]) / hz
        except (OSError, IndexError, ValueError):
            continue
    return None

def mark_applied():
    """The DECK tab's f ran gen: the deck still has to restart to show it."""
    try:
        os.makedirs(data_dir(), exist_ok=True)
        open(_apply_mark(), "w").close()
    except OSError:
        pass

def restart_pending(sess):
    """f's gen went through but the deck running now is older than it: the
    restart never happened (or failed), so f must still offer it."""
    try:
        at = os.path.getmtime(_apply_mark())
    except OSError:
        return False
    started = session_started(sess)
    return started is not None and started < at

def exe(name):
    """A program's path: ~/.local/bin first (the zellij server's PATH lacks it)."""
    if not name: return None
    name = os.path.expanduser(name)
    if os.sep in name:
        return name if os.access(name, os.X_OK) else None
    local = os.path.expanduser("~/.local/bin/" + name)
    import shutil
    return local if os.access(local, os.X_OK) else shutil.which(name)

def login_shell():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_shell or None
    except Exception as e:
        import dlog
        dlog.event("DECKCONF", "login-shell-failed", str(e)[:60])
        return None

def shell(prof):
    """`shell` in [deck], else your login shell, else bash, else sh."""
    want = ((prof or {}).get("deck") or {}).get("shell")
    for s in (want, login_shell(), "bash", "/bin/sh"):
        p = exe(s)
        if p: return p
    return "/bin/sh"

def editor(prof, ask_login=True):
    """`editor` in [deck], else your $EDITOR, else nano, else vi. Without one,
    programs fall back to vi, which traps people."""
    want = ((prof or {}).get("deck") or {}).get("editor")
    if want: return want
    e = os.environ.get("EDITOR", "")
    if not e and ask_login:
        try:
            import subprocess
            e = subprocess.run(["bash", "-lc", "echo $EDITOR"], capture_output=True,
                               text=True, timeout=5).stdout.strip()
        except Exception as err:
            import dlog
            dlog.event("DECKCONF", "editor-probe-failed", str(err)[:60])
            e = ""
    return e or exe("nano") or "vi"

def installed(names):
    return [n for n in names if exe(n)]

def mount_root(prof):
    return os.path.expanduser(((prof or {}).get("deck") or {}).get("mount_root", "~/fleet"))

def mount_hosts(prof):
    """Non-local hosts with `mount` set: exactly the ones gen.py wires up as
    a fleet-<name>.service (rclone sftp) -- the ones a zombie transport
    (see mount_zombie) can hit."""
    return [h for h in hosts(prof) if not h.get("local") and h.get("mount")]

def mount_zombie(mp):
    """A FUSE mountpoint (rclone sftp, under mount_root) that the kernel
    still lists as mounted but whose transport died: every access fails
    with ENOTCONN ('Transport endpoint is not connected'), common when a
    remote sleeps or changes IP over Tailscale -- os.path.ismount() alone
    says "mounted" either way, so it can't tell the two apart. `stat` runs
    with its own timeout so a mount that's merely slow, not dead, is never
    mistaken for one and never blocks the caller."""
    try:
        r = subprocess.run(["stat", mp], capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode != 0 and "Transport endpoint is not connected" in (r.stderr or "")

def label(m):
    """Folder name of a local disk under mount_root/<host>/: / is root, ~ is
    home, anything else its last component (/mnt/Data2 -> Data2)."""
    m = m.rstrip("/") or "/"
    if m == "/":
        return "root"
    if os.path.expanduser(m) == os.path.expanduser("~"):
        return "home"
    return os.path.basename(os.path.expanduser(m))

def fleet_map(prof):
    """[(prefix under mount_root, host, real path)]: the same map gen mounts
    with, so path translates exactly what yazi shows."""
    out = []
    for h in hosts(prof):
        if h.get("local"):
            for m in h.get("mounts", []):
                out.append(("%s/%s" % (h["name"], label(m)), h["name"], os.path.expanduser(m)))
        elif h.get("mount"):
            out.append((h["name"], h["name"], h["mount"]))
    return out
