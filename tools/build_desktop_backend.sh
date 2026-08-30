#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_dir="${project_root}/backend"
venv_dir="${backend_dir}/.venv-desktop"
python_bin="${NOVA_DESKTOP_PYTHON:-python3.12}"

if ! command -v "${python_bin}" >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    python_bin="$(uv python find 3.12 2>/dev/null || true)"
  fi
fi

if [[ -z "${python_bin}" || ! -x "$(command -v "${python_bin}" 2>/dev/null || printf '%s' "${python_bin}")" ]]; then
  echo "Python 3.12 is required. On Arch, run: uv python install 3.12" >&2
  exit 1
fi

"${python_bin}" -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --disable-pip-version-check \
  --requirement "${backend_dir}/requirements-desktop.txt"

rm -rf "${backend_dir}/build" "${backend_dir}/dist"
(
  cd "${backend_dir}"
  "${venv_dir}/bin/pyinstaller" \
    --noconfirm \
    --clean \
    --onefile \
    --name nova-backend \
    --paths . \
    --hidden-import trimesh.exchange.stl \
    desktop_launcher.py
)

target_triple="${NOVA_TAURI_TARGET:-$(rustc -vV | sed -n 's/^host: //p')}"
destination="${project_root}/src-tauri/binaries/nova-backend-${target_triple}"
install -Dm755 "${backend_dir}/dist/nova-backend" "${destination}"
echo "Desktop backend sidecar: ${destination}"
