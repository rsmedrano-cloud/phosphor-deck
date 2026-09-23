---
title: Privacy
sidebar:
  order: 13
---


- No listening daemon, no agents on watched machines, no telemetry. Fleet
  metrics come from a shell script piped over ssh; files travel over SFTP.
- The session and everything it shows live on the brain: it is the valuable
  machine now (updates, backups, who can log in). On a shared brain other users
  may reach what the deck reaches.
- The brain holds ssh keys into the fleet: narrow them in `authorized_keys`
  (e.g. `from="100.64.0.0/10"` with tailscale).
- The tools you run inside talk to their own services (your chat client --
  matterhorn, iamb, gomuks... -- to its server, an assistant to its
  provider). Phosphor adds no leaks and can't stop theirs.
- Your profile is personal and lives in `~/.config`, not the repo. Before you
  push a fork: `phosphor privacy` (or `--install` as a pre-commit hook). It
  reads your profile, git email, user, home, tailscale addresses, headscale
  and matterhorn servers, and scans what git would publish.
- A host name that appears on purpose (an example, a CI runner tag) goes in
  `.privacy-allow` at the top of the repo, with the files it may appear in:
  `myserver  profiles/example.toml README.md`. It still warns anywhere else,
  and IPs, users, emails and servers can never be allowed.
