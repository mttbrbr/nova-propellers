"""Run with: python -m inverse_design.example"""

import numpy as np

from .geometry import BezierBladeGeometry, BezierControlPoints
from .optimizer import GeometryConstraints, InverseDesignOptimizer
from .solvers import BEMTSolver


def main() -> None:
    diameter = 0.25
    initial = BezierControlPoints(
        chord=np.array([[0.0, 0.026], [0.33, 0.029], [0.72, 0.016], [1.0, 0.006]]),
        twist=np.array([[0.0, 34.0], [0.33, 25.0], [0.72, 14.0], [1.0, 7.0]]),
    )
    geometry = BezierBladeGeometry(diameter_m=diameter, blades=2)
    bounds = (
        *((0.004, diameter * 0.16) for _ in range(4)),
        *((2.0, 45.0) for _ in range(4)),
    )
    optimizer = InverseDesignOptimizer(
        solver=BEMTSolver(reference_thrust_n=2.0),
        parameterization=geometry,
        initial_parameters=initial,
        constraints=GeometryConstraints(
            parameter_bounds=bounds,
            min_chord_m=0.004,
            max_chord_m=diameter * 0.16,
        ),
    )
    result = optimizer.optimize(target_thrust=2.0, rpm=5000)
    print("success:", result.success)
    print("thrust:", round(result.performance["thrust"], 3), "N")
    print("torque:", round(result.performance["torque"], 4), "Nm")
    print("chord control points:\n", result.parameters.chord)
    print("twist control points:\n", result.parameters.twist)


if __name__ == "__main__":
    main()
