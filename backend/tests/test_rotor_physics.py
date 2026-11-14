import math
import unittest

import numpy as np

from nova.physics import rotors
from nova.physics.axial import AxialRotor, solve_axial
from nova.physics import wake
from nova.physics.corrections import AxialCorrections, VerticalCorrections, du_selig_augmentation, turbine_axial_induction
from nova.physics.fluids import PRESETS, fluid_from
from nova.physics.sections import GRID_DEG, SectionPolar
from nova.physics.vawt import METHODS, VerticalRotor, _inverse_thrust, solve_vertical

BETZ = 16 / 27


def inviscid_section():
    alpha = np.arange(-10.0, 12.5, 0.5)
    points = [{'reynolds': 1e6, 'mach': 0, 'ncrit': 9, 'alpha_deg': a, 'cl': 2 * math.pi * math.radians(a),
               'cd': 1e-4, 'cm': 0} for a in alpha]
    return SectionPolar.from_points('thin plate', points)


class SectionTests(unittest.TestCase):
    def test_full_range_polar_is_continuous_and_reverses_at_180(self):
        section = SectionPolar.synthetic_section('NACA 0018')
        cl, cd = section(GRID_DEG, np.full_like(GRID_DEG, 1e6))
        self.assertAlmostEqual(cl[0], cl[-1], places=6)
        self.assertLess(np.max(np.abs(np.diff(cl))), 0.25)
        self.assertAlmostEqual(float(section(np.array([90.0]), np.array([1e6]))[0][0]), 0.0, places=6)
        self.assertGreater(float(section(np.array([90.0]), np.array([1e6]))[1][0]), 1.2)
        self.assertAlmostEqual(section.zero_lift_angle_deg(), 0.0, places=2)

    def test_reynolds_interpolation_lowers_drag_at_higher_reynolds(self):
        section = SectionPolar.synthetic_section('NACA 0012')
        _, low = section(np.array([0.0]), np.array([1e5]))
        _, high = section(np.array([0.0]), np.array([3e6]))
        self.assertGreater(low[0], high[0])

    def test_fluid_presets_and_overrides(self):
        self.assertTrue(PRESETS['sea_water'].is_liquid)
        self.assertEqual(fluid_from({'preset': 'air', 'density_kg_m3': 1.0}).density_kg_m3, 1.0)
        with self.assertRaises(ValueError):
            fluid_from({'preset': 'air', 'colour': 1})


class AxialTests(unittest.TestCase):
    def test_ideal_optimum_rotor_approaches_glauert_limit(self):
        # Drag-free optimum rotor at λ = 7 without tip loss: Glauert's optimum with
        # wake rotation is Cp ≈ 0.57, below Betz.
        R, B, tsr = 10.0, 3, 7.0
        section = inviscid_section()
        x = np.linspace(0.1, 0.99, 60)
        phi = 2 / 3 * np.arctan(1 / (tsr * x))
        alpha_d = 6.0
        chord = 8 * math.pi * x * R * (1 - np.cos(phi)) / (B * 2 * math.pi * math.radians(alpha_d))
        rotor = AxialRotor(B, R, 0.0, x * R, chord, np.degrees(phi) - alpha_d, section)
        result = solve_axial(rotor, mode='turbine', velocity_m_s=10, rpm=tsr * 10 / R * 60 / (2 * math.pi), fluid=PRESETS['air'],
                             corrections=AxialCorrections(tip_loss='none', hub_loss='none', high_induction='none'))
        self.assertTrue(result['converged'])
        self.assertGreater(result['coefficients']['CP'], 0.53)
        self.assertLess(result['coefficients']['CP'], BETZ)
        a = [s['a'] for s in result['stations'] if s['r_over_R'] > 0.4]
        self.assertTrue(all(0.27 < v < 0.36 for v in a))

    def test_cp_lambda_curve_respects_betz_and_has_interior_optimum(self):
        curve = rotors.performance_curve({'kind': 'hawt'}, points=13)
        cp = [r['CP'] for r in curve['rows']]
        self.assertTrue(all(c < BETZ for c in cp))
        self.assertTrue(3 < curve['optimum']['tip_speed_ratio'] < 11)
        self.assertGreater(curve['optimum']['value'], 0.3)

    def test_tip_and_hub_losses_reduce_power(self):
        spec = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}}
        with_losses = rotors.analyze(spec)['coefficients']['CP']
        without = rotors.analyze({**spec, 'corrections': {'tip_loss': 'none', 'hub_loss': 'none'}})['coefficients']['CP']
        self.assertLess(with_losses, without)

    def test_high_induction_models_are_continuous_and_bounded(self):
        k = np.linspace(0.0, 6.0, 400)
        for model in ('none', 'glauert', 'buhl', 'spera'):
            a = turbine_axial_induction(k, np.ones_like(k), model)
            self.assertTrue(np.all(np.isfinite(a)))
            self.assertLess(np.max(np.abs(np.diff(a))), 0.05, model)
        self.assertLess(turbine_axial_induction(np.array([4.0]), np.array([1.0]), 'buhl')[0],
                        turbine_axial_induction(np.array([4.0]), np.array([1.0]), 'none')[0])

    def test_propeller_static_and_advance_behaviour(self):
        static = rotors.analyze({'kind': 'propeller', 'operating': {'rpm': 6000, 'advance_ratio': 0.0}})
        self.assertTrue(0.3 < static['coefficients']['figure_of_merit'] < 0.85)
        curve = rotors.performance_curve({'kind': 'propeller'}, points=8)
        kt = [r['KT'] for r in curve['rows']]
        self.assertTrue(all(b < a for a, b in zip(kt, kt[1:])))
        self.assertTrue(all((r.get('efficiency') or 0) < 1 for r in curve['rows']))


