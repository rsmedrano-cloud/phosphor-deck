---
title: Patterns
sidebar:
  order: 3
---


Not new commands -- ways to put the ones you already have together. What to
reach for, and when.

## Which shape

`phosphor init` asks once; here's the reasoning behind each answer.

- **homelab** (the default): you have, or expect to have, more than one
  machine. You want the fleet panel, the file browser and the monitoring
  from day one. Most people start here.
- **revived**: one machine, brain and only screen at once -- often older or
  weaker hardware you're giving a second life as the brain (see concepts:
  that's the whole idea of reusing what you have). Skips CLOUD, the
  heaviest tab (three TUIs at once), because there's no fleet to browse yet
  and the machine may not have the headroom to spare. Add CLOUD back later
  with `phosphor keep` once you do have somewhere to point yazi.
- **dev**: you already know you'll spend most of your time with an AI
  assistant. Puts a two-assistant tab first (Alt-1) instead of last.

None of this is permanent. `phosphor recipe` adds what a shape left out;
`phosphor tabs` reorders; Alt-r changes any tab by hand.

## Growing it

Three ways to add a tab, from least to most committed:

1. **`phosphor recipe NAME`** -- a bundle Phosphor ships (`homelab`, `dev`,
   `bubble`, `workbench`). Fastest, and undoing it is `phosphor tabs`, `f`.
2. **A `tabs.d/*.toml` file of your own** -- same mechanism recipes use, but
   the content is yours: something you built once and want on every deck
   you run, or a tab a friend sent you as a file. Drop it in, `phosphor
   gen`. See profile.
3. **`phosphor keep`** -- you arranged a tab by hand (split it, swapped a
   program in) and want to keep it. This writes straight into your
   profile: the most permanent of the three, and the only one Alt-r's
   **s** and `phosphor keep` will ever touch again.

Recipes and tabs.d are how you move a tab *to* a deck. `phosphor keep` is
how you turn something you built live *into* one.

## Moving to a new brain

Nothing about a deck is tied to the machine it runs on except the machine
itself. To move the whole thing:

1. On the new machine: `sh install.sh` (see install), stopping before
   `phosphor init` -- you're not building a new profile, you're bringing yours.
2. Copy over, from the old brain: `~/.config/phosphor/` (your profile and
   `apps.toml`, `tabs.d/`), and your notebook -- `~/.local/share/phosphor/notes.md`
   and `-archive.md`, unless `[notes] folder` already points it at a
   synced vault, in which case it's already there.
3. `phosphor gen && phosphor up` on the new machine. Hosts with `local =
   true` in your profile describe the *old* brain: edit that block (or run
   `phosphor setup` and let it walk you through the new machine's own disks)
   before your first `gen` there.
4. Point every screen's `deck` command at the new brain: rerun `phosphor
   phone` / `phosphor screen` from it for each one (see phones).

Nothing is deleted from the old machine by any of this -- `phosphor down`
there when you're done, by hand, once you've confirmed the new one works.

## Sharing one tab

The same idea as moving a whole deck, scaled down: put the `[[tabs]]` block
in a file, hand the file over. `phosphor keep --dry-run` prints a tab's
block without writing it, ready to paste into a `tabs.d/*.toml` -- yours to
keep, or someone else's to drop in.

## Backing out

Every write phosphor's tools make to your profile keeps a `deck.toml.bak`
first (the *previous* version -- only one deep, not a history). `phosphor
gen --dry-run` shows what a change would write without writing it. Nothing
here replaces real version control: a profile is one text file, so `git
init ~/.config/phosphor` (kept out of any repo you publish, see privacy) is
a real history if you want one.
