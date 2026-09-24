#!/usr/bin/env python3
"""Cut a release from a dev checkout, the whole way, stopping at the first thing
that isn't right.

    python3 tests/release.py 0.2.26 "a short title"          # a dev release
    python3 tests/release.py 0.3.0 "a short title" --main    # a stable one

1. dev, clean, pushed as it is; the version is newer; Unreleased says something
2. the fast checks
3. VERSION and CHANGELOG.md (`## Unreleased` becomes `## 0.1.10 — title`),
   committed, dev pushed, its pipeline green
4. the tag v0.2.26 pushed on dev and its pipeline green; with --main, main
   fast-forwarded to it first on the remote. The pipeline's release job
   publishes the notes (if it couldn't, this does it with glab)

Which releases go to main is the maintainer's policy: while a minor version is
being built (0.2.x) every release stays on dev, which is the nightly channel;
main, the stable one, only moves when a minor is done (--main, 0.3.0).

5. The public GitHub mirror (github.com/rsmedrano-cloud/phosphor-deck): a
   squashed commit onto its own dev (or main, with --main), never GitLab's
   real history -- building on that branch's previous sync there, same as a
   normal commit, just never carrying GitLab's granular one. Best-effort:
   a GitHub hiccup here doesn't undo an already-shipped GitLab release, it
   just prints what to fix by hand. With --main only, also a real GitHub
   Release with the cross-compiled Rust binaries (rust-release's job
   artifacts on this tag's own pipeline) attached, for install.sh's
   fetch() to find (#32).

It never touches the checkout the live deck runs from: the brain gets the
release like anyone else, with `phosphor update` (the DECK tab offers it).
"""
import json, os, re, shutil, subprocess, sys, tempfile, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

GITHUB = "https://github.com/rsmedrano-cloud/phosphor-deck.git"
GITHUB_REPO = "rsmedrano-cloud/phosphor-deck"

def gh_identity():
    """This checkout's own git identity -- already the maintainer's noreply
    address (see privacy), never hardcoded here: phosphor privacy blocks a
    real email or username in tracked source, on purpose, no exceptions."""
    name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True).stdout.strip()
    email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True).stdout.strip()
    return name, email

def sh(*a, check=True, quiet=True):
    r = subprocess.run(list(a), capture_output=quiet, text=True)
    if check and r.returncode != 0:
        stop("%s failed%s" % (" ".join(a[:3]), (":\n" + (r.stderr or r.stdout).strip()) if quiet else ""))
    return r

def stop(why):
    print("release: " + why); sys.exit(1)

def vtuple(v):
    return tuple(int(x) for x in v.split("."))

