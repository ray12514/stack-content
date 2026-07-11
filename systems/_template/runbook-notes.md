# <System> — Operator Notes

Use `stack-planning/docs/runbook.md` for the common procedure. This file records
only the values and checks that differ for this system. Apply the matching
platform acceptance checklist from `stack-planning/docs/`.

## System identity

- System name:
- Platform family:
- Scheduler:
- Login, build, CPU-runtime, and GPU-runtime node types:
- Module implementation:

## Selected inputs

- Reviewed profile: `systems/<system>/profile.yaml`
- Inspector hints, if needed:
- Deployment overlay:
- Stack file:
- Package set:
- Spack release:
- `spack-packages` release:

## Supported surfaces

| Compiler | MPI provider/version | GPU toolkit/architecture | Expected lanes |
|---|---|---|---|
| | | | |

## Site paths

- Install tree:
- Build stage:
- Source and misc caches:
- View root:
- Module root and publish root:
- Buildcache destination:

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
- [ ] `cse/<Compiler>` exposes core plus lane selectors
- [ ] Loading a second conflicting lane fails
- [ ] Representative serial, MPI, and GPU runtime tests pass

## Findings and follow-up

Record concise system-specific findings here. Put reusable technical lessons in
`stack-planning/docs/spack-learnings/CSE-Spack-Learnings.md` and implementation
defects in the owning repository.
