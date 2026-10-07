"""The brain's own backup: `phosphor backup [FILE]` and `phosphor restore FILE`.

Moving a deck to a new brain used to be four steps by hand (patterns). A
backup is one tar.gz (0600: it holds your notebook and the glance token)
with what can't be made again: the profile, apps.toml, tabs.d, the
notebook (unless [notes] folder already keeps it in a synced vault), the
glance token, your adjutant faces and the folders "where?" remembers.
Never ssh keys, nothing under ~/.ssh, nothing the deck regenerates (gen's
files, caches, logs).

Every file sits under a name of its own in the tar (deck.toml,
tabs.d/X.toml, notes/X.md...) next to phosphor-backup.json, and restore
only takes those names: no paths from the archive, no links, nothing
extracted blindly. It shows each file as new, replaced or the same, writes
on one 'restore it?' Enter (the profile through write_profile, with its
.bak; any other file it replaces keeps a .bak too), and ends with a
`phosphor gen --dry-run` of what the deck would become."""
import io, json, os, re, subprocess, sys, tarfile, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

FORMAT = 1
MANIFEST = "phosphor-backup.json"
# what restore takes from an archive, and nothing else
NAMES = re.compile(r"^(deck\.toml|apps\.toml|glance-token|folders|"
                   r"tabs\.d/[\w.-]+\.toml|notes/[\w.-]+\.md|faces/[\w.-]+\.json)$")
PRIVATE = {"glance-token"}          # written 0600

def tilde(p):
    h = os.path.expanduser("~")
    return "~" + p[len(h):] if p == h or p.startswith(h + "/") else p

def notes_folder():
    """[notes] folder when the profile sets one: that vault is synced by
    its own means, so the backup leaves it out."""
    prof = deckconf.load()[0] or {}
    return (prof.get("notes") or {}).get("folder")

def target(name):
    """Where an archive name lives on this machine."""
    import apps
    data = deckconf.data_dir()
    if name == "deck.toml":
        return os.environ.get("PHOSPHOR_PROFILE", deckconf.CONF)
    if name == "apps.toml":
        return apps.path()
    if name.startswith("tabs.d/"):
        return os.path.join(deckconf.tabs_d_path(), name[len("tabs.d/"):])
    if name.startswith("notes/"):
        return os.path.join(data, name[len("notes/"):])
    return os.path.join(data, *name.split("/"))

def _files(d, ext):
    try:
        return sorted(f for f in os.listdir(d) if f.endswith(ext) and os.path.isfile(os.path.join(d, f)))
    except OSError:
        return []

def collect():
    """[(archive name, path)] of what exists here, and [(what, why)] of what's left out."""
    out, left = [], []
    names = ["deck.toml"] if not deckconf.example() else []
    names += ["apps.toml"]
    names += ["tabs.d/" + f for f in _files(deckconf.tabs_d_path(), ".toml")]
    if notes_folder():
        left.append(("notebook", "lives in %s ([notes] folder), synced its own way" % notes_folder()))
    else:
        names += ["notes/" + f for f in _files(deckconf.data_dir(), ".md")]
    names += ["glance-token", "folders"]
    names += ["faces/" + f for f in _files(os.path.join(deckconf.data_dir(), "faces"), ".json")]
    for n in names:
        p = target(n)
        if NAMES.match(n) and os.path.isfile(p):
            out.append((n, p))
    return out, left

def default_file():
    return os.path.expanduser("~/phosphor-backup-%s.tar.gz" % time.strftime("%Y-%m-%d-%H%M"))

def make(dest, files):
    """Write the archive: 0600, through a temp file, so a half-written one never takes dest's name."""
    import version
    manifest = {"format": FORMAT, "phosphor": version.current()["version"],
                "made": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": [n for n, _ in files]}
    d = os.path.dirname(os.path.abspath(dest))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".phosphor-backup.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz") as tar:
            def add(name, data):
                ti = tarfile.TarInfo(name)
                ti.size, ti.mtime, ti.mode = len(data), int(time.time()), 0o600
                tar.addfile(ti, io.BytesIO(data))
            add(MANIFEST, (json.dumps(manifest, indent=1) + "\n").encode())
            for n, p in files:
                add(n, open(p, "rb").read())
        os.replace(tmp, dest)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return manifest

def read(src):
    """(manifest, {name: bytes}) from an archive, or raises ValueError saying why not.
    Only regular files under NAMES are taken; anything else in it is an error."""
    try:
        tar = tarfile.open(src, "r:*")
    except (OSError, tarfile.TarError) as e:
        raise ValueError("not a backup: %s" % str(e)[:60])
    with tar:
        files, manifest = {}, None
        for m in tar.getmembers():
            if m.isdir():
                continue
            if not m.isfile():
                raise ValueError("%s: not a plain file" % m.name[:40])
            if m.name == MANIFEST:
                try:
                    manifest = json.loads(tar.extractfile(m).read())
                except ValueError:
                    raise ValueError("its %s doesn't parse" % MANIFEST)
            elif NAMES.match(m.name):
                files[m.name] = tar.extractfile(m).read()
            else:
                raise ValueError("%s: not something a backup holds" % m.name[:40])
    if not isinstance(manifest, dict):
        raise ValueError("no %s: not a phosphor backup" % MANIFEST)
    if not isinstance(manifest.get("format"), int) or manifest["format"] > FORMAT:
        raise ValueError("format %s: a newer phosphor made it (phosphor update)" % manifest.get("format"))
    return manifest, files

