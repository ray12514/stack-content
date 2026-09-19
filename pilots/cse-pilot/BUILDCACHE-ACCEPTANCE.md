# Acceptance before signed buildcache push

`scripts/accept-and-push-buildcache.py` runs an explicit consumer acceptance
command and pushes only after it succeeds against unchanged `spack.yaml` and
`spack.lock` bytes. It is an opt-in operator command; it does not change trial
launcher defaults or activate public modules.

Use the pinned Spack 1.2.2 executable, a quiescent installed environment, an
explicit candidate mirror, and a new evidence directory:

```bash
python3 "$CONTENT/pilots/cse-pilot/scripts/accept-and-push-buildcache.py" \
  --spack "$SPACK_ROOT/bin/spack" \
  --environment "$ENVIRONMENT" \
  --destination "$CANDIDATE_BUILDCACHE" \
  --evidence "$EVIDENCE/accept-and-push-01" \
  --timeout 600 \
  -- "$VALIDATION_COMMAND" --inventory "$REVIEWED_INVENTORY"
```

Arguments after `--` form the exact command argument vector; no implicit shell
parsing occurs. The command runs with the environment directory as its working
directory and the operator's existing environment. The validation command must
test the intended installed roots and fail nonzero on a bad result. Choose the
native module/consumer checks required by the SOP; passing a trivial command
does not establish acceptance. This wrapper does not select or approve tests.

The gate records input copies and SHA-256 digests, exact root hashes, both
command arguments, exit statuses, elapsed times, and output logs. The signed
push explicitly selects the recorded root hashes and includes their
non-external dependencies, including build dependencies. Missing installations
fail the push. It does not install, concretize, or change locks.

Failed acceptance, timeout, or changed input bytes prevents any push. A timeout
kills the local command process group; scheduler-submitted jobs must have their
own bounded lifetime. A push failure can leave a partial candidate mirror and
is recorded as failure. A successful push is recorded only if both commands
pass and inputs remain unchanged. A change during the push is reported as
`inputs_changed_during_push`; retain and inspect the candidate mirror before
retrying. This is not an atomic remote publication transaction.

Do not run builders or edit the workspace during this operation. Included Spack
configuration, external runtimes, the installed prefixes, and test coverage
remain the operator's reviewed acceptance inputs; the wrapper's automatic drift
check covers the environment YAML and lock only.

The destination must be an explicit filesystem path or supported non-OCI URL.
Spack 1.2.2 disables signing for OCI pushes, so the wrapper rejects OCI and
configured mirror aliases. Configure the approved signing key in the pinned
Spack context beforehand. It does not import or automatically trust mirror keys.

After a successful candidate push, continue the CSE SOP's signed cache-only
installation and native user-entry checks before promotion. The wrapper never
changes a public entrance. See the lab's
[failure scenarios](../../../hpc-lab/docs/stack-recovery-acceptance.md) for the
small-package rejection and success rehearsal.
