#!/usr/bin/env python3
"""An independent audit of dev, by another assistant, before a minor.

    python3 tests/audit.py [--timeout MINUTES] [--ref REF] [--print]

Runs `agy -p --dangerously-skip-permissions` against a throwaway clone of
the remote's dev (detached, with no remote at all, so nothing it does can
be pushed), with the deck's session variables stripped (no zellij call
lands in the live deck) and phosphor's data, cache and notebook pointed at
copies in the same scratch folder. The report goes into the deck's
notebook (`--by agy`, titled "audit VERSION (SHA)"), never into the repo;
`--print` only prints it; `--ref` audits another commit (no fetch).
The scratch folder is removed either way.

The report is a second opinion, not a verdict: the first one had real
findings and real mistakes side by side. Read it against the code, fix
what holds, then cut the minor. `tests/release.py --main` says so when the
notebook has no audit of the version being promoted.
"""
import os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
os.chdir(ROOT)

PROMPT = """You are auditing Phosphor Deck at version {version} (commit {sha}), a
throwaway clone in the current folder. Read AGENTS.md first.

Rules for this run:
- Nothing leaves this folder: no git push, no glab/gh writes, no edits to
  ~/phosphor-deck or ~/phosphor-dev, no phosphor gen/up/restart/down/update,
  no zellij command against any existing session.
- You may read anything here, run `sh tests/check.sh` and single tests.
- Every claim needs evidence you checked: a file:line, a command and its
  output. Don't describe a feature from its name or from memory; if you
  didn't verify it, leave it out.

Report, in Spanish, markdown, first line a one-line title:
1. Bugs: what breaks, how to reproduce it, file:line, a proposed fix.
2. Docs that say something the code doesn't do (or the other way round).
3. Tests that hang, flake, or pass without testing what their name says.
4. Privacy and safety: personal data in the repo, commands that touch live
   state without asking.
5. At most five ideas, cheapest first, one line each.
Say "nada" for a section with nothing verified. Be brief.
"""

def sh(*a, **kw):
    return subprocess.run(a, capture_output=True, text=True, **kw)

def remote():
    return "gitlab" if "gitlab" in sh("git", "remote").stdout.split() else "origin"

def title(version, sha):
    return "audit %s (%s)" % (version, sha)

def seen(version, path=None):
    """Whether the notebook already holds an audit of this version."""
    import notes
    return any(e["title"].startswith("audit %s " % version) for e in notes.entries(path))

def main(argv):
    minutes = 40
    if "--timeout" in argv:
        i = argv.index("--timeout")
        minutes = int(argv[i + 1]); del argv[i:i + 2]
    only_print = "--print" in argv
    ref = None
    if "--ref" in argv:
        i = argv.index("--ref")
        ref = argv[i + 1]; del argv[i:i + 2]
    if not shutil.which("agy"):
        print("audit: agy isn't installed"); return 1
    if not ref:
        ref = "%s/dev" % remote()
        sh("git", "fetch", "-q", remote(), "dev")
    sha = sh("git", "rev-parse", "--short", ref).stdout.strip()
    if not sha:
        print("audit: no %s to audit" % ref); return 1
    version = sh("git", "show", "%s:VERSION" % sha).stdout.strip()

    import notes
    book = notes.PATH
    tmp = tempfile.mkdtemp(prefix="phosphor-audit-")
    try:
        work = os.path.join(tmp, "phosphor-deck")
        if sh("git", "clone", "-q", "--no-checkout", ROOT, work).returncode != 0:
            print("audit: couldn't clone"); return 1
        sh("git", "-C", work, "checkout", "-q", "--detach", sha)
        sh("git", "-C", work, "remote", "remove", "origin")
        for d in ("data", "cache"):
            os.makedirs(os.path.join(tmp, d))
        copy = os.path.join(tmp, "data", "notes.md")
        if os.path.exists(book):
            shutil.copy(book, copy)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
        env.update(PHOSPHOR_DATA=os.path.join(tmp, "data"), PHOSPHOR_CACHE=os.path.join(tmp, "cache"),
                   PHOSPHOR_NOTES=copy)
        print("audit: agy on %s %s, up to %d minutes" % (version, sha, minutes))
        try:
            r = subprocess.run(["agy", "-p", PROMPT.format(version=version, sha=sha),
                                "--dangerously-skip-permissions", "--print-timeout", "%dm" % minutes],
                               cwd=work, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=minutes * 60 + 120)
        except subprocess.TimeoutExpired:
            print("audit: agy didn't finish in %d minutes" % minutes); return 1
        report = r.stdout.strip()
        if r.returncode != 0 or not report:
            print("audit: agy failed (exit %d)" % r.returncode)
            for l in r.stderr.strip().splitlines()[-10:]: print("    " + l)
            return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if only_print:
        print(report); return 0
    notes.append(book, "summary", "agy", title(version, sha), report)
    print("audit: in the notebook as \"%s\" (phosphor notes). Check it against the code "
          "before acting on it." % title(version, sha))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
