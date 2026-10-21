#!/bin/sh
# The fast checks: under a minute, no docker, no network. What CI runs on every
# push and merge request, and what a release refuses to skip.
#
#     sh tests/check.sh          one step per core, reported in order
#     sh tests/check.sh -j1      one at a time (or -jN)
#
# Each step is its own process with its own throwaway HOME, zellij socket
# dir and ports, so they run side by side; one that ever shares a resource
# (a fixed path, a port) goes inside a single step, run in a row.
# The slow ones (a clean install in a systemd container) are
# tests/from-zero.sh and tests/tester-sim.py.
cd "$(dirname "$0")/.." || exit 1
# a caller's own data/cache/notebook (tests/audit.py sets them) must not leak into tests
unset PHOSPHOR_DATA PHOSPHOR_CACHE PHOSPHOR_NOTES
jobs=$(nproc 2>/dev/null || echo 4)
case "$1" in -j[1-9]*) jobs=${1#-j} ;; "") ;; *) echo "usage: sh tests/check.sh [-jN]" >&2; exit 2 ;; esac
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
trap 'exit 130' INT TERM

# The steps that aren't one python file
shells_parse() { for f in install.sh tests/*.sh; do sh -n "$f" 2>&1 || echo "$f"; done | grep . && return 1 || return 0; }
failed_clone() {
    # a git whose clone fails and a curl that never reaches the network (CI's image has neither)
    out=$(t=$(mktemp -d) && mkdir "$t/bin" && printf '#!/bin/sh\nexit 128\n' > "$t/bin/git" &&
          printf '#!/bin/sh\nexit 1\n' > "$t/bin/curl" && chmod +x "$t/bin/git" "$t/bin/curl" &&
          PATH="$t/bin:$PATH" HOME=$t PHOSPHOR_DEST=$t/dest PHOSPHOR_REPO=$t/no-such-repo \
          PHOSPHOR_NO_WIZARD=1 sh install.sh 2>&1; echo "rc=$?"; rm -rf "$t")
    case "$out" in *"couldn't clone"*rc=1) ;; *) printf '%s\n' "$out"; return 1 ;; esac
}
qr() { out=$(python3 tests/qr-check.py 2>&1) || { printf '%s\n' "$out" | tail -3; return 1; }; }
release_notes() { v=$(cat VERSION); grep -q "^## $v" CHANGELOG.md || { echo "CHANGELOG.md has no '## $v' entry"; return 1; }; }

steps() {
check "python compiles"                    python3 -m py_compile phosphor lib/*.py tests/*.py
check "no function shadows the module's"   python3 tests/shadow-check.py
check "every name used is defined"         python3 tests/names-check.py
check "flaky tests: a second run, counted, only for the listed" python3 tests/flaky-check.py
check "shell scripts parse"                shells_parse
check "install: a failed clone stops it"   failed_clone
check "the docs name every command"        python3 tests/docs-check.py
check "AGENTS.md matches the manual"       python3 phosphor docs --check
check "help: an image, not raw markdown"   python3 tests/docs-render-check.py
check "a live tab reads back"              python3 tests/keep-check.py
check "a frozen program is closed"         python3 tests/hang-check.py
check "a touch screen is never stuck"      python3 tests/touch-check.py
check "--reconnect backs off instead of hammering a dead link" python3 tests/run-reconnect-check.py
check "welcome invites, not a key list"    python3 tests/welcome-check.py
check "a deck for each kind of screen"     python3 tests/screen-kinds-check.py
check "setup: a deck of its own, or not"   python3 tests/screen-setup-check.py
check "a warm-up on the way in, skippable" python3 tests/splash-check.py
check "panels that draw don't echo keys"   python3 tests/passive-input-check.py
check "notes: a vault folder, migrated"    python3 tests/notes-vault-check.py
check "tabs.d: shared tabs, read-only"     python3 tests/tabs-d-check.py
check "recipes, and wizard shapes"         python3 tests/recipe-check.py
check "wizard: never offers itself back as a fleet candidate" python3 tests/wizard-dedup-check.py
check "fleet: keys over a card (--live in CI)" python3 tests/fleet-keys-check.py
check "fleet: the last 24 hours, h over a card" python3 tests/fleet-history-check.py
check "text from outside is text: no escapes reach a screen" python3 tests/sanitize-check.py
check "your apps, the store opens them"    python3 tests/apps-check.py
check "tabs forgotten and moved, as text"  python3 tests/tabs-check.py
check "your keys, and what gen may touch"  python3 tests/keys-check.py
check "a profile write's undo depth: .bak, .bak.2, .bak.3" python3 tests/backup-check.py
check "the profile is written whole, checked, and never over a newer write" python3 tests/profile-write-check.py
check "an older profile migrates"          python3 tests/migrate-check.py
check "a new default in a shape has its offer" python3 tests/shapes-check.py
check "a backup holds its own files, and restore takes only those" python3 tests/brain-backup-check.py
check "one way to run zellij, sh and ssh"  python3 tests/proc-check.py
check "a misspelled profile key is said"   python3 tests/profile-schema-check.py
check "one set of limits for every panel, [alerts]" python3 tests/limits-check.py
check "zellij pinned in one place"         python3 tests/zellij-pin-check.py
check "the reaper takes only the deck"     python3 tests/reap-check.py
check "notes change only their own entry"  python3 tests/notes-check.py
check "channels follow their branch"       python3 tests/update-check.py
check "update cache stays honest"          python3 tests/version-check.py
check "a workspace, folder to tab"         python3 tests/workspace-check.py
check "a workspace's tab marks when NOTES.md changes" python3 tests/workspace-notes-watch-check.py
check "ask picks an assistant, no tab"     python3 tests/ask-check.py
check "commands.json: one definition for help, completion and the menu" python3 tests/commands-manifest-check.py
check "doors: every public command has a card, a door in the deck" python3 tests/doors-check.py
check "an unknown flag is a usage error; no call of phosphor's own is one" python3 tests/argv-check.py
check "deprecated: warns on stderr, goes when it said it would" python3 tests/deprecations-check.py
check "web on: never restarts unattended without --yes" python3 tests/web-check.py
check "new --here: refuses with nobody attached" python3 tests/newtab-attach-check.py
check "new: an assistant asks which folder it starts in" python3 tests/newtab-folder-check.py
check "new: / searches tabs, the menu, workspaces, tools, commands" python3 tests/search-check.py
check "commands: category/leaf picker, only safe ones auto-run" python3 tests/commands-menu-check.py
check "commands ask instead of quitting"   python3 tests/asks-check.py
check "panels you act from: services and workspace" python3 tests/act-check.py
check "theme: preview per palette, picker writes nothing until Enter" python3 tests/theme-check.py
check "tail: journalctl/docker/podman through phosphor run --reconnect" python3 tests/tail-check.py
check "--help explains, never runs"        python3 tests/help-flag-check.py
check "triage: snapshot over ssh, piped into phosphor ask" python3 tests/triage-check.py
check "broadcast: asks first, then every host" python3 tests/broadcast-check.py
check "panel: DECK tab actions (host pickers; q, Esc, Enter go back from every one)" python3 tests/panel-actions-check.py
check "panel: cards reflow with the width" python3 tests/panel-grid-check.py
check "card: the widget, its value, line and tap" python3 tests/card-check.py
check "dash: a dashboard of your own, its gallery, kept in its tab" python3 tests/dash-check.py
check "build: the pickers' first-time hint (--live in CI: the whole path)" python3 tests/build-check.py
check "zoom: a tap on a title, a summary in a short pane" python3 tests/zoom-check.py
check "Esc steps back, q closes, ? lists the keys, on every screen" python3 tests/exit-keys-check.py
check "did you know: the DECK tab's tip line" python3 tests/tips-check.py
check "every card's tap comes back: by itself or on Esc" python3 tests/card-exits-check.py
check "the other cards: Esc backs out, a y/n guards, the right command runs" python3 tests/card-taps-check.py
check "the docs' pictures: there, described, none left over" python3 tests/images-check.py
check "state: every card with a state finds it in the real --json" python3 tests/state-json-check.py
check "a hand-edited profile says so (DECK tab f, doctor)" python3 tests/profile-changed-check.py
check "prometheus gauges, fake server"     python3 tests/prom-check.py
check "CI pipelines status, fake server"   python3 tests/ci-check.py
check "QR codes read back"                 qr
check "deck logs: crash, hang, trace"      python3 tests/log-check.py
check "stats: commands counted locally"    python3 tests/stats-check.py
check "--json on the read-only commands"   python3 tests/json-check.py
check "phosphor mcp: read-only, clean JSON-RPC" python3 tests/mcp-check.py
check "panels.d: your own panels"          python3 tests/panels-check.py
check "TTS notifications and voices"       python3 tests/tts-check.py
check "push notifications (ntfy)"          python3 tests/push-check.py
check "notify: --no-event, --fleet-alert, PHOSPHOR_CACHE" python3 tests/notify-check.py
check "fleet alerts: down/back, debounced, cooled down" python3 tests/fleet-alert-check.py
check "snooze: quiet everywhere, expires, worse wakes it" python3 tests/snooze-check.py
check "while you were away: since you left, nothing when nothing" python3 tests/away-check.py
check "a mention pushes and speaks too"    python3 tests/mentions-push-check.py
check "demo mode: fake fleet and notes"    python3 tests/demo-check.py
check "every tool follows theme"           python3 tests/tool-colors-check.py
check "yazi: c t clips the file"           python3 tests/yazi-keymap-check.py
check "send: one file, one link, gone"     python3 tests/send-check.py
check "receive: the other way, one upload, gone" python3 tests/receive-check.py
check "services: units match what gen writes" python3 tests/services-check.py
check "the deck's panes get your PATH"  python3 tests/deck-path-check.py
check "containers: listing parses, host names stay out of a shell" python3 tests/containers-check.py
check "ListPanel: keys and taps with no terminal" python3 tests/tui-check.py
check "security: who reaches a file, secrets, sshd" python3 tests/security-check.py
check "digest: the day as one note, fenced for an assistant with no tools" python3 tests/digest-check.py
check "read: a page as text, a web search, --ask fenced for an assistant with no tools" python3 tests/read-check.py
check "glance: fleet, mentions, todos"     python3 tests/glance-check.py
check "mirror: one pane for a slow screen"  python3 tests/mirror-check.py
check "solaros: the switch, pairing, the panel menu" python3 tests/solaros-check.py
check "phosphor review: MRs/PRs, safely"   python3 tests/review-check.py
check "phosphor screens: who's attached, kick one" python3 tests/screens-check.py
check "phosphor mem: memory per tab and pane" python3 tests/mem-check.py
check "animations slow down for a screen through a relay" python3 tests/relay-check.py
check "fleet: CPU temperature, battery, SMART" python3 tests/fleet-sensors-check.py
check "fleet: pending updates, counted in the background" python3 tests/fleet-updates-check.py
check "fleet: a slow poll tags itself and logs" python3 tests/fleet-timing-check.py
check "adjutant: fleet.json read once per change, not per tick" python3 tests/adjutant-check.py
check "adjutant: stays inside its pane, 8 to 90 columns" python3 tests/adjutant-width-check.py
check "usage: provider answers to bars, expired tokens stay offline" python3 tests/usage-check.py
check "adjutant's bitmap face, GIF frames" python3 tests/face-check.py
check "fleet: rust poller picked when installed, else python" python3 tests/fleet-poller-check.py
check "fleet: a zombie ~/fleet mount self-heals" python3 tests/mount-zombie-check.py
check "hotswap: which code changes are safe to refresh live" python3 tests/hotswap-check.py
check "restart: poll instead of blind sleeps, same worst case" python3 tests/restart-check.py
check "restart: nothing new until the old deck is gone" python3 tests/down-gate-check.py
check "site/ (GitHub Pages) matches the manual" python3 tests/site-check.py
check "VERSION has release notes"          release_notes
check "audit: a clone with no remote"      python3 tests/audit-check.py
}

# 1. Run them: $jobs slots in a pipe; a step takes one to start and gives it
# back when it ends. Output and exit code land in $T/N.out and $T/N.rc.
mkfifo "$T/slots" && exec 3<>"$T/slots" || exit 1
i=0; while [ $i -lt "$jobs" ]; do echo >&3; i=$((i+1)); done
n=0
# sh starts a job with & with Ctrl-C ignored, and no trap undoes that; a
# python that starts that way never raises KeyboardInterrupt, which the
# tests that press Ctrl-C need: python gives the default back, then runs it.
sigint() { python3 -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])' "$@"; }
check() {
    n=$((n+1)); label=$1; shift
    # through the quarantine: a test in tests/flaky.json gets a second run
    case $1 in python3) set -- sigint python3 tests/flaky.py "$@" ;; esac
    read -r _ <&3
    ( "$@" > "$T/$n.out" 2>&1 < /dev/null 3>&-; echo $? > "$T/$n.rc.tmp"; mv "$T/$n.rc.tmp" "$T/$n.rc"; echo >&3 ) &
}
( steps; wait ) &
launcher=$!

# 2. Report them, in order, as each one ends
fail=0
n=0
check() {
    n=$((n+1)); printf '  %-34s' "$1"
    while [ ! -f "$T/$n.rc" ]; do sleep 0.1; done
    if [ "$(cat "$T/$n.rc")" = 0 ]; then
        if grep -q '^FLAKY ' "$T/$n.out"; then printf 'ok, on its second run\n'; grep '^FLAKY ' "$T/$n.out" | sed 's/^/      /'
        else printf 'ok\n'; fi
    else printf 'FAIL\n'; [ -s "$T/$n.out" ] && sed 's/^/      /' "$T/$n.out"; fail=1; fi
}
steps
wait $launcher

[ $fail = 0 ] && printf '\nPASS: the fast checks\n' || printf '\nFAIL\n'
exit $fail
