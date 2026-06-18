from dataclasses import dataclass
from math import atan2, cos, pi, radians, sin, sqrt

import numpy as np
import trimesh

from polar_database import interpolate_polar


AIR_DENSITY = 1.225
AIR_VISCOSITY = 1.81e-5
AXIAL_FLIGHT_SPEED = 0.1

AIRFOILS = {
    "NACA 0012": {"m": 0.00, "p": 0.40, "t": 0.12, "cl0": 0.00},
    "NACA 2412": {"m": 0.02, "p": 0.40, "t": 0.12, "cl0": 0.22},
    "NACA 4412": {"m": 0.04, "p": 0.40, "t": 0.12, "cl0": 0.42},
    "NACA 6409": {"m": 0.06, "p": 0.40, "t": 0.09, "cl0": 0.55},
}


@dataclass(frozen=True)
class PropellerSpec:
    thrust_target: float
    rpm: float
    diameter: float
    blades: int
    airfoil: str = "NACA 4412"
    design_mode: str = "bemt"
    profile_strategy: str = "constant"
    design_alpha_deg: float = 5.0


@dataclass(frozen=True)
class BladePlan:
    radii: np.ndarray
    fractions: np.ndarray
    chord: np.ndarray
    twist: np.ndarray
    airfoil_m: np.ndarray
    airfoil_p: np.ndarray
    airfoil_t: np.ndarray


def generate_propeller_mesh(spec: PropellerSpec) -> trimesh.Trimesh:
    plan = design_blade_plan(spec)
    radius = spec.diameter / 2.0
    hub_radius = max(radius * 0.14, 0.012)
    hub_height = max(radius * 0.09, 0.008)

    hub = trimesh.creation.cylinder(
        radius=hub_radius,
        height=hub_height,
        sections=64,
        process=False,
    )

    base_blade_vertices, base_blade_faces = _build_blade_geometry(plan)
    blade_meshes = []

    for blade_index in range(spec.blades):
        angle = 2.0 * pi * blade_index / spec.blades
        rotation = trimesh.transformations.rotation_matrix(
            angle=angle,
            direction=(0, 0, 1),
            point=(0, 0, 0),
        )
        blade = trimesh.Trimesh(
            vertices=base_blade_vertices.copy(),
            faces=base_blade_faces.copy(),
            process=False,
        )
        blade.apply_transform(rotation)
        blade_meshes.append(blade)

    mesh = trimesh.util.concatenate([hub, *blade_meshes])
    return _lightweight_mesh_cleanup(mesh)


