from io import BytesIO
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from database import (
    create_airfoil,
    delete_airfoil,
    delete_run,
    get_airfoil,
    get_polar_points,
    get_polar_sets,
    get_run,
    get_project_stl,
    init_database,
    list_airfoils,
    list_runs,
    save_project_bundle,
    save_airfoil_coordinates,
    summarize_polar_quality,
    update_airfoil,
    upsert_polar_points,
)
from airfoil_management import AirfoilLoft, AirfoilManager
from geometry_engine import (
    AIR_DENSITY,
    PropellerSpec,
    build_canonical_geometry,
    generate_mesh_from_geometry,
)
from inverse_design import (
    BezierBladeGeometry,
    BezierControlPoints,
    GeometryData,
    GeometryConstraints,
    InverseDesignOptimizer,
    create_solver,
    list_methods,
)


class AirfoilCreate(BaseModel):
    name: str = Field(..., max_length=80)
    family: str = Field("custom", max_length=80)
    camber: float = Field(0.0, ge=0.0, le=0.12)
    thickness: float = Field(0.12, ge=0.03, le=0.24)
    source: str = Field("user", max_length=120)
    notes: str = Field("", max_length=800)


class PolarPoint(BaseModel):
    reynolds: float = Field(..., gt=0)
    mach: float = Field(0.03, ge=0.0, le=0.8)
    ncrit: float = Field(9.0, ge=1.0, le=14.0)
    alpha_deg: float
    cl: float
    cd: float = Field(..., ge=0)
    cm: float = 0.0


class PolarImport(BaseModel):
    source: str = Field("user_import", max_length=120)
    method: Literal["xfoil", "wind_tunnel", "cfd", "manual", "seed", "user_import"] = "user_import"
    label: str = Field("Imported polar set", max_length=160)
    mach: float = Field(0.03, ge=0.0, le=0.8)
    ncrit: float = Field(9.0, ge=1.0, le=14.0)
    notes: str = Field("", max_length=800)
    points: list[PolarPoint]


class SizingRequest(BaseModel):
    thrust_target: float = Field(..., gt=0, le=200)
    disk_loading: float = Field(..., gt=1, le=5000, description="Target disk loading in N/m²")


class GeometryRequest(BaseModel):
    project_name: str = Field("Untitled propeller", max_length=120)
    propeller_type: Literal["traditional", "toroidal"] = "traditional"
    thrust_target: float = Field(..., gt=0, le=200)
    rpm: float = Field(..., gt=0, le=60000)
    diameter: float = Field(..., gt=0.02, le=2.0)
    blades: int = Field(..., ge=2, le=8)
    airfoil: str = Field("NACA 4412", max_length=80)
    geometry_method: Literal["bezier", "laguerre"]
    geometry_parameters: dict = Field(default_factory=dict)
    airfoil_assignments: list[dict] = Field(default_factory=list)


class AnalysisRequest(BaseModel):
    model: Literal["actuator_disk", "bemt", "llt", "vlm", "bem"]
    inputs: GeometryRequest
    geometry: dict


class ProjectBundleSave(BaseModel):
    project_name: str = Field(..., max_length=120)
    inputs: GeometryRequest
    geometry: dict
    analyses: list[dict] = Field(default_factory=list)


class InverseDesignRequest(BaseModel):
    target_thrust: float = Field(..., gt=0, le=200)
    rpm: float = Field(..., gt=0, le=60000)
    diameter: float = Field(..., gt=0.02, le=2.0)
    blades: int = Field(..., ge=1, le=8)
    airfoil: str = Field("NACA 4412", max_length=80)
    solver: Literal["bemt", "llt", "vlm", "bem"] = "bemt"
    chord_points: list[dict]
    twist_points: list[dict]
    min_chord_m: float = Field(0.003, gt=0)
    max_chord_m: float | None = Field(None, gt=0)
    min_twist_deg: float = Field(2.0, ge=-20, le=45)
    max_twist_deg: float = Field(45.0, ge=0, le=80)
    max_iterations: int = Field(180, ge=10, le=1000)


class AirfoilDatImport(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    content: str = Field(..., min_length=20)
    family: str = Field("custom DAT", max_length=80)
    source: str = Field("UIUC/XFOIL DAT", max_length=120)
    notes: str = Field("", max_length=800)


class AirfoilLoftRequest(BaseModel):
    assignments: list[dict]
    radial_fraction: float = Field(..., ge=0, le=1)
    method: Literal["linear", "spline"] = "linear"


app = FastAPI(
    title="Nova Propeller API",
    version="0.1.0-alpha.1",
    description="Fast geometry generation API for drone propeller MVPs.",
)


@app.on_event("startup")
def startup() -> None:
    init_database()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Disposition",
        "X-Mesh-Watertight",
        "X-Estimated-Thrust",
        "X-Power-W",
        "X-Design-Method",
    ],
)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/airfoils")
def airfoils() -> list[dict]:
    return list_airfoils()


