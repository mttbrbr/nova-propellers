#!/usr/bin/env bash
# Run inside a disposable distribution runtime container after installation.
set -euo pipefail

executable="${1:-/usr/bin/nova-propellers}"
sidecar="${2:-/usr/bin/nova-backend}"

for binary in "${executable}" "${sidecar}"; do
  dependencies="$(ldd "${binary}")"
  if [[ "${dependencies}" == *'not found'* ]]; then
    printf '%s\n' "${dependencies}" >&2
    echo "Installed binary has unresolved shared libraries: ${binary}" >&2
    exit 1
  fi
done

if command -v dpkg-query >/dev/null; then
  dpkg-query -W -f='${Package}\n' nova-propellers | grep -qx nova-propellers
elif command -v pacman >/dev/null; then
  pacman -Q nova-propellers
fi

desktop_file="$(find /usr/share/applications -maxdepth 1 -iname '*nova*.desktop' -print -quit)"
[[ -n "${desktop_file}" ]]
desktop-file-validate "${desktop_file}"

# These settings are confined to the disposable headless test container.
# Nested WebKit sandboxing is not available in all rootless container kernels.
export WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1
export LIBGL_ALWAYS_SOFTWARE=1
export GDK_BACKEND=x11
export XDG_DATA_HOME=/tmp/nova-qualified-data
export XDG_CACHE_HOME=/tmp/nova-qualified-cache

unset NOVA_SESSION_TOKEN
./tools/smoke_installed_workflow.sh "${sidecar}"

export NOVA_DESKTOP_ENTRY="$(basename "${desktop_file}" .desktop)"
xvfb-run --auto-servernum env NOVA_XVFB_ACTIVE=1 dbus-run-session -- \
  ./tools/smoke_desktop_lifecycle.sh "${executable}"