def plan(files):
    """[(name, path, state)], state: new, replace or same."""
    out = []
    for n in sorted(files, key=lambda n: (n != "deck.toml", n)):
        p = target(n)
        try:
            state = "same" if open(p, "rb").read() == files[n] else "replace"
        except OSError:
            state = "new"
        out.append((n, p, state))
    return out

def _write(p, data, private):
    d = os.path.dirname(p)
    os.makedirs(d, exist_ok=True)
    if os.path.exists(p):
        with open(p, "rb") as old, open(p + ".bak", "wb") as b:
            b.write(old.read())
        os.chmod(p + ".bak", os.stat(p).st_mode & 0o777)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(p) + ".")
    try:
        os.fchmod(fd, 0o600 if private else 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def apply(files, steps):
    """Write every new or replaced file. [(name, error)] of what failed."""
    errs = []
    for n, p, state in steps:
        if state == "same":
            continue
        try:
            if n == "deck.toml":
                err = deckconf.write_profile(files[n].decode(), p=p)
                if err:
                    errs.append((n, err))
            else:
                _write(p, files[n], n in PRIVATE)
        except (OSError, UnicodeDecodeError) as e:
            errs.append((n, str(e)[:60]))
    return errs

def local_hosts(text):
    try:
        prof = deckconf.tomllib.loads(text)
    except Exception:
        return []
    return [h.get("name", "?") for h in prof.get("hosts", []) if h.get("local")]

# ── the commands ──────────────────────────────────────────────
def main():
    argv = [a for a in sys.argv[1:]]
    if any(a in ("-h", "--help") for a in argv):
        print("usage: phosphor backup [FILE]   (default ~/phosphor-backup-DATE.tar.gz)"); return 0
    dest = os.path.abspath(os.path.expanduser(argv[0])) if argv else default_file()
    print()
    print(BLOOM + "  phosphor backup" + RST)
    if os.path.exists(dest):
        print(row(BAD, "backup", "%s is already there" % tilde(dest), note="name another file")); return 1
    files, left = collect()
    if not files:
        print(row(WARN, "backup", "nothing to back up: no profile yet", note="phosphor init")); return 1
    try:
        make(dest, files)
    except OSError as e:
        print(row(BAD, "backup", "can't write it: %s" % str(e)[:50])); return 1
    for n, p in files:
        print("  " + PH + "+" + RST + " " + n + DIM + "   " + tilde(p) + RST)
    for what, why in left:
        print("  " + MUTE + "-" + RST + " " + what + DIM + "   " + why + RST)
    print()
    print(row(OK, "written", tilde(dest), note="0600; no ssh keys in it"))
    print("  " + DIM + "on the new brain: phosphor restore " + os.path.basename(dest) + RST)
    return 0

def restore_main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv or "-n" in argv
    args = [a for a in argv if not a.startswith("-")]
    if not args or any(a in ("-h", "--help") for a in argv):
        print("usage: phosphor restore FILE [--dry-run]"); return 0 if args else 1
    src = os.path.expanduser(args[0])
    print()
    print(BLOOM + "  phosphor restore" + RST + DIM + ("  (dry-run)" if dry else "") + RST)
    try:
        manifest, files = read(src)
    except ValueError as e:
        print(row(BAD, "restore", str(e))); return 1
    print(DIM + "  %s, made %s by phosphor %s" % (tilde(os.path.abspath(src)), manifest.get("made", "?"),
                                                 manifest.get("phosphor", "?")) + RST)
    if "deck.toml" in files:
        try:
            deckconf.tomllib.loads(files["deck.toml"].decode())
        except Exception as e:
            print(row(BAD, "restore", "its profile doesn't parse: %s" % str(e)[:50])); return 1
    steps = plan(files)
    print()
    mark = {"new": PH + "+ new    " + RST, "replace": AMB + "~ replace" + RST, "same": DIM + "= same   " + RST}
    for n, p, state in steps:
        print("  " + mark[state] + " " + n + DIM + "   " + tilde(p) + RST)
    todo = [s for s in steps if s[2] != "same"]
    print()
    if not todo:
        print(row(OK, "restore", "everything in it is already here")); return 0
    if dry:
        return 0
    from init import yes
    if not yes("restore it? (whatever it replaces keeps a .bak)", True):
        return 0
    errs = apply(files, steps)
    for n, err in errs:
        print(row(BAD, n, err))
    print(row(OK if not errs else WARN, "restored", "%d file%s" % (len(todo) - len(errs), "" if len(todo) - len(errs) == 1 else "s")))
    if "deck.toml" in files:
        for h in local_hosts(files["deck.toml"].decode()):
            print(row(WARN, h, "local = true: that was the old brain's own disks",
                      note="edit it, or phosphor setup"))
    print("  " + DIM + "the screens still go to the old brain: rerun phosphor phone / phosphor screen for each" + RST)
    print()
    print(rule("phosphor gen --dry-run"))
    subprocess.call([os.path.join(deckconf.REPO, "phosphor"), "gen", "--dry-run"])
    print("  " + DIM + "looks right? phosphor gen && phosphor up" + RST)
    return 1 if errs else 0

if __name__ == "__main__":
    sys.exit(main() or 0)
