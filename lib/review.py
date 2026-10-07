#!/usr/bin/env python3
"""phosphor review - merge requests / pull requests, from the deck.

Detects GitLab or GitHub from this repo's remote and drives `glab`/`gh`:
the diff, whether CI passed, whether it merges cleanly, and a way to check
the branch out into its own worktree to try it -- never your working copy.

    phosphor review           the panel
"""
import json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, PH, AMB, RED, RST, pad, vlen, topbar
import tui
import ci as cimod
import deckconf, proc
from sanitize import clean_tree

HOME = os.path.expanduser("~")
REVIEW_DIR = os.path.join(HOME, ".cache/phosphor/review")
INV = "\x1b[7m"


def tool(name):
    """glab/gh by full path: a pane's PATH (systemd's) lacks ~/.local/bin."""
    return deckconf.exe(name) or name


def run(cmd, timeout=20, **kw):
    return proc.run(cmd, timeout=timeout, **kw)


def remote_names():
    return run(["git", "remote"]).stdout.split()


def remote_url():
    names = remote_names()
    for pref in ("gitlab", "origin"):
        if pref in names:
            u = run(["git", "remote", "get-url", pref]).stdout.strip()
            if u:
                return u
    return run(["git", "remote", "get-url", names[0]]).stdout.strip() if names else ""


def provider(url=None):
    u = remote_url() if url is None else url
    if "gitlab" in u:
        return "gitlab"
    if "github" in u:
        return "github"
    return None


def repo_slug(url=None):
    u = (remote_url() if url is None else url).rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    if "://" not in u and "@" in u and ":" in u:
        u = u.split(":", 1)[1]
    return "/".join(u.split("/")[-2:])


def list_gitlab():
    r = run([tool("glab"), "mr", "list", "--output", "json"])
    if r.returncode != 0:
        return [], (r.stderr or "glab mr list failed").strip()
    try:
        data = clean_tree(json.loads(r.stdout or "[]"))
    except json.JSONDecodeError as e:
        return [], "glab returned bad JSON: %s" % e
    items = []
    for m in data:
        items.append({
            "id": m["iid"], "title": m["title"], "author": m.get("author", {}).get("username", "?"),
            "src": m["source_branch"], "dst": m["target_branch"],
            "conflicts": bool(m.get("has_conflicts")), "draft": bool(m.get("draft")),
            "url": m.get("web_url", ""),
        })
    return items, None


def list_github():
    r = run([tool("gh"), "pr", "list", "--json",
             "number,title,author,headRefName,baseRefName,mergeable,isDraft,url"])
    if r.returncode != 0:
        return [], (r.stderr or "gh pr list failed").strip()
    try:
        data = clean_tree(json.loads(r.stdout or "[]"))
    except json.JSONDecodeError as e:
        return [], "gh returned bad JSON: %s" % e
    items = []
    for m in data:
        items.append({
            "id": m["number"], "title": m["title"], "author": m.get("author", {}).get("login", "?"),
            "src": m["headRefName"], "dst": m["baseRefName"],
            "conflicts": m.get("mergeable") == "CONFLICTING", "draft": bool(m.get("isDraft")),
            "url": m.get("url", ""),
        })
    return items, None


def list_items(prov):
    if prov == "gitlab":
        return list_gitlab()
    if prov == "github":
        return list_github()
    return [], "this repo's remote isn't GitLab or GitHub"


def fetch_ci(prov, item, repo):
    """Reuse phosphor ci's own fetchers: same pipeline/run data, same colors."""
    spec = {"repo": repo, "branch": item["src"], "name": item["title"]}
    if prov == "gitlab":
        return cimod.fetch_gitlab_pipeline(spec)
    return cimod.fetch_github_pipeline(spec)


def diff_cmd(prov, item):
    if prov == "gitlab":
        return [tool("glab"), "mr", "diff", str(item["id"])]
    return [tool("gh"), "pr", "diff", str(item["id"])]


def diff_text(prov, item):
    r = run(diff_cmd(prov, item), timeout=25)
    text = r.stdout or r.stderr or "(no diff)"
    delta = shutil.which("delta")
    if delta:
        d = run([delta], input=text, timeout=20)
        if d.stdout:
            text = d.stdout
    return text


def worktree_dir(prov, item):
    return os.path.join(REVIEW_DIR, "%s-%s" % (prov[:2], item["id"]))


