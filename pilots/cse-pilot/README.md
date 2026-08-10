# CSE pilot starter kit

This blueprint turns a selected `render-static` catalog into the authored
Spack 1.2 workspace used for the current CSE pilot. It is deliberately separate
from both the generic static catalog and the full curated-stack renderer.

The initializer does not probe a machine and does not select providers. Copy
`site-values.example.yaml`, choose exact catalog scopes and provider versions,
then run:

```sh
stack-composer init-workspace \
  --blueprint stack-content/pilots/cse-pilot \
  --catalog rendered-static/<system>/static/<catalog-release> \
  --values systems/<system>/cse-pilot-values.yaml \
  --output workspaces/<system>/cse-pilot/<release>
```

The result contains native Spack configuration scopes, five independent
environments, and the compiler front-door/lane modulefiles. Build in this
order: Core, Common, Serial, MPI, GPU. Foundation is ambient in the Core view;
GPU is the compatible MPI surface plus the GPU payload.

`compiler.source` and `mpi.source` accept `external` or `build`. External mode
includes the selected catalog scope. Build mode emits producer groups in each
independently buildable environment; the shared store/build cache provides
reuse. The local provider scope supplies explicit toolchain selectors in both
modes.

This is an alpha pilot aid, not a new generic rendering API. Update the
blueprint roster/policy for the CSE pilot; update `render-static` for reusable
platform-catalog behavior.
