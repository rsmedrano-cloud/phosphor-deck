#!/usr/bin/env python3
"""phosphor ci - GitLab and GitHub pipeline visualizer in a pane.

Reads [ci] from the profile (interval, [[ci.pipelines]]),
queries GitLab or GitHub APIs and draws status cards for pipelines and jobs,
colored by status (SUCCESS, RUNNING, FAILED, CANCELED).

    phosphor ci           the panel, redrawn every interval
    phosphor ci --once    one frame on stdout
"""
import json, os, re, shutil, subprocess, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, MUTE, PH, BLOOM, AMB, RED, RULE, RST, FG, vlen
import deckconf

DEFAULT_PIPELINES = [
    {"name": "Example GitHub Pipeline", "provider": "github", "repo": "octocat/Hello-World", "branch": "main"},
    {"name": "Example GitLab Pipeline", "provider": "gitlab", "repo": "gitlab-org/gitlab-runner", "branch": "main"},
]

def settings(prof):
    conf = (prof or {}).get("ci", {})
    return (conf.get("pipelines", DEFAULT_PIPELINES), conf.get("interval", 10))

_TOKENS = {}   # asking glab/gh spawns a process: once per run, not every redraw

def get_glab_token(hostname="gitlab.com"):
    """Ask glab itself for the token: it knows whether it's in its config
    file or the OS keyring (common on a desktop), we don't."""
    try:
        r = subprocess.run([deckconf.exe("glab") or "glab", "config", "get", "token", "--host", hostname],
                            capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None

def get_gh_token():
    """Same idea for gh: `gh auth token` resolves it, keyring included."""
    try:
        r = subprocess.run([deckconf.exe("gh") or "gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None

def resolve_token(token_cfg, provider="github"):
    if token_cfg:
        if token_cfg.startswith("env:"):
            var_name = token_cfg[4:].strip()
            return os.environ.get(var_name)
        return token_cfg
    env = os.environ.get("GITLAB_TOKEN" if provider == "gitlab" else "GITHUB_TOKEN")
    if env:
        return env
    if provider not in _TOKENS:
        _TOKENS[provider] = get_glab_token() if provider == "gitlab" else get_gh_token()
    return _TOKENS[provider] or _TOKENS.pop(provider, None)   # not found: ask again next time

HISTORY = 5            # older runs shown under the latest one, idle or not

def ago(iso):
    """'12m ago' from an ISO 8601 timestamp (GitLab and GitHub both send one)."""
    try:
        import calendar
        t = calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return ""
    d = max(0, int(time.time() - t))
    for n, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if d >= n:
            return "%d%s ago" % (d // n, unit)
    return "just now"

def http_error(e, has_token, provider):
    """Say what an HTTP failure means instead of a bare 'Not Found'."""
    code = getattr(e, "code", None)
    if code == 404 and not has_token:
        if provider == "gitlab":
            return "404: private project or wrong repo? glab auth login, or GITLAB_TOKEN"
        return "404: private repo or wrong name? gh auth login, or GITHUB_TOKEN"
    if code == 404:
        return "404: repo or branch not found (does the token see it?)"
    if code == 401:
        return "401: the token was rejected (expired?)"
    if code == 403:
        return "403: forbidden or rate limited"
    return re.sub(r"^\[Errno -?\d+\] ", "", str(getattr(e, "reason", None) or e))

def fetch_github_pipeline(item, timeout=5):
    """Fetch latest run for GitHub repository."""
    repo = item.get("repo", "")
    branch = item.get("branch")
    token = resolve_token(item.get("token"), "github")
    
    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page={HISTORY + 1}"
    if branch:
        url += f"&branch={urllib.parse.quote(branch)}"
    
    headers = {
        "User-Agent": "phosphor-ci",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"token {token}" if not token.startswith("gho_") and not token.startswith("ghp_") else f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        runs = data.get("workflow_runs", [])
        if not runs:
            return None, "no runs found"
        run = runs[0]
        history = []
        for r in runs[1:HISTORY + 1]:
            r_st = r.get("conclusion") if r.get("status") == "completed" else "RUNNING"
            history.append({"status": (r_st or "SUCCESS").upper(), "sha": (r.get("head_sha") or "")[:7],
                            "ref": r.get("head_branch") or "", "when": ago(r.get("updated_at") or r.get("created_at")),
                            "title": (r.get("display_title") or "").split("\n")[0]})

        status_raw = run.get("status")
        conclusion = run.get("conclusion")
        if status_raw == "completed":
            status = conclusion.upper() if conclusion else "SUCCESS"
        elif status_raw in ("in_progress", "queued", "waiting"):
            status = "RUNNING"
        else:
            status = status_raw.upper() if status_raw else "UNKNOWN"
            
        commit_msg = run.get("head_commit", {}).get("message", "").split("\n")[0]
        author = run.get("head_commit", {}).get("author", {}).get("name") or run.get("actor", {}).get("login", "")
        sha = run.get("head_sha", "")[:7]
        branch_name = run.get("head_branch", branch or "main")
        event = run.get("event", "push")
        
        # Optionally fetch jobs for run
        jobs = []
        jobs_url = run.get("jobs_url")
        if jobs_url:
            try:
                j_req = urllib.request.Request(jobs_url, headers=headers)
                with urllib.request.urlopen(j_req, timeout=timeout) as j_resp:
                    j_data = json.loads(j_resp.read().decode("utf-8"))
                for j in j_data.get("jobs", [])[:6]:
                    j_status_raw = j.get("status")
                    j_conclusion = j.get("conclusion")
                    if j_status_raw == "completed":
                        j_st = j_conclusion.upper() if j_conclusion else "SUCCESS"
                    elif j_status_raw in ("in_progress", "queued", "waiting"):
                        j_st = "RUNNING"
                    else:
                        j_st = j_status_raw.upper() if j_status_raw else "UNKNOWN"
                    jobs.append({"name": j.get("name", "job"), "status": j_st})
            except Exception as e:
                import dlog
                dlog.event_throttled("CI", "github-jobs-failed", str(e)[:60])
                
        return {
            "name": item.get("name") or f"{repo} ({branch_name})",
            "provider": "GitHub",
            "repo": repo,
            "branch": branch_name,
            "status": status,
            "commit": commit_msg,
            "author": author,
            "sha": sha,
            "event": event,
            "jobs": jobs,
            "history": history,
            "when": ago(run.get("updated_at") or run.get("created_at")),
        }, None
    except Exception as e:
        return None, http_error(e, bool(token), "github")

def fetch_gitlab_pipeline(item, timeout=5):
    """Fetch latest pipeline for GitLab repository."""
    repo = item.get("repo", "")
    branch = item.get("branch")
    base_url = (item.get("url") or "https://gitlab.com").rstrip("/")
    token = resolve_token(item.get("token"), "gitlab")
    
    project_id = urllib.parse.quote(repo, safe="")
    url = f"{base_url}/api/v4/projects/{project_id}/pipelines?per_page={HISTORY + 1}"
    if branch:
        url += f"&ref={urllib.parse.quote(branch)}"
        
    headers = {"User-Agent": "phosphor-ci"}
    if token:
        if token.startswith("glpat-") or token.startswith("glcbt-"):
            headers["PRIVATE-TOKEN"] = token
        else:
            headers["Authorization"] = f"Bearer {token}"
        
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            pipelines = json.loads(resp.read().decode("utf-8"))
        if not pipelines:
            return None, "no pipelines found"
        pipe = pipelines[0]
        pipe_id = pipe.get("id")

        status_map = {
            "success": "SUCCESS",
            "failed": "FAILED",
            "running": "RUNNING",
            "pending": "RUNNING",
            "canceled": "CANCELED",
            "skipped": "SKIPPED",
            "manual": "MANUAL",
        }
        status_raw = pipe.get("status", "unknown")
        status = status_map.get(status_raw, status_raw.upper())
        history = [{"status": status_map.get(o.get("status", ""), (o.get("status") or "unknown").upper()),
                    "sha": (o.get("sha") or "")[:7], "ref": o.get("ref") or "",
                    "when": ago(o.get("updated_at") or o.get("created_at")), "title": ""}
                   for o in pipelines[1:HISTORY + 1]]
        
        sha = pipe.get("sha", "")[:7]
        branch_name = pipe.get("ref", branch or "main")
        
        # Fetch detailed info for commit / jobs
        commit_msg = ""
        author = ""
        jobs = []
        
        pipe_detail_url = f"{base_url}/api/v4/projects/{project_id}/pipelines/{pipe_id}"
        try:
            d_req = urllib.request.Request(pipe_detail_url, headers=headers)
            with urllib.request.urlopen(d_req, timeout=timeout) as d_resp:
                d_data = json.loads(d_resp.read().decode("utf-8"))
                user = d_data.get("user", {})
                author = user.get("name") or user.get("username", "")
        except Exception as e:
            import dlog
            dlog.event_throttled("CI", "gitlab-detail-failed", str(e)[:60])

        jobs_url = f"{base_url}/api/v4/projects/{project_id}/pipelines/{pipe_id}/jobs?per_page=50"
        try:
            j_req = urllib.request.Request(jobs_url, headers=headers)
            with urllib.request.urlopen(j_req, timeout=timeout) as j_resp:
                j_data = json.loads(j_resp.read().decode("utf-8"))
            # newest first, retries included: keep each job's latest try, in pipeline order
            latest = {}
            for j in sorted(j_data, key=lambda j: j.get("id", 0)):
                latest[j.get("name", "job")] = j
            for j in sorted(latest.values(), key=lambda j: j.get("id", 0))[:12]:
                j_st_raw = j.get("status", "unknown")
                j_st = status_map.get(j_st_raw, j_st_raw.upper())
                jobs.append({"name": j.get("name", "job"), "status": j_st, "stage": j.get("stage", "")})
                if not commit_msg and j.get("commit"):
                    commit_msg = j.get("commit", {}).get("title", "")
                    if not author:
                        author = j.get("commit", {}).get("author_name", "")
        except Exception as e:
            import dlog
            dlog.event_throttled("CI", "gitlab-jobs-failed", str(e)[:60])

        return {
            "name": item.get("name") or f"{repo} ({branch_name})",
            "provider": "GitLab",
            "repo": repo,
            "branch": branch_name,
            "status": status,
            "commit": commit_msg,
            "author": author,
            "sha": sha,
            "event": "pipeline",
            "jobs": jobs,
            "history": history,
            "when": ago(pipe.get("updated_at") or pipe.get("created_at")),
        }, None
    except Exception as e:
        return None, http_error(e, bool(token), "gitlab")

def fetch_pipeline(item):
    provider = (item.get("provider") or "github").lower()
    if provider == "gitlab":
        return fetch_gitlab_pipeline(item)
    return fetch_github_pipeline(item)

def get_status_style(status):
    st = (status or "UNKNOWN").upper()
    if st in ("SUCCESS", "COMPLETED", "PASSED"):
        return PH, "SUCCESS", "✓"
    elif st in ("RUNNING", "IN_PROGRESS", "PENDING", "QUEUED"):
        return AMB, "RUNNING", "⚡"
    elif st in ("FAILED", "FAILURE"):
        return RED, "FAILED ", "✗"
    elif st in ("CANCELED", "CANCELLED", "SKIPPED"):
        return MUTE, "CANCELED", "⊘"
    return DIM, st[:7], "?"

def cut(s, n):
    return s if len(s) <= n else s[:max(0, n - 1)] + "…"

def card(name, tag, col, body, w):
    inner = w - 2
    title = " %s " % cut(name, max(1, inner - len(tag) - 5))
    top = (RULE + "╭─" + RST + BLOOM + title + RST
           + RULE + "─" * max(0, inner - 1 - len(title) - len(tag) - 2) + RST
           + col + " %s " % tag + RST + RULE + "╮" + RST)
    lines = [top]
    for b in body:
        lines.append(RULE + "│" + RST + b + " " * max(0, inner - vlen(b)) + RULE + "│" + RST)
    lines.append(RULE + "╰" + "─" * inner + "╯" + RST)
    return lines

def draw_pipeline_card(item, data, err, width):
    name = item.get("name") or item.get("repo", "Pipeline")
    inner = width - 2
    if err or not data:
        col, tag = RED, "ERR"
        body = [" " + MUTE + cut(err or "no data", inner - 2) + RST]
        return card(name, tag, col, body, width)
        
    col, tag, symbol = get_status_style(data["status"])
    
    # Subtitle line: branch @ sha by author
    meta_parts = []
    if data.get("branch"):
        meta_parts.append(data["branch"])
    if data.get("sha"):
        meta_parts.append("@" + data["sha"])
    if data.get("author"):
        meta_parts.append("by " + data["author"])
    if data.get("when"):
        meta_parts.append(data["when"])
    meta_str = " · ".join(meta_parts)
    
    body = [
        " " + col + symbol + " " + RST + FG + cut(meta_str, inner - 4) + RST,
    ]
    if data.get("commit"):
        body.append(" " + DIM + cut("💬 " + data["commit"], inner - 2) + RST)
        
    # Render Jobs progress bar / badges if present
    jobs = data.get("jobs", [])
    if jobs:
        body.append(" " + RULE + "─" * max(0, inner - 2) + RST)
        job_badges = []
        for j in jobs:
            j_col, _, j_sym = get_status_style(j["status"])
            j_name = cut(j["name"], 14)
            job_badges.append(j_col + j_sym + " " + j_name + RST)
        
        # Fit badges in rows
        current_row = " "
        for badge in job_badges:
            if vlen(current_row) + vlen(badge) + 2 > inner:
                body.append(current_row)
                current_row = " " + badge + "  "
            else:
                current_row += badge + "  "
        if current_row.strip():
            body.append(current_row)
            
    hist = data.get("history") or []
    if hist:
        body.append(" " + RULE + "─ history " + "─" * max(0, inner - 12) + RST)
        for h in hist:
            h_col, _, h_sym = get_status_style(h["status"])
            line = " " + h_col + h_sym + RST + " " + FG + cut("%s @%s" % (h["ref"], h["sha"]), 22) + RST
            tail = h.get("when", "")
            room = inner - 3 - vlen(line) + 1 - len(tail)
            title = cut(h["title"], max(0, room - 2)) if h.get("title") else ""
            body.append(line + DIM + " " + title + " " * max(1, room - len(title)) + tail + RST)
    if data.get("stale"):
        body.append(" " + AMB + "stale" + RST + DIM + " · " + cut(data["stale"], inner - 12) + RST)
    return card(name, tag, col, body, width)

def frame(cols, rows, results):
    w = max(16, cols)
    out = [RULE + " CI / CD PIPELINES " + "─" * max(0, w - 20) + RST,
           DIM + cut(" Pipelines status · %s" % time.strftime("%H:%M:%S"), w) + RST]
    for item, data, err in results:
        out += draw_pipeline_card(item, data, err, w)
    return out[:max(1, rows)]

_LAST = {}   # the last good answer per pipeline: a hiccup shouldn't turn the card red

def fetch(pipelines):
    with ThreadPoolExecutor(max_workers=max(2, len(pipelines))) as ex:
        futs = [ex.submit(fetch_pipeline, p) for p in pipelines]
        res = []
        for p, f in zip(pipelines, futs):
            try:
                data, err = f.result()
            except Exception as e:                  # one bad pipeline never takes the panel down
                data, err = None, "%s: %s" % (type(e).__name__, str(e)[:60])
            key = (p.get("provider"), p.get("repo"), p.get("branch"))
            if data:
                _LAST[key] = data
            elif key in _LAST:
                data, err = dict(_LAST[key], stale=err), None
            res.append((p, data, err))
        return res

def main():
    prof, _ = deckconf.load()
    pipelines, interval = settings(prof)
    if "--once" in sys.argv:
        cols = shutil.get_terminal_size((80, 24)).columns
        print("\n".join(frame(cols, 10000, fetch(pipelines))))
        return
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            cols, rows = shutil.get_terminal_size((80, 24))
            out = frame(cols, rows, fetch(pipelines))
            sys.stdout.write("\x1b[H" + "\x1b[K\n".join(out) + "\x1b[K\x1b[J")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?1049l\x1b[?25h\n")

if __name__ == "__main__":
    main()
