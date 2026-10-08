#!/bin/sh
# The fast checks: seconds, no docker, no network. What CI runs on every
# push and merge request, and what a release refuses to skip.
#
#     sh tests/check.sh
#
# The slow ones (a clean install in a systemd container) are
# tests/from-zero.sh and tests/tester-sim.py.
cd "$(dirname "$0")/.." || exit 1
# a caller's own data/cache/notebook (tests/audit.py sets them) must not leak into tests
unset PHOSPHOR_DATA PHOSPHOR_CACHE PHOSPHOR_NOTES
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

step "a touch screen is never stuck"
out=$(python3 tests/touch-check.py 2>&1) && ok || bad "$out"

step "--reconnect backs off instead of hammering a dead link"
out=$(python3 tests/run-reconnect-check.py 2>&1) && ok || bad "$out"

step "welcome invites, not a key list"
out=$(python3 tests/welcome-check.py 2>&1) && ok || bad "$out"

step "a deck for each kind of screen"
out=$(python3 tests/screen-kinds-check.py 2>&1) && ok || bad "$out"

step "setup: a deck of its own, or not"
out=$(python3 tests/screen-setup-check.py 2>&1) && ok || bad "$out"

step "a warm-up on the way in, skippable"
out=$(python3 tests/splash-check.py 2>&1) && ok || bad "$out"

step "panels that draw don't echo keys"
out=$(python3 tests/passive-input-check.py 2>&1) && ok || bad "$out"

step "notes: a vault folder, migrated"
out=$(python3 tests/notes-vault-check.py 2>&1) && ok || bad "$out"

step "tabs.d: shared tabs, read-only"
out=$(python3 tests/tabs-d-check.py 2>&1) && ok || bad "$out"

step "recipes, and wizard shapes"
out=$(python3 tests/recipe-check.py 2>&1) && ok || bad "$out"

step "wizard: never offers itself back as a fleet candidate"
out=$(python3 tests/wizard-dedup-check.py 2>&1) && ok || bad "$out"

step "fleet: keys over a card"
out=$(python3 tests/fleet-keys-check.py 2>&1) && ok || bad "$out"
step "fleet: the last 24 hours, h over a card"
out=$(python3 tests/fleet-history-check.py 2>&1) && ok || bad "$out"

step "text from outside is text: no escapes reach a screen"
out=$(python3 tests/sanitize-check.py 2>&1) && ok || bad "$out"

step "your apps, the store opens them"
out=$(python3 tests/apps-check.py 2>&1) && ok || bad "$out"

step "tabs forgotten and moved, as text"
out=$(python3 tests/tabs-check.py 2>&1) && ok || bad "$out"

step "your keys, and what gen may touch"
out=$(python3 tests/keys-check.py 2>&1) && ok || bad "$out"

step "a profile write's undo depth: .bak, .bak.2, .bak.3"
out=$(python3 tests/backup-check.py 2>&1) && ok || bad "$out"

step "the profile is written whole, checked, and never over a newer write"
out=$(python3 tests/profile-write-check.py 2>&1) && ok || bad "$out"

step "an older profile migrates"
out=$(python3 tests/migrate-check.py 2>&1) && ok || bad "$out"

step "a backup holds its own files, and restore takes only those"
out=$(python3 tests/brain-backup-check.py 2>&1) && ok || bad "$out"

step "one way to run zellij, sh and ssh"
out=$(python3 tests/proc-check.py 2>&1) && ok || bad "$out"

step "a misspelled profile key is said"
out=$(python3 tests/profile-schema-check.py 2>&1) && ok || bad "$out"

step "one set of limits for every panel, [alerts]"
out=$(python3 tests/limits-check.py 2>&1) && ok || bad "$out"

step "zellij pinned in one place"
out=$(python3 tests/zellij-pin-check.py 2>&1) && ok || bad "$out"

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

step "commands.json: one definition for help, completion and the menu"
out=$(python3 tests/commands-manifest-check.py 2>&1) && ok || bad "$out"

step "an unknown flag is a usage error; no call of phosphor's own is one"
out=$(python3 tests/argv-check.py 2>&1) && ok || bad "$out"

step "deprecated: warns on stderr, goes when it said it would"
out=$(python3 tests/deprecations-check.py 2>&1) && ok || bad "$out"

step "web on: never restarts unattended without --yes"
out=$(python3 tests/web-check.py 2>&1) && ok || bad "$out"

step "new --here: refuses with nobody attached"
out=$(python3 tests/newtab-attach-check.py 2>&1) && ok || bad "$out"

step "new: an assistant asks which folder it starts in"
out=$(python3 tests/newtab-folder-check.py 2>&1) && ok || bad "$out"

step "new: / searches tabs, the menu, workspaces, tools, commands"
out=$(python3 tests/search-check.py 2>&1) && ok || bad "$out"

