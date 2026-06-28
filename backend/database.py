import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

from polar_database import AIRFOIL_POLAR_SEEDS, ALPHA_GRID, REYNOLDS_GRID, build_seed_table


DB_PATH = Path(os.getenv("NOVA_DB_PATH", "/app/data/nova.db"))


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS airfoils (
                name TEXT PRIMARY KEY,
                family TEXT NOT NULL,
                camber REAL NOT NULL,
                thickness REAL NOT NULL,
                source TEXT NOT NULL,
                notes TEXT NOT NULL,
                coordinates_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS polar_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                airfoil_name TEXT NOT NULL,
                label TEXT NOT NULL,
                source TEXT NOT NULL,
                method TEXT NOT NULL,
                mach REAL NOT NULL,
                ncrit REAL NOT NULL,
                notes TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (airfoil_name) REFERENCES airfoils(name)
            );

            CREATE TABLE IF NOT EXISTS polar_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                polar_set_id INTEGER,
                airfoil_name TEXT NOT NULL,
                reynolds REAL NOT NULL,
                mach REAL NOT NULL DEFAULT 0.03,
                ncrit REAL NOT NULL DEFAULT 9.0,
                alpha_deg REAL NOT NULL,
                cl REAL NOT NULL,
                cd REAL NOT NULL,
                cm REAL NOT NULL DEFAULT 0.0,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (polar_set_id, reynolds, alpha_deg),
                FOREIGN KEY (polar_set_id) REFERENCES polar_sets(id),
                FOREIGN KEY (airfoil_name) REFERENCES airfoils(name)
            );

            CREATE TABLE IF NOT EXISTS propeller_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                design_mode TEXT NOT NULL,
                airfoil TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        _migrate_polar_points(connection)
        _migrate_propeller_runs(connection)
        _migrate_airfoils(connection)

    seed_default_airfoils()


def _migrate_airfoils(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(airfoils)").fetchall()
    }
    if "coordinates_json" not in columns:
        connection.execute("ALTER TABLE airfoils ADD COLUMN coordinates_json TEXT")


