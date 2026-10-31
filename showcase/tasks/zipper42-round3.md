# Follow-up 2 for unxed/zipper#42 — other TAR wrappers

archive/factory.go routes every `.tar`, `.tar.*`, `.tgz`, `.txz`, `.tbz2`, `.tzst` file to
the tar updater, so `tarUpdater.Remove` (already implemented in archive/updater.go: repack
into `<archive>.tmp`, rename on success) effectively claims support for all of them.

1. Extend the table in `TestTarUpdater_Remove` (archive/edge_coverage_test.go) to every TAR
   wrapper this package can CREATE with `NewArchiver` (check which compression methods the
   tar archiver really writes: e.g. `.tar.gz`/`.tgz`, `.tar.xz`, `.tar.bz2`), asserting the
   same things as for `.tar.zst` (entry and subtree removed, retained content readable,
   `fs.ErrNotExist` for a missing name).
2. If removal cannot work correctly for some wrapper (e.g. the archiver cannot write that
   compression, so the repacked archive would change format), make `Remove` return a clear
   error for it BEFORE touching the original (e.g. `archive: removal is not supported for
   <ext>`), add a test for that error and that the original stays byte-for-byte unchanged,
   and mention the limitation in the `Remove` doc comment. Never silently change an
   archive's compression format.

Test command: `GOTOOLCHAIN=auto go test ./archive/...`.