step "commands: category/leaf picker, only safe ones auto-run"
out=$(python3 tests/commands-menu-check.py 2>&1) && ok || bad "$out"

step "commands ask instead of quitting"
out=$(python3 tests/asks-check.py 2>&1) && ok || bad "$out"

step "panels you act from: services and workspace"
out=$(python3 tests/act-check.py 2>&1) && ok || bad "$out"

step "theme: preview per palette, picker writes nothing until Enter"
out=$(python3 tests/theme-check.py 2>&1) && ok || bad "$out"

step "tail: journalctl/docker/podman through phosphor run --reconnect"
out=$(python3 tests/tail-check.py 2>&1) && ok || bad "$out"

step "--help explains, never runs"
out=$(python3 tests/help-flag-check.py 2>&1) && ok || bad "$out"

step "triage: snapshot over ssh, piped into phosphor ask"
out=$(python3 tests/triage-check.py 2>&1) && ok || bad "$out"

step "broadcast: asks first, then every host"
out=$(python3 tests/broadcast-check.py 2>&1) && ok || bad "$out"

step "panel: DECK tab actions (host pickers; q, Esc, Enter go back from every one)"
out=$(python3 tests/panel-actions-check.py 2>&1) && ok || bad "$out"

step "panel: cards reflow with the width"
out=$(python3 tests/panel-grid-check.py 2>&1) && ok || bad "$out"

step "a hand-edited profile says so (DECK tab f, doctor)"
out=$(python3 tests/profile-changed-check.py 2>&1) && ok || bad "$out"

step "prometheus gauges, fake server"
out=$(python3 tests/prom-check.py 2>&1) && ok || bad "$out"

step "CI pipelines status, fake server"
out=$(python3 tests/ci-check.py 2>&1) && ok || bad "$out"

step "QR codes read back"
out=$(python3 tests/qr-check.py 2>&1) && ok || bad "$(printf '%s\n' "$out" | tail -3)"

step "deck logs: crash, hang, trace"
out=$(python3 tests/log-check.py 2>&1) && ok || bad "$out"

step "--json on the read-only commands"
out=$(python3 tests/json-check.py 2>&1) && ok || bad "$out"

step "phosphor mcp: read-only, clean JSON-RPC"
out=$(python3 tests/mcp-check.py 2>&1) && ok || bad "$out"

step "panels.d: your own panels"
out=$(python3 tests/panels-check.py 2>&1) && ok || bad "$out"

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
out=$(python3 tests/containers-check.py 2>&1) && ok || bad "$out"
out=$(python3 tests/tui-check.py 2>&1) && ok || bad "$out"
out=$(python3 tests/security-check.py 2>&1) && ok || bad "$out"

step "digest: the day as one note, fenced for an assistant with no tools"
out=$(python3 tests/digest-check.py 2>&1) && ok || bad "$out"

step "read: a page as text, a web search, --ask fenced for an assistant with no tools"
out=$(python3 tests/read-check.py 2>&1) && ok || bad "$out"

step "glance: fleet, mentions, todos"
out=$(python3 tests/glance-check.py 2>&1) && ok || bad "$out"

step "phosphor review: MRs/PRs, safely"
out=$(python3 tests/review-check.py 2>&1) && ok || bad "$out"

step "phosphor screens: who's attached, kick one"
out=$(python3 tests/screens-check.py 2>&1) && ok || bad "$out"

step "phosphor mem: memory per tab and pane"
out=$(python3 tests/mem-check.py 2>&1) && ok || bad "$out"

step "animations slow down for a screen through a relay"
out=$(python3 tests/relay-check.py 2>&1) && ok || bad "$out"

step "fleet: CPU temperature, battery, SMART"
out=$(python3 tests/fleet-sensors-check.py 2>&1) && ok || bad "$out"

step "fleet: pending updates, counted in the background"
out=$(python3 tests/fleet-updates-check.py 2>&1) && ok || bad "$out"

step "fleet: a slow poll tags itself and logs"
out=$(python3 tests/fleet-timing-check.py 2>&1) && ok || bad "$out"

step "adjutant: fleet.json read once per change, not per tick"
out=$(python3 tests/adjutant-check.py 2>&1) && ok || bad "$out"

step "adjutant: stays inside its pane, 8 to 90 columns"
out=$(python3 tests/adjutant-width-check.py 2>&1) && ok || bad "$out"

step "usage: provider answers to bars, expired tokens stay offline"
out=$(python3 tests/usage-check.py 2>&1) && ok || bad "$out"

step "adjutant's bitmap face, GIF frames"
out=$(python3 tests/face-check.py 2>&1) && ok || bad "$out"

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

step "audit: a clone with no remote"
out=$(python3 tests/audit-check.py 2>&1) && ok || bad "$out"

[ $fail = 0 ] && printf '\nPASS: the fast checks\n' || printf '\nFAIL\n'
exit $fail
