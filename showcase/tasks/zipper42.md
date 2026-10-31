# archive: support removing entries from tar.zst archives

## Goal

Support removing entries from TAR-based archives through `archive.NewUpdater(...).Remove`, including `.tar.zst`, so the archive remains usable after the update. This is required by the zipgui “Delete” step in unxed/goWidgets#30 (plan step 9a): its acceptance test deletes one file from a `.tar.zst` archive and confirms that `archive.List` no longer returns it.

## Current behavior

For a `.tar.zst` archive, `NewUpdater(filename, opts).Remove(names...)` returns `archive: in-place removal is not supported natively for tar`. The same TAR updater limitation may apply to other TAR stream variants. `engine.Formats()` currently marks `.tar.zst` as updateable, so the GUI exposes an enabled Delete action that cannot succeed.

## Requested change

Implement removal for TAR-based updater formats, using a safe rewrite/repack strategy if native in-place removal is impossible. Preserve every non-removed entry and its relevant TAR metadata/content, including the format's compression wrapper. Do not silently claim update support for formats that remain unsupported; keep `Update` capability reporting consistent with the implementation.

The operation should not leave a truncated/corrupt original archive if reading, writing, cancellation, or replacement fails. Follow the existing updater API's error and context conventions; document any limitations.

## Acceptance tests

- Create a `.tar.zst` archive with at least two entries; remove one using `NewUpdater(...).Remove`; close/update and verify `archive.List` contains the retained entry and not the removed one, and that retained contents can still be read.
- Cover removal of a directory/subtree or explicitly document the matching semantics.
- Verify a failed/cancelled rewrite does not replace the original with a partial archive.
- Add coverage for uncompressed TAR and other TAR wrappers if the implementation claims support for them.

No CLI behavior change is requested. This is a follow-up to unxed/zipper#35 and unxed/goWidgets#30 step 9a.


## Implementation notes from the maintainer's tracker
- The relevant code is archive/updater.go (tarUpdater.Remove currently returns
  "in-place removal is not supported natively for tar"); mirror zipUpdater.Remove
  conventions for signature, errors and context handling.
- Write the rewritten archive to a temp file in the same directory and rename it over
  the original only on success; remove the temp file on any error or cancellation.
- Add tests in archive/ (Go `testing`), runnable with `go test ./archive/...`.
