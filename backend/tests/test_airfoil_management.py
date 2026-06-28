import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from airfoil_management import AirfoilManager
from airfoil_management.example import _write_fake_dat
from inverse_design import (
    BEMTSolver,
    BezierBladeGeometry,
    BezierControlPoints,
    GeometryConstraints,
    InverseDesignOptimizer,
    OptimizationSafetyError,
)


class AirfoilManagementTests(unittest.TestCase):
    def test_dat_normalization_and_loft(self) -> None:
        with TemporaryDirectory() as directory:
            first = Path(directory) / "a.dat"
            second = Path(directory) / "b.dat"
            _write_fake_dat(first, 0.12)
            _write_fake_dat(second, 0.08)
            manager = AirfoilManager()
            profile_a = manager.read_dat(first)
            profile_b = manager.read_dat(second)
            self.assertEqual(profile_a.coordinates.shape, (100, 2))
            self.assertAlmostEqual(float(profile_a.coordinates[:, 0].min()), 0.0, places=6)
            self.assertAlmostEqual(float(profile_a.coordinates[:, 0].max()), 1.0, places=6)
            blended = manager.blend({0.2: profile_a, 1.0: profile_b}, 0.6)
            np.testing.assert_allclose(
                blended,
                0.5 * profile_a.coordinates + 0.5 * profile_b.coordinates,
                atol=1e-9,
            )

    def test_dynamic_bezier_is_allowed_manually_but_guarded_for_inverse_design(self) -> None:
        x = np.linspace(0.0, 1.0, 8)
        points = BezierControlPoints(
            chord=np.column_stack((x, np.linspace(0.028, 0.006, 8))),
            twist=np.column_stack((x, np.linspace(34.0, 7.0, 8))),
        )
        parameterization = BezierBladeGeometry(0.25, 2, station_count=16)
        self.assertEqual(len(parameterization.build(points).radius_m), 16)
        constraints = GeometryConstraints(
            parameter_bounds=tuple([(0.004, 0.04)] * 8 + [(2.0, 45.0)] * 8),
            min_chord_m=0.004,
            max_chord_m=0.04,
        )
        optimizer = InverseDesignOptimizer(
            BEMTSolver(2.0), parameterization, points, constraints
        )
        with self.assertRaisesRegex(OptimizationSafetyError, "chord=8, twist=8"):
            optimizer.optimize(2.0, 5000)


if __name__ == "__main__":
    unittest.main()
