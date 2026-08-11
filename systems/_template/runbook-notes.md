# <System> static pilot notes

Use `stack-planning/docs/runbook.md` for the common static-pilot procedure. This
file records only the values, promotion evidence, recovery decision, and checks
that differ for this system. Apply the matching platform acceptance checklist
from `stack-planning/docs/`.

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
- Cluster Inspector commit:
- Stack Composer commit:
- Stack Content commit:

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
- CSE Unix group: `cse`
- Package/publication read audience:

## Run state and recovery

- Current release state (`working`, `locked`, `validated`, `cached`,
  `published`, `accepted`, or `held`):
- Last successful checkpoint (1-8):
- Held checkpoint/lane, if any:
- Exact failed command and exit status:
- Log or evidence path:
- Did any durable input or concrete hash change (`yes` or `no`):
- Recovery decision (`resume same release` or `new release`):
- Earliest checkpoint to rerun:
- Exact next command:

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

## System-specific commands

Record only scheduler allocations, transfers, environment activation, or other
commands that differ from the canonical runbook.

## Acceptance status

- [ ] Profile verified against the live system
- [ ] Static catalog reviewed against the profile
- [ ] Restricted workspace and five native `modules.yaml` files generated
- [ ] Five restricted lockfiles reviewed
- [ ] Serial lockfile contains no MPI implementation
- [ ] System-provided externals are used rather than fetched
- [ ] Every lane builds and passes its target runtime checks
- [ ] Approved binaries and cache index are complete
- [ ] Shared installation is cache-only and published hashes match
- [ ] Published views and package modules regenerate cleanly
- [ ] `cse/<Compiler>` exposes the expected lane selectors
- [ ] Loading a second conflicting lane fails
- [ ] Clean login and compute sessions pass the platform checklist
- [ ] Release owner approves publication

## Findings and follow-up

Record concise system-specific findings here. Put reusable technical lessons in
`stack-planning/docs/spack-learnings/CSE-Spack-Learnings.md` and implementation
defects in the owning repository.
