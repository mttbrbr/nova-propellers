"""Wind-turbine mass, cost and cost-of-energy models.

Component masses and costs follow the NREL Cost and Scaling Model (Fingersh, Hand & Laxson 2006,
NREL/TP-500-40566) in its 2015 mass–cost update, with the coefficients of the open-source
implementation in NREL's WISDEM (``wisdem.nrelcsm``, Apache-2.0): every component mass is a curve fit of
rotor diameter, machine rating, rotor torque or hub height, and every cost is a mass (or rating)
multiplier. The gearbox follows WISDEM's 2024 torque-density form (200 N·m/kg, 50 USD/kN·m) and the brake
its 2020 update. Costs are in the USD of the coefficients (2015 dollars for most components); they are
scaling estimates for comparing designs, not quotations. Land-based balance of station and operating
costs are user inputs per kW, as in WISDEM's plant-finance model:

    LCOE = (FCR · (TCC + BOS) / P + OpEx / P) / (AEP_net / P)
"""
import math

import numpy as np

# coefficient table: name → value (documented in docs/technical/cost-models.md)
COEFFICIENTS = {
    'blade_mass_coeff': 0.5, 'blade_cost_per_kg': 14.6,
    'hub_mass_coeff': 2.3, 'hub_mass_intercept': 1320.0, 'hub_cost_per_kg': 3.9,
    'pitch_bearing_mass_coeff': 0.1295, 'pitch_bearing_mass_intercept': 491.31, 'pitch_housing_fraction': 0.328,
    'pitch_mass_offset': 555.0, 'pitch_cost_per_kg': 22.1,
    'spinner_mass_coeff': 15.5, 'spinner_mass_intercept': -980.0, 'spinner_cost_per_kg': 11.1,
    'lss_mass_coeff': 13.0, 'lss_mass_exp': 0.65, 'lss_mass_intercept': 775.0, 'lss_cost_per_kg': 11.9,
    'bearing_mass_coeff': 0.0001, 'bearing_mass_exp': 3.5, 'bearing_cost_per_kg': 4.5,
    'gearbox_torque_density_nm_kg': 200.0, 'gearbox_cost_per_knm': 50.0,
    'brake_mass_per_nm': 0.00122, 'brake_cost_per_kg': 3.6254,
    'hss_mass_per_kw': 0.19894, 'hss_cost_per_kg': 6.8,
    'generator_mass_per_kw': 2.3, 'generator_mass_intercept': 3400.0, 'generator_cost_per_kg': 12.4,
    'bedplate_mass_exp': 2.2, 'bedplate_cost_per_kg': 2.9,
    'yaw_mass_coeff': 0.0009, 'yaw_mass_exp': 3.314, 'yaw_cost_per_kg': 8.3,
    'hvac_mass_per_kw': 0.08, 'hvac_cost_per_kg': 124.0,
    'cover_mass_per_kw': 1.2817, 'cover_mass_intercept': 428.19, 'cover_cost_per_kg': 5.7,
    'platforms_mass_fraction': 0.125, 'platforms_cost_per_kg': 17.1, 'crane_mass_kg': 3000.0, 'crane_cost': 12000.0,
    'transformer_mass_per_kw': 1.915, 'transformer_mass_intercept': 1910.0, 'transformer_cost_per_kg': 18.8,
    'electrical_cost_per_kw': 41.85, 'controls_cost_per_kw': 21.15,
    'tower_mass_coeff': 19.828, 'tower_mass_exp': 2.0282, 'tower_cost_per_kg': 2.9,
}
BLADE_EXPONENT = {(1, True): 2.47, (1, False): 2.54, (2, True): 2.44, (2, False): 2.50}


class CostError(ValueError):
    pass


