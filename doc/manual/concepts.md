# Concepts

**The deck** is one terminal session (zellij) with your tabs, laid out once
from your profile. It keeps running when you leave; you come back to the same
tabs, scrollback and half-typed text.

**The brain** is the machine that keeps the deck running: it should stay on.
There is one. You get into it from anywhere with one word, `deck`: on the
brain itself, on another computer (`phosphor gen` writes it there), on a phone
(the phone kit writes it).

**The fleet** is your other machines. The deck watches them (CPU, RAM, disks,
containers, over ssh; nothing is installed on them) and shows their files as
folders under `~/fleet` on the brain: `~/fleet/<machine>/...`. Nothing is
copied or moved; you see the files where they are (rclone sftp mounts, or
links for the brain's own disks).

**Faces** are the screens you look at the deck from: a desktop, a tablet, a
phone, an e-ink reader. They hold no state; the deck lives on the brain.

**The profile** (`~/.config/phosphor/deck.toml`) describes all of it and is
the only source of truth. `phosphor gen` turns it into the real files.