def analyze_propeller(spec: PropellerSpec) -> dict:
    plan = design_blade_plan(spec)
    bemt = _evaluate_bemt(spec, plan)
    mesh_quality = estimate_mesh_quality(spec)
    chord_mm = plan.chord * 1000.0
    twist_deg = np.degrees(plan.twist)

    return {
        "method": _method_label(spec.design_mode),
        "airfoil": spec.airfoil,
        "profile_strategy": spec.profile_strategy,
        "summary": {
            "target_thrust_n": round(spec.thrust_target, 3),
            "estimated_thrust_n": round(bemt["thrust"], 3),
            "thrust_error_pct": round(
                100.0 * (bemt["thrust"] - spec.thrust_target) / spec.thrust_target,
                2,
            ),
            "torque_nm": round(bemt["torque"], 4),
            "power_w": round(bemt["power"], 2),
            "figure_of_merit": round(bemt["figure_of_merit"], 3),
            "mean_reynolds": round(float(np.mean(bemt["reynolds"])), 0),
            "min_reynolds": round(float(np.min(bemt["reynolds"])), 0),
            "tip_mach": round(bemt["tip_mach"], 3),
            "mean_alpha_deg": round(float(np.mean(bemt["alpha_deg"])), 2),
            "max_alpha_deg": round(float(np.max(bemt["alpha_deg"])), 2),
            "mean_induction_a": round(float(np.mean(bemt["induction_a"])), 3),
            "mean_circulation": round(float(np.mean(bemt["circulation"])), 4),
        },
        "geometry": {
            "stations": len(plan.radii),
            "root_chord_mm": round(float(chord_mm[0]), 2),
            "mid_chord_mm": round(float(chord_mm[len(chord_mm) // 2]), 2),
            "tip_chord_mm": round(float(chord_mm[-1]), 2),
            "root_twist_deg": round(float(twist_deg[0]), 2),
            "mid_twist_deg": round(float(twist_deg[len(twist_deg) // 2]), 2),
            "tip_twist_deg": round(float(twist_deg[-1]), 2),
        },
        "mesh_quality": mesh_quality,
        "stations": [
            {
                "r_over_R": round(float(plan.fractions[index]), 3),
                "radius_m": round(float(plan.radii[index]), 4),
                "chord_mm": round(float(chord_mm[index]), 2),
                "twist_deg": round(float(twist_deg[index]), 2),
                "alpha_deg": round(float(bemt["alpha_deg"][index]), 2),
                "phi_deg": round(float(bemt["phi_deg"][index]), 2),
                "cl": round(float(bemt["cl"][index]), 3),
                "cd": round(float(bemt["cd"][index]), 4),
                "circulation": round(float(bemt["circulation"][index]), 5),
                "loading_coefficient": round(float(bemt["loading_coefficient"][index]), 5),
                "induction_a": round(float(bemt["induction_a"][index]), 3),
                "induction_aprime": round(float(bemt["induction_aprime"][index]), 3),
                "reynolds": round(float(bemt["reynolds"][index]), 0),
                "d_thrust_n": round(float(bemt["d_thrust"][index]), 4),
                "d_power_w": round(float(bemt["d_power"][index]), 3),
            }
            for index in range(len(plan.radii))
        ],
    }


def design_blade_plan(spec: PropellerSpec) -> BladePlan:
    radius = spec.diameter / 2.0
    hub_radius = max(radius * 0.14, 0.012)
    station_count = 28
    radii = np.linspace(hub_radius * 0.95, radius, station_count)
    fractions = (radii - radii[0]) / (radii[-1] - radii[0])

    airfoil = AIRFOILS.get(spec.airfoil, AIRFOILS["NACA 4412"])
    airfoil_m, airfoil_p, airfoil_t = _airfoil_distribution(spec, fractions, airfoil)

    chord = _initial_chord_distribution(spec, radii, fractions)
    twist = _twist_distribution(spec, radii)

    if spec.design_mode in {"bemt", "larrabee"}:
        chord, twist = _solve_loaded_distribution(spec, radii, fractions, chord, twist)

    return BladePlan(
        radii=radii,
        fractions=fractions,
        chord=chord,
        twist=twist,
        airfoil_m=airfoil_m,
        airfoil_p=airfoil_p,
        airfoil_t=airfoil_t,
    )


def _solve_loaded_distribution(
    spec: PropellerSpec,
    radii: np.ndarray,
    fractions: np.ndarray,
    chord: np.ndarray,
    twist: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if spec.design_mode == "larrabee":
        return _solve_larrabee_distribution(spec, radii, fractions, chord, twist)

    for _ in range(14):
        analysis = _evaluate_bemt_arrays(spec, radii, chord, twist)
        phi = np.radians(analysis["phi_deg"])
        scale = np.clip(spec.thrust_target / max(analysis["thrust"], 1e-6), 0.72, 1.34)
        chord = chord * (0.70 + 0.30 * scale)

        twist = phi + radians(spec.design_alpha_deg)

    min_chord = spec.diameter * 0.014
    max_chord = spec.diameter * 0.13 / max(spec.blades / 2, 1)
    return np.clip(chord, min_chord, max_chord), np.clip(twist, radians(4.0), radians(42.0))


def _solve_larrabee_distribution(
    spec: PropellerSpec,
    radii: np.ndarray,
    fractions: np.ndarray,
    chord: np.ndarray,
    twist: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    radius = spec.diameter / 2.0
    design_cl = _design_cl(spec)
    dr = np.gradient(radii)
    omega = 2.0 * pi * spec.rpm / 60.0
    min_chord = spec.diameter * 0.012
    max_chord = spec.diameter * 0.16 / max(spec.blades / 2, 1)

    for _ in range(28):
        analysis = _evaluate_bemt_arrays(spec, radii, chord, twist)
        phi = np.radians(analysis["phi_deg"])
        relative_velocity = analysis["relative_velocity"]
        loss = analysis["loss_factor"]
        x = np.clip(radii / radius, 0.16, 0.995)

        # Goldstein/Larrabee-style circulation shape: zero near root/tip,
        # weighted by Prandtl losses and radius so useful work moves outboard.
        circulation_shape = (
            loss
            * x
            * np.sqrt(np.maximum(1.0 - x**2, 0.012))
            * np.sin(pi * np.clip(fractions, 0.03, 0.97)) ** 0.25
        )
        circulation_shape = np.maximum(circulation_shape, 1e-6)
        thrust_per_unit_gamma = (
            spec.blades
            * AIR_DENSITY
            * relative_velocity
            * circulation_shape
            * np.cos(phi)
            * dr
            * loss
        )
        gamma_scale = spec.thrust_target / max(float(np.sum(thrust_per_unit_gamma)), 1e-9)
        target_gamma = gamma_scale * circulation_shape

        target_chord = 2.0 * target_gamma / np.maximum(relative_velocity * design_cl, 1e-6)
        chord = 0.58 * chord + 0.42 * np.clip(target_chord, min_chord, max_chord)

        # Larrabee optimum keeps the section close to its selected design Cl.
        # Drag shifts effective inflow slightly; this keeps alpha from drifting.
        drag_angle = np.arctan2(analysis["cd"], np.maximum(analysis["cl"], 1e-6))
        twist = phi + radians(spec.design_alpha_deg) + 0.18 * drag_angle

        # Mild pitch smoothing avoids abrupt geometric kinks in the STL.
        twist[1:-1] = 0.25 * twist[:-2] + 0.50 * twist[1:-1] + 0.25 * twist[2:]
        chord[1:-1] = 0.20 * chord[:-2] + 0.60 * chord[1:-1] + 0.20 * chord[2:]

        error = abs(analysis["thrust"] - spec.thrust_target) / max(spec.thrust_target, 1e-6)
        if error < 0.015:
            break

    return np.clip(chord, min_chord, max_chord), np.clip(twist, radians(3.0), radians(44.0))


def _evaluate_bemt(spec: PropellerSpec, plan: BladePlan) -> dict:
    return _evaluate_bemt_arrays(spec, plan.radii, plan.chord, plan.twist)


def _evaluate_bemt_arrays(
    spec: PropellerSpec,
    radii: np.ndarray,
    chord: np.ndarray,
    twist: np.ndarray,
) -> dict:
    radius = spec.diameter / 2.0
    omega = 2.0 * pi * spec.rpm / 60.0
    axial_velocity = max(_momentum_induced_velocity(spec), AXIAL_FLIGHT_SPEED)
    tangential_velocity = omega * radii
    induction_a = np.full_like(radii, 0.08, dtype=float)
    induction_aprime = np.full_like(radii, 0.01, dtype=float)
    sigma = spec.blades * chord / np.maximum(2.0 * pi * radii, 1e-6)

    for _ in range(40):
        axial = axial_velocity * (1.0 + induction_a)
        tangential = tangential_velocity * (1.0 - induction_aprime)
        relative_velocity = np.sqrt(axial**2 + tangential**2)
        phi = np.arctan2(axial, np.maximum(tangential, 1e-6))
        alpha = twist - phi
        reynolds = AIR_DENSITY * relative_velocity * chord / AIR_VISCOSITY
        cl, cd = _polar_coefficients(spec, alpha, reynolds)
        cn = cl * np.cos(phi) - cd * np.sin(phi)
        ct = cl * np.sin(phi) + cd * np.cos(phi)
        loss = _prandtl_loss(spec.blades, radii, radius, phi)

        next_a = 1.0 / (
            (4.0 * loss * np.sin(phi) ** 2) / np.maximum(sigma * cn, 1e-6)
            - 1.0
        )
        next_aprime = 1.0 / (
            (4.0 * loss * np.sin(phi) * np.cos(phi)) / np.maximum(sigma * ct, 1e-6)
            + 1.0
        )
        next_a = np.clip(next_a, -0.2, 0.55)
        next_aprime = np.clip(next_aprime, -0.08, 0.22)
        induction_a = 0.72 * induction_a + 0.28 * next_a
        induction_aprime = 0.72 * induction_aprime + 0.28 * next_aprime

    axial = axial_velocity * (1.0 + induction_a)
    tangential = tangential_velocity * (1.0 - induction_aprime)
    relative_velocity = np.sqrt(axial**2 + tangential**2)
    phi = np.arctan2(axial, np.maximum(tangential, 1e-6))
    alpha = twist - phi
    alpha_deg = np.degrees(alpha)
    reynolds = AIR_DENSITY * relative_velocity * chord / AIR_VISCOSITY
    cl, cd = _polar_coefficients(spec, alpha, reynolds)
    loss = _prandtl_loss(spec.blades, radii, radius, phi)
    dr = np.gradient(radii)

    q = 0.5 * AIR_DENSITY * relative_velocity**2
    lift = q * chord * cl
    drag = q * chord * cd
    circulation = 0.5 * relative_velocity * chord * cl
    d_thrust = spec.blades * (lift * np.cos(phi) - drag * np.sin(phi)) * dr * loss
    d_torque = spec.blades * radii * (lift * np.sin(phi) + drag * np.cos(phi)) * dr * loss

    thrust = float(np.sum(d_thrust))
    torque = float(np.sum(d_torque))
    power = float(max(torque * omega, 0.0))
    d_power = np.maximum(d_torque * omega, 0.0)
    ideal_power = spec.thrust_target * axial_velocity
    figure_of_merit = float(np.clip(ideal_power / max(power, 1e-6), 0.0, 1.0))
    tip_mach = omega * radius / 343.0

    return {
        "thrust": thrust,
        "torque": torque,
        "power": power,
        "figure_of_merit": figure_of_merit,
        "reynolds": reynolds,
        "alpha_deg": alpha_deg,
        "phi_deg": np.degrees(phi),
        "cl": cl,
        "cd": cd,
        "circulation": circulation,
        "loading_coefficient": circulation / np.maximum(omega * radii**2, 1e-6),
        "relative_velocity": relative_velocity,
        "loss_factor": loss,
        "induction_a": induction_a,
        "induction_aprime": induction_aprime,
        "d_thrust": d_thrust,
        "d_power": d_power,
        "tip_mach": tip_mach,
    }


def _build_blade_geometry(plan: BladePlan) -> tuple[np.ndarray, np.ndarray]:
    points_per_section = 83
    vertices = []

    for index, radius in enumerate(plan.radii):
        airfoil = _naca_points(
            m=float(plan.airfoil_m[index]),
            p=float(plan.airfoil_p[index]),
            thickness=float(plan.airfoil_t[index]),
            point_count=42,
        )
        fraction = float(plan.fractions[index])
        chord = float(plan.chord[index])
        twist = float(plan.twist[index])

        for x_norm, z_norm in airfoil:
            chordwise = (x_norm - 0.35) * chord
            thickness = z_norm * chord
            tangential = chordwise * cos(twist) - thickness * sin(twist)
            vertical = chordwise * sin(twist) + thickness * cos(twist)
            sweep = 0.035 * plan.radii[-1] * sin(pi * fraction)
            vertices.append((radius, tangential + sweep, vertical))

    faces = []
    station_count = len(plan.radii)
    for station_index in range(station_count - 1):
        current = station_index * points_per_section
        next_station = (station_index + 1) * points_per_section
        for point_index in range(points_per_section):
            point_next = (point_index + 1) % points_per_section
            faces.append((current + point_index, next_station + point_index, next_station + point_next))
            faces.append((current + point_index, next_station + point_next, current + point_next))

    root_center = len(vertices)
    vertices.append((float(plan.radii[0]), 0.0, 0.0))
    tip_center = len(vertices)
    vertices.append((float(plan.radii[-1]), 0.0, 0.0))
    tip_start = (station_count - 1) * points_per_section

    for point_index in range(points_per_section):
        point_next = (point_index + 1) % points_per_section
        faces.append((root_center, point_next, point_index))
        faces.append((tip_center, tip_start + point_index, tip_start + point_next))

    vertices_array = np.asarray(vertices, dtype=float)
    faces_array = _orient_faces_outward(vertices_array, np.asarray(faces, dtype=np.int64))
    return vertices_array, faces_array


def _lightweight_mesh_cleanup(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    finite_vertices = np.isfinite(mesh.vertices).all(axis=1)
    valid_faces = finite_vertices[mesh.faces].all(axis=1)
    mesh.update_faces(valid_faces)
    mesh.remove_unreferenced_vertices()
    return mesh


def _orient_faces_outward(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    center = vertices.mean(axis=0)
    oriented = faces.copy()
    triangles = vertices[oriented]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    face_centers = triangles.mean(axis=1)
    inward = np.einsum("ij,ij->i", normals, face_centers - center) < 0
    tmp = oriented[inward, 1].copy()
    oriented[inward, 1] = oriented[inward, 2]
    oriented[inward, 2] = tmp
    return oriented


def estimate_mesh_quality(spec: PropellerSpec) -> dict:
    mesh = generate_propeller_mesh(spec)
    try:
        watertight = bool(mesh.is_watertight)
    except Exception:
        watertight = False
    try:
        bodies = int(len(mesh.split(only_watertight=False)))
    except Exception:
        bodies = -1

    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight": watertight,
        "bodies": bodies,
        "bounds_m": [round(float(value), 4) for value in mesh.extents],
    }


def _initial_chord_distribution(
    spec: PropellerSpec,
    radii: np.ndarray,
    fractions: np.ndarray,
) -> np.ndarray:
    prop_area = pi * (spec.diameter / 2.0) ** 2
    disk_loading = spec.thrust_target / max(prop_area, 1e-6)
    loading_factor = np.clip(sqrt(disk_loading / 200.0), 0.75, 1.45)
    local_radius_ratio = radii / (spec.diameter / 2.0)
    planform = 0.055 + 0.12 * np.sin(pi * fractions) ** 0.7
    taper = 1.0 - 0.38 * fractions
    root_relief = np.clip(local_radius_ratio / 0.22, 0.62, 1.0)
    chord = spec.diameter * planform * taper * loading_factor * root_relief / spec.blades
    return np.clip(chord, spec.diameter * 0.018, spec.diameter * 0.095)


def _twist_distribution(spec: PropellerSpec, radii: np.ndarray) -> np.ndarray:
    omega = 2.0 * pi * spec.rpm / 60.0
    induced_velocity = _momentum_induced_velocity(spec)
    tangential_velocity = np.maximum(omega * radii, 1e-6)
    inflow_angle = np.arctan2(induced_velocity, tangential_velocity)
    twist = inflow_angle + radians(spec.design_alpha_deg)
    return np.clip(twist, radians(8.0), radians(38.0))


def _airfoil_distribution(
    spec: PropellerSpec,
    fractions: np.ndarray,
    airfoil: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = np.full_like(fractions, airfoil["m"], dtype=float)
    p = np.full_like(fractions, airfoil["p"], dtype=float)
    thickness = np.full_like(fractions, airfoil["t"], dtype=float)

    if spec.profile_strategy == "root_cambered":
        m *= 1.18 - 0.28 * fractions
        thickness *= 1.08 - 0.10 * fractions
    elif spec.profile_strategy == "tip_thin":
        thickness *= 1.10 - 0.32 * fractions
    elif spec.profile_strategy == "optimized":
        m *= 1.20 - 0.40 * fractions
        thickness *= 1.12 - 0.36 * fractions
        p = np.clip(p + 0.06 * fractions, 0.25, 0.55)

    return np.clip(m, 0.0, 0.09), np.clip(p, 0.2, 0.65), np.clip(thickness, 0.06, 0.16)


def _polar_coefficients(
    spec: PropellerSpec,
    alpha: np.ndarray,
    reynolds: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    if reynolds is None:
        reynolds = np.full_like(alpha, 90000.0, dtype=float)
    return interpolate_polar(spec.airfoil, np.degrees(alpha), reynolds)


def _design_cl(spec: PropellerSpec) -> float:
    alpha = radians(spec.design_alpha_deg)
    cl, _ = _polar_coefficients(spec, np.asarray([alpha]))
    return float(np.clip(cl[0], 0.35, 1.05))


def _momentum_induced_velocity(spec: PropellerSpec) -> float:
    disk_area = pi * (spec.diameter / 2.0) ** 2
    return sqrt(spec.thrust_target / (2.0 * AIR_DENSITY * disk_area))


def _prandtl_loss(blades: int, radii: np.ndarray, radius: float, phi: np.ndarray) -> np.ndarray:
    sin_phi = np.maximum(np.sin(np.abs(phi)), 1e-4)
    hub_radius = max(radius * 0.14, 0.012)
    tip_exponent = -blades / 2.0 * (radius - radii) / np.maximum(radii * sin_phi, 1e-6)
    root_exponent = -blades / 2.0 * (radii - hub_radius) / np.maximum(hub_radius * sin_phi, 1e-6)
    tip_factor = 2.0 / pi * np.arccos(np.clip(np.exp(tip_exponent), 0.0, 1.0))
    root_factor = 2.0 / pi * np.arccos(np.clip(np.exp(root_exponent), 0.0, 1.0))
    return np.clip(tip_factor * root_factor, 0.12, 1.0)


def _method_label(design_mode: str) -> str:
    if design_mode == "larrabee":
        return "Larrabee circulation design"
    if design_mode == "bemt":
        return "Simplified BEMT"
    return "Preliminary momentum sizing"


def _naca_points(m: float, p: float, thickness: float, point_count: int) -> np.ndarray:
    beta = np.linspace(0.0, pi, point_count)
    x = 0.5 * (1.0 - np.cos(beta))
    yt = 5.0 * thickness * (
        0.2969 * np.sqrt(x)
        - 0.1260 * x
        - 0.3516 * x**2
        + 0.2843 * x**3
        - 0.1015 * x**4
    )

    if m <= 0:
        yc = np.zeros_like(x)
        dyc_dx = np.zeros_like(x)
    else:
        yc = np.where(
            x < p,
            m / p**2 * (2.0 * p * x - x**2),
            m / (1.0 - p) ** 2 * ((1.0 - 2.0 * p) + 2.0 * p * x - x**2),
        )
        dyc_dx = np.where(
            x < p,
            2.0 * m / p**2 * (p - x),
            2.0 * m / (1.0 - p) ** 2 * (p - x),
        )

    theta = np.arctan(dyc_dx)
    xu = x - yt * np.sin(theta)
    zu = yc + yt * np.cos(theta)
    xl = x + yt * np.sin(theta)
    zl = yc - yt * np.cos(theta)

    upper = np.column_stack((xu[::-1], zu[::-1]))
    lower = np.column_stack((xl[1:], zl[1:]))
    return np.vstack((upper, lower))
