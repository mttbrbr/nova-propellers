#!/usr/bin/env bash
set -euo pipefail

app_executable="${1:-nova-propellers}"
log_file="$(mktemp /tmp/nova-desktop-smoke.XXXXXX.log)"

for command_name in xvfb-run xdotool pgrep; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing lifecycle smoke-test dependency: ${command_name}" >&2
    exit 2
  fi
done

if pgrep --exact nova-backend >/dev/null; then
  echo "Refusing to run while another nova-backend process exists." >&2
  exit 2
fi

xvfb-run --auto-servernum "${app_executable}" >"${log_file}" 2>&1 &
desktop_pid=$!

cleanup() {
  if kill -0 "${desktop_pid}" 2>/dev/null; then
    kill "${desktop_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

backend_started=false
for _ in {1..30}; do
  if pgrep --parent "${desktop_pid}" nova-backend >/dev/null; then
    backend_started=true
    break
  fi
  if ! kill -0 "${desktop_pid}" 2>/dev/null; then
    break
  fi
  sleep 1
done

if [[ "${backend_started}" != true ]]; then
  echo "Tauri did not start the backend sidecar." >&2
  sed -n '1,120p' "${log_file}" >&2
  exit 1
fi

window_id=""
for _ in {1..30}; do
  window_id="$(xdotool search --name '^Nova Propellers$' 2>/dev/null | head -n 1 || true)"
  if [[ -n "${window_id}" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "${window_id}" ]]; then
  echo "Tauri did not show its window after backend readiness." >&2
  sed -n '1,120p' "${log_file}" >&2
  exit 1
fi

xdotool windowclose "${window_id}"
for _ in {1..20}; do
  if ! kill -0 "${desktop_pid}" 2>/dev/null; then
    break
  fi
  sleep 1
done

if kill -0 "${desktop_pid}" 2>/dev/null; then
  echo "Tauri did not exit after its window was closed." >&2
  exit 1
fi
wait "${desktop_pid}" || true

if pgrep --exact nova-backend >/dev/null; then
  echo "The backend sidecar remained alive after Tauri exited." >&2
  exit 1
fi

trap - EXIT
echo "Desktop lifecycle smoke test passed; log: ${log_file}"