def turbine(*, rotor_diameter_m, rating_kw, hub_height_m, blades=3, max_tip_speed_m_s=80.0, drivetrain_efficiency=0.95,
            turbine_class=2, carbon_spar=False, main_bearings=2, crane=False, blade_mass_kg=None, tower_mass_kg=None,
            coefficients=None):
    """Component masses (kg) and costs (USD) of a land-based three-stage geared turbine."""
    k = {**COEFFICIENTS, **(coefficients or {})}
    D, P = float(rotor_diameter_m), float(rating_kw)
    if D <= 0 or P <= 0 or hub_height_m <= 0 or max_tip_speed_m_s <= 0 or not 0 < drivetrain_efficiency <= 1:
        raise CostError('Rotor diameter, rating, hub height, tip speed and efficiency must be positive')
    exponent = BLADE_EXPONENT[(1 if turbine_class == 1 else 2, bool(carbon_spar))]
    m, c = {}, {}
    m['blade'] = blade_mass_kg if blade_mass_kg is not None else k['blade_mass_coeff'] * (D / 2) ** exponent
    c['blade'] = k['blade_cost_per_kg'] * m['blade']
    m['hub'] = k['hub_mass_coeff'] * m['blade'] + k['hub_mass_intercept']
    c['hub'] = k['hub_cost_per_kg'] * m['hub']
    bearing = k['pitch_bearing_mass_coeff'] * m['blade'] * blades + k['pitch_bearing_mass_intercept']
    m['pitch_system'] = bearing * (1 + k['pitch_housing_fraction']) + k['pitch_mass_offset']
    c['pitch_system'] = k['pitch_cost_per_kg'] * m['pitch_system']
    m['spinner'] = max(k['spinner_mass_coeff'] * D + k['spinner_mass_intercept'], 0.0)
    c['spinner'] = k['spinner_cost_per_kg'] * m['spinner']
    m['low_speed_shaft'] = k['lss_mass_coeff'] * (m['blade'] * P * 1e-3) ** k['lss_mass_exp'] + k['lss_mass_intercept']
    c['low_speed_shaft'] = k['lss_cost_per_kg'] * m['low_speed_shaft']
    m['main_bearings'] = main_bearings * k['bearing_mass_coeff'] * D ** k['bearing_mass_exp']
    c['main_bearings'] = k['bearing_cost_per_kg'] * m['main_bearings']
    omega = max_tip_speed_m_s / (D / 2)
    torque_knm = P / drivetrain_efficiency / omega
    m['gearbox'] = torque_knm * 1e3 / k['gearbox_torque_density_nm_kg']
    c['gearbox'] = torque_knm * k['gearbox_cost_per_knm']
    m['brake'] = k['brake_mass_per_nm'] * torque_knm * 1e3
    c['brake'] = k['brake_cost_per_kg'] * m['brake']
    m['high_speed_shaft'] = k['hss_mass_per_kw'] * P
    c['high_speed_shaft'] = k['hss_cost_per_kg'] * m['high_speed_shaft']
    m['generator'] = k['generator_mass_per_kw'] * P + k['generator_mass_intercept']
    c['generator'] = k['generator_cost_per_kg'] * m['generator']
    m['bedplate'] = D ** k['bedplate_mass_exp']
    c['bedplate'] = k['bedplate_cost_per_kg'] * m['bedplate']
    m['yaw_system'] = k['yaw_mass_coeff'] * D ** k['yaw_mass_exp']
    c['yaw_system'] = k['yaw_cost_per_kg'] * m['yaw_system']
    m['hydraulics_cooling'] = k['hvac_mass_per_kw'] * P
    c['hydraulics_cooling'] = k['hvac_cost_per_kg'] * m['hydraulics_cooling']
    m['nacelle_cover'] = k['cover_mass_per_kw'] * P + k['cover_mass_intercept']
    c['nacelle_cover'] = k['cover_cost_per_kg'] * m['nacelle_cover']
    m['platforms'] = k['platforms_mass_fraction'] * m['bedplate'] + (k['crane_mass_kg'] if crane else 0.0)
    c['platforms'] = k['platforms_cost_per_kg'] * k['platforms_mass_fraction'] * m['bedplate'] + (k['crane_cost'] if crane else 0.0)
    m['transformer'] = k['transformer_mass_per_kw'] * P + k['transformer_mass_intercept']
    c['transformer'] = k['transformer_cost_per_kg'] * m['transformer']
    c['electrical_connections'] = k['electrical_cost_per_kw'] * P
    c['controls'] = k['controls_cost_per_kw'] * P
    m['tower'] = tower_mass_kg if tower_mass_kg is not None else k['tower_mass_coeff'] * hub_height_m ** k['tower_mass_exp']
    c['tower'] = k['tower_cost_per_kg'] * m['tower']
    hub_system = ('hub', 'pitch_system', 'spinner')
    nacelle = ('low_speed_shaft', 'main_bearings', 'gearbox', 'brake', 'high_speed_shaft', 'generator', 'bedplate', 'yaw_system',
               'hydraulics_cooling', 'nacelle_cover', 'platforms', 'transformer')
    totals = {
        'rotor_mass_kg': blades * m['blade'] + sum(m[x] for x in hub_system),
        'nacelle_mass_kg': sum(m[x] for x in nacelle),
        'tower_mass_kg': m['tower'],
        'rotor_cost_usd': blades * c['blade'] + sum(c[x] for x in hub_system),
        'nacelle_cost_usd': sum(c[x] for x in nacelle) + c['electrical_connections'] + c['controls'],
        'tower_cost_usd': c['tower'],
        'rated_torque_knm': torque_knm, 'rated_rpm': omega * 30 / math.pi,
    }
    totals['turbine_mass_kg'] = totals['rotor_mass_kg'] + totals['nacelle_mass_kg'] + totals['tower_mass_kg']
    totals['turbine_cost_usd'] = totals['rotor_cost_usd'] + totals['nacelle_cost_usd'] + totals['tower_cost_usd']
    totals['turbine_cost_per_kw'] = totals['turbine_cost_usd'] / P
    rows = [{'component': name, 'mass_kg': m.get(name), 'cost_usd': c[name] * (blades if name == 'blade' else 1),
             'count': blades if name == 'blade' else 1} for name in c]
    return {'components': rows, 'totals': totals, 'blade_exponent': exponent}


