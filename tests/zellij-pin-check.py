#!/usr/bin/env python3
"""zellij is pinned in one place, share/versions.json: install.sh and
tests/fetch-zellij.py both read it, never "latest" unless asked, and
phosphor doctor says when the installed one differs. No network.

    python3 tests/zellij-pin-check.py
"""
import json, os, re, subprocess, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))

fails = []
def check(what, ok):
    if not ok: fails.append(what)

pin = json.load(open(os.path.join(REPO, "share", "versions.json")))["zellij"]
check("versions.json pins zellij to X.Y.Z", re.fullmatch(r"\d+\.\d+\.\d+", pin))

# install.sh's own line, run against the repo: same version, pinned URL
src = open(os.path.join(REPO, "install.sh")).read()
zv = next((l for l in src.splitlines() if l.startswith('ZV="${PHOSPHOR_ZELLIJ')), "")
check("install.sh reads the pin", zv)
def install_url(env):
    sh = "DEST=%s\nGH=https://github.com\nM=x86_64\n%s\n%s\n" % (REPO, zv,
         '\n'.join(l for l in src.splitlines() if l.startswith(('ZV="${ZV', 'if [ -z "$ZV"', 'else ZREL'))))
    sh += 'echo "$ZREL $GH/zellij-org/zellij/releases/$ZDL/zellij-$M-unknown-linux-musl.tar.gz"'
    e = {k: v for k, v in os.environ.items() if k != "PHOSPHOR_ZELLIJ"}; e.update(env)
    return subprocess.run(["sh", "-c", sh], capture_output=True, text=True, env=e).stdout.strip()
check("install.sh fetches the pinned release",
      install_url({}) == "tags/v%s https://github.com/zellij-org/zellij/releases/download/v%s/"
                         "zellij-x86_64-unknown-linux-musl.tar.gz" % (pin, pin))
check("PHOSPHOR_ZELLIJ=latest takes the newest", install_url({"PHOSPHOR_ZELLIJ": "latest"}).startswith(
      "latest https://github.com/zellij-org/zellij/releases/latest/download/"))
check("PHOSPHOR_ZELLIJ=v0.44.0 takes that one", install_url({"PHOSPHOR_ZELLIJ": "v0.44.0"}).startswith(
      "tags/v0.44.0 https://github.com/zellij-org/zellij/releases/download/v0.44.0/"))
check("zellij's fetch passes the release to the API", re.search(r'fetch zellij .*\n.*"\$ZREL"', src))
check("no other zellij download uses latest", "zellij/releases/latest" not in src)

fz = open(os.path.join(REPO, "tests", "fetch-zellij.py")).read()
check("fetch-zellij.py reads versions.json", "versions.json" in fz)

# doctor: a fake zellij on PATH, the pinned one and another
import doctor
d = tempfile.mkdtemp()
fake = os.path.join(d, "zellij")
for v, warn in ((pin, False), ("9.9.9", True)):
    open(fake, "w").write("#!/bin/sh\necho zellij %s\n" % v); os.chmod(fake, 0o755)
    doctor.have = lambda b: fake
    got, tested = doctor.zellij_versions()
    check("doctor reads zellij %s" % v, got == v and tested == pin)
    check("doctor %s zellij %s" % ("warns about" if warn else "is quiet with", v), (got != tested) == warn)

if fails:
    print("\n".join("FAIL: " + f for f in fails)); sys.exit(1)
print("zellij pin: ok")
