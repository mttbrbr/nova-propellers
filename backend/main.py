from io import BytesIO
from typing import Literal

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
    init_database,
    list_airfoils,
    list_runs,
    save_propeller_run,
    summarize_polar_quality,
    update_airfoil,
    upsert_polar_points,
)
from geometry_engine import PropellerSpec, analyze_propeller, generate_propeller_mesh


class PropellerRequest(BaseModel):
    project_name: str = Field("Untitled propeller", max_length=120)
    thrust_target: float = Field(..., gt=0, le=200, description="Target thrust in Newtons")
    rpm: float = Field(..., gt=0, le=60000, description="Rotational speed in revolutions per minute")
    diameter: float = Field(..., gt=0.02, le=2.0, description="Propeller diameter in meters")
    blades: int = Field(..., ge=2, le=8, description="Number of propeller blades")
    airfoil: str = Field("NACA 4412", max_length=80)
    design_mode: Literal["preliminary", "bemt", "larrabee"] = "bemt"
    profile_strategy: Literal["constant", "root_cambered", "tip_thin", "optimized"] = "constant"
    design_alpha_deg: float = Field(5.0, ge=1.0, le=10.0, description="Design angle of attack in degrees")


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


class PropellerSave(BaseModel):
    project_name: str = Field(..., max_length=120)
    payload: PropellerRequest
    analysis: dict


app = FastAPI(
    title="Nova Propeller API",
    version="0.1.0",
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


@app.get("/api/propellers")
def propellers() -> list[dict]:
    return list_runs()


@app.post("/api/propellers")
def save_propeller(payload: PropellerSave) -> dict:
    run_id = save_propeller_run(
        payload.project_name,
        payload.payload.model_dump(),
        payload.analysis,
    )
    return {"id": run_id}


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


@app.get("/api/reports/runs")
def report_runs() -> list[dict]:
    return list_runs()


@app.get("/api/reports/runs/{run_id}")
def report_run(run_id: int) -> dict:
    try:
        return get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


def _to_spec(payload: PropellerRequest) -> PropellerSpec:
    return PropellerSpec(
        thrust_target=payload.thrust_target,
        rpm=payload.rpm,
        diameter=payload.diameter,
        blades=payload.blades,
        airfoil=payload.airfoil,
        design_mode=payload.design_mode,
        profile_strategy=payload.profile_strategy,
        design_alpha_deg=payload.design_alpha_deg,
    )


@app.post("/api/analyze-propeller")
def analyze_propeller_endpoint(payload: PropellerRequest) -> dict:
    try:
        analysis = analyze_propeller(_to_spec(payload))
        return analysis
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Propeller analysis failed: {exc}",
        ) from exc


@app.post("/api/generate-propeller")
def generate_propeller(payload: PropellerRequest) -> Response:
    try:
        analysis = analyze_propeller(_to_spec(payload))
        mesh = generate_propeller_mesh(_to_spec(payload))
        stl_buffer = BytesIO()
        mesh.export(stl_buffer, file_type="stl")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Geometry generation failed: {exc}",
        ) from exc
    try:
        is_watertight = str(mesh.is_watertight).lower()
    except Exception:
        is_watertight = "unknown"

    filename = (
        f"nova_propeller_{payload.blades}blade_"
        f"{int(payload.diameter * 1000)}mm_{int(payload.rpm)}rpm.stl"
    )

    return Response(
        content=stl_buffer.getvalue(),
        media_type="model/stl",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Mesh-Watertight": is_watertight,
            "X-Estimated-Thrust": str(analysis["summary"]["estimated_thrust_n"]),
            "X-Power-W": str(analysis["summary"]["power_w"]),
            "X-Design-Method": analysis["method"],
        },
    )
