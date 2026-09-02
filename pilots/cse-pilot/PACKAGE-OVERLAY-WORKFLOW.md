# CSE trial package overlay workflow

This procedure defines how a CSE package manager or an on-system agent
diagnoses a package failure, develops a trial overlay in an existing workspace,
validates the correction, and returns the approved files to Stack Content.

The generated workspace package repository is the working location for
system-local diagnosis:

```text
<workspace>/package-repos/spack_repo/cse_trials/
```

The corresponding Stack Content tree is the canonical source for future
workspace renders:

```text
stack-content/pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/
```

Do not edit Spack's cached `builtin` repository. A change made only in the
generated workspace is temporary and must not be treated as part of an
accepted release.

## Release boundary

Develop an overlay in place only while the affected lock set is an unaccepted
release candidate. If the lock set was accepted or its binaries were pushed to
a release build cache, preserve that release and create a new one.

An overlay is complete only when all of the following are retained together:

1. The original failure evidence.
2. A repeatable command that produces the failure.
3. The overlay `package.py` and any patch files.
4. Before and after concrete hashes for every affected environment.
5. The successful rerun of the original failing command.
6. Package-specific binary or runtime validation.
7. The recovery commands used on the system.
8. The canonical Stack Content commit containing the correction.

## 1. Capture the failure

Before changing a recipe or environment, record:

1. Package name and version.
2. Compiler family and version.
3. Variants and important dependencies.
4. Environment and lane.
5. Concrete hash.
6. Complete build log.
7. Exact failing command and its standard error.
8. Relevant generated files such as `link.txt`, `CMakeCache.txt`,
   `config.log`, or the generated Makefile.

Sanitization may replace private directory prefixes, but it must preserve
library names, compiler and linker options, error messages, and the order of
arguments. Removing the paths from a colon-separated RPATH can make a valid
RPATH look like a series of empty entries, so note explicitly when that
transformation was made.

Create the smallest practical command that reproduces the reported failure.
For a parallel build failure, rerun only the failing target with one build job
and verbose output. Do not begin with a package-wide workaround when the
failing command is not yet known.

## 2. Identify the correction layer

Place the correction at the narrowest layer that owns the failure:

| Evidence | Correction layer |
| --- | --- |
| Upstream source or configure defect | Source patch in the package overlay |
| Builtin Spack recipe defect | Subclass and override the smallest recipe method |
| Version, variant, provider, or dependency policy | Roster, `packages.yaml`, or environment manifest |
| Incorrect compiler metadata demonstrated by unrelated packages | Compiler package overlay |
| Shell variable used only to expose the cause | Diagnostic only, not the released fix |

For example, zlib requesting `+shared` but silently installing only `libz.a`
is a zlib package contract failure. It must not be hidden by changing Perl or
by exporting a global linker flag.

## 3. Inspect the builtin recipe without modifying it

Enter the existing workspace's prepared login shell and confirm the selected
repository order:

```bash
cd "$BUILD_WORKSPACE"
./cse-build login shell

spack repo list
spack location --package-dir "builtin.<package>"
```

The `cse_trials` repository must appear before `builtin`. Use the builtin
package directory only as a reference. Do not edit files below it.

Spack repository API v2 uses Python module names for package directories and
imports. Replace hyphens with underscores when needed. For example,
`netlib-lapack` is imported through `netlib_lapack`.

## 4. Create a narrow overlay

Create the package directory with the trial's collaboration permissions:

```bash
: "${CSE_BUILD_WORKSPACE:?Run this block inside ./cse-build login shell}"

OVERLAY_REPO="$CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials"
PACKAGE_MODULE="<package-module-name>"
PACKAGE_DIR="$OVERLAY_REPO/packages/$PACKAGE_MODULE"

install -d -m 2770 -g "$CSE_GROUP" "$PACKAGE_DIR"
```

Subclass the builtin recipe instead of copying the complete builtin
`package.py`. A source-patch overlay has this form:

```python
from spack_repo.builtin.packages.netlib_lapack.package import (
    NetlibLapack as BuiltinNetlibLapack,
)

from spack.package import *


class NetlibLapack(BuiltinNetlibLapack):
    """CSE trial corrections for netlib LAPACK."""

    patch(
        "descriptive-fix-name.patch",
        when="@3.12.1+shared %cce",
    )
```

Use the exact builtin class name and import path for the selected package. The
`when` constraint must describe only the verified failure surface. Include the
affected version or inspected version range, compiler, variants, and
architecture when each dimension is material to the defect.

Use a recipe method override when the defect is in Spack behavior rather than
upstream source. Call the builtin implementation with `super()` and change only
the required result. Do not duplicate an entire build phase when a flag
handler, argument method, or callback is sufficient.

Install the overlay files with group write access:

```bash
install -m 0660 -g "$CSE_GROUP" \
  package.py \
  descriptive-fix-name.patch \
  "$PACKAGE_DIR/"
```

## 5. Prove that the overlay is selected

Check the affected environment before changing its lock:

```bash
TARGET_ENV="$CSE_BUILD_WORKSPACE/environments/<compiler>/<lane>"

spack -e "$TARGET_ENV" repo list
spack -e "$TARGET_ENV" spec -N "<package>@<version>"
spack -e "$TARGET_ENV" spec -Il "<package>@<version>"
```

