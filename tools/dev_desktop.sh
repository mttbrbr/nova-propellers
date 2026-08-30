#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_port="${NOVA_DEV_BACKEND_PORT:-8765}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. On Arch, run: sudo pacman -S uv" >&2
  exit 1
fi

if [[ ! "${backend_port}" =~ ^[0-9]+$ ]] || ((backend_port < 1024 || backend_port > 65535)); then
  echo "NOVA_DEV_BACKEND_PORT must be a number between 1024 and 65535." >&2
  exit 1
fi

(
  cd "${project_root}/backend"
  exec uv run \
    --python 3.12 \
    --with-requirements requirements.lock \
    --no-project \
    python -m uvicorn main:app \
    --host 127.0.0.1 \
    --port "${backend_port}" \
    --reload
) &
backend_pid=$!

cleanup() {
  if kill -0 "${backend_pid}" 2>/dev/null; then
    kill "${backend_pid}" 2>/dev/null || true
    wait "${backend_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=/usr/bin/gcc \
CC=/usr/bin/gcc \
CXX=/usr/bin/g++ \
VITE_CACHE_DIR="${XDG_CACHE_HOME:-${HOME}/.cache}/nova-propellers/vite" \
NOVA_BACKEND_ENDPOINT="http://127.0.0.1:${backend_port}/api" \
  npm --prefix "${project_root}/frontend" run desktop:dev