def _migrate_propeller_runs(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(propeller_runs)").fetchall()
    }
    additions = {
        "propeller_type": "TEXT NOT NULL DEFAULT 'traditional'",
        "geometry_method": "TEXT NOT NULL DEFAULT 'legacy'",
        "geometry_json": "TEXT",
        "analyses_json": "TEXT",
        "stl_blob": "BLOB",
        "schema_version": "INTEGER NOT NULL DEFAULT 1",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE propeller_runs ADD COLUMN {name} {definition}")


def _migrate_polar_points(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(polar_points)").fetchall()
    }
    if {"polar_set_id", "mach", "ncrit", "cm"}.issubset(columns):
        return

    connection.execute("ALTER TABLE polar_points RENAME TO polar_points_legacy")
    connection.execute(
        """
        CREATE TABLE polar_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            polar_set_id INTEGER,
            airfoil_name TEXT NOT NULL,
            reynolds REAL NOT NULL,
            mach REAL NOT NULL DEFAULT 0.03,
            ncrit REAL NOT NULL DEFAULT 9.0,
            alpha_deg REAL NOT NULL,
            cl REAL NOT NULL,
            cd REAL NOT NULL,
            cm REAL NOT NULL DEFAULT 0.0,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (polar_set_id, reynolds, alpha_deg),
            FOREIGN KEY (polar_set_id) REFERENCES polar_sets(id),
            FOREIGN KEY (airfoil_name) REFERENCES airfoils(name)
        )
        """
    )

    legacy_airfoils = connection.execute(
        "SELECT DISTINCT airfoil_name, source FROM polar_points_legacy"
    ).fetchall()
    set_ids = {}
    for row in legacy_airfoils:
        source = row["source"] or "legacy"
        cursor = connection.execute(
            """
            INSERT INTO polar_sets (airfoil_name, label, source, method, mach, ncrit, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["airfoil_name"],
                f"{source} migrated",
                source,
                "legacy",
                0.03,
                9.0,
                "Migrated from the original single-table polar storage.",
                _now(),
            ),
        )
        set_ids[row["airfoil_name"]] = int(cursor.lastrowid)

    legacy_rows = connection.execute("SELECT * FROM polar_points_legacy").fetchall()
    for row in legacy_rows:
        connection.execute(
            """
            INSERT OR IGNORE INTO polar_points
            (polar_set_id, airfoil_name, reynolds, mach, ncrit, alpha_deg, cl, cd, cm, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                set_ids.get(row["airfoil_name"]),
                row["airfoil_name"],
                float(row["reynolds"]),
                0.03,
                9.0,
                float(row["alpha_deg"]),
                float(row["cl"]),
                float(row["cd"]),
                0.0,
                row["source"],
                row["created_at"],
            ),
        )

    connection.execute("DROP TABLE polar_points_legacy")


def seed_default_airfoils() -> None:
    with connect() as connection:
        existing = {
            row["name"]
            for row in connection.execute("SELECT name FROM airfoils").fetchall()
        }
        now = _now()

        for name, seed in AIRFOIL_POLAR_SEEDS.items():
            if name not in existing:
                connection.execute(
                    """
                    INSERT INTO airfoils (name, family, camber, thickness, source, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        "NACA 4-digit",
                        _infer_camber(name),
                        _infer_thickness(name),
                        "internal_seed_xfoil_style",
                        "Seeded tabulated polar. Replace with imported XFOIL or wind-tunnel CSV for production use.",
                        now,
                    ),
                )

            point_count = connection.execute(
                "SELECT COUNT(*) AS count FROM polar_points WHERE airfoil_name = ?",
                (name,),
            ).fetchone()["count"]
            if point_count == 0:
                table = build_seed_table(name)
                polar_set_id = _create_polar_set(
                    connection,
                    name,
                    label="Seeded low-Re table",
                    source="internal_seed_xfoil_style",
                    method="seed",
                    mach=0.03,
                    ncrit=9.0,
                    notes="Synthetic startup table. Replace with imported XFOIL, CFD or wind-tunnel data for production use.",
                )
                _insert_polar_table(
                    connection,
                    polar_set_id,
                    name,
                    table,
                    "internal_seed_xfoil_style",
                    0.03,
                    9.0,
                )


def list_airfoils() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT
                a.name,
                a.family,
                a.camber,
                a.thickness,
                a.source,
                a.notes,
                a.created_at,
                COUNT(p.id) AS polar_points,
                COUNT(DISTINCT ps.id) AS polar_sets,
                MIN(p.reynolds) AS min_reynolds,
                MAX(p.reynolds) AS max_reynolds,
                CASE WHEN a.coordinates_json IS NULL THEN 0 ELSE 1 END AS has_coordinates
            FROM airfoils a
            LEFT JOIN polar_points p ON p.airfoil_name = a.name
            LEFT JOIN polar_sets ps ON ps.airfoil_name = a.name
            GROUP BY a.name
            ORDER BY a.name
            """
        ).fetchall()
        return [dict(row) for row in rows]


def create_airfoil(data: dict) -> dict:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO airfoils (name, family, camber, thickness, source, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"],
                data.get("family", "custom"),
                data.get("camber", 0.0),
                data.get("thickness", 0.12),
                data.get("source", "user"),
                data.get("notes", ""),
                _now(),
            ),
        )
    return get_airfoil(data["name"])


