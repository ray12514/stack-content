# <System> Initial Conversion Trials notes

Use `stack-planning/docs/runbook.md` for the common trial procedure. This
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
- Restricted build values: `systems/<system>/cse-trials-build-values.yaml`
- Step 7 provider exports:
  - shared compiler/MPI:
  - platform compiler/MPI:
  - MPI source choices (`external` or `build`):
  - reviewed build node type and job count:
  - generated temp/scratch/`${WORKDIR}` stage order:
- Publication values: `systems/<system>/cse-trials-publish-values.yaml`
- Active trial roster: `pilots/cse-pilot/roster.yaml`
- Spack release:
- `spack-packages` release:
- Cluster Inspector commit:
- Stack Composer commit:
- Stack Content commit:

## Supported surfaces

| Surface | Compiler | MPI provider/version | Environments |
|---|---|---|---|
| Shared CSE | GCC 12.5.0 | | Core, Common, Serial, MPI |
| Platform | | | Core, Common, Serial, MPI |

## Site paths

- Restricted workspace and install tree:
- Restricted source/misc caches:
- Restricted views/modules:
- Private CSE build-cache URL:
- Published workspace and install tree:
- Published views/modules:
- Build and publication scratch stages:
- Shared-build Unix group: `<recorded collaboration group>`
- Package/publication read audience:

## Shared-builder permission contract

- Restricted collaboration group:
- Workspace/source-cache/misc-cache/view/module/buildcache handoff check:
- Install-tree Spack permission and cross-node lock/access check:
- Last owner-to-group resume test:
- Exact affected root and owner/admin recovery, if needed:

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

| Environment | Concretized | Built | Target runtime passed | Cache pushed | Cache-only published | Hashes match |
|---|---|---|---|---|---|---|
| GCC Core | | | | | | |
| GCC Common | | | | | | |
| GCC Serial | | | | | | |
| GCC MPI | | | | | | |
| Platform Core | | | | | | |
| Platform Common | | | | | | |
| Platform Serial | | | | | | |
| Platform MPI | | | | | | |

- Signing key/policy:
- Build-cache index verification:
- Clean-shell module verification:
- Release-owner approval:

## System-specific commands

Record only scheduler allocations, transfers, environment activation, or other
commands that differ from the canonical runbook.

During an active system trial, put the exact system-specific diagnostic or
recovery commands in this file before handing them to an operator. Label an
unverified action as a diagnosis or proposed test, include the expected
pass/fail evidence, and replace it with the confirmed recovery only after the
target-system result is known. Required operating commands must not exist only
in chat or in an untracked note. Promote a reusable procedure to the canonical
runbook after it has been validated across the applicable system family.

## Acceptance status

- [ ] Profile verified against the live system
- [ ] Static catalog reviewed against the profile
- [ ] Restricted workspace and eight native `modules.yaml` files generated
- [ ] Eight restricted lockfiles reviewed
- [ ] Serial lockfile contains no MPI implementation
- [ ] System-provided externals are used rather than fetched
- [ ] Every lane builds and passes its target runtime checks
- [ ] Approved binaries and cache index are complete
- [ ] Shared installation is cache-only and published hashes match
- [ ] Published views and package modules regenerate cleanly
- [ ] Both `cse/<Compiler>` front doors expose the expected lane selectors
- [ ] Loading a second conflicting lane fails
- [ ] Clean login and compute sessions pass the platform checklist
- [ ] Release owner approves publication

## Findings and follow-up

Record concise system-specific findings here. Put reusable technical lessons in
`stack-planning/docs/spack-learnings/CSE-Spack-Learnings.md` and implementation
defects in the owning repository.
