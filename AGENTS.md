# Agent guidance for `stack-content`

This repo owns authored stack inputs: templates, package sets, package repos,
system profile/deployment examples, and runbook notes. It does not probe hosts
and it does not build Spack environments.

## Cross-repo boundaries

- `cluster-inspector` produces observed `profile.yaml` facts.
- `stack-composer` consumes this repo plus profile/deployment inputs and renders
  a workspace tree.
- `stack-planning` owns the canonical design docs and schemas.

Before changing content shape, check the relevant `stack-planning` design doc
and keep examples/runbooks aligned with the current pre-v1 model.

## Commit hygiene

All commits must be authored and committed as:

- `Ravon Venters <ray12514@gmail.com>`

Do not add assistant/tool attribution to commit messages, trailers, file
headers, generated docs, or comments. Do not include automated co-author
trailers, generated-by footers, assistant signatures, or similar tool stamps.
If a tool proposes one, remove it before committing.
