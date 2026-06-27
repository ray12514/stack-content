# stack-content

The human-authored **source of truth** that `stack-composer render` consumes —
the "stack directory" / definition center for the stack-generation project. It is
**data, not a tool**: the fourth repo alongside `cluster-inspector`,
`stack-composer`, and `stack-planning`.

It is synced onto each target's shared filesystem (or read GitLab-direct) where
`stack-composer render` and the chosen build path run. There may be more than one
stack-content repo (per team or per stack family); the pattern is the same.

![What the stack-content repo holds](docs/stack_content_contents.svg)

For how these inputs become per-stack workspaces and one shared install tree, see
the lifecycle note in stack-planning: `docs/stack_workspace_lifecycle_v1.md`.

## Layout

```text
templates/<set>/                 # the reusable placeholder tree (the INPUT)
  defaults.yaml                  #   site policy merged into every stack
  configs/                       #   Spack component yamls as Jinja (.j2): common, os/, target/,
                                 #     vendor/, mpi/<provider>/, gpu/<toolkit>/
  environments/                  #   per-lane spack.yaml.j2 (core, serial, mpi, gpu)
package-sets/*.yaml              # curated Spack spec sets a stack can reference
package-repos/<name>/            # optional Spack package repositories
stacks/<stack>/stack.yaml        # package intent (spec-native: name + specs [+ kind])
systems/<system>/profile.yaml    # observed facts from cluster-inspector (tracked per system)
systems/<system>/deployment.yaml # installer-chosen roots (install tree, caches, view/module, spack root)
```

`deployment.yaml` is required for render. It owns install tree, build-stage,
cache, view-root, module-root, and buildcache destination choices for that
system.

## Two trees — what's authored vs what's generated

- **Authored (here):** `templates/<set>/` is the placeholder tree. It barely
  changes between systems; the `.j2` files carry `{{ placeholders }}` (OS,
  target, compiler prefixes, …).
- **Generated (by stack-composer, not committed here):** the rendered workspace
  — concrete `configs/` + `environments/<compiler>/<lane>/spack.yaml` that
  `include::`s them + `release-manifest.yaml`. That tree is the **handoff** to a
  build path (stack tools / spack-build / Ansible / bare Spack). See
  stack-planning `docs/stack_build_handoff_note_v1.md`.

`stack-composer` fills the placeholders from `profile ∩ deployment ∩ defaults ∩
stack`. The rendered `configs/` therefore differ per system even though the
template is shared.

## How render consumes this repo

```sh
stack-composer render \
  --profile      systems/<system>/profile.yaml \
  --deployment   systems/<system>/deployment.yaml \
  --stack        stacks/<stack>/stack.yaml \
  --templates    templates \
  --package-sets package-sets \
  --package-repos package-repos \
  --output-root  <render-dir> --release <release>
```

## Status

Pre-v1; no release deployed. The template set was lifted out of
`stack-composer/tests/fixtures` (stack-composer keeps minimal fixtures for its
own unit tests). If the shape is wrong, change it directly before v1.
