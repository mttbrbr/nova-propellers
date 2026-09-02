"""Adapter and conservative acquisition helpers for official UIUC text files."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

import numpy as np

from inverse_design.geometry import GeometryData
from validation.experimental import ExperimentalPoint, ExperimentalSeries


class UIUCVolume1Adapter:
    dataset = "UIUC Propeller Database, Volume 1, version 3"

    @staticmethod
    def _rows(path: Path, columns: int) -> list[list[float]]:
        if not path.is_file():
            raise FileNotFoundError(f"Required local UIUC file is missing: {path}")
        rows = []
        for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped[0].isalpha():
                continue
            try:
                row = [float(value) for value in stripped.split()]
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: non-numeric UIUC row") from exc
            if len(row) != columns:
                raise ValueError(f"{path}:{line_number}: expected {columns} columns")
            rows.append(row)
        if not rows:
            raise ValueError(f"No data rows found in {path}")
        return rows

    def parse_dynamic(self, path: Path, *, rpm: float, provenance: dict) -> ExperimentalSeries:
        points = tuple(ExperimentalPoint(j, ct, cp, eta, rpm) for j, ct, cp, eta in self._rows(path, 4))
        return ExperimentalSeries(self.dataset, provenance["case_id"], provenance["propeller_id"], points, provenance)

    def parse_geometry(self, path: Path, *, diameter_m: float, blades: int, airfoil: str) -> GeometryData:
        rows = self._rows(path, 3)
        fraction, chord_ratio, beta_deg = np.asarray(rows, dtype=float).T
        radius = diameter_m / 2
        return GeometryData(
            radius_m=fraction * radius,
            chord_m=chord_ratio * radius,
            twist_rad=np.radians(beta_deg),
            diameter_m=diameter_m,
            blades=blades,
            airfoil=airfoil,
        )


def acquire(url: str, destination: Path) -> dict:
    """Download one declared official file, refusing silent replacement."""
    if destination.exists():
        raise FileExistsError(f"Refusing to replace existing file: {destination}")
    if not url.startswith("https://m-selig.ae.illinois.edu/props/"):
        raise ValueError("UIUC acquisition accepts only the declared official HTTPS host/path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - allowlisted above
            payload = response.read()
        destination.write_bytes(payload)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"path": str(destination), "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
