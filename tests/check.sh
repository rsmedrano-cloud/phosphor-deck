#!/bin/sh
# The fast checks: seconds, no docker, no network. What CI runs on every
# push and merge request, and what a release refuses to skip.
#
#     sh tests/check.sh
#
# The slow ones (a clean install in a systemd container) are
# tests/from-zero.sh and tests/tester-sim.py.
cd "$(dirname "$0")/.." || exit 1
fail=0
step() { printf '  %-34s' "$1"; }
ok()   { printf 'ok\n'; }
bad()  { printf 'FAIL\n'; [ -n "$1" ] && printf '%s\n' "$1" | sed 's/^/      /'; fail=1; }

step "python compiles"
out=$(python3 -m py_compile phosphor lib/*.py tests/*.py 2>&1) && ok || bad "$out"

step "no function shadows the module's"
out=$(python3 tests/shadow-check.py 2>&1) && ok || bad "$out"

step "shell scripts parse"
out=$(for f in install.sh tests/*.sh; do sh -n "$f" || echo "$f"; done 2>&1)
[ -z "$out" ] && ok || bad "$out"

step "the docs name every command"
out=$(python3 tests/docs-check.py 2>&1) && ok || bad "$out"

step "AGENTS.md matches the manual"
out=$(python3 phosphor docs --check 2>&1) && ok || bad "$out"

step "help: an image, not raw markdown"
out=$(python3 tests/docs-render-check.py 2>&1) && ok || bad "$out"

step "a live tab reads back"
out=$(python3 tests/keep-check.py 2>&1) && ok || bad "$out"

step "a frozen program is closed"
out=$(python3 tests/hang-check.py 2>&1) && ok || bad "$out"

step "--reconnect backs off instead of hammering a dead link"
out=$(python3 tests/run-reconnect-check.py 2>&1) && ok || bad "$out"

step "welcome invites, not a key list"
out=$(python3 tests/welcome-check.py 2>&1) && ok || bad "$out"

step "notes: a vault folder, migrated"
out=$(python3 tests/notes-vault-check.py 2>&1) && ok || bad "$out"

step "tabs.d: shared tabs, read-only"
out=$(python3 tests/tabs-d-check.py 2>&1) && ok || bad "$out"

step "recipes, and wizard shapes"
out=$(python3 tests/recipe-check.py 2>&1) && ok || bad "$out"

step "your apps, the store opens them"
out=$(python3 tests/apps-check.py 2>&1) && ok || bad "$out"

step "tabs forgotten and moved, as text"
out=$(python3 tests/tabs-check.py 2>&1) && ok || bad "$out"

step "your keys, and what gen may touch"
out=$(python3 tests/keys-check.py 2>&1) && ok || bad "$out"

step "a profile write's undo depth: .bak, .bak.2, .bak.3"
out=$(python3 tests/backup-check.py 2>&1) && ok || bad "$out"

step "the reaper takes only the deck"
out=$(python3 tests/reap-check.py 2>&1) && ok || bad "$out"

step "notes change only their own entry"
out=$(python3 tests/notes-check.py 2>&1) && ok || bad "$out"

step "channels follow their branch"
out=$(python3 tests/update-check.py 2>&1) && ok || bad "$out"

step "update cache stays honest"
out=$(python3 tests/version-check.py 2>&1) && ok || bad "$out"

step "a workspace, folder to tab"
out=$(python3 tests/workspace-check.py 2>&1) && ok || bad "$out"

step "a workspace's tab marks when NOTES.md changes"
out=$(python3 tests/workspace-notes-watch-check.py 2>&1) && ok || bad "$out"

step "ask picks an assistant, no tab"
out=$(python3 tests/ask-check.py 2>&1) && ok || bad "$out"

step "commands.json matches phosphor's own command list"
out=$(python3 tests/commands-manifest-check.py 2>&1) && ok || bad "$out"

step "web on: never restarts unattended without --yes"
out=$(python3 tests/web-check.py 2>&1) && ok || bad "$out"

step "new --here: refuses with nobody attached"
out=$(python3 tests/newtab-attach-check.py 2>&1) && ok || bad "$out"

step "commands: category/leaf picker, only safe ones auto-run"
out=$(python3 tests/commands-menu-check.py 2>&1) && ok || bad "$out"

step "prometheus gauges, fake server"
out=$(python3 tests/prom-check.py 2>&1) && ok || bad "$out"

step "CI pipelines status, fake server"
out=$(python3 tests/ci-check.py 2>&1) && ok || bad "$out"

step "QR codes read back"
out=$(python3 tests/qr-check.py 2>&1) && ok || bad "$(printf '%s\n' "$out" | tail -3)"

step "deck logs: crash, hang, trace"
out=$(python3 tests/log-check.py 2>&1) && ok || bad "$out"

step "TTS notifications and voices"
out=$(python3 tests/tts-check.py 2>&1) && ok || bad "$out"

step "push notifications (ntfy)"
out=$(python3 tests/push-check.py 2>&1) && ok || bad "$out"

step "notify: --no-event, --fleet-alert, PHOSPHOR_CACHE"
out=$(python3 tests/notify-check.py 2>&1) && ok || bad "$out"

step "fleet alerts: down/back, debounced, cooled down"
out=$(python3 tests/fleet-alert-check.py 2>&1) && ok || bad "$out"

step "a mention pushes and speaks too"
out=$(python3 tests/mentions-push-check.py 2>&1) && ok || bad "$out"

step "demo mode: fake fleet and notes"
out=$(python3 tests/demo-check.py 2>&1) && ok || bad "$out"

step "every tool follows theme"
out=$(python3 tests/tool-colors-check.py 2>&1) && ok || bad "$out"

step "yazi: c t clips the file"
out=$(python3 tests/yazi-keymap-check.py 2>&1) && ok || bad "$out"

step "send: one file, one link, gone"
out=$(python3 tests/send-check.py 2>&1) && ok || bad "$out"

step "receive: the other way, one upload, gone"
out=$(python3 tests/receive-check.py 2>&1) && ok || bad "$out"

step "services: units match what gen writes"
out=$(python3 tests/services-check.py 2>&1) && ok || bad "$out"

step "glance: fleet, mentions, todos"
out=$(python3 tests/glance-check.py 2>&1) && ok || bad "$out"

step "phosphor review: MRs/PRs, safely"
out=$(python3 tests/review-check.py 2>&1) && ok || bad "$out"

step "phosphor screens: who's attached, kick one"
out=$(python3 tests/screens-check.py 2>&1) && ok || bad "$out"

step "fleet: a slow poll tags itself and logs"
out=$(python3 tests/fleet-timing-check.py 2>&1) && ok || bad "$out"

step "adjutant: fleet.json read once per change, not per tick"
out=$(python3 tests/adjutant-check.py 2>&1) && ok || bad "$out"

step "fleet: rust poller picked when installed, else python"
out=$(python3 tests/fleet-poller-check.py 2>&1) && ok || bad "$out"

step "fleet: a zombie ~/fleet mount self-heals"
out=$(python3 tests/mount-zombie-check.py 2>&1) && ok || bad "$out"

step "hotswap: which code changes are safe to refresh live"
out=$(python3 tests/hotswap-check.py 2>&1) && ok || bad "$out"

step "restart: poll instead of blind sleeps, same worst case"
out=$(python3 tests/restart-check.py 2>&1) && ok || bad "$out"

step "restart: nothing new until the old deck is gone"
out=$(python3 tests/down-gate-check.py 2>&1) && ok || bad "$out"

step "site/ (GitHub Pages) matches the manual"
out=$(python3 tests/site-check.py 2>&1) && ok || bad "$out"

step "VERSION has release notes"
v=$(cat VERSION)
grep -q "^## $v" CHANGELOG.md && ok || bad "CHANGELOG.md has no '## $v' entry"

step "the help lists every tool"
out=$(python3 - <<'PY'
import re
src = open("phosphor").read()
tools = re.search(r"TOOLS = \(([^)]*)\)", src, re.S).group(1)
names = re.findall(r'"(\w+)"', tools)
usage = src.split('USAGE = """', 1)[1].split('"""', 1)[0]
alias = {"newtab": "new", "tunnels": "tunnel", "run": None, "completion": "completion"}
miss = [n for n in names if alias.get(n, n) and "phosphor %s" % alias.get(n, n) not in usage]
print(" ".join(miss))
PY
)
[ -z "$out" ] && ok || bad "missing from phosphor help: $out"

step "completion knows every command"
out=$(python3 - <<'PY'
import re, sys
sys.path.insert(0, "lib")
import completion
usage = open("phosphor").read().split('USAGE = """', 1)[1].split('"""', 1)[0]
words = set(re.findall(r"^\s*phosphor ([a-z][a-z-]*)", usage, re.M)) - {"completion"}
print(" ".join(sorted(words - set(completion.CMDS.split()))))
PY
)
[ -z "$out" ] && ok || bad "missing from completion: $out"

[ $fail = 0 ] && printf '\nPASS: the fast checks\n' || printf '\nFAIL\n'
exit $fail
