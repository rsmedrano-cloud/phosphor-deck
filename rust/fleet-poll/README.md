# phosphor-fleet-poll

A standalone rewrite of `lib/fleet.py`'s poller: ssh `share/collect.sh` to
every host in the profile, debounce a blip into a real down/back transition
(`phosphor notify --fleet-alert`), and write `fleet.json` -- the same file
`glance`, the adjutant, and `phosphor fleet`'s own card already read
(`fleet.read_state()`).

**Optional, and additive.** `phosphor fleet` looks for this binary
(`deckconf.exe("phosphor-fleet-poll")`, so `~/.local/bin` first) and only
falls back to its own Python poller thread if it isn't there, isn't
executable, or fails to start. Nothing in `install.sh` builds or fetches it
yet -- there's no release binary to distribute, on purpose, until this has
had more real use. Until then it only runs where someone built it by hand
and put it in `~/.local/bin/phosphor-fleet-poll` themselves.

## Building it, and updating it live

```sh
curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal   # once
cd rust/fleet-poll
cargo build --release
cp target/release/phosphor-fleet-poll ~/.local/bin/
```

`phosphor fleet` (or `phosphor restart`) picks it up the next time it starts.
From then on `lib/fleet.py`'s `RustPoller` supervises it every redraw frame
(about once a second): a rebuild -- `cargo build --release && cp ... ~/.local/
bin/` again, live, no restart -- is noticed by its changed mtime and swapped
in within a second, the old one terminated first; a crash relaunches it the
same way. Only a real crash loop (more than `RustPoller.MAX_RAPID_FAILS`
deaths inside `RAPID_WINDOW` seconds -- not a deliberate rebuild, which is
never treated as a failure) gives up on Rust for that pane's life and starts
the Python thread instead, so the panel keeps updating either way. Remove
the binary and restart the tab to go back to the Python poller for good --
nothing else to undo.

## Testing it

```sh
cargo test
```

Not in `tests/check.sh` (see CONTRIBUTING.md): CI's images don't carry a
Rust toolchain yet. `tests/fleet-poller-check.py` (plain Python, in
`check.sh`) covers the Python side: that a binary here gets picked up, that
its absence or a failed spawn falls back to the Python thread, that `[deck]
demo = true` never touches this at all, and -- against real, disposable
scripts standing in for this binary, not mocks -- that `RustPoller.tick()`
relaunches a crashed one, hot-reloads one whose mtime changed, leaves a
healthy unchanged one alone, and gives up to the Python thread after a real
crash loop.

## What it deliberately doesn't do

- **Demo mode.** `[deck] demo = true` fleet.py fakes drifting readings for
  screenshots; this binary refuses to run at all when it sees that flag, so
  there's only ever one place making that data up.
- **A host's name in deck.log.** It's documented as safe to paste into an
  issue (see troubleshooting.md); this writes the same first-poll/slow-round
  lines `lib/fleet.py` does, host-name free, in the exact format
  `dlog.tail_for()` expects.
- **Its own release binary.** Static musl builds (matching how `install.sh`
  already fetches zellij/yazi/rclone) and a CI job to build+test this crate
  are both explicitly out of scope for its first pass.
