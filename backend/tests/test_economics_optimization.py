"""Phase 3: cost model, annual energy, LCOE and optimisers over the downstream workflow."""
import copy
import math
import unittest

from nova.blocks import economics, engine
from nova.physics import costs, rotors


class CostModel(unittest.TestCase):
    def test_component_equations(self):
        out = costs.turbine(rotor_diameter_m=126.0, rating_kw=5000.0, hub_height_m=90.0, max_tip_speed_m_s=80.0)
        parts = {r['component']: r for r in out['components']}
        blade = 0.5 * 63.0**2.50
        self.assertAlmostEqual(parts['blade']['mass_kg'], blade)
        self.assertAlmostEqual(parts['blade']['cost_usd'], 3 * 14.6 * blade)
        self.assertAlmostEqual(parts['hub']['mass_kg'], 2.3 * blade + 1320)
        torque = 5000 / 0.95 / (80 / 63)
        self.assertAlmostEqual(out['totals']['rated_torque_knm'], torque)
        self.assertAlmostEqual(parts['gearbox']['cost_usd'], 50 * torque)
        self.assertAlmostEqual(parts['tower']['mass_kg'], 19.828 * 90**2.0282)
        self.assertAlmostEqual(parts['main_bearings']['mass_kg'], 2 * 0.0001 * 126**3.5)
        self.assertAlmostEqual(out['totals']['turbine_cost_usd'], sum(r['cost_usd'] for r in out['components']))

    def test_carbon_and_class_exponents(self):
        light = costs.turbine(rotor_diameter_m=100, rating_kw=2000, hub_height_m=80, turbine_class=1, carbon_spar=True)
        heavy = costs.turbine(rotor_diameter_m=100, rating_kw=2000, hub_height_m=80, turbine_class=1, carbon_spar=False)
        self.assertLess(light['totals']['rotor_mass_kg'], heavy['totals']['rotor_mass_kg'])

    def test_weibull_step_curve(self):
        """Constant power between v1 and v2: AEP = P · 8760 · (e^{-(v1/c)^k} − e^{-(v2/c)^k})."""
        v = [0.0, 4.999, 5.0, 15.0, 15.001, 30.0]
        p = [0.0, 0.0, 1000.0, 1000.0, 0.0, 0.0]
        aep, scale = costs.weibull_aep(v, p, mean_wind_m_s=7.0, shape=2.0, availability=1.0)
        expected = 1.0 * 8760 * (math.exp(-(5 / scale) ** 2) - math.exp(-(15 / scale) ** 2))
        self.assertAlmostEqual(aep, expected, delta=2e-3 * expected)

    def test_lcoe(self):
        value, icc = costs.lcoe(turbine_cost_usd=1.0e6, rating_kw=1000, aep_kwh=3.0e6, bos_per_kw=400, opex_per_kw_yr=40)
        self.assertAlmostEqual(icc, 1400)
        self.assertAlmostEqual(value, (1400 * 0.075 + 40) / 3000)

    def test_block_needs_site_costs_for_lcoe(self):
        out = economics.cost_model({'config': {'rating_kw': 20.0, 'hub_height_m': 20.0}}, {'spec': rotors.merged({'kind': 'hawt'})})
        self.assertNotIn('lcoe_usd_kwh', out['values'])
        out = economics.cost_model({'config': {'rating_kw': 20.0, 'hub_height_m': 20.0, 'bos_per_kw': 500, 'opex_per_kw_yr': 50}},
                                   {'spec': rotors.merged({'kind': 'hawt'}), 'values': {'aep_kwh': 4.0e4}})
        self.assertGreater(out['values']['lcoe_usd_kwh'], 0)


def _node(nid, kind, config=None):
    return {'id': nid, 'type': kind, 'config': config or {}}


def _edge(a, ap, b, bp):
    return {'source': a, 'source_port': ap, 'target': b, 'target_port': bp}


def _base():
    rotor = copy.deepcopy(engine.BLOCKS['rotor_hawt']['defaults'])
    return [_node('rotor', 'rotor_hawt', rotor),
            _node('op', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 7.0}})], \
        [_edge('rotor', 'spec', 'op', 'spec')]


