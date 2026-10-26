#!/usr/bin/env bash
# Snapshot the worktree and build/install/test packages in disposable containers.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
qualification_dir="${NOVA_QUALIFICATION_DIR:-${project_root}/.desktop-tools/qualification}"
target="${1:-all}"
if [[ "${target}" != arch && "${target}" != ubuntu && "${target}" != all ]]; then
  echo 'Usage: tools/qualify_linux_packages.sh [arch|ubuntu|all]' >&2
  exit 2
fi
for command in podman python git; do
  command -v "${command}" >/dev/null
done
mkdir -p "${qualification_dir}"

# Include approved uncommitted changes without changing the source repository.
python - "${project_root}" "${qualification_dir}" "${target}" <<'PY'
import shutil
import subprocess
import sys
from pathlib import Path
root, output, target = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
files = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']).split(b'\0')
for distro in ('arch', 'ubuntu') if target == 'all' else (target,):
    destination = output / distro
    if destination.exists():
        raise SystemExit(f'{destination} already exists; choose a fresh NOVA_QUALIFICATION_DIR to preserve prior evidence')
    destination.mkdir()
    for raw in files:
        if not raw:
            continue
        relative = Path(raw.decode())
        source = root / relative
        if source.is_file():
            copied = destination / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
    subprocess.run(['git', 'init', '--quiet', str(destination)], check=True)
    subprocess.run(['git', '-C', str(destination), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(destination), '-c', 'user.name=NOVA package verification', '-c', 'user.email=local@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Isolated current-worktree package verification'], check=True)
PY

qualify_arch() {
  podman build --build-arg "USER_ID=$(id -u)" --build-arg "GROUP_ID=$(id -g)" \
    -t localhost/nova-arch-qualification -f "${project_root}/packaging/arch/Containerfile" "${project_root}/packaging/arch" \
    >"${qualification_dir}/arch-builder.log" 2>&1
  podman run --rm --userns keep-id --env CARGO_BUILD_JOBS=2 \
    -v "${qualification_dir}/arch:/workspace:Z" localhost/nova-arch-qualification \
    bash -lc './tools/package_arch.sh' >"${qualification_dir}/arch-build.log" 2>&1
  podman build -t localhost/nova-arch-runtime -f "${project_root}/packaging/qualification/arch.Containerfile" "${project_root}/packaging/qualification" \
    >"${qualification_dir}/arch-runtime-image.log" 2>&1
  podman run --rm --init \
    -v "${qualification_dir}/arch/packaging/arch:/packages:ro,Z" \
    -v "${project_root}/tools:/qualification/tools:ro,Z" localhost/nova-arch-runtime \
    bash -lc 'pacman -U --noconfirm /packages/*.pkg.tar.zst && ./tools/qualify_installed_desktop.sh' \
    >"${qualification_dir}/arch-installed.log" 2>&1
}
qualify_ubuntu() {
  podman build -t localhost/nova-ubuntu-qualification -f "${project_root}/packaging/deb/Containerfile" "${project_root}/packaging/deb" \
    >"${qualification_dir}/ubuntu-builder.log" 2>&1
  podman run --rm --env CARGO_BUILD_JOBS=2 \
    -v "${qualification_dir}/ubuntu:/workspace:Z" localhost/nova-ubuntu-qualification \
    bash -lc './tools/package_deb.sh && python3 tools/smoke_desktop_backend.py src-tauri/binaries/nova-backend-x86_64-unknown-linux-gnu && python3 tools/smoke_workflow_backend.py src-tauri/binaries/nova-backend-x86_64-unknown-linux-gnu && python3 tools/smoke_integrations_backend.py src-tauri/binaries/nova-backend-x86_64-unknown-linux-gnu' \
    >"${qualification_dir}/ubuntu-build.log" 2>&1
  podman build -t localhost/nova-ubuntu-runtime -f "${project_root}/packaging/qualification/ubuntu.Containerfile" "${project_root}/packaging/qualification" \
    >"${qualification_dir}/ubuntu-runtime-image.log" 2>&1
  podman run --rm --init \
    -v "${qualification_dir}/ubuntu/src-tauri/target/debian/release/bundle/deb:/packages:ro,Z" \
    -v "${project_root}/tools:/qualification/tools:ro,Z" localhost/nova-ubuntu-runtime \
    bash -lc 'apt-get update && apt-get install --yes /packages/*.deb && ./tools/qualify_installed_desktop.sh' \
    >"${qualification_dir}/ubuntu-installed.log" 2>&1
}
if [[ "${target}" == arch || "${target}" == all ]]; then qualify_arch; fi
if [[ "${target}" == ubuntu || "${target}" == all ]]; then qualify_ubuntu; fi
printf 'Package qualification passed; evidence: %s\n' "${qualification_dir}"
