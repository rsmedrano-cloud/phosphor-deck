#!/bin/sh
# ─────────────────────────────────────────────────────────────
#  Phosphor Deck · installer
#
#    curl -fsSL .../install.sh | sh
#
#  Fetches the static binaries it needs, leaves the repo in
#  ~/phosphor-deck and points you to `phosphor doctor`. No root:
#  everything goes to ~/.local/bin. If something needs sudo, it
#  tells you and carries on without it.
# ─────────────────────────────────────────────────────────────
set -eu

REPO="${PHOSPHOR_REPO:-}"
# New installs go to a hidden folder; an install that already exists keeps
# its place, so updating never moves anything under your feet.
DEST="${PHOSPHOR_DEST:-}"
[ -n "$DEST" ] || { if [ -d "$HOME/phosphor-deck" ]; then DEST="$HOME/phosphor-deck"; else DEST="$HOME/.phosphor"; fi; }
BIN="$HOME/.local/bin"

g()  { printf '\033[38;2;51;255;68m%s\033[0m\n'  "$1"; }
a()  { printf '\033[38;2;255;176;0m%s\033[0m\n'  "$1"; }
r()  { printf '\033[38;2;255;51;68m%s\033[0m\n'  "$1"; }
d()  { printf '\033[38;2;107;154;118m%s\033[0m\n' "$1"; }
say() { printf '  %s\n' "$1"; }

need() { command -v "$1" >/dev/null 2>&1; }

arch_tag() {
  case "$(uname -m)" in
    x86_64|amd64) echo x86_64 ;;
    aarch64|arm64) echo aarch64 ;;
    armv7l|armv6l) echo arm ;;
    *) echo unsupported ;;
  esac
}

# GitHub hiccups (5xx) happen: retry, and prefer the fixed "latest/download"
# links, which don't use the API or its rate limit.
RETRY="--retry 3 --retry-delay 2"
curl --help all 2>/dev/null | grep -q -- --retry-all-errors && RETRY="$RETRY --retry-all-errors"

# fetch <binary> <direct url, or empty> <repo> <asset regex for the API>
fetch() {
  name="$1"; url="$2"; repo="$3"; pat="$4"
  if [ -x "$BIN/$name" ]; then say "· $name already there"; return 0; fi
  if [ -z "$url" ]; then
    url=$(curl -fsSL $RETRY "https://api.github.com/repos/$repo/releases/latest" 2>/dev/null \
          | grep browser_download_url | grep -E "$pat" | head -1 | cut -d\" -f4) || true
  fi
  if [ -z "${url:-}" ]; then a "  ! $name: no release found for $(arch_tag) (GitHub busy? run it again)"; return 1; fi
  tmp=$(mktemp -d); f="$tmp/$(basename "$url")"
  if ! curl -fsSL $RETRY -o "$f" "$url"; then
    # plan B: the same asset through the API's own link
    alt=""
    [ -n "$repo" ] && alt=$(curl -fsSL $RETRY "https://api.github.com/repos/$repo/releases/latest" 2>/dev/null \
          | grep browser_download_url | grep -F "$(basename "$url")" | head -1 | cut -d\" -f4) || true
    if [ -z "$alt" ] || ! curl -fsSL $RETRY -o "$f" "$alt"; then
      r "  ! $name: download failed (GitHub busy? run it again)"; rm -rf "$tmp"; return 1
    fi
  fi
  case "$f" in
    *.tar.gz|*.tgz)  tar xzf "$f" -C "$tmp" ;;
    *.tar.xz)        tar xJf "$f" -C "$tmp" ;;
    *.tar.bz2)       tar xjf "$f" -C "$tmp" ;;
    *.zip)           python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$f" "$tmp" ;;
    *)               cp "$f" "$tmp/$name" ;;
  esac
  found=$(find "$tmp" -type f \( -name "$name" -o -name "$name.exe" \) | head -1)
  [ -z "$found" ] && found=$(find "$tmp" -type f -size +100k ! -name "*.tar*" ! -name "*.zip" \
                              ! -name "*.md" ! -name "*.txt" | head -1)
  if [ -z "$found" ]; then r "  ! $name: couldn't find the binary"; rm -rf "$tmp"; return 1; fi
  install -Dm755 "$found" "$BIN/$name"; rm -rf "$tmp"
  g "  + $name"
}

printf '\n'
g "  PHOSPHOR DECK"
d "  installer — none of this needs root"
printf '\n'

A=$(arch_tag)
[ "$A" = unsupported ] && { r "  unsupported architecture: $(uname -m)"; exit 1; }
say "machine: $(uname -s) $(uname -m)  ->  $A"

for t in curl tar python3; do
  need "$t" || { r "  '$t' is missing and it's essential"; exit 1; }
done

mkdir -p "$BIN"

printf '\n'; d "── repo ──"
if [ -d "$DEST/.git" ]; then
  say "already in $DEST"
elif [ -n "$REPO" ]; then
  need git || { r "  git is missing"; exit 1; }
  git clone -q "$REPO" "$DEST" && g "  + cloned into $DEST"
