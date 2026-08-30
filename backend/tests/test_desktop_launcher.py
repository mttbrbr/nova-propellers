import os
import selectors
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_launcher import ENDPOINT_PREFIX, bind_backend_socket, default_data_dir


class DesktopLauncherTests(unittest.TestCase):
    def test_dynamic_socket_is_loopback_only(self) -> None:
        listener = bind_backend_socket()
        try:
            host, port = listener.getsockname()
            self.assertEqual(host, "127.0.0.1")
            self.assertGreater(port, 0)
        finally:
            listener.close()

    def test_occupied_port_is_rejected(self) -> None:
        listener = bind_backend_socket()
        try:
            port = int(listener.getsockname()[1])
            with self.assertRaises(OSError):
                bind_backend_socket(port)
        finally:
            listener.close()

    def test_xdg_data_directory(self) -> None:
        with TemporaryDirectory() as directory:
            previous = os.environ.get("XDG_DATA_HOME")
            os.environ["XDG_DATA_HOME"] = directory
            try:
                self.assertEqual(default_data_dir(), Path(directory) / "nova-propellers")
            finally:
                if previous is None:
                    os.environ.pop("XDG_DATA_HOME", None)
                else:
                    os.environ["XDG_DATA_HOME"] = previous

    def test_standalone_process_health_and_shutdown(self) -> None:
        with TemporaryDirectory() as directory:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "desktop_launcher.py",
                    "--port",
                    "0",
                    "--data-dir",
                    directory,
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                endpoint = self._read_endpoint(process)
                with urllib.request.urlopen(f"{endpoint}/health", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b'{"status":"ok"}')
            finally:
                process.terminate()
                process.wait(timeout=5)
            self.assertIsNotNone(process.returncode)

    @staticmethod
    def _read_endpoint(process: subprocess.Popen[str]) -> str:
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + 15
        output = []
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            for key, _ in selector.select(timeout=0.2):
                line = key.fileobj.readline()
                output.append(line)
                if line.startswith(ENDPOINT_PREFIX):
                    return line.removeprefix(ENDPOINT_PREFIX).strip()
        raise AssertionError(f"backend did not report its endpoint: {''.join(output)}")


if __name__ == "__main__":
    unittest.main()
