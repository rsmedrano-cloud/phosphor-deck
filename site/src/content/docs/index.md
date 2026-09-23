---
title: Phosphor Deck
description: One terminal session as your whole command room.
template: splash
hero:
  tagline: One terminal session (zellij) as your whole command room --
    your machines, your notebook, your chat, from any screen.
  image:
    file: ../../assets/logo.svg
  actions:
    - text: Read the manual
      link: manual/concepts/
      icon: right-arrow
    - text: GitHub
      link: https://github.com/rsmedrano-cloud/phosphor-deck
      icon: external
      variant: minimal
---

## Install

On the machine that will be the brain:

```sh
sh install.sh
```

No root, no dependencies beyond a POSIX shell: it downloads zellij,
yazi, btop, gping, ctop and rclone into `~/.local/bin` and asks
"set it up now?" -- see [install](manual/install/) for what it does by hand.

## Manual

| topic | what it covers |
|---|---|
| [concepts](manual/concepts/) | the deck, the brain, the fleet, faces |
| [install](manual/install/) | from nothing to inside the deck, and how to remove it |
| [patterns](manual/patterns/) | which shape to pick, growing a deck, moving it to a new brain |
| [profile](manual/profile/) | every setting in ~/.config/phosphor/deck.toml, and your own apps |
| [commands](manual/commands/) | every `phosphor` command |
| [keys](manual/keys/) | keys inside the deck, and what happens when a program ends |
| [phones](manual/phones/) | screens: phones, other computers, anything with ssh |
| [workspaces](manual/workspaces/) | a tab per idea: its folder, its assistants, its notebook |
| [mentions](manual/mentions/) | the read-only chat feed and "prepare notes" |
| [web](manual/web/) | the deck in a browser, only inside your tailnet |
| [tunnels](manual/tunnels/) | keeping your ssh config's LocalForward tunnels up |
| [clipboard](manual/clipboard/) | one clipboard for every screen |
| [privacy](manual/privacy/) | what stays where, and checking a fork before you push |
| [troubleshooting](manual/troubleshooting/) | when something doesn't work |

