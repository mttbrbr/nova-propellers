"""Scientific design configuration shared by HTTP, studies and scripts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nova.core.data import canonical_json


class GeometryRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    @model_validator(mode="after")
    def finite_nested_configuration(self):
        canonical_json(self.geometry_parameters)
        canonical_json(self.airfoil_assignments)
        return self

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



class InverseDesignRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    @model_validator(mode="after")
    def finite_configuration(self):
        canonical_json(self.chord_points)
        canonical_json(self.twist_points)
        if self.max_chord_m is not None and self.min_chord_m > self.max_chord_m:
            raise ValueError('Minimum chord exceeds maximum chord')
        if self.min_twist_deg > self.max_twist_deg:
            raise ValueError('Minimum twist exceeds maximum twist')
        return self

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

