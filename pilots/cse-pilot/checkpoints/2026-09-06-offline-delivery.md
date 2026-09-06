# Offline delivery checkpoint

Date: 2026-09-06

Status: local candidate. No push or production promotion. Existing trial
workspaces, locks, installations, caches, and shared lab services are unchanged.
The local environment was used only as a model of the intended HPC handoff.

## Matching payload revisions

| Repository | Commit |
|---|---|
| Stack Composer | `997520a190acb7b80be61d73a8ec9cc2ba1ec18e` |
| Stack Content | `a1f3d1d2252066561b5fe1f4030c4e7762066708` |
| Stack Planning | `013382915ad58fa332347ba4402e580487e45713` |

This receipt and the updated runbook are subsequent documentation-only
changes. The payload uses the explicit revisions above. Cluster Inspector is
not included. No template, package pin, lane, compiler selection, or existing
workspace changed as part of this checkpoint.

## Results

Two fresh network-disabled builds produced identical `.pyz`, portable release
tar, and native release tar bytes. The complete input capsule contains the
source exports, matching helpers, hash-locked dependency wheels, pure-wheel
source inputs, and the saved builder image. It can rebuild without the
original development repositories or a package index.

Six initialized Linux and Cray-shaped workspaces were moved and checked in a
separate container that could not access the original sources or catalogs.
Fresh workspaces passed real Spack 1.2.2 login and compute preflights for all
eight environments. Partial and complete lock fixtures retained exact bytes;
they are synthetic preservation fixtures, not built package DAGs. A fresh
offline recipe cache also loaded the relocated CSE overlays and local builtin
recipe mirror successfully.

The native executable ran without a host Python command and with `/tmp`
non-executable. The portable artifact ran on Python 3.9.25. Composer's 255
tests passed on Python 3.9.25 and 3.14.7; all 85 CSE support tests passed.

## Operator action

The candidate is in the Composer checkout under
`dist/offline/stack-composer-0.1.0-997520a/`. Its `DELIVERY.md` explains the
artifacts and verification commands. The companion
`2026-09-06-offline-delivery.sha256` identifies the exact delivery bytes.

Verify from the Composer checkout when the archive and unpacked delivery are
both present:

```bash
# Linux
sha256sum --check "$CONTENT/pilots/cse-pilot/checkpoints/2026-09-06-offline-delivery.sha256"

# macOS
shasum -a 256 --check "$CONTENT/pilots/cse-pilot/checkpoints/2026-09-06-offline-delivery.sha256"
```

For the current trial, continue through the existing workspace's `cse-build`.
Do not initialize over it or reconcretize to adopt this packaging change.
Follow [the update runbook](../STACK-COMPOSER-UPDATE.md#offline-delivery-and-copied-workspace-checks)
for the receiving-tool and model-test procedure. Full commands and evidence
are in Composer's `docs/offline-delivery.md` and
`docs/offline-delivery-acceptance-2026-09.md`.

Spack, recipe mirrors, installed prefixes, cache/view/module roots, and
compiler/MPI paths remain explicit site prerequisites. Workspace relocation
does not relocate those resources. Native promotion still needs target-system
acceptance and the pending dependency, Python-support, license and security
decisions. No real Cray compilation or MPI execution was tested here.
