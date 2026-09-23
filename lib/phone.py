"""phosphor phone - a phone or tablet one tap away from the deck.
Project Phosphor Deck.

On the brain it prints what to type on the phone. Piped (that's how the
phone asks for it: `ssh you@brain '~/.local/bin/phosphor phone' | sh`) it
prints a Termux script made for this deck: a key so the password is asked
one last time, the `deck` command, a Termux:Widget icon and the extra keys
that make touch comfortable (KEYBOARD brings the keyboard back, EDIT, ZOOM, EXIT).

It uses plain ssh on purpose: mosh doesn't carry the mouse, so no touch.
"""
import getpass, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf, mesh

HOME = os.path.expanduser("~")
KEYS = ('[[{key: KEYBOARD, popup: DRAWER}, ESC, TAB, CTRL, ALT, UP, DOWN, '
        '{macro: "ALT r", display: "EDIT"}, {macro: "ALT z", display: "ZOOM"}, {macro: "ALT x", display: "EXIT"}]]')
# what earlier kits wrote: a phone that still has exactly one of these gets the new keys
OLD_KEYS = ['[[{key: KEYBOARD, popup: DRAWER}, ESC, TAB, CTRL, ALT, UP, DOWN, '
            '{macro: "ALT z", display: "ZOOM"}, {macro: "ALT x", display: "EXIT"}]]',
            '[[{key: KEYBOARD, popup: DRAWER}, ESC, TAB, CTRL, ALT, UP, DOWN, '
            '{macro: "ALT e", display: "EDIT"}, {macro: "ALT z", display: "ZOOM"}, {macro: "ALT x", display: "EXIT"}]]']

SCRIPT = r"""#!/data/data/com.termux/files/usr/bin/sh
# Phosphor Deck · phone kit for Termux, generated on the brain by
# `phosphor phone`. Safe to run again: it only adds what's missing.
T='@T@'
Z='@Z@'
S='@S@'
# the brain's own launcher: a renamed session can't break this
C='@C@'
say() { printf '\033[38;2;51;255;68m» %s\033[0m\n' "$1"; }

if [ -z "$PREFIX" ] || [ ! -d /data/data/com.termux ]; then
  echo "This kit is for Termux on Android. From anywhere else:"
  echo "  ssh -t $T $C"
  exit 1
fi
command -v ssh >/dev/null 2>&1 || pkg install -y openssh

# 1. a key, so the deck never asks for a password again
if [ ! -f ~/.ssh/id_ed25519 ]; then
  say "creating this phone's ssh key"
  mkdir -p ~/.ssh && ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519
fi
if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$T" true 2>/dev/null; then
  say "the brain asks for your password one last time"
  cat ~/.ssh/id_ed25519.pub | ssh "$T" 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys' \
    || { echo "couldn't copy the key; run this kit again"; exit 1; }
fi

# 2. the deck command
# ssh exits 0 on detach (EXIT key, Ctrl-q) and non-zero when the link drops
# (the phone slept, the network changed): then it reconnects by itself.
cat > "$PREFIX/bin/deck" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
[ -n "\$ZELLIJ" ] && { echo "already inside a zellij session"; exit 1; }
while :; do
  ssh -t -o ServerAliveInterval=15 -o ServerAliveCountMax=2 $T "$C 2>/dev/null || $Z attach $S" && break
  echo "[ lost the deck, reconnecting in 3s. Ctrl-C to stop ]"; sleep 3
done
EOF
chmod +x "$PREFIX/bin/deck"
say "command ready: deck"

# 3. a home-screen icon, through Termux:Widget
mkdir -p ~/.shortcuts
printf '#!/data/data/com.termux/files/usr/bin/sh\nexec deck\n' > ~/.shortcuts/deck
chmod +x ~/.shortcuts/deck

# 4. extra keys: taps go to the deck, so the keyboard needs its own key
P=~/.termux/termux.properties
mkdir -p ~/.termux && touch "$P"
for old in @OLDKEYS@; do
  if grep -qxF "extra-keys = $old" "$P"; then
    grep -vxF "extra-keys = $old" "$P" > "$P.new"; mv "$P.new" "$P"   # grep -v fails when nothing is left
  fi
done
if grep -qxF 'extra-keys = @KEYS@' "$P"; then
  say "extra keys: KEYBOARD, EDIT, ZOOM, EXIT"
elif grep -q '^[[:space:]]*extra-keys' "$P"; then
  say "you already have extra-keys; for the deck's, replace them with:"
  echo '  extra-keys = @KEYS@'
else
  echo 'extra-keys = @KEYS@' >> "$P"
  termux-reload-settings 2>/dev/null || true
  say "extra keys added: KEYBOARD, EDIT, ZOOM, EXIT"
fi

say "done. Type: deck"
echo "  For the icon: install Termux:Widget from the same place you got"
echo "  Termux (F-Droid or GitHub), let Termux 'display over other apps',"
echo "  and add the widget's 'deck' shortcut to your home screen."
"""

