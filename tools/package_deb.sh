#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CARGO_TARGET_DIR="${project_root}/src-tauri/target/debian"

cd "${project_root}"
npm ci --prefix frontend
./tools/build_desktop_backend.sh
npm --prefix frontend run desktop:build -- --bundles deb

echo "Debian package created in ${CARGO_TARGET_DIR}/release/bundle/deb"
