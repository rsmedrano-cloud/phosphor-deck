#!/usr/bin/env python3
"""Wait for the pipelines of this commit and say how they went, briefly.

    python3 tests/ci.py                 the current branch, at HEAD
    python3 tests/ci.py dev main v0.2.0 several refs, all at HEAD's commit
    python3 tests/ci.py --sha f0fd89f main  another commit

One line per job; a failed job prints the end of its log and nothing else.
Exit 0 only when every pipeline passed. Needs glab, logged in.
"""
import json, subprocess, sys, time

TAIL = 40
# seconds: the install job alone can take minutes, and a minor release queues
# TWO full pipelines (main and the tag) back to back on the one runner --
# confirmed against a real 0.4.0 release: main and v0.4.0 started a second
# apart, and only one of them could actually run at a time, pushing the
# combined wait past the old 1500s even though neither pipeline was stuck.
WAIT = 2700

def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True)

def api(path):
    r = sh("glab", "api", path)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return json.loads(r.stdout) if r.stdout.strip().startswith(("[", "{")) else r.stdout

def clean(log):
    """What the job's script printed: no timestamps, colors or runner sections."""
    import re
    out = []
    for l in log.splitlines():
        l = re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\r", "", l)
        l = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z \S+ ?", "", l)
        if "section_end:" in l and "step_script" in l:
            break                                    # the rest is the runner cleaning up
        if l.strip() and "section_" not in l:
            out.append(l)
    return out

def main():
    args = sys.argv[1:]
    at = "HEAD"
    if "--sha" in args:
        i = args.index("--sha"); at = args[i + 1]; del args[i:i + 2]
    sha = sh("git", "rev-parse", at).stdout.strip()
    refs = args or [sh("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()]
    print("ci: %s at %s" % (" ".join(refs), sha[:8]))
    end, pipes = time.time() + WAIT, {}
    while time.time() < end:
        for ref in refs:
            ps = api("projects/:id/pipelines?sha=%s&ref=%s&per_page=1" % (sha, ref))
            if ps: pipes[ref] = ps[0]
        done = [r for r in refs if r in pipes and pipes[r]["status"] not in
                ("created", "waiting_for_resource", "preparing", "pending", "running", "scheduled")]
        if len(done) == len(refs):
            break
        time.sleep(20)
    else:
        missing = [r for r in refs if r not in pipes]
        print("ci: gave up waiting" + (" (no pipeline for %s: pushed?)" % " ".join(missing) if missing else ""))
        return 1
    ok = True
    for ref in refs:
        p = pipes[ref]
        jobs = api("projects/:id/pipelines/%d/jobs?per_page=50" % p["id"])
        print("%-8s %-8s %s" % (ref, p["status"], p["web_url"]))
        for j in sorted(jobs, key=lambda j: j["name"]):
            dur = "%dm%02ds" % divmod(int(j.get("duration") or 0), 60)
            print("   %-9s %-8s %s" % (j["name"], j["status"], dur))
        for j in jobs:
            if j["status"] == "failed":
                log = api("projects/:id/jobs/%d/trace" % j["id"])
                lines = clean(str(log))
                print("--- %s (%s), last %d lines:" % (j["name"], ref, TAIL))
                print("\n".join(lines[-TAIL:]))
        ok = ok and p["status"] == "success"
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
