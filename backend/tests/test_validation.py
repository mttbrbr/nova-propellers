import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from pydantic import ValidationError

import database
from inverse_design import BEMTSolver, BezierBladeGeometry, BezierControlPoints
from polar_database import interpolate_polar
from validation import ConvergenceInfo
from validation.runner import validate_case
from validation.sensitivity import render_markdown
from validation.verification_report import render_markdown as render_verification_markdown


class ValidationTests(unittest.TestCase):
    def test_bemt_baseline_passes_all_declared_checks(self) -> None:
        path = Path(__file__).parents[1] / "validation" / "cases" / "bemt_baseline.json"
        case = json.loads(path.read_text(encoding="utf-8"))
        checks = validate_case(case)
        self.assertIn("power identity P = Q omega", checks)
        self.assertIn("golden regression values", checks)

    def test_converged_contract_rejects_residual_above_tolerance(self) -> None:
        with self.assertRaises(ValidationError):
            ConvergenceInfo(
                converged=True,
                iterations=20,
                residual=0.01,
                tolerance=0.001,
                termination_reason="tolerance_met",
            )

    def test_bemt_uses_explicit_numerical_controls(self) -> None:
        points = BezierControlPoints(
            chord=np.array([[0, 0.026], [0.33, 0.029], [0.72, 0.016], [1, 0.006]]),
            twist=np.array([[0, 34], [0.33, 25], [0.72, 14], [1, 7]]),
        )
        geometry = BezierBladeGeometry(0.25, 2, station_count=12).build(points)
        result = BEMTSolver(tolerance=1e-3, max_iterations=300).evaluate_detailed(
            geometry, 5000
        )
        self.assertEqual(result["convergence"]["tolerance"], 1e-3)
        self.assertLessEqual(result["convergence"]["iterations"], 300)
        self.assertEqual(
            result["convergence"]["diagnostics"]["relaxation_strategy"], "fixed"
        )
        self.assertEqual(
            result["convergence"]["diagnostics"]["history"][-1][
                "max_tangential_induction_ratio"
            ],
            0.75,
        )

    def test_nonconverged_bemt_has_actionable_diagnostics(self) -> None:
        points = BezierControlPoints(
            chord=np.array([[0, 0.026], [0.33, 0.029], [0.72, 0.016], [1, 0.006]]),
            twist=np.array([[0, 34], [0.33, 25], [0.72, 14], [1, 7]]),
        )
        geometry = BezierBladeGeometry(0.25, 2, station_count=12).build(points)
        result = BEMTSolver(tolerance=1e-12, max_iterations=2).evaluate_detailed(
            geometry, 5000
        )
        convergence = result["convergence"]
        self.assertFalse(convergence["converged"])
        self.assertIn(
            convergence["diagnostics"]["classification"],
            {"stagnation", "oscillation", "slow_convergence", "divergence"},
        )
        self.assertEqual(convergence["diagnostics"]["history"][-1]["iteration"], 2)
        final_sample = convergence["diagnostics"]["history"][-1]
        self.assertIn("limiting_alpha_deg", final_sample)
        self.assertIn("limiting_reynolds", final_sample)
        self.assertIn("polar_context", final_sample)
        self.assertEqual(len(final_sample["polar_context"]["alpha_segment_deg"]), 2)

    def test_adaptive_relaxation_is_recorded_and_bounded(self) -> None:
        points = BezierControlPoints(
            chord=np.array([[0, 0.026], [0.33, 0.029], [0.72, 0.016], [1, 0.006]]),
            twist=np.array([[0, 34], [0.33, 25], [0.72, 14], [1, 7]]),
        )
        geometry = BezierBladeGeometry(0.25, 2, station_count=12).build(points)
        result = BEMTSolver(
            tolerance=1e-4,
            max_iterations=300,
            relaxation_strategy="adaptive",
        ).evaluate_detailed(geometry, 5000)
        diagnostics = result["convergence"]["diagnostics"]
        self.assertEqual(diagnostics["relaxation_strategy"], "adaptive")
        self.assertGreaterEqual(diagnostics["minimum_relaxation_factor"], 0.02)
        self.assertLessEqual(diagnostics["maximum_relaxation_factor"], 0.3)

    def test_low_reynolds_strategies_are_finite_and_bounded(self) -> None:
        alpha = np.array([4.0, 4.0, 4.0])
        reynolds = np.array([10000.0, 20000.0, 29999.0])
        for strategy in ("clip", "linear_extrapolation", "smooth_transition"):
            cl, cd = interpolate_polar(
                "NACA 4412", alpha, reynolds, low_re_strategy=strategy
            )
            self.assertTrue(np.all(np.isfinite(cl)))
            self.assertTrue(np.all(np.isfinite(cd)))
            self.assertTrue(np.all(np.abs(cl) <= 2.0))
            self.assertTrue(np.all((cd >= 1e-5) & (cd <= 1.0)))

    def test_smooth_low_reynolds_transition_is_continuous_at_grid_boundary(self) -> None:
        alpha = np.array([4.0, 4.0])
        reynolds = np.array([29999.999, 30000.001])
        cl, cd = interpolate_polar(
            "NACA 4412", alpha, reynolds, low_re_strategy="smooth_transition"
        )
        self.assertLess(abs(cl[1] - cl[0]), 1e-6)
        self.assertLess(abs(cd[1] - cd[0]), 1e-6)

    def test_sensitivity_report_states_its_claim_boundary(self) -> None:
        report = {
            "study_id": "test-study",
            "assessment": {
                "passed": True,
                "evaluations": 1,
                "all_converged": True,
                "nonconverged_evaluations": 0,
                "classifications": {"converged": 1},
                "max_relative_error_at_finest_grid": 0.001,
            },
            "configuration": {
                "geometries": [{"id": "test"}],
                "rpm_values": [5000],
                "station_counts": [12],
                "solver_tolerances": [1e-5],
            },
            "results": [
                {
                    "geometry_id": "test",
                    "rpm": 5000,
                    "station_count": 12,
                    "solver_tolerance": 1e-5,
                    "thrust_n": 1.0,
                    "power_w": 10.0,
                    "iterations": 10,
                    "relative_error": {"thrust_n": 0.001},
                }
            ],
        }
        markdown = render_markdown(report)
        self.assertIn("not experimental validation", markdown)

    def test_consolidated_report_states_status_and_claim_boundary(self) -> None:
        report = {
            "passed": True,
            "claim": "Software verification; not experimental validation.",
            "supported_domain": {"solver": "bemt", "minimum_tolerance": 1e-5},
            "regression": {"passed": True},
            "sensitivity": {
                "passed": True,
                "assessment": {
                    "evaluations": 90,
                    "all_converged": True,
                    "max_relative_error_at_finest_grid": 0.003,
                },
            },
            "root_induction": {"passed": True, "recommended_ratio": 0.75},
        }
        markdown = render_verification_markdown(report)
        self.assertIn("Overall status: **PASS**", markdown)
        self.assertIn("does not establish predictive accuracy", markdown)

    def test_project_round_trip_preserves_convergence_diagnostics(self) -> None:
        original_path = database.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as directory:
                database.DB_PATH = Path(directory) / "validation-round-trip.db"
                database.init_database()
                diagnostics = {
                    "classification": "converged",
                    "history": [{"iteration": 1, "residual": 1e-6}],
                }
                analysis = {
                    "model": "bemt",
                    "summary": {"estimated_thrust_n": 1.0},
                    "convergence": {"converged": True, "diagnostics": diagnostics},
                }
                run_id = database.save_project_bundle(
                    "Diagnostics round trip",
                    {"airfoil": "NACA 4412", "propeller_type": "traditional"},
                    {"method": "bezier"},
                    [analysis],
                    b"stl",
                )
                restored = database.get_run(run_id)
                self.assertEqual(
                    restored["analyses"][0]["convergence"]["diagnostics"], diagnostics
                )
        finally:
            database.DB_PATH = original_path


if __name__ == "__main__":
    unittest.main()
