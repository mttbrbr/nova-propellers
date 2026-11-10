"""Engineering corrections for momentum-based rotor models.

Every correction is opt-in and reported in the result so a study can show the
effect of each model choice. Formulas follow the usual references:

Axial rotors (propellers, wind/tidal turbines, marine propellers)
  * tip / hub loss: Prandtl (Glauert 1935); Shen et al. (2005) tip variant
  * high induction: Glauert empirical, Buhl (2005), Spera (1994)
  * 3-D rotational augmentation: Snel et al. (1994)
  * compressibility: Prandtl–Glauert (subsonic sections only)

Vertical-axis rotors (Darrieus, H-rotor)
  * finite aspect ratio (the VAWT "tip loss"): Lanchester–Prandtl lifting line
  * flow curvature: virtual incidence at 3/4 chord (Migliore et al. 1980)
  * dynamic stall: Gormont (1973) with Berg's (1983) blending, as used by
    Paraschivoiu's DMST
  * strut parasitic drag and central-shaft wake (the VAWT "hub loss")
"""
import math
from dataclasses import asdict, dataclass

import numpy as np

TIP_LOSS = ('none', 'prandtl', 'shen')
HUB_LOSS = ('none', 'prandtl')
HIGH_INDUCTION = ('none', 'glauert', 'buhl', 'spera')
ROTATIONAL = ('none', 'snel')
COMPRESSIBILITY = ('none', 'prandtl_glauert')
DYNAMIC_STALL = ('none', 'gormont_berg')


def _choice(name, value, options):
    if value not in options:
        raise ValueError(f'{name} must be one of {", ".join(options)}')
    return value


@dataclass(frozen=True)
class AxialCorrections:
    tip_loss: str = 'prandtl'
    hub_loss: str = 'prandtl'
    high_induction: str = 'buhl'
    rotational_augmentation: str = 'none'
    compressibility: str = 'none'

    def __post_init__(self):
        _choice('tip_loss', self.tip_loss, TIP_LOSS)
        _choice('hub_loss', self.hub_loss, HUB_LOSS)
        _choice('high_induction', self.high_induction, HIGH_INDUCTION)
        _choice('rotational_augmentation', self.rotational_augmentation, ROTATIONAL)
        _choice('compressibility', self.compressibility, COMPRESSIBILITY)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class VerticalCorrections:
    finite_aspect_ratio: bool = True
    flow_curvature: bool = False
    dynamic_stall: str = 'none'
    high_induction: str = 'glauert'
    strut_drag: bool = False
    shaft_wake: bool = False

    def __post_init__(self):
        _choice('dynamic_stall', self.dynamic_stall, DYNAMIC_STALL)
        _choice('high_induction', self.high_induction, HIGH_INDUCTION)

    def to_dict(self):
        return asdict(self)


def corrections_from(kind, config):
    config = dict(config or {})
    cls = VerticalCorrections if kind == 'vertical' else AxialCorrections
    unknown = set(config) - set(cls.__dataclass_fields__)
    if unknown:
        raise ValueError(f'Unsupported corrections: {", ".join(sorted(unknown))}')
    return cls(**config)


# ----------------------------------------------------------------- axial

def prandtl_factor(exponent):
    return 2.0 / math.pi * np.arccos(np.clip(np.exp(-np.maximum(exponent, 0.0)), 0.0, 1.0))


def tip_loss(model, blades, r, tip_radius, phi, tip_speed_ratio=None):
    if model == 'none':
        return np.ones_like(r)
    sin_phi = np.maximum(np.abs(np.sin(phi)), 1e-6)
    f = blades / 2.0 * (tip_radius - r) / (r * sin_phi)
    if model == 'shen':
        tsr = 7.0 if tip_speed_ratio is None or not math.isfinite(tip_speed_ratio) else tip_speed_ratio
        f = f * (math.exp(-0.125 * (blades * tsr - 21.0)) + 0.1)
    return np.maximum(prandtl_factor(f), 1e-4)


def hub_loss(model, blades, r, hub_radius, phi):
    if model == 'none' or hub_radius <= 0:
        return np.ones_like(r)
    sin_phi = np.maximum(np.abs(np.sin(phi)), 1e-6)
    f = blades / 2.0 * (r - hub_radius) / (hub_radius * sin_phi)
    return np.maximum(prandtl_factor(f), 1e-4)


def turbine_axial_induction(k, loss, model):
    """Axial induction from k = σ' Cn / (4 F sin²φ) in windmill and brake states."""
    k = np.asarray(k, dtype=float)
    F = np.asarray(loss, dtype=float)
    momentum = k / (1.0 + k)
    if model == 'none':
        return momentum
    if model == 'glauert':
        # Glauert's empirical thrust curve, Hansen's form with the loss factor:
        # 4aF(1 - a(5 - 3a)/4) = σ' Cn (1-a)² / sin²φ = 4Fk(1-a)²  for a > 1/3.
        # The F cancels; bisection on [1/3, 1) is robust and vectorized.
        heavy = momentum > 1.0 / 3.0
        if not np.any(heavy):
            return momentum
        kh = k[heavy]
        low, high = np.full_like(kh, 1.0 / 3.0), np.full_like(kh, 0.999)
        for _ in range(60):
            mid = 0.5 * (low + high)
            g = mid * (1 - 0.25 * (5 - 3 * mid) * mid) - kh * (1 - mid) ** 2
            low, high = np.where(g < 0, mid, low), np.where(g < 0, high, mid)
        a = momentum.copy()
        a[heavy] = 0.5 * (low + high)
        return a
    if model == 'spera':
        ac = 0.2
        K = 1.0 / np.maximum(k, 1e-12)
        spera = 0.5 * (2 + K * (1 - 2 * ac) - np.sqrt(np.maximum((K * (1 - 2 * ac) + 2) ** 2 + 4 * (K * ac**2 - 1), 0.0)))
        return np.where(momentum > ac, spera, momentum)
    # Buhl (2005) as formulated by Ning (2014): continuous at a = 0.4 including F.
    g1 = 2 * F * k - (10 / 9 - F)
    g2 = np.maximum(2 * F * k - F * (4 / 3 - F), 0.0)
    g3 = 2 * F * k - (25 / 9 - 2 * F)
    buhl = np.where(np.abs(g3) < 1e-6, 1 - 1 / (2 * np.sqrt(np.maximum(g2, 1e-12))), (g1 - np.sqrt(g2)) / np.where(np.abs(g3) < 1e-6, 1, g3))
    return np.where(k <= 2.0 / 3.0, momentum, buhl)