def weibull_aep(wind_speed, power_w, *, mean_wind_m_s, shape=2.0, availability=1.0, losses=0.0):
    """Annual energy (kWh) of a power curve under a Weibull wind distribution (k = 2 is Rayleigh)."""
    v = np.asarray(wind_speed, dtype=float)
    p = np.asarray(power_w, dtype=float)
    if len(v) < 2 or np.any(np.diff(v) <= 0):
        raise CostError('The power curve needs increasing wind speeds')
    if mean_wind_m_s <= 0 or shape <= 0:
        raise CostError('Mean wind speed and Weibull shape must be positive')
    scale = mean_wind_m_s / math.gamma(1 + 1 / shape)
    grid = np.linspace(0.0, max(v[-1], 1e-6), 2001)
    pdf = (shape / scale) * (grid / scale) ** (shape - 1) * np.exp(-((grid / scale) ** shape))
    power = np.interp(grid, v, p, left=0.0, right=0.0)
    mean_power = np.trapezoid(power * pdf, grid)
    return mean_power * 8760.0 / 1000.0 * availability * (1 - losses), scale


def lcoe(*, turbine_cost_usd, rating_kw, aep_kwh, bos_per_kw, opex_per_kw_yr, fixed_charge_rate=0.075, wake_losses=0.0):
    """Levelised cost of energy (USD/kWh) of one turbine in a plant, WISDEM plant-finance form."""
    if aep_kwh <= 0:
        raise CostError('Annual energy must be positive')
    icc = turbine_cost_usd / rating_kw + bos_per_kw
    net = aep_kwh * (1 - wake_losses) / rating_kw
    return (icc * fixed_charge_rate + opex_per_kw_yr) / net, icc