POSIX_SCRIPT = r"""#!/bin/sh
# Phosphor Deck · screen kit, generated on the brain by `phosphor screen`.
# It leaves one command here: deck. Safe to run again.
T='@T@'
C='@C@'
B="$HOME/.local/bin"
say() { printf '\033[38;2;51;255;68m» %s\033[0m\n' "$1"; }

if [ -n "$PREFIX" ] && [ -d /data/data/com.termux ]; then
  echo "This is Termux: use the phone kit instead:"
  echo "  ssh @T@ '~/.local/bin/phosphor phone' | sh"
  exit 1
fi
command -v ssh >/dev/null 2>&1 || { echo "no ssh here: install openssh first"; exit 1; }

# 1. a key, so the deck never asks for a password again
if [ ! -f ~/.ssh/id_ed25519 ] && [ ! -f ~/.ssh/id_rsa ]; then
  say "creating this machine's ssh key"
  mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519
fi
if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$T" true 2>/dev/null; then
  say "the brain asks for your password one last time"
  if command -v ssh-copy-id >/dev/null 2>&1; then
    ssh-copy-id "$T" || { echo "couldn't copy the key; run this again"; exit 1; }
  else
    cat ~/.ssh/id_ed25519.pub | ssh "$T" 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys' \
      || { echo "couldn't copy the key; run this again"; exit 1; }
  fi
fi

# 2. the deck command
# ssh exits 0 when you detach and non-zero when the link drops or the deck
# restarts: then it goes back in by itself.
mkdir -p "$B"
cat > "$B/deck" <<EOF
#!/bin/sh
[ -n "\$ZELLIJ" ] && { echo "already inside a zellij session"; exit 1; }
while :; do
  ssh -t -o ServerAliveInterval=15 -o ServerAliveCountMax=2 $T "$C" && break
  echo "[ lost the deck, reconnecting in 3s. Ctrl-C to stop ]"; sleep 3
done
EOF
chmod +x "$B/deck"
say "command ready: deck"
case ":$PATH:" in
  *":$B:"*) ;;
  *) echo "  $B isn't in your PATH yet:"
     echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc   (then a new terminal)" ;;
esac
say "done. Type: deck"
"""

def screen_script(prof):
    return POSIX_SCRIPT.replace("@T@", target(prof)).replace("@C@", launcher(prof))

def zellij_path():
    p = os.path.join(HOME, ".local/bin/zellij")
    return p if os.path.exists(p) else (shutil.which("zellij") or "zellij")

def phosphor_cmd():
    """How the phone calls phosphor over ssh: no login shell, so no PATH."""
    if os.path.exists(os.path.join(HOME, ".local/bin/phosphor")):
        return "~/.local/bin/phosphor"
    r = os.path.join(REPO, "phosphor")
    return "~/" + os.path.relpath(r, HOME) if r.startswith(HOME + "/") else r

def brain(prof):
    return next((h for h in (prof or {}).get("hosts", []) if h.get("role") == "brain"), {}) or {}

def address(prof):
    """Where the phone reaches the brain. Asked over ssh, the answer is the
    address the phone just used: it's known to work from there."""
    sc = os.environ.get("SSH_CONNECTION", "").split()
    if len(sc) == 4:
        return sc[2]
    return brain(prof).get("name") or os.uname().nodename

def launcher(prof):
    """The brain's `deck`, by path: a plain `ssh host cmd` gets no login
    shell, so ~/.local/bin isn't in PATH and a bare `deck` isn't found."""
    return "~/.local/bin/" + ((prof or {}).get("deck") or {}).get("command", "deck")

def target(prof):
    return "%s@%s" % (getpass.getuser(), address(prof))    # not $USER: may be unset