def try_branch(prov, item):
    """A throwaway worktree for the branch -- never the user's own checkout,
    never a real merge (same spirit as tests/mrs-check.py)."""
    os.makedirs(REVIEW_DIR, exist_ok=True)
    names = remote_names()
    rem = "gitlab" if "gitlab" in names else ("origin" if "origin" in names else (names[0] if names else ""))
    if not rem:
        return False, "no git remote configured here"
    run(["git", "fetch", "-q", rem, item["src"]], timeout=30)
    wt = worktree_dir(prov, item)
    if not os.path.isdir(wt):
        r = run(["git", "worktree", "add", "-q", wt, "%s/%s" % (rem, item["src"])], timeout=30)
        if r.returncode != 0:
            return False, ("couldn't check out the branch: " + r.stderr.strip())[:160]
    else:
        run(["git", "-C", wt, "checkout", "-q", item["src"]], timeout=15)
        run(["git", "-C", wt, "reset", "-q", "--hard", "%s/%s" % (rem, item["src"])], timeout=15)
    short = wt.replace(HOME, "~", 1)
    if not os.environ.get("ZELLIJ"):
        return True, "checked out at " + short + " (open it from inside the deck for a tab of its own)"
    import gen, newtab, deckconf
    prof, _ = deckconf.load()
    label = ("MR" if prov == "gitlab" else "PR") + str(item["id"])
    name = newtab.unique(label, newtab.taken_names())
    d = os.path.join(deckconf.cache_dir(), "apps")
    os.makedirs(d, exist_ok=True)
    lay = os.path.join(d, "%s-%s.kdl" % (name.lower(), time.strftime("%Y%m%d-%H%M%S")))
    with open(lay, "w") as f:
        f.write(gen.tab_kdl({"name": name, "panes": [{"cwd": wt}]}, gen.Ctx(prof or {}), "phosphor review"))
    newtab.zj("new-tab", "--layout", lay, "--name", name)
    return True, "opened a shell in " + name + " at " + short


def drop_branch(prov, item):
    r = run(["git", "worktree", "remove", "--force", worktree_dir(prov, item)], timeout=15)
    if r.returncode != 0:
        return False, ("couldn't remove it: " + r.stderr.strip())[:160]
    return True, "removed the worktree"


def cut(s, n):
    return s if vlen(s) <= n else s[:max(0, n - 1)] + "…"


def ci_tag(prov, item, repo, cache):
    key = item["id"]
    if key not in cache:
        data, err = fetch_ci(prov, item, repo)
        cache[key] = (data, err)
    data, err = cache[key]
    if err or not data:
        return DIM, "no CI"
    col, tag, symbol = cimod.get_status_style(data["status"])
    return col, symbol + " " + tag.strip()


class Panel(tui.ListPanel):
    KEYS = [("d", "diff"), ("c", "ci"), ("t", "try the branch"), ("x", "drop worktree"),
            ("r", "refresh"), ("q", "quit")]
    INTERVAL = 60        # glab/gh over the network: once a minute, r for now

    def __init__(self, prov, repo):
        super().__init__()
        self.prov, self.repo, self.ci = prov, repo, {}

    def fetch(self):
        items, err = list_items(self.prov)
        self.ci = {}
        if err:
            self.problem = err
        return items

    def header(self, w):
        return topbar("REVIEW", "GitLab" if self.prov == "gitlab" else "GitHub", self.repo, min(w, 110))

    def lines(self, w, sel):
        if not self.rows:
            return [" " + DIM + "no open merge/pull requests" + RST]
        w = min(w, 110)
        out = []
        for i, it in enumerate(self.rows):
            col, tag = ci_tag(self.prov, it, self.repo, self.ci)
            mark = RED + "⚠ conflicts" + RST if it["conflicts"] else (col + tag + RST)
            idlabel = ("!%d" if self.prov == "gitlab" else "#%d") % it["id"]
            nm = "%-4s %s" % (idlabel, cut(it["title"], max(10, w - 34)))
            by = DIM + ("by " + it["author"]) + RST
            if it["draft"]:
                by = AMB + "draft" + RST + " " + by
            line = pad(pad(" " + FG + nm + RST, w - 24) + by, w - 12) + mark
            out.append(INV + pad(" " + nm, w - 4) + RST if i == sel else line)
        return out

    def act(self, k, it):
        if k == "r":
            self.refresh(); return self.say("refreshed", PH)
        if k == "d":
            return self.page(diff_text(self.prov, it))
        if k == "c":
            self.ci.pop(it["id"], None)
            col, tag = ci_tag(self.prov, it, self.repo, self.ci)
            return self.say(tag, col)
        if k == "t":
            ok, m = try_branch(self.prov, it)
            return self.say(("✓ " if ok else "✗ ") + m, PH if ok else RED)
        if not os.path.isdir(worktree_dir(self.prov, it)):
            return self.say("nothing checked out for this one", DIM)
        self.confirm("drop the worktree of %s?" % it["src"], lambda: drop_branch(self.prov, it),
                     "anything changed in " + worktree_dir(self.prov, it).replace(HOME, "~", 1) + " is lost")


def main():
    prov = provider()
    if not prov:
        print(RED + "this repo's remote isn't GitLab or GitHub -- phosphor review needs glab or gh" + RST)
        return 1
    if not deckconf.exe("glab" if prov == "gitlab" else "gh"):
        print(RED + "%s isn't installed" % ("glab" if prov == "gitlab" else "gh") + RST)
        return 1
    repo = repo_slug()

    if not sys.stdin.isatty():
        items, err = list_items(prov)
        if err:
            print(err); return 1
        for it in items:
            flag = "CONFLICTS" if it["conflicts"] else ("draft" if it["draft"] else "")
            print("%s%-4s %-40s %-12s %s" % ("#" if prov == "gitlab" else "#", it["id"], it["title"][:40], it["author"], flag))
        return 0
    return Panel(prov, repo).run()


if __name__ == "__main__":
    sys.exit(main() or 0)