class MarineTests(unittest.TestCase):
    def test_b_series_open_water_point_is_in_family(self):
        # Wageningen B4-55, P/D = 1.0 at J = 0.6: K_T ≈ 0.28, 10K_Q ≈ 0.45, η0 ≈ 0.60.
        result = rotors.analyze({'kind': 'marine'})
        marine = result['marine']
        self.assertAlmostEqual(marine['advance_ratio_J'], 0.6, places=6)
        self.assertLess(abs(marine['KT'] - 0.28) / 0.28, 0.25)
        self.assertLess(abs(marine['10KQ'] - 0.45) / 0.45, 0.25)
        self.assertTrue(0.5 < marine['open_water_efficiency'] < 0.7)

    def test_cavitation_quantities_match_hand_calculation(self):
        result = rotors.analyze({'kind': 'marine'})
        m, f = result['marine'], PRESETS['sea_water']
        n, D, T = 2.0, 4.0, result['performance']['thrust_n']
        static = f.ambient_pressure_pa + f.density_kg_m3 * 9.80665 * 5.0 - f.vapour_pressure_pa
        va = 0.6 * n * D
        sigma = static / (0.5 * f.density_kg_m3 * (va**2 + (0.7 * math.pi * n * D) ** 2))
        self.assertAlmostEqual(m['cavitation_number_07R'], sigma, places=9)
        self.assertAlmostEqual(m['keller_minimum_area_ratio'], (1.3 + 0.3 * 4) * T / (static * D**2) + 0.2, places=9)
        self.assertAlmostEqual(m['hull_efficiency'], 0.85 / 0.8, places=9)
        self.assertAlmostEqual(m['effective_thrust_n'], T * 0.85, places=6)

    def test_marine_requires_liquid(self):
        with self.assertRaises(ValueError):
            rotors.analyze({'kind': 'marine', 'fluid': {'preset': 'air'}})


