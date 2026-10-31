# Follow-up 3 for unxed/zipper#42 — test coverage of the new removal code

PR #43 is green but Codecov reports only 50% of the new lines covered (target 55.81%).
The uncovered lines are mostly the error paths of `tarUpdater.Remove` in archive/updater.go
(closing the current updater, creating/initialising/closing the temporary archive, opening
the original with `OpenFS`, the copy walk, closing the new updater, the final rename, and
`reopen()` after each failure).

Add tests in archive/edge_coverage_test.go (package archive, Go `testing`, deterministic,
no root-only tricks; skip when running as root if you rely on permissions) that drive as many
of those error paths as practical, e.g.: a corrupt/truncated archive (OpenFS or the walk
fails), removing every entry, removing a nested file inside a directory (not the whole dir),
names given with a trailing slash, calling Remove twice in a row on the same updater and then
appending/closing (the updater must still work after a successful repack), an unwritable
directory for the temp file (already covered — keep it), and a rename failure if you can make
one deterministically. Each failure test must also check the original archive is unchanged.

Do not change the implementation unless a new test exposes a real bug (then fix it and say
so). Test command: `GOTOOLCHAIN=auto go test ./archive/...`.
