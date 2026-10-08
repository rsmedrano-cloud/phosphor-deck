# Privacy

- No listening daemon (`phosphor glance --serve` listens only when you run it:
  tailnet only, a token, read-only), no agents on watched machines, no telemetry. Fleet
  metrics come from a shell script piped over ssh; files travel over SFTP.
  What it leaves there: one-line files in `$XDG_RUNTIME_DIR` holding the
  last answer of what's too slow to ask every 15 seconds -- `phosphor-smart`
  (where `smartctl` exists) and `phosphor-updates` (the pending updates).
  The day of readings FLEET's `h` draws stays on the brain
  (`~/.cache/phosphor/history.json`).
- The session and everything it shows live on the brain: it is the valuable
  machine now (updates, backups, who can log in). On a shared brain other users
  may reach what the deck reaches: `phosphor security` says where they would
  (file permissions, the fleet's ssh servers, ports, sockets) and how to close it.
- The brain holds ssh keys into the fleet: narrow them in `authorized_keys`
  (e.g. `from="100.64.0.0/10"` with tailscale).
- `phosphor backup` writes one file, 0600, holding your profile, notebook and
  glance token (never ssh keys): keep it where you'd keep those, and know
  that whoever has it can read your notes and ask your glance.
- What comes from outside the brain is shown as text, never as terminal
  commands: a host's poll answer, its logs through `phosphor tail`, a chat
  notification, a broadcast's output, CI and review data. Escape sequences
  in them (one that writes every screen's clipboard, clears or retitles a
  pane, or reorders a line) are dropped before they reach a screen, so a
  compromised machine, or anyone who gets a line into a container's log,
  can't use the deck's terminals. Plain colors in logs stay. An ssh shell
  on a host (`s` in FLEET, an ssh tab) is a real terminal and passes
  everything, as any ssh does.
- `phosphor triage` hands a host's snapshot to an AI assistant, so a line
  planted there could try to steer the answer. The assistant gets it as
  fenced data with no tools to act with, and a dangerous command in what
  it answers is flagged before you'd copy it (see commands).
- `phosphor digest` sends a day of your commit messages, notes, todos and
  fleet trouble to an assistant's provider, only when you run it (`--print`
  shows what would go). It goes in fenced as data, to an assistant with no
  tools.
- `phosphor read` fetches the address you give it, and a search sends its
  words to DuckDuckGo, from the brain, only when you run it. `--ask` sends
  the page and your question to an assistant's provider.
- `phosphor mcp` hands your notes, fleet readings, workspace names and the
  deck's log to whichever assistant you registered it with, and so to that
  assistant's provider, whenever it calls one of its tools. It only reads,
  and only on this machine; take it out of the assistant's MCP config to stop it.
- The tools you run inside talk to their own services (your chat client --
  matterhorn, iamb, gomuks... -- to its server, an assistant to its
  provider). Phosphor adds no leaks and can't stop theirs.
- `phosphor usage`, where you put it in a tab, is the one panel that talks
  to an AI provider itself: it uses the token claude or agy already keeps
  on this machine to ask that same provider (Anthropic, Google) how much
  of your plan is used. Nothing else goes with it, and it never refreshes
  or copies the token.
- Your profile is personal and lives in `~/.config`, not the repo. Before you
  push a fork: `phosphor privacy` (or `--install` as a pre-commit hook). It
  reads your profile, git email, user, home, tailscale addresses, headscale
  and matterhorn servers, and scans what git would publish.
- A host name that appears on purpose (an example, a CI runner tag) goes in
  `.privacy-allow` at the top of the repo, with the files it may appear in:
  `myserver  profiles/example.toml README.md`. It still warns anywhere else,
  and IPs, users, emails and servers can never be allowed.
