# Composer stabilization checkpoint

Date: 2026-09-04

Status: local checkpoint. No remote push, release tag, public publication, or
live-system deployment was performed. The native executable remains an opt-in
candidate. Cluster Inspector and the active trial workspace are unchanged.

## Matching implementation revisions

| Repository | Commit |
|---|---|
| Stack Composer | `6e48725245f17d8496b267600126a5b1ba584244` |
| Stack Planning | `013382915ad58fa332347ba4402e580487e45713` |
| Stack Content | `1dba9b11b1e86f22a7be8a4732f8ee0fbf615fce` |

The Stack Content revision above contains the tested launcher and update
procedure. This receipt and its checksum file are added by a subsequent
documentation-only commit; they do not change the trial template or runtime
payload. Keep this record with the corresponding implementation revisions.

## Candidate artifacts

Paths are relative to the Stack Composer checkout:

```text
dist/stack-composer.pyz
dist/stack-composer-0.1.0.tar.gz
dist/native/stack-composer-0.1.0-linux-x86_64-glibc2.28-candidate.tar.gz
dist/native/stack-composer-0.1.0-linux-x86_64-glibc2.28-candidate/stack-composer
```

The [SHA-256 inventory](2026-09-04-composer-stabilization.sha256) identifies
these exact local bytes. The artifacts were built during working-tree
validation before the source checkpoint. Application-file inventories match
the checkpoint source; this is not a clean-commit production build attestation
or a promise that a future complete tarball rebuild will have the same hash.
These files are local build outputs, not binaries committed to this repository.

When the complete recorded artifact set is present, verify it from the Composer
checkout using the appropriate command for the host:

```bash
# Linux
sha256sum --check "$CONTENT/pilots/cse-pilot/checkpoints/2026-09-04-composer-stabilization.sha256"

# macOS
shasum -a 256 --check "$CONTENT/pilots/cse-pilot/checkpoints/2026-09-04-composer-stabilization.sha256"
```

Keep the native executable beside its `_internal` directory. Execute it
directly, not through Python. It is Linux x86_64 with a checked glibc symbol
floor of 2.28, not a universal binary. The full frozen directory has its own
`SHA256SUMS` inventory and component report.

## Validation

The Composer suite has 248 passing tests on macOS Python 3.9.25 and 3.14.7,
and Linux Python 3.12.3. The CSE support suite has 85 passing tests. The
Composer and CSE suites were rerun successfully immediately before the source
commits. Schema validation, source-of-truth drift checks, lint checks, artifact
inventory checks, and Linux/Cray fixture comparisons also passed.

The initialized Linux and Cray fixture configurations match their baseline
outputs after normalizing private test paths. Only the workspace manifest gains
input digests. These checks did not regenerate active workspaces, reconcretize
trial locks, install packages, or modify caches.

Detailed results are in Stack Composer's `docs/stabilization-2026-09.md`.

## Next trial step

After the matching changes have been reviewed and transferred through the
approved process, follow
[Stack Composer update during the current trial](../STACK-COMPOSER-UPDATE.md).
Rebuild only Composer and compare copied inputs in a new temporary output
directory. Resume the existing build through its existing `cse-build`.

Real-system acceptance on Blueback remains pending. Native promotion also
requires the dependency/Python support decision, complete runtime license and
security review, hash-locked acquisition, and target shared-filesystem checks.
Do not change Foundation sharing policy or the trial layout as part of this
checkpoint.
