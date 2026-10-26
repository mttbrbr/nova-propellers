import os
import secrets
from io import BytesIO
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from airfoil_management import AirfoilLoft, AirfoilManager
from database import (
    create_airfoil,
    delete_airfoil,
    delete_run,
    get_airfoil,
    get_polar_points,
    get_polar_sets,
    get_project_stl,
    get_run,
    init_database,
    list_airfoils,
    list_runs,
    save_airfoil_coordinates,
    save_project_bundle,
    summarize_polar_quality,
    update_airfoil,
    upsert_polar_points,
)
from geometry_engine import (
    AIR_DENSITY,
    generate_mesh_from_geometry,
)
from inverse_design import (
    list_methods,
)
from nova.application.analysis import run_propeller_analysis
from nova.application.geometry import create_propeller_geometry
from nova.application.optimization import run_inverse_design
from nova.core.design import GeometryRequest, InverseDesignRequest
from nova.infrastructure import jobs, library
from nova.transport.api import router as nova_router
from nova.transport.external_api import router as external_router
from nova.transport.external_archive_api import router as external_archive_router
from nova.transport.external_case_api import router as external_case_router
from nova.transport.simulation_api import router as simulation_router
from nova.transport.mixed_api import router as mixed_router


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




class AnalysisRequest(BaseModel):
    model: Literal["actuator_disk", "bemt", "llt", "vlm", "bem"]
    inputs: GeometryRequest
    geometry: dict


class ProjectBundleSave(BaseModel):
    project_name: str = Field(..., max_length=120)
    inputs: GeometryRequest
    geometry: dict
    analyses: list[dict] = Field(default_factory=list)




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
    version="0.1.0-alpha.2",
    description="Fast geometry generation API for drone propeller MVPs.",
)


@app.on_event("startup")
def startup() -> None:
    init_database()
    library.initialize()
    jobs.start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "NOVA_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:1420,http://127.0.0.1:1420,tauri://localhost,http://tauri.localhost,https://tauri.localhost",
    ).split(",") if origin.strip()],
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


@app.middleware("http")
async def authorize_desktop(request, call_next):
    token = os.getenv("NOVA_SESSION_TOKEN")
    if token and request.url.path != "/api/health" and request.method != "OPTIONS":
        if not secrets.compare_digest(request.headers.get("X-Nova-Session", ""), token):
            return JSONResponse({"detail": "Local session authorization required"}, status_code=401)
    return await call_next(request)


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
        asset = library.make_asset({"kind": "airfoil_geometry", "airfoil": payload.name,
                                    "source": payload.content, "coordinates": profile.coordinates.tolist(),
                                    "source_type": "dat", "notes": payload.notes})
        return {"asset_id": asset["id"],
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
        geometry = create_propeller_geometry(payload.model_dump())
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
    if payload.propeller_type != "traditional":
        raise HTTPException(status_code=501, detail="Toroidal geometry is planned but not available.")
    try:
        geometry = create_propeller_geometry(payload.model_dump())
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


def validate_geometry_inputs(inputs, geometry):
    expected = create_propeller_geometry(inputs.model_dump())
    if any(expected.get(key) != geometry.get(key) for key in ("diameter_m", "blades", "airfoil", "propeller_type")):
        raise ValueError("Geometry belongs to a different input revision; regenerate it")
    if len(expected["stations"]) != len(geometry.get("stations", [])):
        raise ValueError("Geometry station count does not match inputs")
    for left, right in zip(expected["stations"], geometry["stations"]):
        for key in ("radius_m", "chord_m", "twist_deg"):
            if not np.isclose(left[key], right[key], rtol=1e-7, atol=1e-9):
                raise ValueError("Geometry belongs to a different input revision; regenerate it")


@app.post("/api/analyses")
def run_analysis(payload: AnalysisRequest) -> dict:
    try:
        validate_geometry_inputs(payload.inputs, payload.geometry)
        return run_propeller_analysis(
            model=payload.model, geometry_data=payload.geometry,
            rpm=payload.inputs.rpm, target_thrust_n=payload.inputs.thrust_target,
            propeller_type=payload.inputs.propeller_type, solver_version=app.version,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{payload.model} analysis failed: {exc}") from exc


@app.get("/api/computational-methods")
def computational_methods() -> list[dict]:
    return list_methods()


@app.post("/api/projects")
def save_project(payload: ProjectBundleSave) -> dict:
    try:
        validate_geometry_inputs(payload.inputs, payload.geometry)
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
        return run_inverse_design(payload.model_dump())
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


app.include_router(nova_router)
app.include_router(external_router)
app.include_router(external_archive_router)
app.include_router(external_case_router)
app.include_router(simulation_router)
app.include_router(mixed_router)


@app.on_event("shutdown")
def shutdown_workflows():
    jobs.shutdown()
