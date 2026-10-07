#!/usr/bin/env python3
"""phosphor backup / restore: the archive holds the profile, apps.toml,
tabs.d, the notebook, the glance token, faces and folders, and nothing
else (no .bak, no feed, no ssh); it's 0600; a [notes] folder leaves the
notebook out; restore takes only those names (no paths, links or
strangers from the tar, no newer format), says new/replace/same, keeps a
.bak of whatever it replaces and writes the token 0600; --dry-run writes
nothing. Every path is a temp dir: nothing real is read or written.

    python3 tests/brain-backup-check.py
"""
import contextlib, io, json, os, sys, tarfile, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))

fails = []
def check(what, ok):
    if not ok: fails.append(what)

def brain(root):
    """Point every phosphor path at root (a made-up brain)."""
    os.environ.update(PHOSPHOR_PROFILE=os.path.join(root, "conf", "deck.toml"),
                      PHOSPHOR_APPS=os.path.join(root, "conf", "apps.toml"),
                      PHOSPHOR_TABS_D=os.path.join(root, "conf", "tabs.d"),
                      PHOSPHOR_DATA=os.path.join(root, "data"))
    for d in ("conf/tabs.d", "data/faces"):
        os.makedirs(os.path.join(root, d), exist_ok=True)

def put(root, rel, text, mode=0o644):
    p = os.path.join(root, rel)
    with open(p, "w") as f:
        f.write(text)
    os.chmod(p, mode)
    return p

old, new = tempfile.mkdtemp(), tempfile.mkdtemp()
brain(old)
import deckconf, backup
PROFILE = '[deck]\nsession = "deck"\nversion = 2\n\n[[hosts]]\nname = "nimbus"\nlocal = true\n'
put(old, "conf/deck.toml", PROFILE)
put(old, "conf/deck.toml.bak", "old\n")
put(old, "conf/apps.toml", "[apps]\n")
put(old, "conf/tabs.d/db-box.toml", "[[tabs]]\nname = \"DB\"\n")
put(old, "data/notes.md", "# notes\n")
put(old, "data/notes-archive.md", "# archive\n")
put(old, "data/glance-token", "s3cret\n", 0o600)
put(old, "data/folders", "~/src\n")
put(old, "data/mentions.jsonl", "{}\n")
put(old, "data/faces/robot.json", "{}\n")

files, left = backup.collect()
names = sorted(n for n, _ in files)
check("backup takes what can't be made again", names == sorted(
    ["deck.toml", "apps.toml", "tabs.d/db-box.toml", "notes/notes.md", "notes/notes-archive.md",
     "glance-token", "folders", "faces/robot.json"]))
check("...and nothing else", not left)

arch = os.path.join(old, "b.tar.gz")
with contextlib.redirect_stdout(io.StringIO()):
    sys.argv = ["phosphor-backup", arch]
    check("backup exits 0", backup.main() == 0)
    check("...and never overwrites a file", backup.main() == 1)
check("the archive is 0600", os.stat(arch).st_mode & 0o777 == 0o600)
manifest, got = backup.read(arch)
check("the manifest lists its files", sorted(manifest["files"]) == names and manifest["format"] == backup.FORMAT)
check("the contents round-trip", got["glance-token"] == b"s3cret\n" and got["deck.toml"] == PROFILE.encode())

# a vault keeps the notebook: the backup leaves it out and says why
put(old, "conf/deck.toml", PROFILE + '\n[notes]\nfolder = "%s"\n' % os.path.join(old, "vault"))
files, left = backup.collect()
check("[notes] folder leaves the notebook out", not any(n.startswith("notes/") for n, _ in files)
      and left and left[0][0] == "notebook")
put(old, "conf/deck.toml", PROFILE)

# restore only takes its own names
def tar(members, manifest={"format": 1}):
    p = tempfile.mktemp(suffix=".tar.gz", dir=old)
    with tarfile.open(p, "w:gz") as t:
        for name, data in [(backup.MANIFEST, json.dumps(manifest).encode())] * (manifest is not None) + members:
            ti = tarfile.TarInfo(name); ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return p

def refused(p):
    try:
        backup.read(p); return False
    except ValueError:
        return True

check("a path out of the tree is refused", refused(tar([("../evil.toml", b"x")])))
check("an absolute path is refused", refused(tar([("/etc/passwd", b"x")])))
check("a name it doesn't hold is refused", refused(tar([("ssh/id_ed25519", b"x")])))
check("no manifest: not a backup", refused(tar([("deck.toml", b"")], manifest=None)))
check("a newer format is refused", refused(tar([], manifest={"format": backup.FORMAT + 1})))
p = tempfile.mktemp(suffix=".tar.gz", dir=old)
with tarfile.open(p, "w:gz") as t:
    m = tarfile.TarInfo(backup.MANIFEST); d = b'{"format": 1}'; m.size = len(d); t.addfile(m, io.BytesIO(d))
    l = tarfile.TarInfo("deck.toml"); l.type = tarfile.SYMTYPE; l.linkname = "/etc/passwd"; t.addfile(l)
check("a link is refused", refused(p))
check("not a tar at all is refused", refused(os.path.join(old, "conf/apps.toml")))

# onto a new brain
brain(new)
put(new, "conf/apps.toml", "[apps]\nmine = 1\n")
steps = backup.plan(got)
state = {n: s for n, _, s in steps}
check("the profile comes first", steps[0][0] == "deck.toml")
check("new, replace and same", state["deck.toml"] == "new" and state["apps.toml"] == "replace")
with contextlib.redirect_stdout(io.StringIO()):
    sys.argv = ["phosphor-restore", arch, "--dry-run"]
    check("restore --dry-run exits 0", backup.restore_main() == 0)
check("--dry-run writes nothing", not os.path.exists(os.path.join(new, "conf/deck.toml"))
      and open(os.path.join(new, "conf/apps.toml")).read() == "[apps]\nmine = 1\n")

check("restore writes everything", backup.apply(got, steps) == [])
check("the profile is back", open(os.path.join(new, "conf/deck.toml")).read() == PROFILE)
check("tabs.d, notebook, faces are back", all(os.path.isfile(os.path.join(new, r)) for r in
      ("conf/tabs.d/db-box.toml", "data/notes.md", "data/notes-archive.md", "data/faces/robot.json")))
check("the token is back, 0600", open(os.path.join(new, "data/glance-token")).read() == "s3cret\n"
      and os.stat(os.path.join(new, "data/glance-token")).st_mode & 0o777 == 0o600)
check("a replaced file keeps a .bak", open(os.path.join(new, "conf/apps.toml.bak")).read() == "[apps]\nmine = 1\n")
check("the feed stayed behind", not os.path.exists(os.path.join(new, "data/mentions.jsonl")))
check("a second restore finds it all the same", all(s == "same" for _, _, s in backup.plan(got)))
check("local = true hosts are pointed out", backup.local_hosts(PROFILE) == ["nimbus"])

if fails:
    print("brain-backup-check FAILED:\n  " + "\n  ".join(fails)); sys.exit(1)
print("brain-backup-check ok")