class VerticalTests(unittest.TestCase):
    def rotor(self, **extra):
        return VerticalRotor(3, 1.0, 2.0, 0.12, SectionPolar.synthetic_section('NACA 0018', 2.0 / 0.12), **extra)

    def test_all_streamtube_methods_converge_below_betz(self):
        for method in METHODS:
            for tsr in (2.0, 3.0, 4.5):
                result = solve_vertical(self.rotor(), method=method, wind_speed_m_s=8, rpm=tsr * 8 * 60 / (2 * math.pi),
                                        fluid=PRESETS['air'], corrections=VerticalCorrections())
                self.assertTrue(result['converged'], (method, tsr))
                self.assertLess(result['coefficients']['CP'], BETZ)

    def test_dmst_downwind_half_sees_slower_flow(self):
        result = rotors.analyze({'kind': 'vawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 3.5}})
        up = [p['local_velocity_ratio'] for p in result['azimuth'] if p['half'] == 'upwind']
        down = [p['local_velocity_ratio'] for p in result['azimuth'] if p['half'] == 'downwind']
        self.assertLess(np.mean(down), np.mean(up))
        self.assertTrue(all(p['alpha_deg'] > 0 for p in result['azimuth'] if p['half'] == 'upwind'))

    def test_low_solidity_single_and_double_multiple_agree(self):
        spec = {'kind': 'vawt', 'geometry': {'chord_m': 0.03}, 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 5}}
        single = rotors.analyze({**spec, 'method': 'single_streamtube'})['coefficients']['CP']
        dmst = rotors.analyze({**spec, 'method': 'double_multiple_streamtube'})['coefficients']['CP']
        self.assertLess(abs(single - dmst) / dmst, 0.2)

    def test_corrections_change_the_prediction_in_the_expected_direction(self):
        base = {'kind': 'vawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 3}}
        reference = rotors.analyze(base)['coefficients']['CP']
        infinite = rotors.analyze({**base, 'corrections': {'finite_aspect_ratio': False}})['coefficients']['CP']
        struts = rotors.analyze({**base, 'corrections': {'strut_drag': True}})
        self.assertGreater(infinite, reference)
        self.assertLess(struts['coefficients']['CP'], reference)
        self.assertGreater(struts['performance']['strut_torque_loss_nm'], 0)
        for options in ({'flow_curvature': True}, {'dynamic_stall': 'gormont_berg'}, {'shaft_wake': True}):
            changed = rotors.analyze({**base, 'corrections': options})['coefficients']['CP']
            self.assertNotAlmostEqual(changed, reference, places=4, msg=options)

    def test_upstream_wake_deficits_follow_the_models(self):
        rotor_wake = {'kind': 'rotor', 'model': 'jensen', 'diameter_m': 10, 'coefficient': 0.75, 'distance_m': 50, 'decay': 0.05}
        # Jensen: (1 - sqrt(1 - Ct)) (D / (D + 2 k x))^2 = 0.5 * (10 / 15)^2 over a fully covered disk.
        full = wake.mean_deficit(rotor_wake, 10)
        self.assertAlmostEqual(full['mean_deficit'], 0.5 * (10 / 15) ** 2, places=3)
        self.assertAlmostEqual(full['covered_fraction'], 1.0, places=2)
        # Moving the source sideways uncovers the disk and lowers the mean deficit.
        shifted = wake.mean_deficit({**rotor_wake, 'offset_m': 12}, 10)
        self.assertLess(shifted['mean_deficit'], full['mean_deficit'])
        self.assertLess(shifted['covered_fraction'], 1.0)
        far = wake.mean_deficit({**rotor_wake, 'distance_m': 400}, 10)
        self.assertLess(far['mean_deficit'], full['mean_deficit'])
        gaussian = wake.mean_deficit({**rotor_wake, 'model': 'gaussian'}, 10)
        self.assertTrue(0 < gaussian['mean_deficit'] < gaussian['peak_deficit'] < 0.5)
        self.assertEqual(wake.mean_deficit(None, 10)['mean_deficit'], 0.0)
        for bad in ({'kind': 'rotor', 'diameter_m': -1, 'coefficient': 0.5, 'distance_m': 5}, {'kind': 'rotor'},
                    {'kind': 'body', 'model': 'x', 'diameter_m': 1, 'coefficient': 1, 'distance_m': 5}):
            with self.assertRaises(ValueError):
                wake.validate(bad)

    def test_upstream_wake_reduces_power_and_inflow_for_a_turbine(self):
        base = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}}
        free = rotors.analyze(base)
        behind = rotors.analyze({**base, 'upstream_wake': {'kind': 'body', 'model': 'gaussian', 'diameter_m': 4, 'coefficient': 1.0, 'distance_m': 20}})
        self.assertGreater(behind['upstream_wake']['mean_deficit'], 0.0)
        self.assertLess(behind['upstream_wake']['effective_velocity_m_s'], 8)
        self.assertLess(behind['performance']['power_w'], free['performance']['power_w'])
        self.assertNotIn('upstream_wake', free)

    def test_du_selig_leaves_attached_flow_alone_and_delays_stall_near_the_hub(self):
        alpha = np.array([4.0, 25.0])
        slope, alpha0 = 2 * math.pi, 0.0
        cl2d = np.array([slope * math.radians(4.0), 0.9])
        cd2d = np.array([0.01, 0.2])
        cl, cd = du_selig_augmentation(cl2d, cd2d, 0.01, alpha, np.full(2, 0.4), np.full(2, 1.0), 10.0, 7.0, alpha0, slope)
        self.assertAlmostEqual(cl[0], cl2d[0], places=9)
        self.assertGreater(cl[1], cl2d[1])
        self.assertGreater(cd[1], cd2d[1])
        outboard_cl, _ = du_selig_augmentation(cl2d, cd2d, 0.01, alpha, np.full(2, 0.4), np.full(2, 9.0), 10.0, 7.0, alpha0, slope)
        self.assertLess(outboard_cl[1] - cl2d[1], cl[1] - cl2d[1])
        stalled = rotors.analyze({'kind': 'hawt', 'operating': {'velocity_m_s': 5, 'tip_speed_ratio': 3}, 'corrections': {'rotational_augmentation': 'du_selig'}})
        self.assertTrue(stalled['converged'])
        self.assertEqual(stalled['corrections']['rotational_augmentation'], 'du_selig')

    def test_resolved_inflow_reduces_to_the_axisymmetric_solution_when_uniform(self):
        base = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}}
        reference = rotors.analyze(base)
        resolved = rotors.analyze({**base, 'inflow': {'resolved': True}})
        for key in ('thrust_n', 'torque_nm', 'power_w'):
            self.assertAlmostEqual(resolved['performance'][key] / reference['performance'][key], 1.0, places=6)
        self.assertAlmostEqual(resolved['performance']['blade_thrust_variation'], 0.0, places=9)
        self.assertEqual(len(resolved['rotation']), 36)
        propeller = {'kind': 'propeller', 'operating': {'rpm': 3000, 'advance_ratio': 0.5}}
        self.assertAlmostEqual(rotors.analyze({**propeller, 'inflow': {'resolved': True}})['performance']['thrust_n'] /
                               rotors.analyze(propeller)['performance']['thrust_n'], 1.0, places=6)

    def test_yaw_loses_power_like_cos_cubed_and_loads_vary_around_the_azimuth(self):
        base = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}}
        free = rotors.analyze(base)['performance']['power_w']
        left = rotors.analyze({**base, 'inflow': {'resolved': True, 'yaw_deg': 20}})
        right = rotors.analyze({**base, 'inflow': {'resolved': True, 'yaw_deg': -20}})
        self.assertTrue(left['converged'])
        self.assertTrue(0.7 < left['performance']['power_w'] / free < 0.9, left['performance']['power_w'] / free)
        self.assertAlmostEqual(left['performance']['power_w'] / right['performance']['power_w'], 1.0, delta=0.02)
        self.assertGreater(left['performance']['blade_thrust_variation'], 0.1)
        # The blade that moves against the in-plane wind component carries a different load from the one moving with it.
        thrust = [row['blade_thrust_n'] for row in left['rotation']]
        self.assertNotAlmostEqual(thrust[9], thrust[27], delta=0.05 * abs(sum(thrust) / len(thrust)))

    def test_shear_and_tower_shadow_act_where_they_should(self):
        base = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}}
        uniform = rotors.analyze({**base, 'inflow': {'resolved': True}})
        sheared = rotors.analyze({**base, 'inflow': {'resolved': True, 'shear_exponent': 0.2, 'hub_height_m': 30}})
        self.assertAlmostEqual(sheared['performance']['thrust_n'] / uniform['performance']['thrust_n'], 1.0, delta=0.02)
        thrust = [row['blade_thrust_n'] for row in sheared['rotation']]
        self.assertGreater(thrust[0], thrust[18])  # blade up sees faster wind than blade down
        shadow = rotors.analyze({**base, 'inflow': {'resolved': True, 'hub_height_m': 30, 'tower': {'kind': 'upwind', 'radius_m': 0.5, 'distance_m': 2.5}}})
        loads = [row['blade_thrust_n'] for row in shadow['rotation']]
        self.assertEqual(loads.index(min(loads)), 18)  # directly in front of the tower
        self.assertLess(shadow['performance']['power_w'], uniform['performance']['power_w'])
        downwind = rotors.analyze({**base, 'inflow': {'resolved': True, 'hub_height_m': 30, 'tower': {'kind': 'downwind', 'radius_m': 0.5, 'distance_m': 2.5}}})
        self.assertLess(downwind['performance']['power_w'], uniform['performance']['power_w'])

    def test_partial_upstream_wake_is_resolved_around_the_disk(self):
        base = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}}
        wake_config = {'kind': 'rotor', 'model': 'gaussian', 'diameter_m': 10, 'coefficient': 0.75, 'distance_m': 40, 'offset_m': 6}
        resolved = rotors.analyze({**base, 'upstream_wake': wake_config, 'inflow': {'resolved': True}})
        self.assertGreater(resolved['performance']['blade_thrust_variation'], 0.3)
        self.assertLess(resolved['inflow']['speed_ratio_min'], 0.8)
        self.assertNotIn('upstream_wake', resolved)
        rows = resolved['rotation']
        # The wake lies on the +y side (ψ = 90°), so that blade position is the most loaded-down one.
        self.assertLess(rows[9]['inflow_ratio'], rows[27]['inflow_ratio'])

    def test_oye_dynamic_stall_changes_loads_only_when_incidence_varies(self):
        base = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}, 'corrections': {'dynamic_stall': 'oye'}}
        steady = rotors.analyze(base)
        self.assertTrue(any('Dynamic stall' in w for w in steady['warnings']))
        self.assertAlmostEqual(steady['performance']['power_w'], rotors.analyze({**base, 'corrections': {}})['performance']['power_w'], places=6)
        # Yaw at low tip-speed ratio drives inboard sections into stall with changing incidence.
        low = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 4}, 'inflow': {'resolved': True, 'yaw_deg': 20}}
        static = rotors.analyze(low)
        dynamic = rotors.analyze({**low, 'corrections': {'dynamic_stall': 'oye'}})
        self.assertEqual(dynamic['inflow']['dynamic_stall'], 'oye')
        self.assertLessEqual(dynamic['inflow']['attached_fraction_min'], 1.0)
        self.assertTrue(dynamic['converged'])
        self.assertNotAlmostEqual(dynamic['performance']['torque_nm'], static['performance']['torque_nm'], places=3)

    def test_invalid_resolved_inflow_is_rejected(self):
        base = {'kind': 'hawt', 'operating': {'velocity_m_s': 8, 'tip_speed_ratio': 7}}
        for inflow in ({'resolved': True, 'shear_exponent': 0.2}, {'resolved': True, 'yaw_deg': 80}, {'resolved': True, 'azimuth_steps': 7},
                       {'resolved': True, 'colour': 1}, {'resolved': True, 'hub_height_m': 30, 'tower': {'kind': 'upwind', 'radius_m': 3, 'distance_m': 2}}):
            with self.assertRaises(ValueError, msg=inflow):
                rotors.analyze({**base, 'inflow': inflow})
        with self.assertRaises(ValueError):
            rotors.analyze({'kind': 'vawt', 'inflow': {'resolved': True}})

    def test_streamtube_inverse_thrust_is_monotonic(self):
        ct = np.linspace(0, 1.8, 200)
        for model in ('glauert', 'buhl', 'spera'):
            a = _inverse_thrust(ct, model)
            self.assertTrue(np.all(np.diff(a) >= -1e-9), model)

    def test_troposkien_has_smaller_swept_area(self):
        straight = rotors.analyze({'kind': 'vawt'})
        curved = rotors.analyze({'kind': 'vawt', 'geometry': {'shape': 'troposkien'}})
        self.assertLess(curved['geometry']['swept_area_m2'], straight['geometry']['swept_area_m2'])

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            rotors.analyze({'kind': 'vawt', 'geometry': {'chord_m': 2.0}})
        with self.assertRaises(ValueError):
            rotors.analyze({'kind': 'vawt', 'method': 'unknown'})
        with self.assertRaises(ValueError):
            rotors.analyze({'kind': 'hawt', 'corrections': {'tip_loss': 'magic'}})

    def test_only_family_corrections_are_accepted(self):
        catalog = rotors.catalog()['corrections_by_kind']
        self.assertEqual(catalog['marine'], ['tip_loss', 'hub_loss'])
        self.assertNotIn('compressibility', catalog['hawt'])
        for kind, corrections in (('marine', {'compressibility': 'prandtl_glauert'}), ('marine', {'high_induction': 'buhl'}),
                                  ('marine', {'rotational_augmentation': 'du_selig'}), ('hawt', {'compressibility': 'prandtl_glauert'})):
            with self.assertRaisesRegex(ValueError, 'not applicable'):
                rotors.analyze({'kind': kind, 'corrections': corrections})


if __name__ == '__main__':
    unittest.main()
