from functools import lru_cache
from pathlib import Path

import numpy as np

REYNOLDS_GRID = np.asarray([30000.0, 60000.0, 100000.0, 200000.0, 500000.0])
ALPHA_GRID = np.asarray([-8.0, -4.0, 0.0, 4.0, 8.0, 12.0, 16.0])

# Synthetic parameters for UI demonstration and software tests only. They are
# not measurements and are not derived from XFOIL, CFD or wind-tunnel data.
SYNTHETIC_POLAR_PARAMETERS = {
    "NACA 0012": {"cl0": 0.00, "slope": 0.092, "clmax": 1.05, "cd0": 0.014, "cm0": 0.000},
    "NACA 2412": {"cl0": 0.22, "slope": 0.098, "clmax": 1.18, "cd0": 0.015, "cm0": -0.055},
    "NACA 4412": {"cl0": 0.42, "slope": 0.103, "clmax": 1.28, "cd0": 0.016, "cm0": -0.095},
    "NACA 6409": {"cl0": 0.55, "slope": 0.096, "clmax": 1.22, "cd0": 0.013, "cm0": -0.120},
}


def interpolate_polar(
    airfoil_name: str,
    alpha_deg: np.ndarray,
    reynolds: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    table = _load_polar_table(airfoil_name)
    alpha = np.clip(alpha_deg, ALPHA_GRID[0], ALPHA_GRID[-1])
    re = np.clip(reynolds, REYNOLDS_GRID[0], REYNOLDS_GRID[-1])

    cl_by_re = np.vstack(
        [np.interp(alpha, ALPHA_GRID, table["cl"][row_index]) for row_index in range(len(REYNOLDS_GRID))]
    )
    cd_by_re = np.vstack(
        [np.interp(alpha, ALPHA_GRID, table["cd"][row_index]) for row_index in range(len(REYNOLDS_GRID))]
    )

    cl = _interp_reynolds(cl_by_re, re)
    cd = _interp_reynolds(cd_by_re, re)
    return cl, cd


def _interp_reynolds(values_by_re: np.ndarray, reynolds: np.ndarray) -> np.ndarray:
    output = np.empty_like(reynolds, dtype=float)
    for index, re_value in np.ndenumerate(reynolds):
        output[index] = np.interp(re_value, REYNOLDS_GRID, values_by_re[:, index[0]])
    return output


@lru_cache(maxsize=16)
def _load_polar_table(airfoil_name: str) -> dict[str, np.ndarray]:
    db_table = _load_database_table(airfoil_name)
    if db_table is not None:
        return db_table
    csv_table = _load_csv_table(airfoil_name)
    if csv_table is not None:
        return csv_table
    return build_seed_table(airfoil_name)


def clear_cache() -> None:
    _load_polar_table.cache_clear()


def _load_database_table(airfoil_name: str) -> dict[str, np.ndarray] | None:
    try:
        from database import get_polar_table

        return get_polar_table(airfoil_name)
    except Exception:
        return None


def _load_csv_table(airfoil_name: str) -> dict[str, np.ndarray] | None:
    safe_name = airfoil_name.lower().replace(" ", "_")
    path = Path(__file__).with_name("polars") / f"{safe_name}.csv"
    if not path.exists():
        return None

    rows = np.genfromtxt(path, delimiter=",", names=True)
    cl = np.zeros((len(REYNOLDS_GRID), len(ALPHA_GRID)))
    cd = np.zeros((len(REYNOLDS_GRID), len(ALPHA_GRID)))

    for re_index, re_value in enumerate(REYNOLDS_GRID):
        re_rows = rows[np.isclose(rows["re"], re_value)]
        if len(re_rows) == 0:
            return None
        cl[re_index] = np.interp(ALPHA_GRID, re_rows["alpha_deg"], re_rows["cl"])
        cd[re_index] = np.interp(ALPHA_GRID, re_rows["alpha_deg"], re_rows["cd"])

    return {"cl": cl, "cd": cd}


def build_seed_table(airfoil_name: str) -> dict[str, np.ndarray]:
    seed = SYNTHETIC_POLAR_PARAMETERS.get(
        airfoil_name, SYNTHETIC_POLAR_PARAMETERS["NACA 4412"]
    )
    cl_table = []
    cd_table = []
    cm_table = []

    for reynolds in REYNOLDS_GRID:
        re_factor = np.clip((np.log10(reynolds) - 4.35) / 0.95, 0.62, 1.06)
        stall_alpha = 13.5 - 4.0 * (1.0 - re_factor)
        clmax = seed["clmax"] * re_factor
        cd0 = seed["cd0"] + np.clip(90000.0 / reynolds, 0.0, 2.0) * 0.004
        cl_row = []
        cd_row = []
        cm_row = []

        for alpha in ALPHA_GRID:
            cl_linear = seed["cl0"] * re_factor + seed["slope"] * alpha * re_factor
            cl = np.clip(cl_linear, -0.55 * re_factor, clmax)
            if abs(alpha) > stall_alpha:
                cl *= np.clip(stall_alpha / max(abs(alpha), 1e-6), 0.58, 1.0)
            stall_drag = max(abs(alpha) / max(stall_alpha, 1e-6) - 1.0, 0.0) * 0.045
            cd = cd0 + 0.020 * cl**2 + stall_drag
            cm = seed["cm0"] - 0.004 * alpha + 0.012 * max(abs(alpha) - stall_alpha, 0.0)
            cl_row.append(cl)
            cd_row.append(cd)
            cm_row.append(cm)

        cl_table.append(cl_row)
        cd_table.append(cd_row)
        cm_table.append(cm_row)

    return {"cl": np.asarray(cl_table), "cd": np.asarray(cd_table), "cm": np.asarray(cm_table)}
