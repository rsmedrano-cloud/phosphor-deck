# phosphor-run

An optional Rust rewrite of `lib/run.py`, the watcher every pane in the deck
runs through: spawn the program, close it if it froze (the same heuristic as
`lib/hung.py` -- a resize queued and never answered), show a banner and
Enter/x/l when it ends, and reconnect an ssh pane on its own.

**Not wired into anything.** `gen.py` still always wraps every pane in
`python3 phosphor run ...` -- this binary isn't a drop-in the deck picks up
by itself the way `rust/fleet-poll` is. To try it on one tab, point that
pane's `cmd` at the built binary directly in your profile:

```toml
[[tabs]]
name = "PROBE"
panes = [
  { cmd = "/path/to/phosphor-deck/rust/run/target/release/phosphor-run",
    args = ["--name", "BTOP", "--", "btop"] }
]
```

then `phosphor gen && phosphor restart`. Point `cmd` back at whatever it was
to go back -- nothing else to undo.

## Building it

```sh
curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal   # once
cd rust/run
cargo build --release
```

## What it deliberately doesn't do (yet)

- **Mouse taps.** `lib/run.py`'s "kept tab" prompt also accepts a tap on its
  own row (a DSR cursor-position query). This binary is keyboard-only:
  Enter/x/f/l always work, tapping the row doesn't yet.
- **Editing the profile itself.** A kept tab's `f` (forget it, out of your
  profile) needs `lib/tabs.py`'s comment-preserving text surgery on
  `deck.toml`. Reimplementing that without its own test coverage wasn't a
  risk worth taking for this rare case (a kept tab's last program ending),
  so this shells out to `phosphor tabs --closing` (is this even that case?)
  and `phosphor tabs --forget NAME` instead of touching the profile itself.
  `tests/tabs-check.py` covers both flags on the Python side.

## Testing it

```sh
cargo test                        # 12 unit tests: theme, dlog, hang detection
python3 ../../tests/run-rust-check.py   # the real binary, in a real pty
```

The pty test reuses the exact frozen/healthy/busy shapes
`tests/hang-check.py` already uses against the Python `phosphor run`, so the
two are checked the same way. Neither is in `tests/check.sh` yet -- see
CONTRIBUTING.md.

Not covered by an automated test yet: the "kept tab" prompt's shell-out to
`phosphor tabs --closing`/`--forget` from inside a *real* zellij session
(the pty test above runs this binary standalone, with `ZELLIJ` unset, so
`closing()` always returns `None` there). Lower risk than it sounds -- the
profile-editing logic itself is `lib/tabs.py`'s, already covered -- but
worth knowing before leaning on that specific path.