def keys_row(prof):
    """The extra keys, with EDIT, ZOOM and EXIT sending the keys in [keys]."""
    import shortcuts
    k = shortcuts.current(prof)
    row = ['{key: KEYBOARD, popup: DRAWER}', 'ESC', 'TAB', 'CTRL', 'ALT', 'UP', 'DOWN']
    for action, label in (("edit", "EDIT"), ("zoom", "ZOOM"), ("leave", "EXIT")):
        if k[action]:
            row.append('{macro: "%s", display: "%s"}' % (shortcuts.phone_macro(k[action]), label))
    return "[[" + ", ".join(row) + "]]"

def script(prof):
    sess = ((prof or {}).get("deck") or {}).get("session", "deck")
    cmd = launcher(prof)
    return (SCRIPT.replace("@T@", target(prof)).replace("@Z@", zellij_path())
                  .replace("@S@", sess).replace("@C@", cmd).replace("@OLDKEYS@", " ".join("'%s'" % k for k in OLD_KEYS)).replace("@KEYS@", keys_row(prof)))

def qr_lines(text, w):
    """The line as a QR, when the pane is wide enough for it to be scanned."""
    try:
        import qr
    except ImportError:
        return []
    need = qr.width(text)
    if not need or need > w:
        return []
    m = qr.encode(text)
    return qr.render(m) if m else []

def instructions(prof):
    b, t = brain(prof), target(prof)
    cmd = launcher(prof)
    line = "ssh %s '%s phone' | sh" % (t, phosphor_cmd())
    pc = "ssh %s '%s screen' | sh" % (t, phosphor_cmd())
    w = width()
    print("\n" + rule("add a screen"))
    print("  " + DIM + "On this machine you're already there: %s." % os.path.basename(cmd) + RST)
    print()
    print("  " + FG + "A phone or tablet" + RST + DIM + " (Android + Termux):" + RST)
    print("    " + PH + "pkg install -y openssh" + RST)
    print("    " + PH + line + RST)
    q = qr_lines(line, w)
    if q:
        print("  " + DIM + "or scan this with the phone's camera and paste it in Termux:" + RST)
        for l in q:
            print("  " + l)
    else:
        print("  " + DIM + "Alt-z (zoom) turns that line into a QR you can scan." + RST)
    print("  " + DIM + "It makes the phone's key (your password, one last time), the deck" + RST)
    print("  " + DIM + "command, a home-screen icon and the extra keys. Plain ssh: touch works." + RST)
    print()
    print("  " + FG + "Another computer" + RST + DIM + " (Linux, macOS, WSL — an old laptop is a fine screen):" + RST)
    print("    " + PH + pc + RST)
    print("  " + DIM + "The same without Termux: a key, and a `deck` command in ~/.local/bin." + RST)
    print()
    print("  " + FG + "Anything that only has ssh" + RST
          + DIM + " (an old terminal, an ssh app, a pocket one):" + RST)
    print("    " + PH + "ssh -t %s %s" % (t, cmd) + RST)
    kind, control = mesh.current(prof)
    if kind == "tailscale":
        print("  " + DIM + "Phones reach the brain through the Tailscale app, in the same tailnet." + RST)
    elif kind == "headscale":
        print("  " + DIM + "The screen needs the Tailscale app logged into your headscale server" + RST)
        print("  " + DIM + "(the app's custom/alternate login server): " + RST + PH + (control or "?") + RST)
    if b.get("ip") and b.get("ip") != address(prof):
        print("  " + DIM + "If '%s' doesn't resolve from there, use %s instead." % (address(prof), b["ip"]) + RST)
    print()

def main():
    prof, _ = deckconf.load()
    argv = sys.argv[1:]
    posix = "--screen" in argv
    if "--qr" in argv:
        line = "ssh %s '%s %s' | sh" % (target(prof), phosphor_cmd(), "screen" if posix else "phone")
        q = qr_lines(line, width())
        print("\n  " + PH + line + RST + "\n")
        for l in q:
            print("  " + l)
        if not q:
            print("  " + DIM + "the pane is too narrow for the QR: widen it or zoom (Alt-z)" + RST)
        return 0
    if "--script" in argv or not sys.stdout.isatty():
        import panel
        panel.mark("phone")
        sys.stdout.write(screen_script(prof) if posix else script(prof))
        return 0
    instructions(prof)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
