"""phosphor update - bring in a newer version and apply it.

Three steps people forget: get the code, run the installer (new binaries,
the deck command, completion), restart the deck so the panes stop running
the code they started with.

    phosphor update              git pull if this is a clone, then install
    phosphor update FOLDER       take the code from a folder you copied
                                 (remembered: next time plain `update` goes back there)
    phosphor update --no-restart
    phosphor update --full       always a real restart -- skip hotswap's own judgement
    phosphor update --channel nightly   follow dev: what's done, not yet released
    phosphor update --channel stable    back to releases

Nothing of yours is touched: the profile, the notes and the fleet stay.

When the pull only touched one tool's own module (lib/hotswap.py decides,
conservatively -- see its own docs), only the panes running that tool get a
fresh process, in place, live: no session restart. Anything else -- shared
code, share/*, phosphor or install.sh itself -- still gets a real
`phosphor restart`, same as always. `--full` skips the judgement call and
always restarts, same as before hotswap existed.
"""
import json, os, shlex, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf
import hotswap

# A copy has no .git: this file says which folder it came from, so a plain
# `phosphor update` (and the version check) can go back there.
SOURCE = os.path.join(REPO, ".phosphor-source")

def remembered():
    try:
        return json.load(open(SOURCE)).get("src")
    except (OSError, ValueError):
        return None

def remember(src):
    commit = run(["git", "-C", src, "rev-parse", "HEAD"]).stdout.strip() \
        if os.path.isdir(os.path.join(src, ".git")) else ""
    json.dump({"src": src, "commit": commit}, open(SOURCE, "w"))

def run(cmd, **k):
    return subprocess.run(cmd, capture_output=True, text=True, **k)

def is_clone(d):
    # a worktree's .git is a file, not a folder
    return bool(d) and os.path.exists(os.path.join(d, ".git"))

PULL_TIMEOUT = int(os.environ.get("PHOSPHOR_PULL_TIMEOUT", "120"))

def pull(where):
    """git pull --ff-only in the open: git's own output and any prompt it needs
    (a passphrase, a credential) reach the terminal, and a pull that never
    finishes (a dead network, a credential helper waiting on a window nobody
    sees) stops with a message instead of hanging silently."""
    print("  " + DIM + "git pull   " + where + RST, flush=True)
    p = subprocess.Popen(["git", "-C", where, "pull", "--ff-only"])
    try:
        rc = p.wait(timeout=PULL_TIMEOUT)
    except subprocess.TimeoutExpired:
        # git's own children (ssh, a credential helper) outlive a plain kill of
        # git and keep its output open: take the whole tree down. Not a new
        # process group: git has to keep the terminal to ask for a passphrase.
        import screens
        for pid in reversed(screens.descendants(p.pid)):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        p.wait()
        print(row(BAD, "git pull", "no answer in %ds" % PULL_TIMEOUT,
                  note="try it by hand: git -C %s pull" % where))
        return False
    return rc == 0

def from_git():
    if not is_clone(REPO):
        return None
    before = run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"]).stdout.strip()
    if not pull(REPO):
        print(row(BAD, "git pull", "failed", note="nothing was installed")); return False
    after = run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"]).stdout.strip()
    print(row(OK, "git pull", ("%s → %s" % (before, after)) if before != after else "already up to date (%s)" % after))
    return True

TARBALL = os.path.join(REPO, ".phosphor-tarball")

def from_tarball():
    """Installed by downloading (no git on the machine): install.sh, which
    runs next, downloads the newer copy over this one. None if it wasn't."""
    if not os.path.isfile(TARBALL):
        return None
    print(row(OK, "download", "the installer brings the newest copy", note="no git: a tarball"))
    return True

def from_folder(src):
    src = os.path.abspath(os.path.expanduser(src))
    if not os.path.isfile(os.path.join(src, "phosphor")):
        print(row(BAD, src, "no phosphor there")); return False
    if shutil.which("rsync"):
        r = run(["rsync", "-a", "--delete", "--exclude", ".git", "--exclude", ".phosphor-source",
                 src + "/", REPO + "/"])
    else:
        # tar, not cp -r: cp would carry the source's .git into the install
        r = subprocess.run("cd %s && tar --exclude=.git -cf - . | (cd %s && tar -xf -)"
                           % (shlex.quote(src), shlex.quote(REPO)), shell=True,
                           capture_output=True, text=True)
    print(row(OK if r.returncode == 0 else BAD, "code", "%s → %s" % (src, REPO)))
    if r.returncode == 0:
        remember(src)
    return r.returncode == 0

CHANNELS = {"nightly": "dev", "dev": "dev", "stable": "main", "main": "main"}

