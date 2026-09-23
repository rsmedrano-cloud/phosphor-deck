#!/usr/bin/env python3
"""phosphor review - merge requests / pull requests, from the deck.

Detects GitLab or GitHub from this repo's remote and drives `glab`/`gh`:
the diff, whether CI passed, whether it merges cleanly, and a way to check
the branch out into its own worktree to try it -- never your working copy.

    phosphor review           the panel
"""
import json, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, MUTE, PH, BLOOM, AMB, RED, RULE, RST, getkey as ui_getkey, pad, vlen
import ci as cimod
import deckconf

HOME = os.path.expanduser("~")
REVIEW_DIR = os.path.join(HOME, ".cache/phosphor/review")
INV = "\x1b[7m"


def tool(name):
    """glab/gh by full path: a pane's PATH (systemd's) lacks ~/.local/bin."""
    return deckconf.exe(name) or name


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 20), **kw)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


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
        data = json.loads(r.stdout or "[]")
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
        data = json.loads(r.stdout or "[]")
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


def raw_screen(on):
    sys.stdout.write("\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h" if on
                      else "\x1b[?1006l\x1b[?1000l\x1b[?1049l\x1b[?25h")
    sys.stdout.flush()


def show_diff(prov, item):
    r = run(diff_cmd(prov, item), timeout=25)
    text = r.stdout or r.stderr or "(no diff)"
    delta = shutil.which("delta")
    if delta:
        d = run([delta], input=text, timeout=20)
        if d.stdout:
            text = d.stdout
    raw_screen(False)
    try:
        p = subprocess.Popen(["less", "-R"], stdin=subprocess.PIPE)
        p.communicate(text.encode("utf-8", "replace"))
    except (OSError, subprocess.SubprocessError):
        print(text)
        input(DIM + "-- press enter --" + RST)
    finally:
        raw_screen(True)


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
    d = os.path.expanduser("~/.cache/phosphor/apps")
    os.makedirs(d, exist_ok=True)
    lay = os.path.join(d, "%s-%s.kdl" % (name.lower(), time.strftime("%Y%m%d-%H%M%S")))
    with open(lay, "w") as f:
        f.write(gen.tab_kdl({"name": name, "panes": [{"cwd": wt}]}, gen.Ctx(prof or {}), "phosphor review"))
    newtab.zj("new-tab", "--layout", lay, "--name", name)
    return True, "opened a shell in " + name + " at " + short


def drop_branch(prov, item):
    wt = worktree_dir(prov, item)
    if not os.path.isdir(wt):
        return DIM + "nothing checked out for this one" + RST
    run(["git", "worktree", "remove", "--force", wt], timeout=15)
    return PH + "removed the worktree" + RST


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

    items, err = list_items(prov)
    ci_cache = {}
    sel, msg = 0, (AMB + err + RST) if err else ""
    raw_screen(True)
    try:
        while True:
            cols, rows = shutil.get_terminal_size((90, 30))
            w = min(cols, 110)
            head = "─ PHOSPHOR REVIEW · %s " % ("GitLab" if prov == "gitlab" else "GitHub")
            tail = "─ %s ─" % repo
            out = [RULE + "╭" + head + "─" * max(0, w - 2 - len(head) - len(tail)) + tail + "╮" + RST]
            if not items:
                out.append(RULE + "│" + RST + pad(" " + DIM + "no open merge/pull requests" + RST, w - 2) + RULE + "│" + RST)
            for i, it in enumerate(items):
                col, tag = ci_tag(prov, it, repo, ci_cache)
                mark = RED + "⚠ conflicts" + RST if it["conflicts"] else (col + tag + RST)
                idlabel = ("!%d" if prov == "gitlab" else "#%d") % it["id"]
                nm = "%-4s %s" % (idlabel, cut(it["title"], max(10, w - 34)))
                line = " " + FG + nm + RST
                by = DIM + ("by " + it["author"]) + RST
                if it["draft"]:
                    by = AMB + "draft" + RST + " " + by
                line = pad(line, w - 24) + by
                line = pad(line, w - 12) + mark
                if i == sel:
                    line = INV + pad(" " + nm, w - 4) + RST
                out.append(RULE + "│" + RST + pad(line, w - 2) + RULE + "│" + RST)
            out.append(RULE + "╰" + "─" * (w - 2) + "╯" + RST)
            hint = " j/k move · d diff · c ci · t try the branch · x drop worktree · r refresh · q quit"
            out.append(DIM + hint[:w] + RST)
            if msg:
                out.append(" " + msg)
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()

            k = ui_getkey(None)
            msg = ""
            if k in ("q", "\x03"):
                break
            elif k in ("j", "\x1b[B"):
                sel = min(sel + 1, max(0, len(items) - 1))
            elif k in ("k", "\x1b[A"):
                sel = max(sel - 1, 0)
            elif k == "r":
                items, err = list_items(prov)
                ci_cache = {}
                msg = (AMB + err + RST) if err else PH + "refreshed" + RST
            elif k == "d" and items:
                show_diff(prov, items[sel])
            elif k == "c" and items:
                ci_cache.pop(items[sel]["id"], None)
                col, tag = ci_tag(prov, items[sel], repo, ci_cache)
                msg = col + tag + RST
            elif k == "t" and items:
                ok, m = try_branch(prov, items[sel])
                msg = (PH + "✓ " if ok else RED + "✗ ") + m + RST
            elif k == "x" and items:
                msg = drop_branch(prov, items[sel])
    except KeyboardInterrupt:
        pass
    finally:
        raw_screen(False)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