@app.post("/api/airfoils")
def add_airfoil(payload: AirfoilCreate) -> dict:
    try:
        return create_airfoil(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to create airfoil: {exc}") from exc


@app.get("/api/airfoils/{name}")
def airfoil_detail(name: str) -> dict:
    try:
        airfoil = get_airfoil(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Airfoil not found") from exc
    airfoil["polars"] = get_polar_points(name)
    airfoil["polar_sets"] = get_polar_sets(name)
    airfoil["polar_quality"] = summarize_polar_quality(name)
    return airfoil


@app.put("/api/airfoils/{name}")
def edit_airfoil(name: str, payload: AirfoilCreate) -> dict:
    try:
        return update_airfoil(name, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Airfoil not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to update airfoil: {exc}") from exc


@app.delete("/api/airfoils/{name}")
def remove_airfoil(name: str) -> dict:
    try:
        delete_airfoil(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Airfoil not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to delete airfoil: {exc}") from exc
    return {"deleted": name}


@app.post("/api/airfoils/{name}/polars")
def import_polars(name: str, payload: PolarImport) -> dict:
    try:
        count = upsert_polar_points(
            name,
            [point.model_dump() for point in payload.points],
            payload.source,
            payload.method,
            payload.label,
            payload.mach,
            payload.ncrit,
            payload.notes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Airfoil not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to import polars: {exc}") from exc

    return {
        "airfoil": name,
        "imported_points": count,
        "quality": summarize_polar_quality(name),
    }


@app.post("/api/airfoils/import-dat")
def import_airfoil_dat(payload: AirfoilDatImport) -> dict:
    try:
        profile = AirfoilManager().parse_dat(payload.content, payload.name)
        try:
            get_airfoil(payload.name)
        except KeyError:
            create_airfoil(
                {
                    "name": payload.name,
                    "family": payload.family,
                    "camber": 0.0,
                    "thickness": 0.12,
                    "source": payload.source,
                    "notes": payload.notes,
                }
            )
        detail = save_airfoil_coordinates(payload.name, profile.coordinates.tolist())
        return {
            "airfoil": detail,
            "point_count": len(profile.coordinates),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"DAT import failed: {exc}") from exc


@app.post("/api/airfoils/loft")
def preview_airfoil_loft(payload: AirfoilLoftRequest) -> dict:
    try:
        loft = _build_airfoil_loft(payload.assignments)
        coordinates = loft.section(payload.radial_fraction, payload.method)
        return {
            "radial_fraction": payload.radial_fraction,
            "method": payload.method,
            "coordinates": coordinates.tolist(),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Airfoil loft failed: {exc}") from exc


@app.get("/api/propellers")
def propellers() -> list[dict]:
    return list_runs()


@app.get("/api/propellers/{run_id}")
def propeller_detail(run_id: int) -> dict:
    try:
        return get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Propeller not found") from exc


@app.delete("/api/propellers/{run_id}")
def remove_propeller(run_id: int) -> dict:
    try:
        delete_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Propeller not found") from exc
    return {"deleted": run_id}


def _geometry_to_spec(payload: GeometryRequest) -> PropellerSpec:
    return PropellerSpec(
        thrust_target=payload.thrust_target,
        rpm=payload.rpm,
        diameter=payload.diameter,
        blades=payload.blades,
        airfoil=payload.airfoil,
    )


def _build_airfoil_loft(assignments: list[dict]) -> AirfoilLoft:
    if len(assignments) < 2:
        raise ValueError("At least two airfoil stations are required")
    radial_positions = sorted(float(item["radial_fraction"]) for item in assignments)
    if len(set(radial_positions)) != len(radial_positions):
        raise ValueError("Airfoil station positions must be unique")
    if abs(radial_positions[0]) > 1e-8 or abs(radial_positions[-1] - 1.0) > 1e-8:
        raise ValueError("Airfoil stations must cover the complete span from r/R=0 to r/R=1")
    profiles = {}
    for assignment in assignments:
        radial_fraction = float(assignment["radial_fraction"])
        detail = get_airfoil(str(assignment["airfoil"]))
        if not detail.get("coordinates"):
            raise ValueError(f"{detail['name']} has no imported DAT coordinates")
        profiles[radial_fraction] = np.asarray(detail["coordinates"], dtype=float)
    return AirfoilLoft(profiles)


def _apply_airfoil_loft(geometry: dict, assignments: list[dict]) -> dict:
    if not assignments:
        return geometry
    loft = _build_airfoil_loft(assignments)
    for station in geometry["stations"]:
        section = loft.section(float(station["r_over_R"]), "linear")
        station["airfoil_coordinates"] = np.round(section, 8).tolist()
    geometry["airfoil_loft"] = assignments
    return geometry


@app.post("/api/sizing/actuator-disk")
def size_with_actuator_disk(payload: SizingRequest) -> dict:
    area = payload.thrust_target / payload.disk_loading
    diameter = 2.0 * (area / 3.141592653589793) ** 0.5
    induced_velocity = (payload.thrust_target / (2.0 * AIR_DENSITY * area)) ** 0.5
    return {
        "model": "actuator_disk",
        "diameter_m": round(diameter, 6),
        "disk_area_m2": round(area, 7),
        "disk_loading_n_m2": round(payload.disk_loading, 3),
        "induced_velocity_m_s": round(induced_velocity, 4),
        "ideal_power_w": round(payload.thrust_target * induced_velocity, 3),
    }


@app.post("/api/geometries")
def create_geometry(payload: GeometryRequest) -> dict:
    if payload.propeller_type != "traditional":
        raise HTTPException(status_code=501, detail="Toroidal geometry is planned but not available.")
    try:
        geometry = build_canonical_geometry(
            _geometry_to_spec(payload), payload.geometry_method, payload.geometry_parameters
        )
        geometry = _apply_airfoil_loft(geometry, payload.airfoil_assignments)
        mesh = generate_mesh_from_geometry(geometry)
        return {
            "geometry": geometry,
            "mesh_quality": {
                "watertight": bool(mesh.is_watertight),
                "vertices": int(len(mesh.vertices)),
                "faces": int(len(mesh.faces)),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Geometry generation failed: {exc}") from exc


@app.post("/api/geometries/stl")
def download_geometry(payload: GeometryRequest) -> Response:
    try:
        geometry = build_canonical_geometry(
            _geometry_to_spec(payload), payload.geometry_method, payload.geometry_parameters
        )
        geometry = _apply_airfoil_loft(geometry, payload.airfoil_assignments)
        mesh = generate_mesh_from_geometry(geometry)
        buffer = BytesIO()
        mesh.export(buffer, file_type="stl")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Geometry export failed: {exc}") from exc
    return Response(
        buffer.getvalue(),
        media_type="model/stl",
        headers={
            "Content-Disposition": f'attachment; filename="nova_{payload.geometry_method}_{int(payload.diameter * 1000)}mm.stl"',
            "X-Mesh-Watertight": str(mesh.is_watertight).lower(),
        },
    )


@app.post("/api/analyses")
def run_analysis(payload: AnalysisRequest) -> dict:
    try:
        geometry = GeometryData.from_dict(payload.geometry)
        solver = create_solver(payload.model, target_thrust_n=payload.inputs.thrust_target)
        detailed = solver.evaluate_detailed(geometry, payload.inputs.rpm)
        performance = detailed["performance"]
        omega = 2.0 * np.pi * payload.inputs.rpm / 60.0
        descriptor = next(item for item in list_methods() if item["id"] == payload.model)
        return {
            "model": payload.model,
            "method": descriptor["name"],
            "fidelity": descriptor["fidelity"],
            "description": descriptor["description"],
            "curve_source": detailed["curve_source"],
            "summary": {
                "target_thrust_n": round(payload.inputs.thrust_target, 4),
                "estimated_thrust_n": round(performance["thrust"], 4),
                "thrust_error_pct": round(
                    100.0
                    * (performance["thrust"] - payload.inputs.thrust_target)
                    / payload.inputs.thrust_target,
                    3,
                ),
                "torque_nm": round(performance["torque"], 6),
                "power_w": round(performance["torque"] * omega, 4),
                "efficiency": round(performance["efficiency"], 4),
            },
            "stations": detailed["curves"],
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{payload.model} analysis failed: {exc}") from exc


@app.get("/api/computational-methods")
def computational_methods() -> list[dict]:
    return list_methods()


@app.post("/api/projects")
def save_project(payload: ProjectBundleSave) -> dict:
    try:
        mesh = generate_mesh_from_geometry(payload.geometry)
        buffer = BytesIO()
        mesh.export(buffer, file_type="stl")
        project_id = save_project_bundle(
            payload.project_name,
            payload.inputs.model_dump(),
            payload.geometry,
            payload.analyses,
            buffer.getvalue(),
        )
        return {"id": project_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to save project: {exc}") from exc


@app.post("/api/inverse-design")
def inverse_design(payload: InverseDesignRequest) -> dict:
    try:
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
        max_chord = payload.max_chord_m or payload.diameter * 0.16
        bounds = (
            *((payload.min_chord_m, max_chord) for _ in range(len(chord))),
            *((payload.min_twist_deg, payload.max_twist_deg) for _ in range(len(twist))),
        )
        solver = create_solver(payload.solver, target_thrust_n=payload.target_thrust)
        initial_performance = solver.evaluate(parameterization.build(initial), payload.rpm)
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Inverse design failed: {exc}") from exc


@app.get("/api/propellers/{run_id}/stl")
def saved_project_stl(run_id: int) -> Response:
    try:
        content = get_project_stl(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Stored STL not found") from exc
    return Response(
        content,
        media_type="model/stl",
        headers={"Content-Disposition": f'attachment; filename="nova_project_{run_id}.stl"'},
    )
