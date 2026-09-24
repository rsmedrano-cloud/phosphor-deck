---
title: Clipboard
sidebar:
  order: 12
---


Select text in the deck (drag with a finger or the mouse) and it lands on the
clipboard of every device looking at the deck, phone and PC at once (OSC 52).
Pasting into the deck works as usual (Termux: long-press → Paste; PC:
Ctrl+Shift+V).

    phosphor clip notes.txt          # a file onto that clipboard
    git log -1 | phosphor clip       # a pipe
    phosphor clip --save out.txt     # paste, then Ctrl-D: into a file

Up to ~70 KB: Termux drops more than ~100 KB (Android's limit). Move bigger
things through `~/fleet`. Some desktop terminals don't support OSC 52.

**Middle-click paste (X11/Wayland primary selection) doesn't come from this:**
`mouse_mode` (zellij's own setting, on by default so drag-select and pane
resizing work) means your terminal hands every mouse event to zellij instead
of handling selection itself -- the same reason vim or tmux with their own
mouse mode on don't feed your desktop's primary selection either. Your
terminal emulator's own bypass still works underneath zellij: hold **Shift**
while you drag (Alacritty, kitty, foot, GNOME Terminal, xterm, Windows
Terminal...; **Option** in iTerm2) to make a plain selection your terminal
handles itself, which does land in the primary selection -- middle-click
pastes it, same as any other program. Nothing to turn on, and nothing
Phosphor could add on top: primary selection lives in your desktop's X11 or
Wayland session, one machine at a time, independent of the clipboard OSC 52
already bridges across every screen looking at the deck.

**From yazi:** `c` already opens a chord that copies the path, the URL, the
filename... two more join it, on the hovered file, no shell tab needed:
`c` `t` for `phosphor clip` (its contents, onto every screen's clipboard)
and `c` `s` for `phosphor send` (the file itself -- see below). `phosphor
gen` writes both into `~/.config/yazi/keymap.toml`; a `keymap.toml` of your
own is left alone, same as `theme.toml`.

The paste side is always the plain Android/desktop clipboard, not a
Phosphor-specific spot: on the phone it's a long-press → Paste in whatever
app you're pointed at, not something you'll find "inside" Phosphor. And it's
live, not stored: the screen you're pasting into has to be attached to the
deck at the moment you copy, same as the drag-select above.

## A real file

The clipboard only ever moves text -- a 70 KB cap, and even under that, what
lands on your phone is pasted text, not a file your gallery or a "share to"
sheet can open. For an actual file, of any size or type, saved as itself:

    phosphor send notes.md               # one real file
    phosphor send report.pdf --timeout 60

It opens a one-time link on your tailnet (or your LAN, without one) behind a
random token, prints it with a QR to scan, and shuts itself down the moment
someone downloads it -- or after the timeout (default 180s) if nobody does.
Nothing is kept running, nothing is stored anywhere: it's the deck-native
version of the throwaway "open a port, send the file, close it" script
you'd otherwise reach for by hand. Scan the QR from your phone's camera
(or `curl` the link) and it saves as a real file, e.g. to Downloads.
The link is also printed as a clickable hyperlink (OSC 8: a tap or click opens it,
if your terminal supports it) and copied to the clipboard of every screen looking
at the deck, so on a phone it's paste into the browser, no scanning or retyping.
From yazi, `c` `s` does the same to the hovered file.