def sync_github(branch, v, title):
    """Squash HEAD onto GitHub's own `branch` as one commit, building on
    that branch's previous sync there (a real, if squashed, history on
    GitHub -- never GitLab's granular one). Best-effort on purpose: prints
    what to fix by hand instead of raising, so a GitHub hiccup never undoes
    a GitLab release that already shipped."""
    tmp = tempfile.mkdtemp(prefix="phosphor-ghmirror-")
    try:
        c = subprocess.run(["git", "clone", "-q", GITHUB, tmp], capture_output=True, text=True)
        if c.returncode != 0:
            print("release: GitHub mirror sync skipped (clone failed): " + c.stderr.strip()); return
        has = subprocess.run(["git", "-C", tmp, "rev-parse", "-q", "--verify", "origin/" + branch],
                             capture_output=True).returncode == 0
        if has:
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-B", branch, "origin/" + branch])
            subprocess.run(["git", "-C", tmp, "rm", "-rq", "."], capture_output=True)
        else:
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "--orphan", branch])
        arc = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True).stdout
        t = subprocess.run(["tar", "-xf", "-"], input=arc, cwd=tmp, capture_output=True)
        if t.returncode != 0:
            print("release: GitHub mirror sync skipped (couldn't lay down the tree): " + t.stderr.decode()); return
        subprocess.run(["git", "-C", tmp, "add", "-A"], capture_output=True)
        name, email = gh_identity()
        env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)
        cm = subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "%s — %s" % (v, title)],
                            capture_output=True, text=True, env=env)
        if cm.returncode != 0:
            print("release: GitHub mirror sync skipped (nothing changed since its last sync)"); return
        p = subprocess.run(["git", "-C", tmp, "push", "-q", "-u", "origin", branch],
                           capture_output=True, text=True)
        if p.returncode != 0:
            print("release: GitHub mirror push failed, fix by hand: " + p.stderr.strip()); return
        print("release: GitHub mirror's %s updated too (github.com/rsmedrano-cloud/phosphor-deck)" % branch)
    except Exception as e:
        print("release: GitHub mirror sync skipped (%s)" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def rust_release_job(v):
    """This tag's own rust-release job id, or None. Not `glab job artifact`
    (its own ref+job lookup 404ed against a real tag pipeline in testing,
    even though the artifact plainly exists and downloads fine by job id
    -- see sync_github_binaries()) -- straight at the API instead, the same
    way tests/ci.py already talks to it."""
    p = subprocess.run(["glab", "api", "projects/:id/pipelines?ref=v%s&per_page=1" % v],
                       capture_output=True, text=True)
    pipes = json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else []
    if not pipes:
        return None
    j = subprocess.run(["glab", "api", "projects/:id/pipelines/%d/jobs?per_page=50" % pipes[0]["id"]],
                       capture_output=True, text=True)
    jobs = json.loads(j.stdout) if j.returncode == 0 and j.stdout.strip() else []
    hit = next((x for x in jobs if x["name"] == "rust-release"), None)
    return hit["id"] if hit else None

def sync_github_binaries(v, title):
    """Attach the cross-compiled Rust binaries (rust/fleet-poll, rust/run --
    see #32) to a real GitHub Release: install.sh's fetch() looks at
    GitHub's releases/latest for these, same as zellij/yazi/etc, and it
    always installs from main -- so this only runs for a --main release.
    Shipping it at every dev patch too would make releases/latest drift
    ahead of what a plain `git clone` of main actually checks out.

    The binaries themselves were already built by the tag's own pipeline
    (the rust-release job) -- tests/ci.py already waited for that pipeline
    to go green before this runs, so rust_release_job() just finds what's
    already there. Best-effort, same spirit as sync_github(): a GitHub
    hiccup here never undoes the GitLab release that already shipped."""
    tmp = tempfile.mkdtemp(prefix="phosphor-ghrelease-")
    try:
        jid = rust_release_job(v)
        if jid is None:
            print("release: GitHub release skipped (no rust-release job found for v%s)" % v); return
        zpath = os.path.join(tmp, "artifacts.zip")
        r = subprocess.run(["glab", "api", "projects/:id/jobs/%d/artifacts" % jid,
                            "-H", "Accept: application/octet-stream"],
                           capture_output=True)
        if r.returncode != 0 or not r.stdout:
            print("release: GitHub release skipped (couldn't download rust-release's artifacts): "
                  + r.stderr.decode(errors="replace").strip()); return
        open(zpath, "wb").write(r.stdout)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        dist = os.path.join(tmp, "dist")
        bins = sorted(os.listdir(dist)) if os.path.isdir(dist) else []
        if not bins:
            print("release: GitHub release skipped (rust-release built no binaries)"); return
        c = subprocess.run(["gh", "release", "create", "v" + v, "--repo", GITHUB_REPO,
                            "--title", "%s — %s" % (v, title), "--target", "main",
                            "--notes", "See CHANGELOG.md."]
                           + [os.path.join(dist, b) for b in bins],
                           capture_output=True, text=True)
        if c.returncode != 0:
            print("release: GitHub release failed, fix by hand: " + (c.stderr or c.stdout).strip()); return
        print("release: GitHub release v%s published with %s" % (v, ", ".join(bins)))
    except Exception as e:
        print("release: GitHub release skipped (%s)" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def main():
    args = [a for a in sys.argv[1:] if a != "--main"]
    to_main = len(args) != len(sys.argv) - 1
    if len(args) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", args[0]) or not args[1].strip():
        print(__doc__.split("\n\n")[1]); return 2
    v, title = args[0], args[1].strip()
    remotes = sh("git", "remote").stdout.split()
    rem = "gitlab" if "gitlab" in remotes else "origin"

    # 1. where we are
    if sh("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != "dev":
        stop("run it from a checkout of dev")
    if sh("git", "status", "--porcelain").stdout.strip():
        stop("the tree has uncommitted changes")
    sh("git", "fetch", "-q", rem, "dev", "main", "--tags")
    if sh("git", "rev-parse", "HEAD").stdout != sh("git", "rev-parse", "%s/dev" % rem).stdout:
        stop("dev isn't the same as %s/dev: push it (or pull) first" % rem)
    if sh("git", "merge-base", "--is-ancestor", "%s/main" % rem, "HEAD", check=False).returncode != 0:
        stop("%s/main has commits dev doesn't: merge them into dev first" % rem)
    cur = open("VERSION").read().strip()
    if vtuple(v) <= vtuple(cur):
        stop("%s isn't newer than %s" % (v, cur))
    if sh("git", "rev-parse", "-q", "--verify", "refs/tags/v" + v, check=False).returncode == 0:
        stop("tag v%s already exists" % v)
    log = open("CHANGELOG.md").read()
    m = re.search(r"^## Unreleased\n(.*?)(?=^## )", log, re.S | re.M)
    if not m or not m.group(1).strip():
        stop("## Unreleased is empty: nothing to release")

    # open merge requests: a heads-up, not a blocker -- dev's own state is
    # what's being released, whatever's still open in someone's MR isn't in
    # it yet. See tests/mrs-check.py: their branch never got a pipeline
    # (protected refs only), so this is the only look they get before dev does.
    print("release: open merge requests")
    if subprocess.run([sys.executable, "tests/mrs-check.py"]).returncode != 0:
        print("release: (the above needs a look, but doesn't block this release)")

    # Same idea for the public mirror: nothing else polls it, so without
    # this a bug report or feature request just sits there unseen. See #30.
    print("release: open GitHub issues/PRs")
    subprocess.run([sys.executable, "tests/github-check.py"])

    # 2. the fast checks
    print("release: fast checks")
    if subprocess.run(["sh", "tests/check.sh"], capture_output=True).returncode != 0:
        stop("sh tests/check.sh fails")

    # 3. the version commit, on dev
    open("VERSION", "w").write(v + "\n")
    open("CHANGELOG.md", "w").write(log.replace("## Unreleased\n", "## Unreleased\n\n## %s — %s\n" % (v, title), 1)
                                    .replace("## Unreleased\n\n\n", "## Unreleased\n\n", 1))
    trailer = os.environ.get("RELEASE_TRAILER", "")
    sh("git", "commit", "-qam", v + ("\n\n" + trailer if trailer else ""))
    sh("git", "push", "-q", rem, "dev")
    print("release: dev pushed, waiting for its pipeline")
    if subprocess.run([sys.executable, "tests/ci.py", "dev"]).returncode != 0:
        stop("the dev pipeline failed: fix it on dev, then run this again with the next step's state "
             "(VERSION is already %s: git revert HEAD, or fix and release %s by hand)" % (v, v))

    # 4. main (only if asked) and the tag
    if to_main:
        sh("git", "push", "-q", rem, "HEAD:main")        # the server refuses anything but a fast-forward
    sh("git", "tag", "-a", "v" + v, "-m", "%s — %s" % (v, title))
    sh("git", "push", "-q", rem, "v" + v)
    refs = (["main"] if to_main else []) + ["v" + v]
    print("release: %s pushed, waiting for their pipelines" % " and ".join(refs))
    failed = subprocess.run([sys.executable, "tests/ci.py"] + refs).returncode != 0
    have = sh("glab", "release", "view", "v" + v, check=False).returncode == 0
    if not have:
        m = re.search(r"^## %s[^\n]*\n(.*?)(?=^## |\Z)" % re.escape(v), open("CHANGELOG.md").read(), re.S | re.M)
        notes = os.path.join(os.environ.get("TMPDIR", "/tmp"), "phosphor-release-%s.md" % v)
        open(notes, "w").write(m.group(1).strip() + "\n")
        sh("glab", "release", "create", "v" + v, "--name", "%s — %s" % (v, title), "--notes-file", notes)
        os.unlink(notes)
        print("release: notes published with glab (the pipeline's release job didn't)")
    if failed:
        stop("%s is tagged and its notes are up, but a pipeline failed after it went out: "
             "fix on dev and cut the next patch" % v)

    # 5. the public GitHub mirror -- best-effort, see sync_github's own docstring
    sync_github("main" if to_main else "dev", v, title)
    if to_main:
        sync_github_binaries(v, title)

    print("release: %s — %s is out, on %s. The brain gets it with phosphor update%s." %
          (v, title, "main and dev" if to_main else "dev (nightly)", "" if to_main else " --channel nightly"))
    return 0

if __name__ == "__main__":
    sys.exit(main())