The repository list must place `cse_trials` before `builtin`. The namespace
display must show that the trial recipe is selected. Record the existing
concrete hash before reconcretization.

For a source patch, verify that it applies to the exact source carried by the
locked package:

```bash
cd "<exact-staged-source-directory>"
patch --dry-run -p1 < "$PACKAGE_DIR/descriptive-fix-name.patch"
```

A patch that applies to a convenient upstream branch but not the pinned source
is not acceptable evidence.

## 6. Run a red and green package test

Run the minimal reproducer before applying the correction and retain its
failure. Apply or activate the overlay, then run the same command again. The
command, inputs, and validation must remain unchanged so the result proves the
correction addresses the reported defect.

Examples of useful validation include:

```bash
test -f "<prefix>/lib/<required-shared-library>"
readelf -d "<library>"
readelf --version-info "<library>"
ldd "<executable-or-library>"
```

Numerical and MPI packages also require a small compile, link, and execution
test. An install command returning zero does not by itself validate the
resulting interface.

## 7. Reconcretize affected unaccepted locks

The package recipe and patch content contribute to the concrete package
identity. Do not retry an unchanged lock as the released correction.

For a foundational dependency used by every environment on the compiler
surface, reconcretize all four locks:

```bash
for environment in core common serial "mpi-$PLATFORM_MPI_NAME"; do
  TARGET_ENV="$CSE_BUILD_WORKSPACE/environments/$PLATFORM_COMPILER_NAME/$environment"

  spack -e "$TARGET_ENV" spec -Il "<package>@<version>"
  spack -e "$TARGET_ENV" concretize -f --reuse-deps -j 1
  spack -e "$TARGET_ENV" spec -Il "<package>@<version>"
done
```

For a lane-specific package, reconcretize only the locks containing that
package. The corrected package and affected dependents may receive new hashes.
Unchanged dependencies should remain reusable. Stop if the package hash does
not change or if unrelated parts of the dependency graph change without an
explanation.

## 8. Verify and resume installation

Exit the prepared login shell, verify the updated locks, and resume the
affected surface from its approved compute allocation:

```bash
exit

cd "$CSE_BUILD_WORKSPACE"
./cse-build login verify
./cse-build compute install --surface platform
```

Use `--surface shared` instead when the correction belongs to the CSE-built
GCC surface. Do not run two installers for the same surface concurrently.

After installation, rerun the minimal reproducer and the package-specific
binary or runtime validation. Keep the old failed or incomplete prefix until
the corrected lock and validation evidence are complete. Do not remove a
prefix manually merely because its replacement installed successfully.

## 9. Return the correction to Stack Content

The workspace overlay is not the canonical source. Copy the validated package
directory into the matching Stack Content tree:

```text
pilots/cse-pilot/templates/package-repos/spack_repo/cse_trials/packages/<package-module>/
```

Add or update:

1. The subclassed `package.py`.
2. Every local patch referenced by the recipe.
3. A regression test that checks the affected condition and patch behavior.
4. The system runbook section containing the recovery and validation commands.

Run the pilot test suite before committing:

```bash
python3 -m unittest discover -s pilots/cse-pilot/tests
```

Review the staged diff, commit with the package and cause in the message, and
push the reviewed branch. Future workspace renders must receive the same
overlay without depending on changes retained only in an earlier workspace.

## On-system agent task contract

Use the following task text when assigning a package failure to an on-system
agent:

```text
Diagnose this Spack package failure inside the existing CSE trial workspace.

Constraints:

1. Do not modify Spack's builtin or cached package repository.
2. Do not alter an accepted or published release.
3. Preserve the original build log, concrete spec, hash, compiler, variants,
   environment, and failing command.
4. Create a deterministic command that reproduces the exact failure.
5. Generate three to five falsifiable hypotheses only after obtaining that
   reproducer. Test one variable at a time.
6. Place any package correction under
   $CSE_BUILD_WORKSPACE/package-repos/spack_repo/cse_trials/packages/<package-module>.
7. Subclass the builtin API v2 package recipe. Do not copy the complete builtin
   package.py.
8. Scope the correction to the verified package versions, variants, compiler,
   and architecture.
9. Do not use global compiler or linker flags as the final solution unless
   evidence from unrelated packages proves the behavior is compiler-wide.
10. Confirm that cse_trials precedes builtin with spack repo list.
11. Show the failing command before the correction and the same command passing
    afterward.
12. Reconcretize only affected, unaccepted locks with the trial's established
    -f --reuse-deps process.
13. Compare old and new hashes and verify that unrelated dependencies remain
    reusable.
14. Run ./cse-build login verify, install from the approved compute allocation,
    and perform package-specific binary or runtime validation.
15. Return package.py, patch files, test evidence, affected locks, hash changes,
    and exact recovery commands for inclusion in Stack Content.

Stop and request more evidence instead of guessing when the actual compiler or
linker diagnostic is absent.
```

## References

Spack's package repository documentation defines repository precedence,
namespace-qualified packages, API v2 imports, and subclassing builtin recipes:

<https://spack.readthedocs.io/en/latest/repositories.html>

Spack's environment documentation describes forced reconcretization of an
existing environment:

<https://spack.readthedocs.io/en/latest/environments.html>
