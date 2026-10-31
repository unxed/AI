# Follow-up for unxed/zipper#42 (tar removal) — complete the acceptance tests

The working tree already contains an implementation of `tarUpdater.Remove` in
archive/updater.go (repack into `<archive>.tmp`, rename over the original only on success)
and `TestTarUpdater_Remove` in archive/edge_coverage_test.go. Keep the implementation unless
a test below reveals a bug. Add the missing acceptance tests (Go `testing`, package archive):

1. Retained contents are still readable after removal: after removing `dir` from both
   `test.tar` and `test.tar.zst`, open the archive (e.g. with `OpenFS`) and check that
   `file1.txt` still reads back exactly `data1`.
2. A failed rewrite does not replace the original: create a `.tar.zst` archive, record its
   bytes, then make the rewrite fail (for example make the archive's directory read-only so
   the temp file cannot be created — skip the test when running as root, where permissions
   are not enforced — or another deterministic failure the implementation reaches before
   the rename). `Remove` must return an error, the original file must be byte-for-byte
   unchanged and still list both entries, and no `<archive>.tmp` file may be left behind.
3. Removing a nonexistent name returns an error that `errors.Is(err, fs.ErrNotExist)`.

Also add a short doc comment on `tarUpdater.Remove` describing the strategy and limitations
(full repack: cost proportional to the archive size; name matching: exact entry or a
directory prefix `name/`).

Test command: `GOTOOLCHAIN=auto go test ./archive/...`.
