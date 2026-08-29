import unittest

from fastapi import HTTPException

from main import (
    AnalysisRequest,
    GeometryRequest,
    computational_methods,
    create_geometry,
    download_geometry,
    run_analysis,
)


class ApiContractTests(unittest.TestCase):
    @staticmethod
    def geometry_payload(propeller_type: str = "traditional") -> dict:
        return {
            "project_name": "Contract test",
            "propeller_type": propeller_type,
            "thrust_target": 2.0,
            "rpm": 5000,
            "diameter": 0.25,
            "blades": 2,
            "airfoil": "NACA 4412",
            "geometry_method": "bezier",
            "geometry_parameters": {
                "chord_points": [
                    {"x": 0.0, "y": 0.026},
                    {"x": 0.33, "y": 0.029},
                    {"x": 0.72, "y": 0.016},
                    {"x": 1.0, "y": 0.006},
                ],
                "twist_points": [
                    {"x": 0.0, "y": 34.0},
                    {"x": 0.33, "y": 25.0},
                    {"x": 0.72, "y": 14.0},
                    {"x": 1.0, "y": 7.0},
                ],
            },
        }

    def test_methods_distinguish_sizing_reference_from_analysis(self) -> None:
        methods = computational_methods()
        actuator_disk = next(method for method in methods if method["id"] == "actuator_disk")
        self.assertEqual(actuator_disk["role"], "sizing_reference")
        self.assertEqual(actuator_disk["fidelity"], "ideal_reference")
        self.assertTrue(actuator_disk["warnings"])

    def test_toroidal_geometry_and_stl_are_consistently_rejected(self) -> None:
        request = GeometryRequest(**self.geometry_payload("toroidal"))
        for operation in (create_geometry, download_geometry):
            with self.assertRaises(HTTPException) as raised:
                operation(request)
            self.assertEqual(raised.exception.status_code, 501)

    def test_analysis_exposes_units_maturity_and_convergence(self) -> None:
        inputs = GeometryRequest(**self.geometry_payload())
        geometry = create_geometry(inputs)["geometry"]
        result = run_analysis(AnalysisRequest(model="bemt", inputs=inputs, geometry=geometry))
        self.assertEqual(result["solver"]["version"], "0.1.0-alpha.2")
        self.assertEqual(result["fidelity"], "preliminary")
        self.assertEqual(result["units"]["thrust"], "N")
        self.assertTrue(result["warnings"])
        self.assertIsInstance(result["convergence"]["converged"], bool)
        self.assertIn("residual", result["convergence"])
        if not result["convergence"]["converged"]:
            self.assertIn("did not converge", result["warnings"][-1])


if __name__ == "__main__":
    unittest.main()
