#!/bin/sh
# Install Phosphor from zero in a clean Debian 12 with systemd, the way a
# new user would, and check the deck comes up. Needs docker; the container
# is privileged (systemd inside needs it) and is removed at the end.
#
#   sh tests/from-zero.sh          run it (Debian 12)
#   DISTRO=ubuntu sh tests/from-zero.sh    or fedora, arch (tests/distros/)
#   KEEP=1 sh tests/from-zero.sh   leave the container up to poke around
set -u
cd "$(dirname "$0")/.."
DISTRO=${DISTRO:-debian}
if [ "$DISTRO" = debian ]; then FILE=Containerfile.test; C=phosphor-from-zero
else FILE=tests/distros/$DISTRO.Containerfile; C=phosphor-from-zero-$DISTRO; fi
[ -f "$FILE" ] || { echo "no such distro: $DISTRO (debian, or a file in tests/distros/)"; exit 2; }
X="docker exec -u deck -e HOME=/home/deck -e XDG_RUNTIME_DIR=/run/user/1000 $C"
step() { printf '\n\033[38;2;51;255;68m== %s\033[0m\n' "$1"; }
fail() { printf '\033[38;2;255;51;68mFAIL: %s\033[0m\n' "$1"; [ -n "${KEEP:-}" ] || docker rm -f $C >/dev/null 2>&1; exit 1; }

step "image ($FILE)"
docker build -q -t phosphor-test-$DISTRO -f "$FILE" . >/dev/null || fail "image build"
docker rm -f $C >/dev/null 2>&1
docker run -d --name $C --privileged --tmpfs /run --tmpfs /run/lock phosphor-test-$DISTRO >/dev/null || fail "container start"
for i in $(seq 1 30); do docker exec $C systemctl is-system-running 2>/dev/null | grep -qE 'running|degraded' && break; sleep 1; done

step "a copy of the repo somewhere else, as committed (git archive HEAD)"
git archive --format=tar HEAD | docker exec -i $C sh -c 'mkdir -p /home/deck/phosphor-src && tar -x -C /home/deck/phosphor-src && chown -R deck:deck /home/deck/phosphor-src'
docker exec $C loginctl enable-linger deck
for i in $(seq 1 20); do docker exec $C test -S /run/user/1000/bus && break; sleep 1; done

step "install.sh, run from the copy (it must install into ~/.phosphor)"
$X sh /home/deck/phosphor-src/install.sh || fail "install.sh"
$X test -f /home/deck/.phosphor/phosphor || fail "install.sh didn't put the code in ~/.phosphor"

step "phosphor doctor"
$X /home/deck/.local/bin/phosphor doctor; echo "(doctor exit $?)"

step "phosphor init (every question answered with its default)"
printf '\n\n\n\n\n\n\n\n\n' | docker exec -i -u deck -e HOME=/home/deck $C /home/deck/.local/bin/phosphor init || fail "init"

step "phosphor gen"
$X /home/deck/.local/bin/phosphor gen || fail "gen"

step "phosphor up: the deck comes up under systemd, enabled"
$X /home/deck/.local/bin/phosphor up || true
$X systemctl --user is-enabled deck.timer >/dev/null 2>&1 || fail "deck.timer isn't enabled"
for i in $(seq 1 20); do $X /home/deck/.local/bin/zellij list-sessions -n 2>/dev/null | grep -q '^deck ' && break; sleep 1; done
$X /home/deck/.local/bin/zellij list-sessions -n 2>/dev/null | grep '^deck ' || fail "no deck session"
tabs=$($X /home/deck/.local/bin/zellij -s deck action dump-layout 2>/dev/null | grep -c '    tab name=')
echo "tabs: $tabs"
[ "$tabs" -gt 0 ] || fail "the session has no tabs"

step "a newer copy updates the installed one"
docker exec -i $C sh -c 'echo "# marker-of-a-newer-version" >> /home/deck/phosphor-src/README.md'
upd=$($X sh /home/deck/phosphor-src/install.sh 2>&1) || fail "second install.sh"
$X grep -q "marker-of-a-newer-version" /home/deck/.phosphor/README.md || fail "the update didn't reach ~/.phosphor"
echo "$upd" | grep -q "updated /home/deck/.phosphor" || fail "it didn't say it updated the install"
echo "$upd" | grep -q "phosphor restart" || fail "it didn't tell you to restart the running deck"
echo "   updated in place, and it says to restart the running deck"

step "phosphor update FOLDER does the same in one command"
docker exec -i $C sh -c 'echo "# second-marker" >> /home/deck/phosphor-src/README.md'
$X /home/deck/.local/bin/phosphor update /home/deck/phosphor-src --no-restart > /dev/null 2>&1 || fail "phosphor update"
$X grep -q "second-marker" /home/deck/.phosphor/README.md || fail "phosphor update didn't bring the code"
$X test -x /home/deck/.local/bin/deck || fail "the deck command is missing"
echo "   update brought the code, and the deck command is there"

step "curl | sh on a clean machine (no local copy, no PHOSPHOR_REPO): clones the public repo"
out=$(docker exec -i -u deck -e HOME=/home/deck -e PHOSPHOR_DEST=/home/deck/clean-install \
      -e PHOSPHOR_PROFILE=/home/deck/no-such-profile.toml -e PHOSPHOR_NO_WIZARD=1 $C sh < install.sh 2>&1) \
      || fail "curl | sh from a clean machine"
$X test -d /home/deck/clean-install/.git || fail "it didn't clone the public repo"
$X test -f /home/deck/clean-install/phosphor || fail "the clone has no phosphor command"
echo "$out" | grep -q "cloning the public repo" || fail "it didn't say it was cloning the public repo"
echo "   cloned the public mirror and left a working phosphor command"

printf '\n\033[38;2;51;255;68mPASS\033[0m: installed from zero, deck up with %s tabs\n' "$tabs"
[ -n "${KEEP:-}" ] && echo "container left up: docker exec -it -u deck $C bash" || docker rm -f $C >/dev/null
