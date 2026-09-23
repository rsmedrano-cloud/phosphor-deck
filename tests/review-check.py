#!/usr/bin/env python3
"""phosphor review checks: provider detection, GitLab/GitHub list parsing,
and that "try the branch" never touches the caller's own checkout.

    python3 tests/review-check.py
"""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import review

fails, total = [], [0]
def check(what, ok):
    total[0] += 1
    if not ok:
        fails.append(what)

# 1. Provider/repo detection from a URL, not this checkout's real remote:
# the "check" job's image has no `git` on purpose (fast, no network), so
# this can't shell out and expect an answer. Cover both hosts and both
# URL shapes (https, ssh-style) instead.
check("gitlab https", review.provider("https://gitlab.com/rsmedranojobs/phosphor-deck.git") == "gitlab")
check("github ssh", review.provider("git@github.com:owner/repo.git") == "github")
check("neither", review.provider("https://example.com/x/y.git") is None)
slug = review.repo_slug("https://gitlab.com/rsmedranojobs/phosphor-deck.git")
check("repo slug looks like owner/name", slug == "rsmedranojobs/phosphor-deck")
check("repo slug from ssh-style remote", review.repo_slug("git@github.com:owner/repo.git") == "owner/repo")

# 2. GitLab list parsing, without touching the network
class FakeResult:
    def __init__(self, out): self.returncode, self.stdout, self.stderr = 0, out, ""

GITLAB_JSON = json.dumps([{
    "iid": 4, "title": "tts support", "author": {"username": "rsmedranojobs"},
    "source_branch": "feature/tts", "target_branch": "dev",
    "has_conflicts": False, "draft": False, "web_url": "https://gitlab.com/x/y/-/merge_requests/4",
}])
real_run = review.run
review.run = lambda cmd, **kw: FakeResult(GITLAB_JSON)
items, err = review.list_gitlab()
check("gitlab: no error", err is None)
check("gitlab: one item", len(items) == 1)
check("gitlab: fields carried over", items and items[0] == {
    "id": 4, "title": "tts support", "author": "rsmedranojobs",
    "src": "feature/tts", "dst": "dev", "conflicts": False, "draft": False,
    "url": "https://gitlab.com/x/y/-/merge_requests/4",
})

GITHUB_JSON = json.dumps([{
    "number": 7, "title": "add widget", "author": {"login": "octocat"},
    "headRefName": "widget", "baseRefName": "main",
    "mergeable": "CONFLICTING", "isDraft": True, "url": "https://github.com/x/y/pull/7",
}])
review.run = lambda cmd, **kw: FakeResult(GITHUB_JSON)
items, err = review.list_github()
check("github: no error", err is None)
check("github: conflicts flag from mergeable", items and items[0]["conflicts"] is True)
check("github: draft flag carried over", items and items[0]["draft"] is True)

review.run = real_run

# 3. Bad JSON from either CLI is reported, not raised
review.run = lambda cmd, **kw: FakeResult("not json")
items, err = review.list_gitlab()
check("bad JSON doesn't crash list_gitlab", items == [] and err is not None)
review.run = real_run

# 4. try_branch() never runs inside the caller's own working tree: it
# always resolves to a path under ~/.cache/phosphor/review/
wt = review.worktree_dir("gitlab", {"id": 42})
check("worktree is under the review cache dir", wt.startswith(review.REVIEW_DIR))
check("worktree encodes the provider and id", "gi-42" in wt)

if fails:
    print("FAIL:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ok: %d checks" % total[0])
