#!/usr/bin/env python3
"""Channels: `phosphor update --channel nightly` follows dev, `stable` goes
back to main, and a clone that never had dev gets it from the remote.

    python3 tests/update-check.py

A scratch remote with main and dev, and a clone of it; no network. Needs git
(CI runs it in the install job, whose image has it).
"""
import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

if not shutil.which("git"):
    print("no git here: skipped"); sys.exit(0)
import contextlib, io, update
def switch(d, name):
    with contextlib.redirect_stdout(io.StringIO()):
        return update.switch_channel(d, name)

fails = []
def need(what, ok):
    if not ok: fails.append(what)

d = tempfile.mkdtemp(prefix="update-check-")
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org", GIT_CONFIG_GLOBAL="/dev/null")
os.environ.update(env)
def git(*a, cwd=None):
    return subprocess.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True, env=env)

src, remote, clone = (os.path.join(d, x) for x in ("src", "remote.git", "clone"))
git("init", "-q", "-b", "main", src)
open(os.path.join(src, "VERSION"), "w").write("0.1.0\n")
git("add", "-A", cwd=src); git("commit", "-q", "-m", "0.1.0", cwd=src)
git("switch", "-q", "-c", "dev", cwd=src)
open(os.path.join(src, "VERSION"), "w").write("0.1.1-dev\n")
git("commit", "-qam", "dev work", cwd=src)
git("clone", "-q", "--bare", src, remote)
git("clone", "-q", "-b", "main", remote, clone)

branch = lambda: git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone).stdout.strip()
version = lambda: open(os.path.join(clone, "VERSION")).read().strip()

need("starts on stable", branch() == "main")
need("nightly: a clone without dev gets it", switch(clone, "nightly") and branch() == "dev")
need("nightly brings dev's code", version() == "0.1.1-dev")
need("stable goes back to main", switch(clone, "stable") and branch() == "main" and version() == "0.1.0")
need("nightly again, dev already there", switch(clone, "nightly") and branch() == "dev")
need("an unknown channel is refused", not switch(clone, "beta") and branch() == "dev")

shutil.rmtree(d, ignore_errors=True)

# refresh(): the restart-or-hotswap decision `phosphor update` makes after
# a pull. hotswap.apply()/deckconf.load() are patched -- this is only the
# control flow, not hotswap's own judgement (tests/hotswap-check.py covers
# that against the real lib/ directory).
import update
real_apply, real_load = update.hotswap.apply, update.deckconf.load

def reset():
    update.hotswap.apply = real_apply
    update.deckconf.load = real_load

try:
    reset()
    update.deckconf.load = lambda: ({"deck": {"session": "deck"}}, "")

    update.hotswap.apply = lambda session, before, after: ([], "gen.py is shared code")
    need("a decline from hotswap means a real restart is needed", update.refresh({}, False) is True)

    update.hotswap.apply = lambda session, before, after: ([(3, "fleet")], None)
    need("a successful swap means no restart is needed", update.refresh({}, False) is False)

    update.hotswap.apply = lambda session, before, after: ([], None)
    need("nothing changed at all: still no restart needed", update.refresh({}, False) is False)

    calls = []
    update.hotswap.apply = lambda *a: calls.append(a) or ([], None)
    need("--full skips hotswap's judgement entirely", update.refresh({}, True) is True)
    need("--full never even calls hotswap.apply", calls == [])

    def raising(*a):
        raise RuntimeError("zellij isn't installed here")
    update.hotswap.apply = raising
    need("an unexpected error still falls back to a real restart, never crashes update",
         update.refresh({}, False) is True)
finally:
    reset()

# main(): its exit status is the whole answer for an unattended update. A
# failed install never restarts the deck; a restart that stopped short (the
# old deck not fully down, see tests/down-gate-check.py) fails the update.
repo = tempfile.mkdtemp(prefix="update-main-")
real = (update.REPO, update.from_git, update.refresh, update.hotswap.snapshot, os.environ.get("HOME"))
try:
    os.environ["HOME"] = repo                  # version.forget() drops a cache under it
    open(os.path.join(repo, "install.sh"), "w").write('exit "${FAKE_INSTALL_RC:-0}"\n')
    open(os.path.join(repo, "phosphor"), "w").write(
        'import os, sys\nopen(os.environ["FAKE_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")\n'
        'sys.exit(int(os.environ.get("FAKE_RESTART_RC", "0")))\n')
    log = os.path.join(repo, "log")
    os.environ["FAKE_LOG"] = log
    update.REPO, update.from_git = repo, lambda: True
    update.refresh = lambda before, full: True       # a real restart is needed
    update.hotswap.snapshot = lambda: {}
    def main(install_rc, restart_rc):
        os.environ["FAKE_INSTALL_RC"], os.environ["FAKE_RESTART_RC"] = str(install_rc), str(restart_rc)
        try: os.remove(log)
        except OSError: pass
        argv, sys.argv = sys.argv, ["phosphor-update"]
        try: rc = update.main()
        finally: sys.argv = argv
        return rc, os.path.exists(log) and "restart" in open(log).read()
    rc, restarted = main(0, 0)
    need("install and restart fine: exit 0", rc == 0 and restarted)
    rc, restarted = main(0, 1)
    need("a restart that stopped short fails the update", rc == 1 and restarted)
    rc, restarted = main(1, 0)
    need("a failed install fails the update and never restarts the deck", rc == 1 and not restarted)
finally:
    update.REPO, update.from_git, update.refresh, update.hotswap.snapshot, home = real
    if home is not None: os.environ["HOME"] = home
    shutil.rmtree(repo, ignore_errors=True)

if fails:
    print("failed: " + "; ".join(fails)); sys.exit(1)
print("ok")