def update_airfoil(name: str, data: dict) -> dict:
    with connect() as connection:
        row = connection.execute("SELECT name FROM airfoils WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(name)
        connection.execute(
            """
            UPDATE airfoils
            SET family = ?, camber = ?, thickness = ?, source = ?, notes = ?
            WHERE name = ?
            """,
            (
                data.get("family", "custom"),
                data.get("camber", 0.0),
                data.get("thickness", 0.12),
                data.get("source", "user"),
                data.get("notes", ""),
                name,
            ),
        )
    clear_polar_cache()
    return get_airfoil(name)


def delete_airfoil(name: str) -> None:
    with connect() as connection:
        row = connection.execute("SELECT name FROM airfoils WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(name)
        connection.execute("DELETE FROM polar_points WHERE airfoil_name = ?", (name,))
        connection.execute("DELETE FROM polar_sets WHERE airfoil_name = ?", (name,))
        connection.execute("DELETE FROM airfoils WHERE name = ?", (name,))
    clear_polar_cache()


def get_airfoil(name: str) -> dict:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM airfoils WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            raise KeyError(name)
        result = dict(row)
        coordinates_json = result.pop("coordinates_json", None)
        result["coordinates"] = json.loads(coordinates_json) if coordinates_json else None
        result["has_coordinates"] = result["coordinates"] is not None
        return result


def save_airfoil_coordinates(name: str, coordinates: list[list[float]]) -> dict:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE airfoils SET coordinates_json = ? WHERE name = ?",
            (json.dumps(coordinates), name),
        )
        if cursor.rowcount == 0:
            raise KeyError(name)
    return get_airfoil(name)


def get_polar_table(name: str) -> dict[str, np.ndarray] | None:
    with connect() as connection:
        polar_set = _latest_polar_set(connection, name)
        if polar_set is None:
            return None
        rows = connection.execute(
            """
            SELECT reynolds, alpha_deg, cl, cd
            FROM polar_points
            WHERE airfoil_name = ? AND polar_set_id = ?
            ORDER BY reynolds, alpha_deg
            """,
            (name, polar_set["id"]),
        ).fetchall()

    if not rows:
        return None

    reynolds_values = sorted({float(row["reynolds"]) for row in rows})
    alpha_values = sorted({float(row["alpha_deg"]) for row in rows})
    cl = np.zeros((len(reynolds_values), len(alpha_values)))
    cd = np.zeros((len(reynolds_values), len(alpha_values)))
    alpha_lookup = {value: index for index, value in enumerate(alpha_values)}
    reynolds_lookup = {value: index for index, value in enumerate(reynolds_values)}

    for row in rows:
        re_index = reynolds_lookup[float(row["reynolds"])]
        alpha_index = alpha_lookup[float(row["alpha_deg"])]
        cl[re_index, alpha_index] = float(row["cl"])
        cd[re_index, alpha_index] = float(row["cd"])

    cl_grid = np.vstack([np.interp(ALPHA_GRID, alpha_values, cl_row) for cl_row in cl])
    cd_grid = np.vstack([np.interp(ALPHA_GRID, alpha_values, cd_row) for cd_row in cd])
    cl_grid = np.vstack(
        [np.interp(REYNOLDS_GRID, reynolds_values, cl_grid[:, alpha_index]) for alpha_index in range(len(ALPHA_GRID))]
    ).T
    cd_grid = np.vstack(
        [np.interp(REYNOLDS_GRID, reynolds_values, cd_grid[:, alpha_index]) for alpha_index in range(len(ALPHA_GRID))]
    ).T
    return {"cl": cl_grid, "cd": cd_grid}


def get_polar_points(name: str) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT
                p.polar_set_id,
                p.reynolds,
                p.mach,
                p.ncrit,
                p.alpha_deg,
                p.cl,
                p.cd,
                p.cm,
                p.source,
                s.label AS set_label,
                s.method AS method
            FROM polar_points p
            LEFT JOIN polar_sets s ON s.id = p.polar_set_id
            WHERE p.airfoil_name = ?
            ORDER BY p.polar_set_id DESC, p.reynolds, p.alpha_deg
            """,
            (name,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_polar_sets(name: str) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT
                s.*,
                COUNT(p.id) AS points,
                MIN(p.reynolds) AS min_reynolds,
                MAX(p.reynolds) AS max_reynolds,
                MIN(p.alpha_deg) AS min_alpha,
                MAX(p.alpha_deg) AS max_alpha
            FROM polar_sets s
            LEFT JOIN polar_points p ON p.polar_set_id = s.id
            WHERE s.airfoil_name = ?
            GROUP BY s.id
            ORDER BY s.id DESC
            """,
            (name,),
        ).fetchall()
        return [dict(row) for row in rows]


