"""Small deterministic comparison harness for all computational methods.

Run with: python -m inverse_design.benchmark
This is a software/physics sanity check, not experimental validation.
"""

import numpy as np

from .geometry import BezierBladeGeometry, BezierControlPoints
from .solvers import create_solver, list_methods


def main() -> None:
    points = BezierControlPoints(
        chord=np.array([[0, 0.026], [0.33, 0.029], [0.72, 0.016], [1, 0.006]]),
        twist=np.array([[0, 34], [0.33, 25], [0.72, 14], [1, 7]]),
    )
    geometry = BezierBladeGeometry(0.25, 2, station_count=18).build(points)
    print(f"{'method':<18} {'thrust [N]':>12} {'torque [Nm]':>13} {'efficiency':>12}")
    for descriptor in list_methods():
        solver = create_solver(descriptor["id"], target_thrust_n=2.0)
        result = solver.evaluate(geometry, 5000)
        print(
            f"{descriptor['id']:<18} {result['thrust']:>12.4f} "
            f"{result['torque']:>13.6f} {result['efficiency']:>12.4f}"
        )


if __name__ == "__main__":
    main()
