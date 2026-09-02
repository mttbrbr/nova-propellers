import unittest

import numpy as np

from inverse_design import (
    ActuatorDiskSolver,
    BEMTSolver,
    BezierBladeGeometry,
    BezierControlPoints,
    BoundaryElementSolver,
    GeometryConstraints,
    InverseDesignOptimizer,
    LLTSolver,
    VLMSolver,
    list_methods,
)


class InverseDesignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.points = BezierControlPoints(
            chord=np.array([[0, 0.026], [0.33, 0.029], [0.72, 0.016], [1, 0.006]]),
            twist=np.array([[0, 34], [0.33, 25], [0.72, 14], [1, 7]]),
        )
        self.parameterization = BezierBladeGeometry(0.25, 2, station_count=16)

    def test_geometry_vectors_are_canonical(self) -> None:
        geometry = self.parameterization.build(self.points)
        self.assertEqual(len(geometry.radius_m), 16)
        self.assertTrue(np.all(np.diff(geometry.radius_m) > 0))
        self.assertTrue(np.all(geometry.chord_m > 0))

    def test_solvers_share_the_same_contract(self) -> None:
        geometry = self.parameterization.build(self.points)
        for solver in (
            ActuatorDiskSolver(2.0),
            BEMTSolver(2.0),
            LLTSolver(),
            VLMSolver(),
            BoundaryElementSolver(),
        ):
            result = solver.evaluate(geometry, 5000)
            self.assertEqual(set(result), {"thrust", "torque", "efficiency"})
            self.assertTrue(all(np.isfinite(list(result.values()))))
            self.assertLessEqual(result["efficiency"], 1.0)

    def test_registry_exposes_every_computational_method(self) -> None:
        methods = list_methods()
        self.assertEqual(
            {method["id"] for method in methods},
            {"actuator_disk", "bemt", "llt", "vlm", "bem"},
        )
        actuator_disk = next(method for method in methods if method["id"] == "actuator_disk")
        self.assertEqual(actuator_disk["role"], "sizing_reference")
        self.assertIn("not a prediction", actuator_disk["warnings"][0])
        for method in methods:
            self.assertEqual(method["suitable_for"], ("traditional",))
            self.assertTrue(method["warnings"])

    def test_aerodynamic_methods_increase_thrust_with_rpm(self) -> None:
        geometry = self.parameterization.build(self.points)
        for solver in (BEMTSolver(2.0), LLTSolver(), VLMSolver(), BoundaryElementSolver()):
            low = solver.evaluate(geometry, 3500)["thrust"]
            high = solver.evaluate(geometry, 5000)["thrust"]
            self.assertGreater(high, low, type(solver).__name__)

    def test_bemt_analysis_is_independent_of_requested_thrust(self) -> None:
        geometry = self.parameterization.build(self.points)
        low_target = BEMTSolver(0.5).evaluate(geometry, 5000)
        high_target = BEMTSolver(20.0).evaluate(geometry, 5000)
        self.assertAlmostEqual(low_target["thrust"], high_target["thrust"], places=10)
        self.assertAlmostEqual(low_target["torque"], high_target["torque"], places=10)

    def test_bemt_detailed_result_reports_convergence(self) -> None:
        geometry = self.parameterization.build(self.points)
        result = BEMTSolver(2.0).evaluate_detailed(geometry, 5000)
        self.assertTrue(result["convergence"]["converged"])
        self.assertEqual(result["convergence"]["termination_reason"], "tolerance_met")
        self.assertLess(result["convergence"]["residual"], result["convergence"]["tolerance"])
        diagnostics = result["convergence"]["diagnostics"]
        self.assertEqual(diagnostics["classification"], "converged")
        self.assertGreater(len(diagnostics["history"]), 1)
        self.assertEqual(
            diagnostics["history"][-1]["iteration"], result["convergence"]["iterations"]
        )

    def test_optimizer_reduces_target_error(self) -> None:
        solver = BEMTSolver(2.0)
        geometry = self.parameterization.build(self.points)
        target = 2.0
        initial_error = ((solver.evaluate(geometry, 5000)["thrust"] - target) / target) ** 2
        constraints = GeometryConstraints(
            parameter_bounds=tuple([(0.004, 0.04)] * 4 + [(2.0, 45.0)] * 4),
            min_chord_m=0.004,
            max_chord_m=0.04,
        )
        result = InverseDesignOptimizer(
            solver,
            self.parameterization,
            self.points,
            constraints,
            options={"maxiter": 60},
        ).optimize(target, 5000)
        self.assertLess(result.loss, initial_error)
        self.assertGreaterEqual(result.geometry.chord_m.min(), constraints.min_chord_m)


if __name__ == "__main__":
    unittest.main()