def switch_channel(d, name):
    """Point the clone d at a channel's branch. True when it's there."""
    b = CHANNELS.get(name)
    if not b:
        print(row(BAD, "channel", name or "?", note="stable or nightly")); return False
    remotes = run(["git", "-C", d, "remote"]).stdout.split()
    rem = "origin" if "origin" in remotes else (remotes[0] if remotes else "origin")
    run(["git", "-C", d, "fetch", "-q", rem])
    have = run(["git", "-C", d, "rev-parse", "--verify", "-q", b]).returncode == 0
    r = run(["git", "-C", d, "switch", b] if have else
            ["git", "-C", d, "switch", "-c", b, "--track", "%s/%s" % (rem, b)])
    ok = r.returncode == 0
    print(row(OK if ok else BAD, "channel", "%s (%s)" % ("nightly" if b == "dev" else "stable", b),
              note="" if ok else ((r.stderr.strip().splitlines() or ["failed"])[-1][:50])))
    return ok

def main():
    argv = sys.argv[1:]
    chan = None
    if "--channel" in argv:
        i = argv.index("--channel")
        chan = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]
    a = [x for x in argv if not x.startswith("-")]
    restart = "--no-restart" not in argv
    full = "--full" in argv
    before_files = hotswap.snapshot()
    print()
    print(BLOOM + "  phosphor update" + RST + DIM + "   " + REPO + RST)
    if chan is not None:
        d = REPO if is_clone(REPO) else remembered()
        if not is_clone(d):
            print(row(BAD, "channel", "needs a git clone", note="or a copy that remembers one"))
            return 1
        if not switch_channel(d, chan):
            return 1
    src = a[0] if a else None
    if src and os.path.realpath(os.path.expanduser(src)) == os.path.realpath(REPO):
        src = None                          # the installed copy itself: a plain update
    if not src and not is_clone(REPO) and remembered():
        src = remembered()                  # a copy: back to the folder it came from
        if is_clone(src):
            ok = pull(src)
            print(row(OK if ok else WARN, "git pull", src,
                      note="" if ok else "failed: installing what's there"))
    ok = from_folder(src) if src else from_git()
    if ok is None:
        ok = from_tarball()
    if ok is None:
        print(row(BAD, "no source", "this isn't a git clone: phosphor update FOLDER"))
        return 1
    if not ok:
        return 1
    # the pull may have changed the modules this process already loaded: read them again, or a
    # new version.py that needs a new deckconf function fails half way through the update
    import importlib
    importlib.reload(deckconf)
    import version
    importlib.reload(version)
    version.forget()
    inst = os.path.join(REPO, "install.sh")
    if os.path.exists(inst):
        # the installer is idempotent: it only fetches what's missing
        r = subprocess.run(["sh", inst], env=dict(os.environ, PHOSPHOR_NO_WIZARD="1", PHOSPHOR_DEST=REPO))
        if r.returncode != 0:
            # a half-done install is no base to restart the deck on: the panes keep the old code
            print(row(BAD, "install", "failed (exit %d)" % r.returncode, note="the deck wasn't touched"))
            return 1
    # (install.sh regenerates from the profile: layouts, units, rclone.conf)
    offer_one_pane()
    if restart:
        print()
        if refresh(before_files, full):
            # unattended updates need to know: a restart that stopped short
            # (old deck not fully down, a missing pane) fails the update too
            rc = subprocess.run([sys.executable, os.path.join(REPO, "phosphor"), "restart"]).returncode
            if rc != 0:
                print(row(BAD, "restart", "didn't finish cleanly", note="see above; phosphor logs"))
            return rc
    else:
        print("  " + DIM + "the panes keep the old code until: phosphor restart" + RST)
    return 0


def offer_one_pane():
    """A profile written before the panel took the whole DECK tab keeps the
    key guide beside it (gen never rewrites a profile): say so once per
    update, and how to change it. Only a hint, the profile isn't touched."""
    try:
        import panel
        name = panel.two_panes(deckconf.load()[0] or {})
    except Exception:
        return
    if name:
        print()
        print(row(WARN, "%s tab" % name, "still has the key guide beside the panel",
                  note="press 1 in it to make it one pane (the keys are ? there)"))


def refresh(before_files, full):
    """Hot-swap the panes an update actually affects, live, instead of a
    real restart -- or decide a real restart is still needed. Always
    prints what it did (or why not); returns True when a restart is
    still needed (--full, hotswap declined, or it hit something
    unexpected -- never silently skips the restart on a surprise)."""
    if full:
        return True
    import kinds
    prof = deckconf.load()[0]
    session = ((prof or {}).get("deck") or {}).get("session", "deck")
    swapped = []
    # the deck's own session, then any kind of screen's (deck-phone...) that's up
    for s in [session] + kinds.all_sessions(prof):
        try:
            got, reason = hotswap.apply(s, before_files, hotswap.snapshot())
        except Exception as e:
            print(row(WARN, "hotswap", "skipped", note="unexpected: %s" % str(e)[:60]))
            return True
        if reason and s == session:
            print(row(WARN, "hotswap", "skipped", note=reason))
            return True
        swapped += got or []
    if swapped:
        for pid, tool in swapped:
            print(row(OK, "hotswap", tool, note="pane %d refreshed live, no restart" % pid))
    else:
        print(row(OK, "hotswap", "nothing to refresh", note="no restart needed"))
    return False

if __name__ == "__main__":
    sys.exit(main() or 0)
