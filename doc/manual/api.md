# What's promised

Some parts of Phosphor are things you build on: your profile, your
scripts, your recipes, the assistant you pointed at `phosphor mcp`. Those
are its public API, and they don't change under you between versions.
Everything else is how Phosphor works today, and can change in any
release.

## Public

- **The profile**: every table and key in `~/.config/phosphor/deck.toml`
  that the profile page documents, with the values it lists. A new key can
  appear; one you use keeps its name and meaning. When a key moves,
  `phosphor migrate` moves it for you (and leaves a `.bak`).
- **The commands**: every `phosphor` command `phosphor help` lists, its
  aliases (`deck`), its flags and words, and its exit codes where the
  commands page gives them (2 is always a usage error).
- **`share/commands.json`**: its fields, as its `_schema` describes them,
  for scripts and assistants that read which commands mutate state.
- **The `--json` output** of every command that has it, and the HTTP
  answer of `phosphor glance --serve`: a field you read keeps its name,
  type and meaning; new fields can appear, so ignore the ones you don't
  know.
- **`phosphor mcp`**: its tools, their arguments and what they return,
  under the same rule as `--json`.
- **Your own files the deck reads**: `tabs.d/*.toml` (and recipes, which
  are tabs.d files), `apps.toml` and `panels.d/`, in the shapes the profile
  page gives them.
- **The notebook's files**: plain Markdown (`notes.md`, a workspace's
  `NOTES.md`), the format `phosphor note` writes, readable by anyone and
  anything.

## Internal

Everything else, even when you can see it:

- the lib/ modules and their functions, and how commands call each other;
- the files under `~/.cache/phosphor` and the logs' line format;
- whatever `phosphor gen` writes (layouts, systemd units, zellij config,
  the `deck` launcher on other machines): it's regenerated, never edited;
- hidden commands (`run`, `mention-hook`, `docs`) and the internal flags
  `share/commands.json` lists under `internal`;
- what panels look like: their text, colors, layout and keys beyond those
  the keys page documents. Read `--json`, never the screen.

## How something goes away

Nothing public disappears without a warning first:

1. It's listed in `share/deprecations.json`, with the version that first
   warns (`since`), the one that drops it (`remove`) and what to use
   instead.
2. While it's listed it still works, and says so: a command or flag prints
   one line on stderr each time it runs (stdout, and `--json`, stay
   clean); `CMD --help` and `phosphor help` mark it; tab completion stops
   offering it; a profile key shows up in `phosphor doctor` and `gen`'s
   warnings.
3. It stays for one full minor on the stable channel: it goes in the minor
   after the first stable (`main`) minor that carried the warning. Warned
   from 1.9.2 (nightly), 2.0.0 is the first stable minor that warns, and
   2.1.0 drops it. The tests fail once the version reaches `remove`, so
   that date is kept.
4. The CHANGELOG says it twice: when the warning starts, and when it goes.

What's deprecated today (`share/deprecations.json` in Phosphor's folder has
the same list):

- `[deck] tts`, since 1.9.2, goes in 2.1.0: use `[tts] enabled`
  (`phosphor migrate` moves it).
- `[deck] notifier`, since 1.9.3, goes in 2.1.0: nothing, a notice marks
  its tab and goes to `[push]` (`phosphor migrate` drops the line).
- `[deck] notify_seconds`, since 1.9.3, goes in 2.1.0: nothing, it only
  timed notifier's floating notice.
- `phosphor pulse`, since 1.9.3, goes in 2.1.0: use `phosphor fleet`.
