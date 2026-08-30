"""Linux desktop entrypoint for the bundled Nova FastAPI backend."""

from __future__ import annotations

import argparse
import os
import socket
from pathlib import Path

import uvicorn

LOOPBACK_HOST = "127.0.0.1"
ENDPOINT_PREFIX = "NOVA_BACKEND_ENDPOINT="


def default_data_dir() -> Path:
    data_home = os.getenv("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return root / "nova-propellers"


def configure_runtime(data_dir: Path | None = None) -> Path:
    resolved = (data_dir or default_data_dir()).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NOVA_DB_PATH", str(resolved / "nova.db"))
    return resolved


def bind_backend_socket(port: int = 0) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((LOOPBACK_HOST, port))
        listener.listen(2048)
        listener.set_inheritable(True)
    except Exception:
        listener.close()
        raise
    return listener


def run_backend(port: int = 0, data_dir: Path | None = None) -> int:
    configure_runtime(data_dir)
    listener = bind_backend_socket(port)
    selected_port = int(listener.getsockname()[1])

    # Import after configuring NOVA_DB_PATH: database.py resolves it at import time.
    from main import app

    endpoint = f"http://{LOOPBACK_HOST}:{selected_port}/api"
    print(f"{ENDPOINT_PREFIX}{endpoint}", flush=True)

    config = uvicorn.Config(
        app,
        host=LOOPBACK_HOST,
        port=selected_port,
        log_level=os.getenv("NOVA_LOG_LEVEL", "info"),
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
    return 0 if server.started else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Nova desktop backend on localhost")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("NOVA_BACKEND_PORT", "0")),
        help="loopback port; 0 selects a free port",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="persistent data directory (defaults to XDG_DATA_HOME/nova-propellers)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_backend(port=args.port, data_dir=args.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
