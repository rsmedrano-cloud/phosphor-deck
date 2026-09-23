"""phosphor version - which version this is, and whether there's a newer one.

    phosphor version             this version, and what the last check found
    phosphor version --check     ask the source now (a git clone: git fetch)
    phosphor version --notes     what this version brought
    phosphor version --new       what a newer one brings, before you update

A copy without .git can't ask anyone: `phosphor update FOLDER` with a newer
copy is how it moves. The check runs at most every few hours, in the
background, and the DECK tab shows its result next to the version.
"""
import json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *

CACHE = os.path.join(deckconf.cache_dir(), "update.json")
EVERY = 6 * 3600

def git(*a, timeout=20, where=None):
    try:
        r = subprocess.run(["git", "-C", where or REPO] + list(a), capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        import dlog
        dlog.event_throttled("VERSION", "git-failed", every=600)   # never str(e): -C quotes the install path
        return None

def current():
    try:
        v = open(os.path.join(REPO, "VERSION")).read().strip()
    except OSError:
        v = "?"
    clone = os.path.exists(os.path.join(REPO, ".git"))
    cur = {"version": v, "commit": git("rev-parse", "--short", "HEAD") if clone else None,
           "upstream": git("rev-parse", "--abbrev-ref", "@{u}") if clone else None,
           "source": None, "copied": None}
    if not clone:
        # a copy: the clone it was copied from (phosphor update FOLDER) can ask
        try:
            rec = json.load(open(os.path.join(REPO, ".phosphor-source")))
        except (OSError, ValueError):
            rec = {}
        src = rec.get("src")
        if src and os.path.isdir(os.path.join(src, ".git")):
            cur["source"], cur["copied"] = src, rec.get("commit") or None
            cur["upstream"] = git("rev-parse", "--abbrev-ref", "@{u}", where=src)
    # the channel is the branch the clone follows: dev is nightly, the rest stable
    if clone or cur["source"]:
        cur["branch"] = git("rev-parse", "--abbrev-ref", "HEAD", where=cur["source"])
    else:
        cur["branch"] = None
    cur["channel"] = "nightly" if cur["branch"] == "dev" else "stable"
    return cur

def cached():
    try:
        return json.load(open(CACHE))
    except (OSError, ValueError):
        return {}

def stale():
    c = cached()
    if time.time() - c.get("checked", 0) > EVERY:
        return True
    # a commit that moved since the last check (a merge --ff-only outside
    # `phosphor update`, not just the update flow that already forget()s)
    # makes the cached behind/latest describe a version we're not on anymore.
    commit = current()["commit"]
    return bool(commit) and c.get("commit") != commit

def forget():
    """After an update the old news is wrong: drop it."""
    try: os.remove(CACHE)
    except OSError: pass

def check():
    cur = current()
    res = {"checked": time.time(), "behind": 0, "latest": None, "commit": cur["commit"]}
    if cur["upstream"]:
        where = cur["source"]                # None: this clone itself
        base = cur["copied"] or "HEAD"       # a copy is as new as the commit it was copied at
        if git("fetch", "-q", timeout=30, where=where) is not None:
            n = git("rev-list", "--count", base + "..@{u}", where=where)
            res["behind"] = int(n) if n and n.isdigit() else 0
            res["latest"] = (git("show", "@{u}:VERSION", where=where) or "").strip() or None
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(res, open(CACHE, "w"))
    return res

def check_later():
    """The panel calls this: a stale check runs detached, never in its way."""
    if stale():
        subprocess.Popen([sys.executable, os.path.join(REPO, "phosphor"), "version", "--check", "--quiet"],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def news():
    """A short line for the panel when a new VERSION is out, else ''. Commits
    that don't bump it (docs, small fixes on their way) announce nothing."""
    c = cached()
    if not c.get("behind"):
        return ""
    cur = current()
    if cur["channel"] == "nightly":           # nightly is every commit: that's the point
        return "%d new on nightly" % c["behind"]
    latest = c.get("latest")
    if not latest or not newer_than(latest, cur["version"]):
        return ""
    return "new version %s" % latest

def parse(text):
    """[(version, lines)] from a CHANGELOG, in file order (newest first)."""
    out, cur = [], None
    for l in text.splitlines():
        m = re.match(r"^## (\d+\.\d+\.\d+)", l)
        if m:
            cur = (m.group(1), [l]); out.append(cur)
        elif cur and not l.startswith("# "):
            cur[1].append(l)
    return out

def newer_than(v, mine):
    k = lambda x: tuple(int(n) for n in x.split("."))
    try: return k(v) > k(mine)
    except ValueError: return False

def whats_new():
    """What the update brings, from the source: the release notes of every
    newer version, or on nightly the Unreleased part (what's done, not out)."""
    cur = current()
    if not cur["upstream"]:
        return []
    text = git("show", "@{u}:CHANGELOG.md", where=cur["source"]) or ""
    if cur["channel"] == "nightly":
        m = re.search(r"^## Unreleased\n(.*?)(?=^## |\Z)", text, re.S | re.M)
        return [("unreleased", ["## Unreleased, on nightly"] + m.group(1).splitlines())] if m else []
    return [(v, ls) for v, ls in parse(text) if newer_than(v, cur["version"])]

def print_notes(sections):
    for v, ls in sections:
        print("  " + BLOOM + ls[0].lstrip("# ").strip() + RST)
        for l in ls[1:]:
            if l.strip():
                print("  " + FG + l + RST)
        print()

def main():
    quiet = "--quiet" in sys.argv[1:]
    if "--new" in sys.argv[1:]:                # what a newer version brings, if any
        print_notes(whats_new())
        return 0
    if "--notes" in sys.argv[1:]:              # this version's own notes
        try:
            text = open(os.path.join(REPO, "CHANGELOG.md")).read()
        except OSError:
            text = ""
        print()
        print_notes([x for x in parse(text) if x[0] == current()["version"]])
        return 0
    cur = current()
    res = check() if "--check" in sys.argv[1:] else cached()
    if quiet:
        return 0
    print()
    print(row(OK, "phosphor", cur["version"], note=(cur["commit"] or "a copy, no git")))
    print(row(OK, "installed in", REPO))
    if cur["source"]:
        print(row(OK, "copied from", cur["source"], note="checks and updates go there"))
    if cur["branch"]:
        other = "stable" if cur["channel"] == "nightly" else "nightly"
        print(row(OK, "channel", "%s (%s)" % (cur["channel"], cur["branch"]),
                  note="phosphor update --channel %s" % other))
    if not cur["commit"] and not cur["source"]:
        print("  " + DIM + "a copy can't check by itself: phosphor update FOLDER with a newer one" + RST)
    elif not cur["upstream"]:
        print("  " + DIM + "no upstream branch: this clone is its own source" + RST)
    elif not res.get("checked"):
        print("  " + DIM + "not checked yet: phosphor version --check" + RST)
    elif res.get("behind") and cur["channel"] == "nightly":
        print(row(WARN, "nightly", "%d new commit%s" % (res["behind"], "" if res["behind"] == 1 else "s"),
                  note="phosphor update"))
        new = whats_new()
        if new:
            print()
            print_notes(new)
    elif res.get("behind") and (not res.get("latest") or res["latest"] == cur["version"]):
        print(row(OK, "up to date", cur["version"],
                  note="%d newer commit%s, no new version yet" % (res["behind"], "" if res["behind"] == 1 else "s")))
    elif res.get("behind"):
        print(row(WARN, "newer version", (res.get("latest") or "?"),
                  note="%d commit%s ahead · phosphor update" % (res["behind"], "" if res["behind"] == 1 else "s")))
        new = whats_new()
        if new:
            print()
            print("  " + DIM + "what it brings:" + RST)
            print_notes(new)
    else:
        ago = int((time.time() - res["checked"]) / 60)
        print(row(OK, "up to date", cur["upstream"], note="checked %s ago" % ("%d min" % ago if ago < 120 else "%d h" % (ago // 60))))
    print()
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
