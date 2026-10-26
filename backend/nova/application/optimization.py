"""Existing inverse-design orchestration, usable without FastAPI."""
import copy

import numpy as np

from inverse_design import (
    BezierBladeGeometry,
    BezierControlPoints,
    GeometryConstraints,
    GeometryData,
    InverseDesignOptimizer,
    create_solver,
)
from nova.application.geometry import create_propeller_geometry
from nova.core.design import InverseDesignRequest


class WorkflowBezierGeometry(BezierBladeGeometry):
    """Use the exact geometry the guided/workflow views will later generate."""
    def __init__(self, inputs):
        self.inputs = copy.deepcopy(inputs)
        super().__init__(inputs['diameter'], inputs['blades'], inputs['airfoil'])

    def build(self, parameters):
        inputs = copy.deepcopy(self.inputs)
        inputs['geometry_parameters'] = {
            'chord_points': [{'x': float(x), 'y': float(y)} for x, y in parameters.chord],
            'twist_points': [{'x': float(x), 'y': float(y)} for x, y in parameters.twist],
        }
        return GeometryData.from_dict(create_propeller_geometry(inputs))


def run_inverse_design(settings, *, solver=None, progress=None, design_inputs=None):
    payload = InverseDesignRequest.model_validate(settings)
    chord = np.array(
        [[float(point["x"]), float(point["y"])] for point in payload.chord_points],
        dtype=float,
    )
    twist = np.array(
        [[float(point["x"]), float(point["y"])] for point in payload.twist_points],
        dtype=float,
    )
    initial = BezierControlPoints(chord=chord, twist=twist)
    parameterization = BezierBladeGeometry(
        diameter_m=payload.diameter,
        blades=payload.blades,
        airfoil=payload.airfoil,
        station_count=24 if payload.solver == "vlm" else 40,
    )
    if design_inputs is not None:
        parameterization = WorkflowBezierGeometry(design_inputs)
    max_chord = payload.max_chord_m or payload.diameter * 0.16
    bounds = (
        *((payload.min_chord_m, max_chord) for _ in range(len(chord))),
        *((payload.min_twist_deg, payload.max_twist_deg) for _ in range(len(twist))),
    )
    solver = solver or create_solver(payload.solver, target_thrust_n=payload.target_thrust)
    baseline = solver.evaluate_detailed(parameterization.build(initial), payload.rpm)
    baseline_valid = not baseline.get('convergence') or baseline['convergence']['converged']
    initial_performance = baseline['performance'] if baseline_valid else None
    optimizer = InverseDesignOptimizer(
        solver=solver,
        parameterization=parameterization,
        initial_parameters=initial,
        constraints=GeometryConstraints(
            parameter_bounds=bounds,
            min_chord_m=payload.min_chord_m,
            max_chord_m=max_chord,
            min_twist_deg=payload.min_twist_deg,
            max_twist_deg=payload.max_twist_deg,
        ),
        options={"maxiter": payload.max_iterations},
        progress_callback=progress,
    )
    result = optimizer.optimize(payload.target_thrust, payload.rpm)
    optimized = result.parameters
    return {
        "success": result.success,
        "message": result.message,
        "iterations": result.iterations,
        "loss": result.loss,
        "solver": payload.solver,
        "initial_performance": initial_performance,
        "initial_convergence": baseline.get('convergence'),
        "performance": result.performance,
        "geometry_parameters": {
            "chord_points": [
                {"x": float(x), "y": float(y)} for x, y in optimized.chord
            ],
            "twist_points": [
                {"x": float(x), "y": float(y)} for x, y in optimized.twist
            ],
        },
        "geometry": result.geometry.to_dict(),
    }
