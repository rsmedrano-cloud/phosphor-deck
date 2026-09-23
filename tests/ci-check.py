#!/usr/bin/env python3
"""CI / CD pipeline status visualizer against fake GitHub and GitLab APIs.

    python3 tests/ci-check.py

A local HTTP server answers GitHub and GitLab REST endpoints.
phosphor ci --once reads [ci] from a throwaway profile:
cards render status badges (SUCCESS, RUNNING, FAILED, ERR), commit messages,
author names and job badges.
"""
import json, os, re, subprocess, sys, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []

def check(what, ok):
    if not ok:
        fails.append(what)

class FakeCI(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path
        if "api.github.com" in path or "/repos/" in path:
            if "/jobs" in path:
                body = {
                    "jobs": [
                        {"name": "build", "status": "completed", "conclusion": "success"},
                        {"name": "test", "status": "in_progress", "conclusion": None}
                    ]
                }
            else:
                body = {
                    "workflow_runs": [{
                        "status": "completed",
                        "conclusion": "success",
                        "head_branch": "main",
                        "head_sha": "1234567890",
                        "event": "push",
                        "jobs_url": f"http://127.0.0.1:{self.server.server_port}/repos/owner/repo/actions/runs/1/jobs",
                        "head_commit": {"message": "Fix CI integration", "author": {"name": "Test User"}}
                    }]
                }
        elif "/api/v4/projects/private%2Frepo" in path and self.headers.get("PRIVATE-TOKEN") != "glpat-fake":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()
            return
        elif "/api/v4/projects/missing%2Frepo" in path:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()
            return
        elif "/api/v4/projects/" in path:
            if "/jobs" in path:
                body = [
                    {"name": "unit-test", "status": "failed", "stage": "test", "commit": {"title": "Failed pipeline", "author_name": "Dev User"}},
                    {"name": "deploy", "status": "canceled", "stage": "deploy"}
                ]
            elif "/pipelines/" in path:
                body = {"id": 42, "user": {"name": "Dev User"}}
            else:
                body = [{"id": 42, "status": "failed", "ref": "dev", "sha": "abcdef12345", "updated_at": "2026-09-21T10:00:00Z"},
                        {"id": 41, "status": "success", "ref": "dev", "sha": "1111111aaaa", "updated_at": "2026-09-20T10:00:00Z"},
                        {"id": 40, "status": "canceled", "ref": "main", "sha": "2222222bbbb", "updated_at": "2026-09-19T10:00:00Z"}]
        else:
            body = {}

        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

srv = HTTPServer(("127.0.0.1", 0), FakeCI)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_port

tmp = tempfile.mkdtemp()
def profile(body):
    p = os.path.join(tmp, "deck%d.toml" % len(os.listdir(tmp)))
    open(p, "w").write('[deck]\nsession = "probe"\n' + body)
    return p

ci_config = f'''
[ci]
interval = 5

[[ci.pipelines]]
name = "GitHub Build"
provider = "github"
repo = "owner/repo"
branch = "main"

[[ci.pipelines]]
name = "GitLab Service"
provider = "gitlab"
repo = "group/repo"
branch = "dev"
url = "http://127.0.0.1:{port}"
'''

def run(prof_path, width=80, **extra):
    env = dict(os.environ, PHOSPHOR_PROFILE=prof_path, COLUMNS=str(width), **extra)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "phosphor"), "ci", "--once"],
                       capture_output=True, text=True, env=env)
    return p.stdout.splitlines()

# Test 1: Frame output contains header and pipeline cards
lines = run(profile(ci_config), 80)
text = "\n".join(lines)

check("header printed", "CI / CD PIPELINES" in text)
check("github pipeline printed", "GitHub Build" in text)
check("gitlab pipeline printed", "GitLab Service" in text)

# history: older pipelines show under the latest one, whatever its state
check("history section printed", "history" in text)
check("history has an older pipeline", "@1111111" in text and "@2222222" in text)
check("history says how long ago", "d ago" in text)

# a private/missing project explains itself instead of a bare "Not Found"
missing = run(profile(ci_config.replace('repo = "group/repo"', 'repo = "missing/repo"')), 80,
             PATH="/nonexistent", HOME=tempfile.mkdtemp(), GITLAB_TOKEN="")
check("404 says what to do", "404" in "\n".join(missing) and "GITLAB_TOKEN" in "\n".join(missing))

# a pane's PATH (systemd's) lacks ~/.local/bin: glab must still be found there, or a private
# project is a 404. A fake glab in a fake home, and a PATH without it.
home = os.path.join(tmp, "home"); os.makedirs(home + "/.local/bin")
open(home + "/.local/bin/glab", "w").write("#!/bin/sh\necho glpat-fake\n")
os.chmod(home + "/.local/bin/glab", 0o755)
priv = run(profile(ci_config.replace('repo = "group/repo"', 'repo = "private/repo"')), 80,
           PATH="/nonexistent", HOME=home, GITLAB_TOKEN="")
check("glab found in ~/.local/bin, private project readable", "FAILED" in "\n".join(priv) and "private project or wrong repo" not in "\n".join(priv))

# a hiccup keeps the last good card (marked stale) instead of turning it red
sys.path.insert(0, os.path.join(ROOT, "lib"))
import ci
item = {"provider": "gitlab", "repo": "group/repo", "branch": "dev", "url": "http://127.0.0.1:%d" % port, "token": "x"}
good = ci.fetch([item])[0]
check("fetch returns a card", good[1] and good[1]["status"] == "FAILED")
down = ci.fetch([dict(item, url="http://127.0.0.1:1")])[0]
check("a failed fetch keeps the last card, stale", down[1] and down[1].get("stale") and down[2] is None)

# Test 2: Check + menu presence
import newtab
check("+ menu includes ci", "ci" in [e[0] for e in newtab.entries({"ci": {"interval": 5}})])
check("+ menu excludes ci when not configured", "ci" not in [e[0] for e in newtab.entries({"deck": {}})])

if fails:
    print("FAILED:", ", ".join(fails), file=sys.stderr)
    sys.exit(1)

print("ok — phosphor ci checks passed")
