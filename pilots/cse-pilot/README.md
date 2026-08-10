# CSE pilot starter kit

This blueprint turns a selected `render-static` catalog into the authored
Spack 1.2 workspace used for the current CSE pilot. It is deliberately separate
from both the generic static catalog and the full curated-stack renderer.

The initializer does not probe a machine and does not select providers. Copy
`site-values.example.yaml` twice, choose exact catalog scopes and provider
versions once, then create a restricted build values file and a publication
values file. The two files keep the same package/provider intent and private
build-cache URL; only `workspace.role` and deployment paths differ.

```sh
stack-composer init-workspace \
  --blueprint stack-content/pilots/cse-pilot \
  --catalog rendered-static/<system>/static/<catalog-release> \
  --values systems/<system>/cse-pilot-build-values.yaml \
  --output restricted/workspaces/<system>/cse-pilot/<release>
```

Initialize the publication workspace separately with
`cse-pilot-publish-values.yaml`. The result in each location contains native
Spack configuration scopes, five independent environments, a build-cache
mirror, and the compiler front-door/lane modulefiles. Build and validate in the
restricted workspace in this order: Core, Common, Serial, MPI, GPU. After
approval, push the concrete specs to the private CSE build cache, copy the
validated lockfiles to the publication workspace, and install there with
`--only-concrete --use-buildcache=only`. A cache miss stops publication; it must
never trigger a source build in the user-facing tree.

Foundation is ambient in the Core view; GPU is the compatible MPI surface plus
the GPU payload. The published views and package modules are regenerated only
after the cache-only installation succeeds.

`compiler.source` and `mpi.source` accept `external` or `build`. External mode
includes the selected catalog scope. Build mode emits producer groups in each
independently buildable environment; the shared store/build cache provides
reuse. The local provider scope supplies explicit toolchain selectors in both
modes.

This is an alpha pilot aid, not a new generic rendering API. Update the
blueprint roster/policy for the CSE pilot; update `render-static` for reusable
platform-catalog behavior.