def summarize_polar_quality(name: str) -> dict:
    points = get_polar_points(name)
    sets = get_polar_sets(name)
    warnings = []
    if not points:
        return {"status": "missing", "warnings": ["No polar points available."], "sets": sets}

    active_set_id = sets[0]["id"] if sets else None
    active_points = [point for point in points if point["polar_set_id"] == active_set_id] or points
    reynolds_values = sorted({float(point["reynolds"]) for point in active_points})
    alpha_values = sorted({float(point["alpha_deg"]) for point in active_points})

    if len(reynolds_values) < 3:
        warnings.append("Less than 3 Reynolds slices are available.")
    if len(alpha_values) < 7:
        warnings.append("Less than 7 alpha samples are available.")
    if min(alpha_values) > -4 or max(alpha_values) < 12:
        warnings.append("Alpha range does not cover the recommended -4 to 12 deg design band.")
    if any(float(point["cd"]) <= 0 for point in active_points):
        warnings.append("Non-positive drag coefficient detected.")

    for reynolds in reynolds_values:
        slice_points = sorted(
            [point for point in active_points if float(point["reynolds"]) == reynolds],
            key=lambda point: float(point["alpha_deg"]),
        )
        linear_band = [
            point
            for point in slice_points
            if -4.0 <= float(point["alpha_deg"]) <= 8.0
        ]
        cl_values = [float(point["cl"]) for point in linear_band]
        if len(cl_values) >= 3 and any(
            next_value < current_value
            for current_value, next_value in zip(cl_values, cl_values[1:])
        ):
            warnings.append(f"Cl is not monotonic in the linear band at Re {reynolds:.0f}.")
            break

    return {
        "status": "ok" if not warnings else "warning",
        "warnings": warnings,
        "sets": sets,
        "active_set_id": active_set_id,
        "reynolds": reynolds_values,
        "alpha": alpha_values,
    }


def upsert_polar_points(
    name: str,
    points: Iterable[dict],
    source: str,
    method: str = "user_import",
    label: str | None = None,
    mach: float = 0.03,
    ncrit: float = 9.0,
    notes: str = "",
) -> int:
    point_list = list(points)
    with connect() as connection:
        get_airfoil(name)
        polar_set_id = _create_polar_set(
            connection,
            name,
            label=label or f"{source} import",
            source=source,
            method=method,
            mach=mach,
            ncrit=ncrit,
            notes=notes,
        )
        count = 0
        for point in point_list:
            connection.execute(
                """
                INSERT INTO polar_points
                (polar_set_id, airfoil_name, reynolds, mach, ncrit, alpha_deg, cl, cd, cm, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (polar_set_id, reynolds, alpha_deg)
                DO UPDATE SET cl = excluded.cl, cd = excluded.cd, cm = excluded.cm, source = excluded.source
                """,
                (
                    polar_set_id,
                    name,
                    float(point["reynolds"]),
                    float(point.get("mach", mach)),
                    float(point.get("ncrit", ncrit)),
                    float(point["alpha_deg"]),
                    float(point["cl"]),
                    float(point["cd"]),
                    float(point.get("cm", 0.0)),
                    source,
                    _now(),
                ),
            )
            count += 1
    clear_polar_cache()
    return count


def save_project_bundle(
    project_name: str,
    payload: dict,
    geometry: dict,
    analyses: list[dict],
    stl_bytes: bytes,
) -> int:
    latest = analyses[-1] if analyses else {"summary": {}}
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO propeller_runs
            (project_name, design_mode, airfoil, payload_json, analysis_json, created_at,
             propeller_type, geometry_method, geometry_json, analyses_json, stl_blob, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_name,
                analyses[-1].get("model", "none") if analyses else "none",
                payload.get("airfoil", "NACA 4412"),
                json.dumps(payload),
                json.dumps(latest),
                _now(),
                payload.get("propeller_type", "traditional"),
                geometry.get("method", "legacy"),
                json.dumps(geometry),
                json.dumps(analyses),
                stl_bytes,
                1,
            ),
        )
        return int(cursor.lastrowid)


