"""Run with: python -m airfoil_management.example"""

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from inverse_design import (
    BEMTSolver,
    BezierBladeGeometry,
    BezierControlPoints,
    GeometryConstraints,
    InverseDesignOptimizer,
    OptimizationSafetyError,
)

from .manager import AirfoilManager


def _write_fake_dat(path: Path, thickness: float) -> None:
    beta = np.linspace(0.0, np.pi, 41)
    x = 0.5 * (1.0 - np.cos(beta))
    y = 5.0 * thickness * (
        0.2969 * np.sqrt(x)
        - 0.1260 * x
        - 0.3516 * x**2
        + 0.2843 * x**3
        - 0.1015 * x**4
    )
    coordinates = np.vstack((
        np.column_stack((x[::-1], y[::-1])),
        np.column_stack((x[1:], -y[1:])),
    ))
    lines = [path.stem, *(f"{px:.8f} {py:.8f}" for px, py in coordinates)]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    manager = AirfoilManager(normalized_point_count=100)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        first_path = root / "Profilo_A.dat"
        second_path = root / "Profilo_B.dat"
        _write_fake_dat(first_path, thickness=0.12)
        _write_fake_dat(second_path, thickness=0.08)

        profile_a = manager.read_dat(first_path)
        profile_b = manager.read_dat(second_path)
        section = manager.blend({0.2: profile_a, 1.0: profile_b}, 0.6)
        print("Normalized profiles:", profile_a.coordinates.shape, profile_b.coordinates.shape)
        print("Blended section at r/R=0.6:", section.shape)

        x = np.linspace(0.0, 1.0, 8)
        eight_points = BezierControlPoints(
            chord=np.column_stack((x, np.linspace(0.028, 0.006, 8))),
            twist=np.column_stack((x, np.linspace(34.0, 7.0, 8))),
        )
        parameterization = BezierBladeGeometry(0.25, 2)
        constraints = GeometryConstraints(
            parameter_bounds=tuple([(0.004, 0.04)] * 8 + [(2.0, 45.0)] * 8),
            min_chord_m=0.004,
            max_chord_m=0.04,
        )
        optimizer = InverseDesignOptimizer(
            BEMTSolver(reference_thrust_n=2.0),
            parameterization,
            eight_points,
            constraints,
        )
        try:
            optimizer.optimize(target_thrust=2.0, rpm=5000)
        except OptimizationSafetyError as warning:
            print("SAFETY WARNING:", warning)


if __name__ == "__main__":
    main()