class Optimisers(unittest.TestCase):
    def test_lcoe_over_the_downstream_chain(self):
        nodes, edges = _base()
        nodes += [
            _node('opt', 'design_optimizer', {'variables': [{'path': 'geometry.radius_m', 'min': 3.0, 'max': 8.0, 'initial': 3.5}],
                                              'objectives': [{'expression': 'lcoe_usd_kwh', 'sense': 'minimize'}], 'method': 'cobyla',
                                              'max_evaluations': 25}),
            _node('curve', 'performance_curve', {'points': 9, 'start': 3.0, 'stop': 11.0}),
            _node('strategy', 'operating_strategy', {'rated_power_w': 20000.0, 'rpm_max': 200.0, 'points': 24}),
            _node('aep', 'annual_energy', {'mean_wind_m_s': 6.5}),
            _node('cost', 'cost_model', {'hub_height_m': 25.0, 'bos_per_kw': 600.0, 'opex_per_kw_yr': 45.0}),
        ]
        edges += [_edge('op', 'spec', 'opt', 'spec'), _edge('opt', 'spec', 'curve', 'spec'), _edge('opt', 'spec', 'strategy', 'spec'),
                  _edge('curve', 'table', 'strategy', 'table'), _edge('strategy', 'table', 'aep', 'table'),
                  _edge('opt', 'spec', 'cost', 'spec'), _edge('aep', 'values', 'cost', 'values')]
        result = engine.execute({'schema_version': 2, 'kind': 'blocks', 'name': 'lcoe', 'nodes': nodes, 'edges': edges})
        self.assertEqual(result['status'], 'succeeded', {k: v.get('error') for k, v in result['blocks'].items()})
        opt = result['blocks']['opt']['outputs']
        rows = [r for r in opt['history']['rows'] if r['state'] == 'succeeded']
        first = rows[0]
        best_lcoe = opt['values']['lcoe_usd_kwh']
        self.assertIn('lcoe_usd_kwh', opt['values'])
        self.assertAlmostEqual(result['blocks']['cost']['outputs']['values']['lcoe_usd_kwh'], best_lcoe, places=10)
        self.assertNotEqual(opt['values']['radius_m'], first['geometry.radius_m'])

    def test_pareto_front_is_non_dominated(self):
        nodes, edges = _base()
        nodes.append(_node('pareto', 'pareto_optimizer', {
            'variables': [{'path': 'geometry.radius_m', 'min': 3.0, 'max': 6.0}, {'path': 'operating.tip_speed_ratio', 'min': 4.0, 'max': 9.0}],
            'objectives': [{'expression': 'power_w', 'sense': 'maximize'}, {'expression': 'thrust_n', 'sense': 'minimize'}],
            'population': 8, 'generations': 3}))
        edges.append(_edge('op', 'spec', 'pareto', 'spec'))
        result = engine.execute({'schema_version': 2, 'kind': 'blocks', 'name': 'p', 'nodes': nodes, 'edges': edges})
        block = result['blocks']['pareto']
        self.assertEqual(block['status'], 'succeeded', block.get('error'))
        rows = block['outputs']['table']['rows']
        for a in rows:
            for b in rows:
                dominated = b['power_w'] >= a['power_w'] and b['thrust_n'] <= a['thrust_n'] and (b['power_w'] > a['power_w'] or b['thrust_n'] < a['thrust_n'])
                self.assertFalse(dominated)
        self.assertEqual(sum(r['knee'] for r in rows), 1)

    def test_multi_fidelity_reaches_the_full_model_optimum(self):
        nodes, edges = _base()
        variables = [{'path': 'operating.tip_speed_ratio', 'min': 4.0, 'max': 11.0}]
        nodes.append(_node('mf', 'multi_fidelity', {'variables': variables, 'objectives': [{'expression': 'CP', 'sense': 'maximize'}],
                                                    'levels': [{'label': 'coarse', 'overrides': {'geometry.stations': 8}, 'evaluations': 20},
                                                               {'label': 'full', 'evaluations': 15, 'trust_region': 0.3}]}))
        nodes.append(_node('sqp', 'design_optimizer', {'variables': variables, 'objectives': [{'expression': 'CP', 'sense': 'maximize'}],
                                                       'method': 'cobyla', 'max_evaluations': 40}))
        edges += [_edge('op', 'spec', 'mf', 'spec'), _edge('op', 'spec', 'sqp', 'spec')]
        result = engine.execute({'schema_version': 2, 'kind': 'blocks', 'name': 'mf', 'nodes': nodes, 'edges': edges})
        mf, sqp = result['blocks']['mf'], result['blocks']['sqp']
        self.assertEqual(mf['status'], 'succeeded', mf.get('error'))
        self.assertAlmostEqual(mf['outputs']['values']['CP'], sqp['outputs']['values']['CP'], delta=2e-3)
        self.assertEqual([lvl['level'] for lvl in mf['outputs']['history']['levels']], ['coarse', 'full'])

    def test_nested_optimisers_are_rejected(self):
        nodes, edges = _base()
        nodes += [_node('a', 'design_optimizer', {'max_evaluations': 4}), _node('b', 'design_optimizer', {'max_evaluations': 4})]
        edges += [_edge('op', 'spec', 'a', 'spec'), _edge('a', 'spec', 'b', 'spec')]
        result = engine.execute({'schema_version': 2, 'kind': 'blocks', 'name': 'n', 'nodes': nodes, 'edges': edges})
        self.assertEqual(result['blocks']['a']['status'], 'failed')
        self.assertIn('nested', result['blocks']['a']['error'])


if __name__ == '__main__':
    unittest.main()
