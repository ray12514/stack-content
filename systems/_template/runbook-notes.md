# <System> — Operator Notes

Use `stack-planning/docs/runbook.md` for the common static-pilot procedure. This
file records only the values, promotion evidence, and checks that differ for
this system. Apply the matching platform acceptance checklist from
`stack-planning/docs/`.

## System identity

- System name:
- Platform family:
- Scheduler:
- Login, build, CPU-runtime, and GPU-runtime node types:
- Module implementation:

## Selected inputs

- Reviewed profile: `systems/<system>/profile.yaml`
- Inspector hints, if needed:
- Static catalog release/path:
- Restricted build values: `systems/<system>/cse-pilot-build-values.yaml`
- Publication values: `systems/<system>/cse-pilot-publish-values.yaml`
- Active pilot roster: `pilots/cse-pilot/roster.yaml`
- Spack release:
- `spack-packages` release:

## Supported surfaces

| Compiler | MPI provider/version | GPU toolkit/architecture | Expected lanes |
|---|---|---|---|
| | | | |

## Site paths

- Restricted workspace and install tree:
- Restricted source/misc caches:
- Restricted views/modules:
- Private CSE build-cache URL:
- Published workspace and install tree:
- Published views/modules:
- Build and publication scratch stages:
- CSE Unix group:
- Package/publication read audience:

## Promotion record

| Lane | Concretized | Built | Target runtime passed | Cache pushed | Cache-only published | Hashes match |
|---|---|---|---|---|---|---|
| Core | | | | | | |
| Common | | | | | | |
| Serial | | | | | | |
| MPI | | | | | | |
| GPU | | | | | | |

- Signing key/policy:
- Build-cache index verification:
- Clean-shell module verification:
- Release-owner approval:
- Package write audience (`user` or `group`):

## System-specific commands

Record only scheduler allocations, transfers, environment activation, or other
commands that differ from the canonical runbook.

## Acceptance status

- [ ] Profile reviewed against the live system
- [ ] Validate and render clean
- [ ] Rendered externals match the selected platform facts
- [ ] Every lane concretizes
- [ ] Serial lockfile contains no MPI implementation
- [ ] System-provided externals are used rather than fetched
- [ ] Install, view, and module generation complete
- [ ] Rendered `packages.yaml` contains the approved package permissions
- [ ] Another collaboration-group member can read the release from login and compute nodes
- [ ] `cse/<Compiler>` exposes core plus lane selectors
- [ ] Loading a second conflicting lane fails
- [ ] Representative serial, MPI, and GPU runtime tests pass

## Findings and follow-up

Record concise system-specific findings here. Put reusable technical lessons in
`stack-planning/docs/spack-learnings/CSE-Spack-Learnings.md` and implementation
defects in the owning repository.