def snel_augmentation(cl, alpha_deg, chord, r, alpha0_deg, slope_per_rad, r_over_R):
    """Snel et al.: Δcl = 3 (c/r)² (cl_inviscid − cl_2D), applied inboard of 80 % span."""
    cl_inviscid = slope_per_rad * np.radians(alpha_deg - alpha0_deg)
    delta = 3.0 * (chord / np.maximum(r, 1e-9)) ** 2 * (cl_inviscid - cl)
    weight = np.clip((0.8 - r_over_R) / 0.1, 0.0, 1.0)
    return cl + weight * np.maximum(delta, 0.0) * (cl_inviscid > cl)


def prandtl_glauert(cl, mach):
    return cl / np.sqrt(1.0 - np.minimum(mach, 0.7) ** 2)


# ----------------------------------------------------------------- vertical

def finite_aspect_ratio_alpha(alpha_deg, alpha0_deg, slope_per_rad, aspect_ratio):
    """Lanchester–Prandtl: the 3-D lift slope a/(1 + a/(πAR)) as an effective incidence."""
    factor = 1.0 / (1.0 + slope_per_rad / (math.pi * max(aspect_ratio, 0.5)))
    return alpha0_deg + (alpha_deg - alpha0_deg) * factor


def induced_drag(cl, aspect_ratio, oswald=0.9):
    return cl**2 / (math.pi * max(aspect_ratio, 0.5) * oswald)


def flow_curvature_deg(omega, chord, pitch_axis_fraction, relative_speed):
    """Virtual incidence at the 3/4-chord point for a blade rotating at Ω."""
    return np.degrees(omega * chord * (0.75 - pitch_axis_fraction) / np.maximum(relative_speed, 1e-9))


def gormont_berg(alpha_deg, alpha_rate, chord, relative_speed, thickness, section, reynolds,
                 stall_angle_deg, alpha0_deg, slope_per_rad, am=6.0):
    """Dynamic-stall corrected cl, cd (Gormont reference angle, Berg blending)."""
    tc = min(max(thickness, 0.06), 0.25)
    gamma_l = 1.4 - 6.0 * (0.06 - tc)
    gamma_d = 1.0 - 2.5 * (0.06 - tc)
    s = np.sqrt(np.abs(chord * alpha_rate / (2.0 * np.maximum(relative_speed, 1e-9))))
    increasing = alpha_rate * np.sign(alpha_deg - alpha0_deg + 1e-12) >= 0
    k1 = np.where(increasing, 1.0, -0.5)
    sign = np.sign(alpha_rate)
    delta_l = np.degrees(gamma_l * s) * sign
    delta_d = np.degrees(gamma_d * s) * sign
    alpha_ml = alpha_deg - k1 * delta_l
    alpha_md = alpha_deg - k1 * delta_d
    cl_static, cd_static = section(alpha_deg, reynolds)
    cl_ref, _ = section(alpha_ml, reynolds)
    _, cd_dynamic = section(alpha_md, reynolds)
    lever = np.where(np.abs(alpha_ml - alpha0_deg) < 1e-6, 1.0, (alpha_deg - alpha0_deg) / (alpha_ml - alpha0_deg))
    cl_dynamic = cl_ref * lever
    magnitude = np.abs(alpha_deg - alpha0_deg)
    limit = am * stall_angle_deg
    blend = np.clip((limit - magnitude) / max(limit - stall_angle_deg, 1e-9), 0.0, 1.0)
    blend = np.where(magnitude <= stall_angle_deg, 1.0, blend)
    cl = cl_static + blend * (cl_dynamic - cl_static)
    cd = cd_static + blend * (cd_dynamic - cd_static)
    return cl, np.maximum(cd, 1e-4)


def strut_torque(density, omega, blades, struts_per_blade, strut_chord, strut_cd, radius):
    """Parasitic torque of radial struts: ∫ ½ρ(Ωr)² c Cd r dr over each strut."""
    return blades * struts_per_blade * 0.5 * density * omega**2 * strut_chord * strut_cd * radius**4 / 4.0


def shaft_wake_deficit(y, shaft_diameter, shaft_cd, wake_width_factor=2.0):
    """Fractional velocity deficit behind the central shaft, uniform over its wake."""
    width = wake_width_factor * shaft_diameter
    deficit = min(shaft_cd * shaft_diameter / (2.0 * width), 0.9)
    return np.where(np.abs(y) <= width / 2.0, deficit, 0.0)