def get_project_stl(run_id: int) -> bytes:
    with connect() as connection:
        row = connection.execute(
            "SELECT stl_blob FROM propeller_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row is None or row["stl_blob"] is None:
        raise KeyError(run_id)
    return bytes(row["stl_blob"])


def list_runs(limit: int = 20) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, project_name, design_mode, airfoil, analysis_json, analyses_json,
                   propeller_type, geometry_method, created_at
            FROM propeller_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    runs = []
    for row in rows:
        analysis = json.loads(row["analysis_json"])
        analyses = json.loads(row["analyses_json"]) if row["analyses_json"] else [analysis]
        runs.append(
            {
                "id": row["id"],
                "project_name": row["project_name"],
                "design_mode": row["design_mode"],
                "propeller_type": row["propeller_type"] or "traditional",
                "geometry_method": row["geometry_method"] or "legacy",
                "airfoil": row["airfoil"],
                "models": [item.get("model", item.get("method", "legacy")) for item in analyses],
                "summary": analysis.get("summary", {}),
                "created_at": row["created_at"],
            }
        )
    return runs


def get_run(run_id: int) -> dict:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM propeller_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        raise KeyError(run_id)

    return {
        "id": row["id"],
        "project_name": row["project_name"],
        "design_mode": row["design_mode"],
        "airfoil": row["airfoil"],
        "payload": json.loads(row["payload_json"]),
        "analysis": json.loads(row["analysis_json"]),
        "analyses": (
            json.loads(row["analyses_json"])
            if row["analyses_json"]
            else [json.loads(row["analysis_json"])]
        ),
        "geometry": json.loads(row["geometry_json"]) if row["geometry_json"] else None,
        "propeller_type": row["propeller_type"] or "traditional",
        "geometry_method": row["geometry_method"] or "legacy",
        "has_stl": row["stl_blob"] is not None,
        "created_at": row["created_at"],
    }


def delete_run(run_id: int) -> None:
    with connect() as connection:
        cursor = connection.execute("DELETE FROM propeller_runs WHERE id = ?", (run_id,))
        if cursor.rowcount == 0:
            raise KeyError(run_id)


def clear_polar_cache() -> None:
    from polar_database import clear_cache

    clear_cache()


def _create_polar_set(
    connection,
    airfoil_name: str,
    label: str,
    source: str,
    method: str,
    mach: float,
    ncrit: float,
    notes: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO polar_sets (airfoil_name, label, source, method, mach, ncrit, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            airfoil_name,
            label,
            source,
            method,
            float(mach),
            float(ncrit),
            notes,
            _now(),
        ),
    )
    return int(cursor.lastrowid)


def _latest_polar_set(connection, airfoil_name: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT *
        FROM polar_sets
        WHERE airfoil_name = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (airfoil_name,),
    ).fetchone()


def _insert_polar_table(
    connection,
    polar_set_id: int,
    airfoil_name: str,
    table: dict[str, np.ndarray],
    source: str,
    mach: float,
    ncrit: float,
) -> None:
    now = _now()
    for re_index, reynolds in enumerate(REYNOLDS_GRID):
        for alpha_index, alpha in enumerate(ALPHA_GRID):
            connection.execute(
                """
                INSERT OR IGNORE INTO polar_points
                (polar_set_id, airfoil_name, reynolds, mach, ncrit, alpha_deg, cl, cd, cm, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    polar_set_id,
                    airfoil_name,
                    float(reynolds),
                    float(mach),
                    float(ncrit),
                    float(alpha),
                    float(table["cl"][re_index, alpha_index]),
                    float(table["cd"][re_index, alpha_index]),
                    float(table.get("cm", np.zeros_like(table["cl"]))[re_index, alpha_index]),
                    source,
                    now,
                ),
            )


def _infer_camber(name: str) -> float:
    digits = name.replace("NACA", "").strip()
    return float(digits[0]) / 100 if len(digits) == 4 else 0.0


def _infer_thickness(name: str) -> float:
    digits = name.replace("NACA", "").strip()
    return float(digits[-2:]) / 100 if len(digits) == 4 else 0.12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
