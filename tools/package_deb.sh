#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${project_root}"
npm ci --prefix frontend
./tools/build_desktop_backend.sh
npm --prefix frontend run desktop:build -- --bundles deb

echo "Debian package created in ${project_root}/src-tauri/target/release/bundle/deb"
