#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
package_dir="${project_root}/packaging/arch"
version="0.1.0-alpha.2"
archive="${package_dir}/nova-propellers-${version}.tar.gz"

git -C "${project_root}" archive \
  --format=tar.gz \
  --prefix="nova-propellers-${version}/" \
  --output="${archive}" \
  HEAD

(
  cd "${package_dir}"
  makepkg --cleanbuild --force
)

echo "Arch package created in ${package_dir}"
