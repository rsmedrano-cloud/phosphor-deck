## What and why

## Checked

- [ ] `sh tests/check.sh` passes
- [ ] CHANGELOG.md says what users get (under `## Unreleased`)
- [ ] The manual page in doc/manual is updated, and `phosphor docs` was run
- [ ] `phosphor privacy` is clean: no IPs, users, emails or real host names
- [ ] English only

A merge request never gets a pipeline of its own (only main, dev and tags do), so
the maintainer runs `python3 tests/mrs-check.py` against it.
