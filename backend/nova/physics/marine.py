"""Marine propeller theory layered on axial BEMT.

Covers the quantities a propeller designer checks beyond open-water BEMT:

  * open-water coefficients  J = V_A/(nD), K_T, K_Q, η_0 = J K_T / (2π K_Q)
  * hull interaction         V_A = V_s (1 − w),  T_eff = T (1 − t),
                             η_H = (1 − t)/(1 − w),  η_D = η_0 η_H η_R
  * cavitation               σ_0.7R, Burrill thrust-loading τ_c (projected-area
                             estimate A_P/A_D ≈ 1.067 − 0.229 P/D), Keller's
                             minimum expanded-area ratio, local section σ
  * blade outline            Wageningen B-series chord distribution

Burrill's acceptance lines are not hard-coded: published curve fits differ, so
the limit is supplied as a workflow constraint on τ_c against σ_0.7R.
"""
import math

import numpy as np

from .axial import AxialRotor
from .fluids import GRAVITY

# Wageningen B-series: c/D · Z/(A_E/A_0) at r/R (Oosterveld & van Oossanen 1975).
B_SERIES_R = np.array([0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
B_SERIES_CHORD = np.array([1.662, 1.882, 2.050, 2.152, 2.187, 2.144, 1.970, 1.582, 0.0])


def b_series_rotor(section, *, diameter_m, blades, area_ratio, pitch_ratio, hub_ratio=0.2, stations=25, pitch_deg=0.0):
    if not 2 <= blades <= 7:
        raise ValueError('B-series outline is defined for 2–7 blades')
    if not 0.3 <= area_ratio <= 1.05:
        raise ValueError('Expanded area ratio must be in 0.30–1.05')
    if not 0.5 <= pitch_ratio <= 1.4:
        raise ValueError('Pitch ratio P/D must be in 0.5–1.4')
    R = diameter_m / 2
    x = np.linspace(max(hub_ratio, 0.2), 1.0, stations)
    chord = np.interp(x, B_SERIES_R, B_SERIES_CHORD) * diameter_m * area_ratio / blades
    # Keep a small finite tip chord so the tip station carries the loss factor.
    chord[-1] = max(chord[-1], 0.02 * diameter_m * area_ratio / blades)
    twist = np.degrees(np.arctan(pitch_ratio / (math.pi * x)))
    return AxialRotor(blades, R, hub_ratio * R, x * R, chord, twist, section, pitch_deg)


def hull_interaction(ship_speed_m_s, wake_fraction, thrust_deduction, relative_rotative=1.0):
    if not 0 <= wake_fraction < 0.6 or not 0 <= thrust_deduction < 0.5 or not 0.8 <= relative_rotative <= 1.2:
        raise ValueError('Expected 0 ≤ w < 0.6, 0 ≤ t < 0.5 and 0.8 ≤ η_R ≤ 1.2')
    return {'advance_speed_m_s': ship_speed_m_s * (1 - wake_fraction),
            'hull_efficiency': (1 - thrust_deduction) / (1 - wake_fraction),
            'wake_fraction': wake_fraction, 'thrust_deduction': thrust_deduction,
            'relative_rotative_efficiency': relative_rotative}


def marine_assessment(result, rotor, fluid, *, shaft_depth_m, area_ratio, pitch_ratio, hull=None, keller_k=0.2):
    """Post-process a propeller-mode BEMT result with marine criteria."""
    if fluid.vapour_pressure_pa is None:
        raise ValueError('Marine assessment needs a liquid with a vapour pressure')
    if shaft_depth_m <= rotor.tip_radius_m:
        raise ValueError('Shaft immersion must exceed the propeller radius')
    rho, D, Z = fluid.density_kg_m3, 2 * rotor.tip_radius_m, rotor.blades
    n = result['operating']['rpm'] / 60
    VA = result['operating']['velocity_m_s']
    T, Q = result['performance']['thrust_n'], result['performance']['torque_nm']
    kt, kq = T / (rho * n**2 * D**4), Q / (rho * n**2 * D**5)
    J = VA / (n * D)
    eta0 = J * kt / (2 * math.pi * kq) if kq > 0 else None
    static = fluid.ambient_pressure_pa + rho * GRAVITY * shaft_depth_m - fluid.vapour_pressure_pa
    v07_sq = VA**2 + (0.7 * math.pi * n * D) ** 2
    sigma07 = static / (0.5 * rho * v07_sq)
    disc = math.pi * D**2 / 4
    developed = area_ratio * disc
    projected = developed * (1.067 - 0.229 * pitch_ratio)
    tau_c = T / (projected * 0.5 * rho * v07_sq)
    keller = (1.3 + 0.3 * Z) * T / (static * D**2) + keller_k
    # Local section cavitation number with the blade at top dead centre (worst case).
    local = []
    for station in result['stations']:
        head = fluid.ambient_pressure_pa + rho * GRAVITY * (shaft_depth_m - station['radius_m']) - fluid.vapour_pressure_pa
        local.append(head / (0.5 * rho * station['relative_velocity_m_s'] ** 2))
    marine = {
        'advance_ratio_J': J, 'KT': kt, 'KQ': kq, '10KQ': 10 * kq, 'open_water_efficiency': eta0,
        'cavitation_number_07R': sigma07, 'thrust_loading_tau_c': tau_c,
        'keller_minimum_area_ratio': keller, 'area_ratio': area_ratio,
        'keller_margin': area_ratio - keller, 'projected_area_m2': projected,
        'minimum_local_cavitation_number': float(min(local)) if local else None,
        'local_cavitation_number': local,
    }
    if hull:
        marine.update(hull)
        marine['effective_thrust_n'] = T * (1 - hull['thrust_deduction'])
        if eta0 is not None:
            marine['quasi_propulsive_efficiency'] = eta0 * hull['hull_efficiency'] * hull['relative_rotative_efficiency']
    warnings = []
    if keller > area_ratio:
        warnings.append(f'Keller criterion: expanded area ratio {area_ratio:.2f} below minimum {keller:.2f}')
    if local and min(local) < 0.5:
        warnings.append('Low local cavitation number near the tip at top dead centre')
    return marine, warnings
