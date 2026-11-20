#!/usr/bin/env python3
"""phosphor privacy checks: the handle before the git email's @ and glab's
login block a commit like the email itself; a made-up owner doesn't.
A throwaway repo and HOME, never this checkout's own setup.

    python3 tests/privacy-check.py
"""
import os, shutil, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if not shutil.which("git"):             # CI's fast job has no git
    print("skipped: no git"); sys.exit(0)

fails, total = [], [0]
def check(what, ok, got=""):
    total[0] += 1
    if not ok:
        fails.append(what + (": " + got[-300:] if got else ""))

tmp = tempfile.mkdtemp(prefix="privacy-check-")
home, repo = os.path.join(tmp, "home"), os.path.join(tmp, "repo")
os.makedirs(os.path.join(home, ".config", "glab-cli"))
os.makedirs(repo)
open(os.path.join(home, ".config", "glab-cli", "config.yml"), "w").write(
    "hosts:\n    gitlab.com:\n        token: x\n        user: quillfox\n")
env = {k: v for k, v in os.environ.items()
       if not k.startswith(("GIT_", "XDG_", "GLAB_"))}
env.update(HOME=home, USER="nobody-here", NO_COLOR="1")

def git(*a):
    return subprocess.run(["git", "-C", repo] + list(a), env=env,
                          capture_output=True, text=True)

def privacy(files):
    for f in os.listdir(repo):
        if f != ".git":
            os.remove(os.path.join(repo, f))
    for name, body in files.items():
        open(os.path.join(repo, name), "w").write(body)
    git("add", "-A")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "privacy", "--hook"],
                       cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr

try:
    git("init", "-q")
    git("config", "user.email", "wrenmoss@example.org")

    code, out = privacy({"example.toml": 'repo = "nimbus/phosphor-deck"\n'})
    check("a made-up owner passes", code == 0 and not out.strip(), out)

    code, out = privacy({"fixture.py": 'author = "wrenmoss"\n'})
    check("the handle before the email's @ blocks", code == 1 and "your handle" in out, out)

    code, out = privacy({"fixture.py": 'who = "wrenmoss@example.org"\n'})
    check("the email is one finding, not two",
          code == 1 and out.count("fixture.py:1") == 1, out)

    code, out = privacy({"example.toml": 'repo = "quillfox/phosphor-deck"\n'})
    check("glab's login blocks", code == 1 and "glab login" in out, out)

    code, out = privacy({"example.toml": 'repo = "quillfoxes/phosphor-deck"\n'})
    check("a longer word that starts with it doesn't", code == 0, out)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("privacy-check: %d/%d" % (total[0] - len(fails), total[0]))
for f in fails:
    print("  FAIL", f)
sys.exit(1 if fails else 0)