else
  SRC=$(cd "$(dirname "$0")" 2>/dev/null && pwd)
  if [ -f "$SRC/phosphor" ] && [ "$SRC" != "$DEST" ]; then
    # run from a copy: install it, or update what's already there
    # never the .git: a copy with someone else's .git is a clone that lies
    if [ -e "$DEST" ]; then
      if need rsync; then rsync -a --delete --exclude .git --exclude .phosphor-source "$SRC"/ "$DEST"/
      else (cd "$SRC" && tar --exclude=.git -cf - .) | (cd "$DEST" && tar -xf -); fi
      g "  + updated $DEST from $SRC"
    else
      mkdir -p "$DEST" && (cd "$SRC" && tar --exclude=.git -cf - .) | (cd "$DEST" && tar -xf -) \
        && g "  + copied $SRC -> $DEST"
    fi
    # from a git clone: remember it, so update and the version check go back there
    if [ -d "$SRC/.git" ]; then
      printf '{"src": "%s", "commit": "%s"}\n' "$SRC" "$(git -C "$SRC" rev-parse HEAD 2>/dev/null)" \
        > "$DEST/.phosphor-source"
    fi
  elif [ -f "$DEST/phosphor" ]; then
    say "using $DEST"
  else
    say "no PHOSPHOR_REPO and no copy to use: run it from inside the repo"
  fi
fi

printf '\n'; d "── deck binaries ──"
case "$A" in
  x86_64)  M=x86_64;  GO=amd64; BT=x86_64-unknown-linux-musl;     GP=x86_64 ;;
  aarch64) M=aarch64; GO=arm64; BT=aarch64-unknown-linux-musl;    GP=arm64  ;;
  arm)     M=arm;     GO=arm;   BT=armv7-unknown-linux-musleabi;  GP=""     ;;
esac
GH=https://github.com
d64() { [ "$A" = arm ] && echo "" || echo "$1"; }   # 32-bit ARM: ask the API

fetch zellij "$(d64 $GH/zellij-org/zellij/releases/latest/download/zellij-$M-unknown-linux-musl.tar.gz)" \
      zellij-org/zellij "zellij-.*linux-musl.*\.tar\.gz" || true
fetch rclone "https://downloads.rclone.org/rclone-current-linux-$GO.zip" rclone/rclone "" || true
fetch yazi   "$(d64 $GH/sxyazi/yazi/releases/latest/download/yazi-$M-unknown-linux-musl.zip)" \
      sxyazi/yazi "yazi-.*linux-musl.*\.zip" || true
fetch gping  "$(d64 $GH/orf/gping/releases/latest/download/gping-Linux-musl-$GP.tar.gz)" \
      orf/gping "gping-Linux-.*\.tar\.gz" || true
fetch btop   "$GH/aristocratos/btop/releases/latest/download/btop-$BT.tar.gz" aristocratos/btop "" || true
fetch ctop   "" bcicen/ctop "ctop-.*-linux-$GO\"" || true

if [ ! -x "$BIN/zellij" ]; then
  r "  ! zellij couldn't be installed and the deck can't run without it."
  say "    Usually GitHub being busy: run install.sh again in a minute."
  exit 1
fi

printf '\n'; d "── commands ──"
if [ -f "$DEST/phosphor" ]; then
  ln -sf "$DEST/phosphor" "$BIN/phosphor"
  g "  + phosphor -> $DEST/phosphor"
else
  a "  ! couldn't find $DEST/phosphor"
fi
# one word to get in, from the first minute (gen keeps it updated later)
if [ -f "$DEST/phosphor" ]; then
  printf '#!/bin/sh\n# written by install.sh; phosphor gen keeps it updated\nexec "%s" attach\n' "$DEST/phosphor" > "$BIN/deck"
  chmod +x "$BIN/deck"
  g "  + deck  (one word to get into the deck)"
fi

# An existing deck: regenerate from its profile. Done here and not only in
# `phosphor update`, so even an update run by an older phosphor (which
# doesn't know it should) ends with files that match the new code.
P="${PHOSPHOR_PROFILE:-$HOME/.config/phosphor/deck.toml}"
if [ -f "$DEST/phosphor" ] && [ -f "$P" ]; then
  if "$DEST/phosphor" gen >/dev/null 2>&1; then g "  + regenerated from your profile (layouts, units, mounts)"
  else a "  ! phosphor gen failed: run it to see why"; fi
fi

printf '\n'; d "── done ──"
# an update only reaches the panes when the deck restarts
if "$BIN/zellij" list-sessions -n 2>/dev/null | grep -q .; then
  a "  ! the deck is running the code it started with"
  say "    phosphor restart   to run this version"
fi
# tab completion, once, for the shell you use
rc=~/.bashrc; line="source <(\"$BIN/phosphor\" completion bash)"
case "${SHELL:-}" in *zsh) rc=~/.zshrc; line="source <(\"$BIN/phosphor\" completion zsh)" ;; esac
if [ -w "$rc" ] || [ ! -e "$rc" ]; then
  grep -qs "phosphor\" completion" "$rc" || { printf '%s\n' "$line" >> "$rc"; g "  + tab completion in $(basename $rc)"; }
fi
say "the binaries are in $BIN"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) a "  ! $BIN isn't in your PATH"
     rc=~/.bashrc; case "${SHELL:-}" in *zsh) rc=~/.zshrc ;; esac
     say "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> $rc   (then open a new terminal)" ;;
esac
printf '\n'
# Straight into the wizard when there's a terminal to ask on (not with
# curl | sh in a script, not in the from-zero test).
if [ -f "$DEST/phosphor" ] && [ -z "${PHOSPHOR_NO_WIZARD:-}" ] && (: </dev/tty) 2>/dev/null; then
  printf '  set it up now? the wizard asks a few things, then the deck starts [Y/n] '
  read ans </dev/tty || ans=n
  case "$ans" in [nN]*) ;; *) exec "$BIN/phosphor" init </dev/tty ;; esac
fi
say "next:"
g  "    phosphor doctor"
d  "    checks this machine can run the deck"
g  "    phosphor init"
d  "    builds your profile with a few questions"
g  "    phosphor gen && phosphor up"
d  "    generates the deck and starts it"
g  "    deck"
d  "    and you're in (the same word from any machine)"
printf '\n'
