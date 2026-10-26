# Linux package qualification

The NOVA workflow increment has passed clean builds and runtime installation
checks on Arch Linux and Ubuntu 24.04. The environments are separate from
CachyOS and from each other; the Ubuntu package includes an Ubuntu-built sidecar.

## Verified checks

- Arch `.pkg.tar.zst` build, frozen backend/workflow smoke tests and Rust tests.
- Ubuntu 24.04 `.deb` build and frozen backend/workflow smoke tests.
- Installation into separate runtime containers using declared dependencies.
- Stable `nova-propellers` package identity and validated desktop entries.
- ELF shared-library resolution for installed desktop/backend executables.
- Native BEMT execution without system Python or development compilers.
- STL generation, project save/reopen and portable archive transfer.
- Launch through `gtk-launch`, virtual-display window readiness and clean exit.
- No backend surviving application shutdown.

Qualification artifacts and logs remain local in `.desktop-tools/qualification/`.
`report.json` records checks, paths and artifact hashes; `SHA256SUMS` records the
package checksums. They are generated evidence, not repository source files.

## Repeat the checks

The current OpenFAST increment passed Arch qualification on 2026-10-21 as
`nova-propellers 0.1.0.alpha.2-3`. It preserves package identity and application
data paths while distinguishing the update from the previous `-2` build.
Evidence: `.desktop-tools/qualification/openfast-integration-report.json` and
`OPENFAST_INTEGRATION_SHA256SUMS`. The previous package and evidence are preserved
in `archives/workflow-expansion-5575294749d6/`. Ubuntu remains at its earlier integration
increment; its artifact does not contain these later UI/workflow changes.

Checks cover three frozen backend smoke tests, five Rust tests, installed
two-axis studies and frozen configuration comparisons, shared geometry/history,
portable external archives with exact original-source comparison, saved PyWake
inputs without an optional interpreter, ELF dependencies, desktop launcher and
clean shutdown. OpenFAST case inspection is checked against the installed
backend without requiring OpenFAST. Separate host tests with independently
installed OpenFAST 5.0.0 compare direct execution and NOVA source/frozen
execution; no external solver or official case is included in the package or
mounted into its clean runtime container. The generated local sidecar matches
the qualified source binary.
Makepkg reports embedded build-source references; installed runtime tests pass
in a container without the builder source directory. Byte-identical builds and
physical GPU/Wayland compatibility remain unverified.

From the repository directory, after closing NOVA, install/update manually:

```sh
sudo pacman -U .desktop-tools/qualification/arch/packaging/arch/nova-propellers-0.1.0.alpha.2-3-x86_64.pkg.tar.zst
```

Qualification did not install a package on the development host.
The final disposable Arch runtime required `jq` and `diffutils` for the test
harness; neither is an added NOVA dependency. Earlier missing-tool attempts and
the passing retry are recorded separately. No Python interpreter, compiler or
OpenFAST executable was present in that runtime.

The shared-geometry/unified-command increment passed clean Arch build and full
installed runtime qualification on 2026-10-11, tracked separately in
`.desktop-tools/qualification/shared-geometry-report.json`. Its backend checks
include immutable geometry revisions, selected adoption, historical results and
archive remapping; current frontend checks include one Save/Run command set,
responsive layouts and study cancellation across workspace/project changes.
The preceding project-simulation package is preserved under
`.desktop-tools/qualification/archives/project-simulations-6802d9d25b7f/` before
replacement. Ubuntu remains at the integration increment. Refer to that increment's
report and `SHARED_GEOMETRY_SHA256SUMS` for the qualified artifact. Three frozen
backend smoke tests, five Rust tests, native/integration execution, ELF dependency
checks, `gtk-launch` and shutdown passed. No package was installed on the host.

The named project-simulation increment passed a new clean Arch build and full
installed runtime qualification on 2026-10-11. Checks cover BEMT/LLT configuration
isolation, archive remapping, native/integration smoke tests, five Rust tests,
ELF dependencies, desktop launch and shutdown. The refreshed frozen sidecar also
passed the named-simulation workflow smoke on the host. Current Arch evidence:
`.desktop-tools/qualification/project-simulations-report.json` and
`PROJECT_SIMULATIONS_SHA256SUMS`. Ubuntu has not been rebuilt for this increment
and remains at the earlier integration version. No package was installed on the
development host during qualification.

The PyWake/OpenFAST integration increment also passed Arch and Ubuntu 24.04
qualification on 2026-10-11. Three frozen backend smoke tests and installed
runtime tests cover the native workflow, OpenFAST import, external execution
fixtures, CSV/artifacts, desktop launcher and clean shutdown. The host frozen
sidecar additionally passed with real PyWake 2.6.20 in a separate environment.
That integration increment used an official binary sample and original process
fixtures, without real OpenFAST execution. On 2026-10-21, source and rebuilt
Arch frozen backends separately passed a real OpenFAST 5.0.0 AOC case on the
host: 101 samples × 30 channels exactly matched independent direct execution.
OpenFAST, official inputs and numerical artifacts remain outside NOVA's
repository, packages and clean runtime containers. This qualifies one case's
execution path, not physical model accuracy or other solver configurations.
Evidence and current hashes are recorded in
`.desktop-tools/qualification/integrations-report.json` and
`INTEGRATIONS_SHA256SUMS`. Qualification images include `diffutils` solely for
raw-source comparison tests; it is not an application dependency.

The Studies/adapter-framework increment was requalified on 2026-10-11 for both
Arch and Ubuntu 24.04. Checks additionally exercise a frozen BEMT sweep,
stored-result comparison and archive round trip. Final artifact/source hashes
and logs are recorded separately in
`.desktop-tools/qualification/studies-resume-report.json` and
`STUDIES_SHA256SUMS`. The local sidecar was refreshed from the final Arch build
and passed the workflow smoke on the development host. Earlier `report.json`
and `SHA256SUMS` describe the preceding milestone.

With Podman, Git and Python available on the development host:

```sh
NOVA_QUALIFICATION_DIR="$PWD/.desktop-tools/qualification-next" \
  ./tools/qualify_linux_packages.sh all
```

Use `arch` or `ubuntu` to qualify one target. Choose a fresh directory: the
script preserves existing evidence. It snapshots tracked and untracked source
files permitted by Git ignore rules, creates a commit only in the isolated
checkout, and leaves the original repository/index untouched.

Runtime recipes are in `packaging/qualification/`. Installation checks use
`tools/qualify_installed_desktop.sh` and `tools/smoke_installed_workflow.sh`.
The latter uses curl/jq to exercise the packaged backend, so a system Python
installation cannot conceal a missing bundled runtime.

## Identity and test limitations

Tauri derives the Debian package name from `productName`. Keep that value
`Nova Propellers` during the identity-preserving migration; changing it to
`NOVA` produces a different `nova` package and breaks the intended upgrade path.
The window title and custom desktop template display NOVA. Executable names,
application identifier and data locations remain unchanged.

Headless test containers use software rendering and disable nested WebKit
sandboxing because it is unavailable on some rootless-container kernels. Those
settings are confined to qualification scripts and are not shipped application
runtime defaults. An init process reaps children launched through GTK.

These checks establish build/install/runtime functionality, not predictive
scientific qualification, physical Wayland/GPU-driver compatibility, or
byte-identical reproducible builds. Arch rolling-release and Ubuntu baseline
artifacts are distinct; do not substitute a CachyOS-built sidecar into the
Ubuntu bundle. Keep optional external scientific software outside the package.
